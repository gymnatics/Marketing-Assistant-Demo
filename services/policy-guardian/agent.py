"""
Policy Guardian Agent - Validates campaign content against business policies.

Uses Qwen3 LLM to check campaign descriptions for policy violations:
- Unreasonable discounts (>50%)
- Unprofessional or misleading content
- Unrealistic promises
- Irresponsible gambling references
"""
import os
import json
import httpx

import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

LANG_MODEL_ENDPOINT = os.environ.get(
    "LANG_MODEL_ENDPOINT",
    "https://qwen3-32b-fp8-dynamic-0-marketing-assistant-demo.apps.cluster-qf44v.qf44v.sandbox543.opentlc.com/v1"
)
LANG_MODEL_NAME = os.environ.get("LANG_MODEL_NAME", "qwen3-32b-fp8-dynamic")
EVENT_HUB_URL = os.environ.get("EVENT_HUB_URL", "http://event-hub:5001")

POLICY_PROMPT = """You are a luxury casino resort marketing policy validator.

RULES:
1. No discounts greater than 50%
2. Must be professional and appropriate for a premium brand
3. No unrealistic or misleading promises
4. No references to gambling addiction or irresponsible behavior
5. Must maintain exclusivity — no cheap or mass-market language

EXAMPLES OF REJECTED CAMPAIGNS:
- "99% Off All Hotel Rooms" → REJECTED: Discount exceeds 50% maximum
- "Free Everything For Everyone" → REJECTED: Unrealistic promise, no exclusivity
- "Buy 2 Nights Get 80% Off" → REJECTED: Discount exceeds 50% maximum
- "Win Big Guaranteed at Our Tables" → REJECTED: Misleading gambling promise
- "Cheapest Rooms in Macau" → REJECTED: Language not appropriate for luxury brand
- "Unlimited Free Drinks and Casino Credits" → REJECTED: Unrealistic promise

EXAMPLES OF APPROVED CAMPAIGNS:
- "Exclusive 30% off suites for platinum members" → APPROVED
- "Complimentary spa treatment with 2-night stay" → APPROVED
- "Private dining experience for diamond tier guests" → APPROVED
- "VIP gala evening with world-class entertainment" → APPROVED
- "50% off luxury suite upgrade for loyalty members" → APPROVED

NOW EVALUATE:
Campaign Name: {campaign_name}
Campaign Description: {description}

Respond with ONLY: APPROVED or REJECTED: <brief reason>
No thinking, no XML tags, one line only."""


async def publish_event(campaign_id: str, event_type: str, agent: str, task: str, data: dict = None):
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{EVENT_HUB_URL}/events/{campaign_id}/publish",
                json={"event_type": event_type, "agent": agent, "task": task, "data": data or {}},
                timeout=5.0
            )
    except Exception as e:
        print(f"[Policy Guardian] Failed to publish event: {e}")


async def validate_policy(campaign_name: str, description: str) -> dict:
    """Call Qwen3 to validate campaign against business policies."""
    prompt = POLICY_PROMPT.format(campaign_name=campaign_name, description=description)

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{LANG_MODEL_ENDPOINT}/chat/completions",
            json={
                "model": LANG_MODEL_NAME,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 300,
            },
        )

        if response.status_code != 200:
            print(f"[Policy Guardian] LLM error: {response.status_code}")
            return {"approved": True, "reason": ""}

        result = response.json()
        answer = result["choices"][0]["message"]["content"].strip()

        if "</think>" in answer:
            answer = answer.split("</think>")[-1].strip()

        if answer.upper().startswith("REJECTED"):
            reason = answer.split(":", 1)[1].strip() if ":" in answer else "Campaign policy violation"
            return {"approved": False, "reason": reason}

        return {"approved": True, "reason": ""}


class PolicyGuardianAgent:
    """Validates campaign content against business policies using LLM reasoning."""

    async def validate(self, params: dict) -> dict:
        campaign_id = params.get("campaign_id", "unknown")
        campaign_name = params.get("campaign_name", "")
        description = params.get("campaign_description", "")

        await publish_event(
            campaign_id=campaign_id,
            event_type="agent_started",
            agent="Policy Guardian",
            task="Checking campaign policies..."
        )

        try:
            result = await validate_policy(campaign_name, description)

            if result["approved"]:
                await publish_event(
                    campaign_id=campaign_id,
                    event_type="agent_completed",
                    agent="Policy Guardian",
                    task="Campaign approved"
                )
                return {"approved": True, "reason": "", "status": "success"}
            else:
                await publish_event(
                    campaign_id=campaign_id,
                    event_type="agent_completed",
                    agent="Policy Guardian",
                    task=f"Campaign rejected: {result['reason']}"
                )
                return {"approved": False, "reason": result["reason"], "status": "success"}

        except Exception as e:
            await publish_event(
                campaign_id=campaign_id,
                event_type="agent_error",
                agent="Policy Guardian",
                task="Policy check failed",
                data={"error": str(e)}
            )
            return {"approved": True, "reason": "", "status": "error", "error": str(e)}
