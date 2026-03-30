"""
Customer Analyst A2A Agent - Retrieves VIP customer profiles for campaign targeting.

Uses MCP to query MongoDB customer database.
"""
import os
import httpx
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from shared.models import (
    CustomerProfile,
    GetTargetCustomersInput,
    GetTargetCustomersOutput
)


app = FastAPI(title="Customer Analyst Agent")

AGENT_CARD = {
    "name": "Customer Analyst",
    "description": "Retrieves VIP customer profiles for marketing campaign targeting",
    "version": "1.0.0",
    "protocol_version": "0.3.0",
    "skills": [
        {
            "name": "get_target_customers",
            "description": "Retrieve customers matching target audience criteria",
            "input_schema": GetTargetCustomersInput.model_json_schema()
        }
    ]
}

MONGODB_MCP_URL = os.environ.get("MONGODB_MCP_URL", "http://mongodb-mcp:8090")
EVENT_HUB_URL = os.environ.get("EVENT_HUB_URL", "http://event-hub:5001")


class InvokeRequest(BaseModel):
    skill: str
    params: dict


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


@app.get("/.well-known/agent-card.json")
async def get_agent_card():
    """Return agent capabilities for A2A discovery."""
    return JSONResponse(content=AGENT_CARD)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "agent": "Customer Analyst"}


@app.post("/a2a/invoke")
async def invoke_skill(request: InvokeRequest):
    """Invoke an agent skill via A2A protocol."""
    
    if request.skill != "get_target_customers":
        raise HTTPException(status_code=400, detail=f"Unknown skill: {request.skill}")
    
    try:
        params = GetTargetCustomersInput(**request.params)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid parameters: {e}")
    
    campaign_id = request.params.get("campaign_id", "unknown")
    
    await publish_event(
        campaign_id=campaign_id,
        event_type="agent_started",
        agent="Customer Analyst",
        task=f"Retrieving {params.target_audience} customers"
    )
    
    try:
        customers_data, recipient_type = await get_customers_by_audience(
            target_audience=params.target_audience,
            limit=params.limit
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
        
        result = GetTargetCustomersOutput(
            customers=customers,
            count=len(customers),
            recipient_type=recipient_type,
            status="success"
        )
        
        await publish_event(
            campaign_id=campaign_id,
            event_type="agent_completed",
            agent="Customer Analyst",
            task=f"Retrieved {len(customers)} {recipient_type}",
            data={"count": len(customers), "recipient_type": recipient_type}
        )
        
        return result.model_dump()
        
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


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8082))
    uvicorn.run(app, host="0.0.0.0", port=port)
