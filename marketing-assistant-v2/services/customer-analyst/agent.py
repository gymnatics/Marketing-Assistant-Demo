"""
Customer Analyst Agent - Pure business logic for retrieving VIP customer profiles.

Uses MCP to query MongoDB customer database for campaign targeting.
"""
import os
import httpx
from typing import List, Optional

import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from shared.models import (
    CustomerProfile,
    GetTargetCustomersInput,
    GetTargetCustomersOutput
)


MONGODB_MCP_URL = os.environ.get("MONGODB_MCP_URL", "http://mongodb-mcp:8090")
EVENT_HUB_URL = os.environ.get("EVENT_HUB_URL", "http://event-hub:5001")


async def publish_event(campaign_id: str, event_type: str, agent: str, task: str, data: dict = None):
    """Publish event to Event Hub for UI updates."""
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{EVENT_HUB_URL}/events/{campaign_id}/publish",
                json={
                    "event_type": event_type,
                    "agent": agent,
                    "task": task,
                    "data": data or {}
                },
                timeout=5.0
            )
    except Exception as e:
        print(f"[Customer Analyst] Failed to publish event: {e}")


async def call_mcp_tool(tool_name: str, arguments: dict) -> dict:
    """Call a tool on the MongoDB MCP server."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{MONGODB_MCP_URL}/tools/{tool_name}",
            json=arguments
        )
        if response.status_code != 200:
            raise Exception(f"MCP tool error: {response.status_code} - {response.text}")
        return response.json()


async def get_customers_by_audience(target_audience: str, limit: int = 50) -> tuple[List[dict], str]:
    """
    Retrieve customers based on target audience description.

    Returns tuple of (customers, recipient_type)
    """
    audience_lower = target_audience.lower()

    try:
        if "new" in audience_lower or "prospect" in audience_lower:
            result = await call_mcp_tool("get_prospects", {"limit": limit})
            return result, "prospects"

        elif "platinum" in audience_lower:
            result = await call_mcp_tool("get_customers_by_tier", {"tier": "platinum", "limit": limit})
            return result, "customers"

        elif "diamond" in audience_lower:
            result = await call_mcp_tool("get_customers_by_tier", {"tier": "diamond", "limit": limit})
            return result, "customers"

        elif "gold" in audience_lower:
            result = await call_mcp_tool("get_customers_by_tier", {"tier": "gold", "limit": limit})
            return result, "customers"

        elif "high spend" in audience_lower or "high-spend" in audience_lower or "vvip" in audience_lower:
            result = await call_mcp_tool("get_high_spend_customers", {"min_spend": 500000, "limit": limit})
            return result, "customers"

        else:
            result = await call_mcp_tool("get_all_vip_customers", {"limit": limit})
            return result, "customers"

    except Exception as e:
        print(f"[Customer Analyst] MCP call failed: {e}")
        raise


class CustomerAnalystAgent:
    """Retrieves VIP customer profiles for marketing campaign targeting via MCP."""

    async def get_customers(self, params: dict) -> dict:
        """
        Retrieve customers matching target audience criteria.

        Args:
            params: dict with keys campaign_id, target_audience, limit

        Returns:
            dict with customers, count, recipient_type, status, and optional error
        """
        campaign_id = params.get("campaign_id", "unknown")
        target_audience = params.get("target_audience", "all VIP")
        limit = params.get("limit", 50)

        await publish_event(
            campaign_id=campaign_id,
            event_type="agent_started",
            agent="Customer Analyst",
            task=f"Retrieving {target_audience} customers"
        )

        try:
            customers_data, recipient_type = await get_customers_by_audience(
                target_audience=target_audience,
                limit=limit
            )

            customers = [
                CustomerProfile(
                    customer_id=c.get("customer_id", ""),
                    name=c.get("name", ""),
                    name_en=c.get("name_en"),
                    email=c.get("email", ""),
                    tier=c.get("tier", ""),
                    preferred_language=c.get("preferred_language", "en"),
                    interests=c.get("interests", []),
                    total_spend=c.get("total_spend"),
                    last_visit=c.get("last_visit"),
                    source=c.get("source")
                )
                for c in customers_data
            ]

            await publish_event(
                campaign_id=campaign_id,
                event_type="agent_completed",
                agent="Customer Analyst",
                task=f"Retrieved {len(customers)} {recipient_type}",
                data={"count": len(customers), "recipient_type": recipient_type}
            )

            return GetTargetCustomersOutput(
                customers=customers,
                count=len(customers),
                recipient_type=recipient_type,
                status="success"
            ).model_dump()

        except Exception as e:
            await publish_event(
                campaign_id=campaign_id,
                event_type="agent_error",
                agent="Customer Analyst",
                task="Customer retrieval failed",
                data={"error": str(e)}
            )

            return GetTargetCustomersOutput(
                customers=[],
                count=0,
                recipient_type="unknown",
                status="error",
                error=str(e)
            ).model_dump()
