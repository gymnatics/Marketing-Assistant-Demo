"""
Campaign API Gateway - REST API for the React frontend.

Routes requests to the Campaign Director and provides campaign management endpoints.
"""
import os
import httpx
from flask import Flask, request, jsonify
from flask_cors import CORS
from pydantic import BaseModel, ValidationError
from typing import Optional

import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from shared.models import CampaignRequest, CampaignTheme


app = Flask(__name__)
CORS(app)

CAMPAIGN_DIRECTOR_URL = os.environ.get("CAMPAIGN_DIRECTOR_URL", "http://campaign-director:8080")


async def call_director(skill: str, params: dict) -> dict:
    """Call Campaign Director agent."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(
            f"{CAMPAIGN_DIRECTOR_URL}/a2a/invoke",
            json={"skill": skill, "params": params}
        )
        if response.status_code != 200:
            raise Exception(f"Director call failed: {response.status_code} - {response.text}")
        return response.json()


def call_director_sync(skill: str, params: dict) -> dict:
    """Call Campaign Director agent (sync version)."""
    with httpx.Client(timeout=300.0) as client:
        response = client.post(
            f"{CAMPAIGN_DIRECTOR_URL}/a2a/invoke",
            json={"skill": skill, "params": params}
        )
        if response.status_code != 200:
            raise Exception(f"Director call failed: {response.status_code} - {response.text}")
        return response.json()


@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint."""
    return jsonify({"status": "healthy", "service": "Campaign API"})


@app.route("/api/themes", methods=["GET"])
def get_themes():
    """Get available campaign themes."""
    from shared.models import CAMPAIGN_THEMES
    return jsonify(CAMPAIGN_THEMES)


@app.route("/api/campaigns", methods=["GET"])
def list_campaigns():
    """List all campaigns."""
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
    """Get campaign by ID."""
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
    """Create a new campaign."""
    try:
        data = request.get_json()
        
        try:
            campaign_request = CampaignRequest(
                campaign_name=data.get("campaign_name"),
                campaign_description=data.get("campaign_description"),
                hotel_name=data.get("hotel_name", "Grand Lisboa Palace"),
                target_audience=data.get("target_audience"),
                theme=data.get("theme", "luxury_gold"),
                start_date=data.get("start_date"),
                end_date=data.get("end_date")
            )
        except ValidationError as e:
            return jsonify({"error": "Invalid request", "details": e.errors()}), 400
        
        result = call_director_sync("create_campaign", campaign_request.model_dump())
        return jsonify(result), 201
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/campaigns/<campaign_id>/generate", methods=["POST"])
def generate_landing_page(campaign_id: str):
    """Generate landing page for a campaign."""
    try:
        result = call_director_sync("generate_landing_page", {"campaign_id": campaign_id})
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/campaigns/<campaign_id>/preview-email", methods=["POST"])
def preview_email(campaign_id: str):
    """Prepare email preview (retrieve customers + generate email)."""
    try:
        result = call_director_sync("prepare_email_preview", {"campaign_id": campaign_id})
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/campaigns/<campaign_id>/approve", methods=["POST"])
def approve_campaign(campaign_id: str):
    """Go live - deploy to production and send emails."""
    try:
        result = call_director_sync("go_live", {"campaign_id": campaign_id})
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/campaigns/<campaign_id>", methods=["DELETE"])
def delete_campaign(campaign_id: str):
    """Delete/cancel a campaign."""
    return jsonify({"message": "Campaign deleted", "campaign_id": campaign_id})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
