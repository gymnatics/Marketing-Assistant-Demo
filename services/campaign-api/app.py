"""
Campaign API Gateway - REST API for the React frontend.

Routes requests to the Campaign Director via A2A protocol and provides campaign management endpoints.
Campaign Director's REST endpoints (/campaigns, /campaigns/{id}) are called directly via httpx.
Campaign Director's A2A skills (create, generate, email, golive) are called via A2AClient.
"""
import os
import uuid
import json
import time
import httpx
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from shared.models import CampaignRequest, CampaignTheme
from shared.vertical_config import competitors as vcfg_competitors, brand

app = Flask(__name__)
CORS(app)

CAMPAIGN_DIRECTOR_URL = os.environ.get("CAMPAIGN_DIRECTOR_URL", "http://campaign-director:8080")

CAMPAIGNS_CREATED = Counter("campaigns_created_total", "Total campaigns created")
CAMPAIGNS_LIVE = Counter("campaigns_live_total", "Total campaigns that went live")
AGENT_CALLS = Counter("agent_calls_total", "A2A calls to Campaign Director", ["skill"])
STEP_DURATION = Histogram("campaign_step_duration_seconds", "Duration of campaign workflow steps", ["step"])
ACTIVE_CAMPAIGNS = Gauge("active_campaigns", "Currently in-progress campaigns")
# Guardrails configuration
HAP_DETECTOR_URL = os.environ.get("HAP_DETECTOR_URL", "http://guardrails-detector-ibm-hap-predictor:8000")
POLICY_GUARDIAN_URL = os.environ.get("POLICY_GUARDIAN_URL", "http://policy-guardian:8084")
PROMPT_INJECTION_URL = os.environ.get("PROMPT_INJECTION_URL", "http://prompt-injection-detector-predictor:8000")

GUARDRAILS_BLOCKED = Counter("guardrails_blocked_total", "Requests blocked by guardrails", ["detector"])

def _build_competitor_pattern() -> str:
    names = vcfg_competitors()
    if names:
        escaped = [name.replace("(", r"\(").replace(")", r"\)") for name in names]
        return r"(?i)(" + "|".join(escaped) + ")"
    return r"(?i)(jennifer casino|jennifer resort|lucky star casino|jade emperor palace|phoenix bay resort|emerald fortune club|royal lotus gaming)"

COMPETITOR_PATTERN = _build_competitor_pattern()


def guardrail_failure(layer_id: str, layer_name: str, title: str, reason: str, guidance: str, details: dict | None = None) -> dict:
    return {
        "passed": False,
        "layer": {
            "id": layer_id,
            "name": layer_name,
        },
        "title": title,
        "reason": reason,
        "guidance": guidance,
        "details": details or {},
    }


def check_guardrails(campaign_name: str, description: str) -> dict:
    """Run campaign through TrustyAI detectors + policy agent."""
    import re
    text = f"{campaign_name} {description}"

    # Layer 1: Regex — competitor names
    match = re.search(COMPETITOR_PATTERN, text)
    if match:
        GUARDRAILS_BLOCKED.labels(detector="regex_competitor").inc()
        blocked_term = match.group(0)
        return guardrail_failure(
            "regex_competitor",
            "Brand Compliance",
            "Competitor reference detected",
            f'The campaign mentions "{blocked_term}", which is blocked by the competitor-name guardrail.',
            "Remove competitor brand names and rewrite the campaign in Simon property terms only.",
            {"matched_text": blocked_term},
        )

    # Layer 2: TrustyAI HAP detector — hate/abuse/profanity
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                f"{HAP_DETECTOR_URL}/api/v1/text/contents",
                json={"contents": [text], "detector_params": {}},
                headers={"Content-Type": "application/json", "detector-id": "hap"}
            )
            if resp.status_code == 200:
                results = resp.json()
                if results and results[0]:
                    for det in results[0]:
                        if det.get("score", 0) > 0.5:
                            GUARDRAILS_BLOCKED.labels(detector="hap").inc()
                            label = det.get("label") or det.get("name") or "unsafe content"
                            score = round(det.get("score", 0), 3)
                            return guardrail_failure(
                                "hap",
                                "Content Safety Check",
                                "Inappropriate language detected",
                                "The campaign contains language that does not meet our professional standards. Please ensure all wording is appropriate for a luxury brand audience.",
                                "Revise the campaign name and description to use professional, premium language suitable for high-value customers.",
                                {"label": label, "score": score},
                            )
    except Exception as e:
        print(f"[Guardrails] HAP check failed (non-blocking): {e}")

    # Layer 3: TrustyAI Prompt Injection detector
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                f"{PROMPT_INJECTION_URL}/api/v1/text/contents",
                json={"contents": [text], "detector_params": {}},
                headers={"Content-Type": "application/json", "detector-id": "prompt_injection"}
            )
            if resp.status_code == 200:
                results = resp.json()
                if results and results[0]:
                    for det in results[0]:
                        if det.get("score", 0) > 0.5:
                            GUARDRAILS_BLOCKED.labels(detector="prompt_injection").inc()
                            label = det.get("label") or det.get("name") or "prompt injection risk"
                            score = round(det.get("score", 0), 3)
                            return guardrail_failure(
                                "prompt_injection",
                                "Input Validation",
                                "Suspicious input pattern detected",
                                "The campaign description contains instruction-like patterns that could interfere with content generation. Please use natural marketing language only.",
                                "Rewrite the description as a straightforward campaign brief — avoid technical instructions, system commands, or directive language.",
                                {"label": label, "score": score},
                            )
    except Exception as e:
        print(f"[Guardrails] Prompt injection check failed (non-blocking): {e}")

    # Layer 4: Policy Guardian Agent (A2A) — business logic
    try:
        import asyncio
        from a2a.client import A2AClient
        from a2a.types import MessageSendParams, SendMessageRequest

        async def _call_policy():
            message_params = MessageSendParams(
                message={
                    "role": "user",
                    "parts": [{"kind": "text", "text": json.dumps({
                        "skill": "validate_campaign",
                        "campaign_name": campaign_name,
                        "campaign_description": description,
                    })}],
                    "messageId": uuid.uuid4().hex,
                }
            )
            request_obj = SendMessageRequest(id=str(uuid.uuid4()), params=message_params)
            timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
            async with httpx.AsyncClient(timeout=timeout) as hc:
                client = A2AClient(httpx_client=hc, url=POLICY_GUARDIAN_URL)
                response = await client.send_message(request_obj)
            resp = response.root
            if hasattr(resp, 'result') and resp.result and hasattr(resp.result, 'artifacts') and resp.result.artifacts:
                text = resp.result.artifacts[0].parts[0].root.text
                return json.loads(text)
            return {"approved": True}

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(_call_policy())
        finally:
            loop.close()

        if result.get("approved") is False:
            GUARDRAILS_BLOCKED.labels(detector="policy_guardian").inc()
            reason = result.get("reason", "Campaign does not meet policy requirements.")
            return guardrail_failure(
                "policy_guardian",
                "Campaign Policy Review",
                "Business policy violation",
                reason,
                "Adjust the offer so it stays realistic, premium, and compliant with Simon campaign policy.",
                {"policy_reason": reason},
            )
    except Exception as e:
        print(f"[Guardrails] Policy Guardian check failed (non-blocking): {e}")

    return {
        "passed": True,
        "layer": None,
        "title": "",
        "reason": "",
        "guidance": "",
        "details": {},
    }




def call_director_a2a_sync(skill: str, params: dict) -> dict:
    """Call Campaign Director via A2A JSON-RPC protocol (synchronous)."""
    from a2a.client import A2AClient
    from a2a.types import MessageSendParams, SendMessageRequest

    import asyncio

    async def _call():
        message_params = MessageSendParams(
            message={
                "role": "user",
                "parts": [{"kind": "text", "text": json.dumps({"skill": skill, **params})}],
                "messageId": uuid.uuid4().hex,
            }
        )
        req = SendMessageRequest(id=str(uuid.uuid4()), params=message_params)

        timeout = httpx.Timeout(connect=30.0, read=300.0, write=30.0, pool=30.0)
        async with httpx.AsyncClient(timeout=timeout) as httpx_client:
            client = A2AClient(httpx_client=httpx_client, url=CAMPAIGN_DIRECTOR_URL)
            response = await client.send_message(req)

        resp = response.root
        if hasattr(resp, 'error') and resp.error:
            return {"error": f"A2A error: {resp.error.message}"}

        task_result = resp.result if hasattr(resp, 'result') else None
        if task_result and hasattr(task_result, 'artifacts') and task_result.artifacts:
            for artifact in task_result.artifacts:
                for part in (artifact.parts or []):
                    text = None
                    if hasattr(part, 'root') and hasattr(part.root, 'text'):
                        text = part.root.text
                    elif hasattr(part, 'text'):
                        text = part.text
                    if text:
                        try:
                            return json.loads(text)
                        except json.JSONDecodeError:
                            return {"status": "success", "content": text}
        return {"error": "No artifact returned from Campaign Director"}

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_call())
    finally:
        loop.close()


@app.route("/healthz", methods=["GET"])
def health_check():
    return jsonify({"status": "healthy", "service": "Campaign API"})

@app.route("/readyz")
def readiness_check():
    return health_check()


@app.route("/metrics")
def metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


@app.route("/api/themes", methods=["GET"])
def get_themes():
    from shared.models import CAMPAIGN_THEMES
    return jsonify(CAMPAIGN_THEMES)


@app.route("/api/config", methods=["GET"])
def get_vertical_config():
    """Return frontend-relevant vertical config (branding, presets, tiers, etc.)."""
    from shared.vertical_config import get_config
    cfg = get_config()
    return jsonify({
        "brand": cfg.get("brand", {}),
        "properties": cfg.get("properties", []),
        "property_label": cfg.get("property_label", "Property"),
        "tiers": cfg.get("tiers", {}),
        "audience_suggestions": cfg.get("audience_suggestions", []),
        "themes": cfg.get("themes", {}),
        "quick_start_presets": cfg.get("quick_start_presets", []),
        "guardrail_presets": cfg.get("guardrail_presets", []),
        "competitors": cfg.get("competitors", []),
    })


@app.route("/api/campaigns", methods=["GET"])
def list_campaigns():
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(f"{CAMPAIGN_DIRECTOR_URL}/campaigns")
            if response.status_code != 200:
                return jsonify({"error": "Failed to fetch campaigns"}), 500
            return jsonify(response.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/campaigns/<campaign_id>", methods=["GET"])
def get_campaign(campaign_id: str):
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(f"{CAMPAIGN_DIRECTOR_URL}/campaigns/{campaign_id}")
            if response.status_code == 404:
                return jsonify({"error": "Campaign not found"}), 404
            if response.status_code != 200:
                return jsonify({"error": "Failed to fetch campaign"}), 500
            return jsonify(response.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/campaigns/validate", methods=["POST"])
def validate_campaign():
    """Validate campaign through guardrails without creating it."""
    try:
        data = request.get_json()
        name = data.get("campaign_name", "")
        desc = data.get("campaign_description", "")
        result = check_guardrails(name, desc)
        if not result["passed"]:
            return jsonify({
                "valid": False,
                "reason": result["reason"],
                "guardrail": result,
            }), 200
        return jsonify({"valid": True, "reason": "", "guardrail": result}), 200
    except Exception as e:
        return jsonify({"valid": True, "reason": ""}), 200


@app.route("/api/campaigns", methods=["POST"])
def create_campaign():
    try:
        data = request.get_json()

        # Run guardrails check before creating
        guardrails = check_guardrails(
            data.get("campaign_name", ""),
            data.get("campaign_description", "")
        )
        if not guardrails["passed"]:
            return jsonify({
                "error": guardrails["reason"],
                "guardrail_blocked": True,
                "guardrail": guardrails,
            }), 400

        AGENT_CALLS.labels(skill="create_campaign").inc()
        result = call_director_a2a_sync("create_campaign", data)
        if "error" in result and result["error"]:
            return jsonify(result), 500
        CAMPAIGNS_CREATED.inc()
        ACTIVE_CAMPAIGNS.inc()
        return jsonify(result), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/campaigns/<campaign_id>/generate", methods=["POST"])
def generate_landing_page(campaign_id: str):
    try:
        AGENT_CALLS.labels(skill="generate_landing_page").inc()
        start = time.time()
        result = call_director_a2a_sync("generate_landing_page", {"campaign_id": campaign_id})
        STEP_DURATION.labels(step="generate").observe(time.time() - start)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/campaigns/<campaign_id>/preview-email", methods=["POST"])
def preview_email(campaign_id: str):
    try:
        AGENT_CALLS.labels(skill="prepare_email_preview").inc()
        start = time.time()
        result = call_director_a2a_sync("prepare_email_preview", {"campaign_id": campaign_id})
        STEP_DURATION.labels(step="email_preview").observe(time.time() - start)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/campaigns/<campaign_id>/approve", methods=["POST"])
def approve_campaign(campaign_id: str):
    try:
        AGENT_CALLS.labels(skill="go_live").inc()
        start = time.time()
        result = call_director_a2a_sync("go_live", {"campaign_id": campaign_id})
        STEP_DURATION.labels(step="go_live").observe(time.time() - start)
        CAMPAIGNS_LIVE.inc()
        ACTIVE_CAMPAIGNS.dec()
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/campaigns/<campaign_id>", methods=["DELETE"])
def delete_campaign(campaign_id: str):
    return jsonify({"message": "Campaign deleted", "campaign_id": campaign_id})



# === Fake Inbox ===
INBOX_TEMPLATES = [
    {
        "from_name": "Simon Casino Resort",
        "from_email": "vip@simoncasino.com",
        "subject": "Your {tier} Membership Has Been Renewed",
        "body": "<p>Dear {name},</p><p>We are pleased to confirm that your {tier} membership has been successfully renewed for another year.</p><p>As a valued member, you continue to enjoy exclusive benefits including priority reservations, complimentary spa access, and dedicated concierge service.</p><p>Best regards,<br>Simon Casino Resort VIP Services</p>",
        "date": "2026-03-15T10:30:00",
    },
    {
        "from_name": "Simon Casino Resort",
        "from_email": "dining@simoncasino.com",
        "subject": "Exclusive Wine Tasting Event — March 28",
        "body": "<p>Dear {name},</p><p>You are cordially invited to an exclusive wine tasting event featuring rare vintages from our award-winning cellar.</p><p><strong>Date:</strong> March 28, 2026<br><strong>Time:</strong> 7:00 PM<br><strong>Venue:</strong> The Grand Cellar, Level B1</p><p>Limited to 20 guests. Please RSVP at your earliest convenience.</p><p>Warm regards,<br>The Dining Team</p>",
        "date": "2026-03-20T14:15:00",
    },
    {
        "from_name": "Simon Casino Resort",
        "from_email": "concierge@simoncasino.com",
        "subject": "Your Suite Upgrade Confirmation",
        "body": "<p>Dear {name},</p><p>Great news! Your upcoming stay has been upgraded to the Presidential Suite as a token of our appreciation for your loyalty.</p><p><strong>Check-in:</strong> April 5, 2026<br><strong>Suite:</strong> Presidential Suite, Floor 38<br><strong>Amenities:</strong> Private butler, panoramic city view, complimentary minibar</p><p>We look forward to welcoming you.</p><p>Best regards,<br>Concierge Team</p>",
        "date": "2026-03-25T09:00:00",
    },
]

CAMPAIGN_EMAILS = []  # Campaign emails added by Delivery Manager


def get_inbox_for(email_filter=None):
    """Get inbox emails, personalizing templates for the requested recipient."""
    all_emails = []

    # Add pre-populated template emails for each known customer
    known_customers = [
        {"name": "Wei Zhang", "email": "wei.zhang@example.com", "tier": "Platinum"},
        {"name": "Ming Li", "email": "ming.li@example.com", "tier": "Platinum"},
        {"name": "John Smith", "email": "john.smith@example.com", "tier": "Platinum"},
        {"name": "Yang Liu", "email": "yang.liu@example.com", "tier": "Diamond"},
        {"name": "Fang Wang", "email": "fang.wang@example.com", "tier": "Gold"},
    ]

    for cust in known_customers:
        if email_filter and cust["email"] != email_filter:
            continue
        for i, tmpl in enumerate(INBOX_TEMPLATES):
            all_emails.append({
                "id": f"inbox-{cust['email']}-{i}",
                "from_name": tmpl["from_name"],
                "from_email": tmpl["from_email"],
                "to_name": cust["name"],
                "to_email": cust["email"],
                "subject": tmpl["subject"].format(name=cust["name"], tier=cust["tier"]),
                "body": tmpl["body"].format(name=cust["name"], tier=cust["tier"]),
                "date": tmpl["date"],
                "read": True,
            })

    # Add campaign emails
    for ce in CAMPAIGN_EMAILS:
        if email_filter and ce.get("to_email") != email_filter:
            continue
        all_emails.append(ce)

    # Sort: unread first, then by date descending
    all_emails.sort(key=lambda e: (e.get("read", True), e.get("date", "")), reverse=False)
    unread = [e for e in all_emails if not e.get("read")]
    read = [e for e in all_emails if e.get("read")]
    read.sort(key=lambda e: e.get("date", ""), reverse=True)
    return unread + read


@app.route("/api/inbox", methods=["GET"])
def get_inbox():
    email_filter = request.args.get("email")
    return jsonify(get_inbox_for(email_filter))


@app.route("/api/inbox", methods=["POST"])
def add_to_inbox():
    email = request.get_json()
    email["id"] = f"inbox-{uuid.uuid4().hex[:6]}"
    email["read"] = False
    CAMPAIGN_EMAILS.append(email)
    return jsonify(email), 201


@app.route("/api/inbox/<email_id>/read", methods=["POST"])
def mark_read(email_id):
    for email in CAMPAIGN_EMAILS:
        if email["id"] == email_id:
            email["read"] = True
            return jsonify(email)
    return jsonify({"read": True}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
