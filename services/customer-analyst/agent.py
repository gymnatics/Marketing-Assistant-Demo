"""
Customer Analyst Agent - Retrieves VIP customer profiles using LLM tool calling + MCP.

Uses Qwen3 LLM to reason about which MCP tools to call based on the target audience,
then executes those tools against the MongoDB MCP server via proper MCP protocol.
"""
import os
import json
import httpx
from typing import List

import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from shared.models import (
    CustomerProfile,
    GetTargetCustomersInput,
    GetTargetCustomersOutput
)


MONGODB_MCP_URL = os.environ.get("MONGODB_MCP_URL", "http://mongodb-mcp:8090")
EVENT_HUB_URL = os.environ.get("EVENT_HUB_URL", "http://event-hub:5001")
LANG_MODEL_ENDPOINT = os.environ.get(
    "LANG_MODEL_ENDPOINT",
    "https://qwen3-32b-fp8-dynamic-0-marketing-assistant-demo.apps.cluster-qf44v.qf44v.sandbox543.opentlc.com/v1"
)
LANG_MODEL_NAME = os.environ.get("LANG_MODEL_NAME", "qwen3-32b-fp8-dynamic")

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_customers_by_tier",
            "description": "Retrieve VIP customers by membership tier (platinum, gold, diamond)",
            "parameters": {
                "type": "object",
                "properties": {
                    "tier": {"type": "string", "description": "Membership tier: platinum, gold, or diamond"},
                    "limit": {"type": "integer", "description": "Max customers to return", "default": 50}
                },
                "required": ["tier"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_prospects",
            "description": "Retrieve prospect list — potential customers who are not yet members",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max prospects to return", "default": 50}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_high_spend_customers",
            "description": "Retrieve customers with total spend above a threshold (whales/VVIPs)",
            "parameters": {
                "type": "object",
                "properties": {
                    "min_spend": {"type": "integer", "description": "Minimum total spend amount", "default": 500000},
                    "limit": {"type": "integer", "description": "Max customers to return", "default": 50}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_all_vip_customers",
            "description": "Retrieve all VIP customers regardless of tier",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max customers to return", "default": 100}
                }
            }
        }
    },
]

SYSTEM_PROMPT = """You are a customer data analyst for a luxury casino resort. Given a target audience description, decide which database tool to call to retrieve the right customer segment. You have access to the following tools:

- get_customers_by_tier: For specific tier queries (platinum, gold, diamond members)
- get_prospects: For new/potential customers who aren't members yet
- get_high_spend_customers: For high-spending VIP/whale customers
- get_all_vip_customers: For broad targeting across all VIP tiers

Call exactly ONE tool based on the target audience description. Do not call multiple tools."""


async def publish_event(campaign_id: str, event_type: str, agent: str, task: str, data: dict = None):
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{EVENT_HUB_URL}/events/{campaign_id}/publish",
                json={"event_type": event_type, "agent": agent, "task": task, "data": data or {}},
                timeout=5.0
            )
    except Exception as e:
        print(f"[Customer Analyst] Failed to publish event: {e}")


async def call_mcp_tool(tool_name: str, arguments: dict, auth_headers: dict = None) -> list:
    """Call a tool on the MongoDB MCP server via proper MCP protocol."""
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport

    mcp_url = f"{MONGODB_MCP_URL}/mcp"
    if auth_headers:
        transport = StreamableHttpTransport(url=mcp_url, headers=auth_headers)
        client = Client(transport)
    else:
        client = Client(mcp_url)

    async with client as mcp_client:
        result = await mcp_client.call_tool(tool_name, arguments)
        if result and result.content:
            return json.loads(result.content[0].text)
        return []


async def llm_select_and_call_tool(target_audience: str, limit: int = 50) -> tuple[list, str]:
    """Use Qwen3 LLM to decide which MCP tool to call, then execute it."""
    url = f"{LANG_MODEL_ENDPOINT}/chat/completions"
    headers = {"Content-Type": "application/json"}

    payload = {
        "model": LANG_MODEL_NAME,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Retrieve customers for this target audience: {target_audience} (limit: {limit})"}
        ],
        "tools": TOOLS,
        "tool_choice": "auto",
        "temperature": 0.1,
        "max_tokens": 256,
        "stream": True,
    }

    tool_call_name = None
    tool_call_args = ""

    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as response:
            if response.status_code != 200:
                error_text = await response.aread()
                raise Exception(f"LLM API error: {response.status_code} - {error_text}")

            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    if "tool_calls" in delta:
                        tc = delta["tool_calls"][0]
                        if "function" in tc:
                            if "name" in tc["function"]:
                                tool_call_name = tc["function"]["name"]
                            if "arguments" in tc["function"]:
                                tool_call_args += tc["function"]["arguments"]
                except json.JSONDecodeError:
                    continue

    if not tool_call_name:
        print(f"[Customer Analyst] LLM did not select a tool, using keyword fallback for: {target_audience}")
        audience_lower = target_audience.lower()
        if "new" in audience_lower or "prospect" in audience_lower:
            tool_call_name = "get_prospects"
            tool_call_args = json.dumps({"limit": limit})
        elif "platinum" in audience_lower:
            tool_call_name = "get_customers_by_tier"
            tool_call_args = json.dumps({"tier": "platinum", "limit": limit})
        elif "diamond" in audience_lower:
            tool_call_name = "get_customers_by_tier"
            tool_call_args = json.dumps({"tier": "diamond", "limit": limit})
        elif "gold" in audience_lower:
            tool_call_name = "get_customers_by_tier"
            tool_call_args = json.dumps({"tier": "gold", "limit": limit})
        elif "high" in audience_lower or "spend" in audience_lower or "whale" in audience_lower:
            tool_call_name = "get_high_spend_customers"
            tool_call_args = json.dumps({"min_spend": 500000, "limit": limit})
        else:
            tool_call_name = "get_all_vip_customers"
            tool_call_args = json.dumps({"limit": limit})

    try:
        arguments = json.loads(tool_call_args) if tool_call_args else {}
    except json.JSONDecodeError:
        arguments = {}

    if "limit" not in arguments:
        arguments["limit"] = limit

    print(f"[Customer Analyst] LLM selected tool: {tool_call_name}({json.dumps(arguments)})")

    result = await call_mcp_tool(tool_call_name, arguments)

    recipient_type = "prospects" if tool_call_name == "get_prospects" else "customers"
    return result, recipient_type


class CustomerAnalystAgent:
    """Retrieves VIP customer profiles using LLM reasoning + MCP tools."""

    async def get_customers(self, params: dict) -> dict:
        campaign_id = params.get("campaign_id", "unknown")
        target_audience = params.get("target_audience", "all VIP")
        limit = params.get("limit", 50)

        await publish_event(
            campaign_id=campaign_id,
            event_type="agent_started",
            agent="Customer Analyst",
            task=f"Identifying {target_audience}..."
        )

        try:
            await publish_event(
                campaign_id=campaign_id,
                event_type="workflow_status",
                agent="Customer Analyst",
                task="Analyzing target audience..."
            )

            customers_data, recipient_type = await llm_select_and_call_tool(
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
                task=f"Found {len(customers)} {recipient_type}",
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
                task="Could not retrieve customers",
                data={"error": str(e)}
            )

            return GetTargetCustomersOutput(
                customers=[],
                count=0,
                recipient_type="unknown",
                status="error",
                error=str(e)
            ).model_dump()
