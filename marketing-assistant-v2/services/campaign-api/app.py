"""
Campaign API Gateway - REST API for the React frontend.

Routes requests to the Campaign Director via A2A protocol and provides campaign management endpoints.
Campaign Director's REST endpoints (/campaigns, /campaigns/{id}) are called directly via httpx.
Campaign Director's A2A skills (create, generate, email, golive) are called via A2AClient.
"""
import os
import uuid
import json
import httpx
from flask import Flask, request, jsonify
from flask_cors import CORS

import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from shared.models import CampaignRequest, CampaignTheme

app = Flask(__name__)
CORS(app)

CAMPAIGN_DIRECTOR_URL = os.environ.get("CAMPAIGN_DIRECTOR_URL", "http://campaign-director:8080")


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

        result_data = response.result
        if hasattr(result_data, 'artifacts') and result_data.artifacts:
            for artifact in result_data.artifacts:
                for part in (artifact.parts or []):
                    if hasattr(part, 'root') and hasattr(part.root, 'text'):
                        return json.loads(part.root.text)
                    elif hasattr(part, 'text'):
                        return json.loads(part.text)
        return {"error": "No artifact returned from Campaign Director"}

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_call())
    finally:
        loop.close()


@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "healthy", "service": "Campaign API"})


@app.route("/api/themes", methods=["GET"])
def get_themes():
    from shared.models import CAMPAIGN_THEMES
    return jsonify(CAMPAIGN_THEMES)


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


@app.route("/api/campaigns", methods=["POST"])
def create_campaign():
    try:
        data = request.get_json()
        result = call_director_a2a_sync("create_campaign", data)
        if "error" in result and result["error"]:
            return jsonify(result), 500
        return jsonify(result), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/campaigns/<campaign_id>/generate", methods=["POST"])
def generate_landing_page(campaign_id: str):
    try:
        result = call_director_a2a_sync("generate_landing_page", {"campaign_id": campaign_id})
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/campaigns/<campaign_id>/preview-email", methods=["POST"])
def preview_email(campaign_id: str):
    try:
        result = call_director_a2a_sync("prepare_email_preview", {"campaign_id": campaign_id})
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/campaigns/<campaign_id>/approve", methods=["POST"])
def approve_campaign(campaign_id: str):
    try:
        result = call_director_a2a_sync("go_live", {"campaign_id": campaign_id})
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/campaigns/<campaign_id>", methods=["DELETE"])
def delete_campaign(campaign_id: str):
    return jsonify({"message": "Campaign deleted", "campaign_id": campaign_id})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
