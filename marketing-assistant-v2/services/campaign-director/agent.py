"""
Campaign Director Agent - Business logic for orchestrating campaign workflows.

Uses LangGraph for workflow orchestration and A2A SDK client to communicate
with specialized agents (Creative Producer, Customer Analyst, Delivery Manager).
"""
import os
import sys
import uuid
import json
import asyncio
import traceback
import httpx
from typing import TypedDict, Annotated, List
import operator

from langgraph.graph import StateGraph, START, END

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from shared.models import (
    CampaignRequest,
    CampaignData,
    CampaignStatus,
    CustomerProfile,
    CAMPAIGN_THEMES
)


CREATIVE_PRODUCER_URL = os.environ.get("CREATIVE_PRODUCER_URL", "http://creative-producer:8081")
CUSTOMER_ANALYST_URL = os.environ.get("CUSTOMER_ANALYST_URL", "http://customer-analyst:8082")
DELIVERY_MANAGER_URL = os.environ.get("DELIVERY_MANAGER_URL", "http://delivery-manager:8083")
EVENT_HUB_URL = os.environ.get("EVENT_HUB_URL", "http://event-hub:5001")
CLUSTER_DOMAIN = os.environ.get("CLUSTER_DOMAIN", "apps.cluster-qf44v.qf44v.sandbox543.opentlc.com")
DEV_NAMESPACE = os.environ.get("DEV_NAMESPACE", "0-marketing-assistant-demo-dev")
PROD_NAMESPACE = os.environ.get("PROD_NAMESPACE", "0-marketing-assistant-demo-prod")

campaigns_store: dict[str, CampaignData] = {}


class CampaignState(TypedDict):
    campaign_id: str
    campaign_name: str
    campaign_description: str
    hotel_name: str
    target_audience: str
    theme: str
    start_date: str
    end_date: str
    status: str
    landing_page_html: str
    preview_url: str
    production_url: str
    email_subject_en: str
    email_body_en: str
    email_subject_zh: str
    email_body_zh: str
    customer_list: List[dict]
    customer_count: int
    error_message: str
    messages: Annotated[list, operator.add]


async def call_a2a_agent(agent_url: str, skill: str, params: dict) -> dict:
    """Call an A2A agent via JSON-RPC (a2a-sdk protocol)."""
    from a2a.client import A2AClient
    from a2a.types import MessageSendParams, SendMessageRequest, TextPart, Part

    message_params = MessageSendParams(
        message={
            "role": "user",
            "parts": [{"kind": "text", "text": json.dumps({"skill": skill, **params})}],
            "messageId": uuid.uuid4().hex,
        }
    )
    request = SendMessageRequest(id=str(uuid.uuid4()), params=message_params)

    timeout = httpx.Timeout(connect=30.0, read=600.0, write=30.0, pool=30.0)
    async with httpx.AsyncClient(timeout=timeout) as httpx_client:
        client = A2AClient(httpx_client=httpx_client, url=agent_url)
        response = await client.send_message(request)

    result_data = response.result
    if hasattr(result_data, 'artifacts') and result_data.artifacts:
        for artifact in result_data.artifacts:
            for part in (artifact.parts or []):
                if hasattr(part, 'root') and hasattr(part.root, 'text'):
                    return json.loads(part.root.text)
                elif hasattr(part, 'text'):
                    return json.loads(part.text)

    return {"status": "error", "error": "No artifact returned from agent"}


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
        print(f"[Campaign Director] Failed to publish event: {e}")


# ── LangGraph Workflow Nodes ──

async def generate_landing_page_node(state: CampaignState) -> CampaignState:
    await publish_event(state["campaign_id"], "workflow_status", "Campaign Director",
                        "Delegating to Creative Producer", {"step": "generating_landing_page"})

    result = await call_a2a_agent(CREATIVE_PRODUCER_URL, "generate_landing_page", {
        "campaign_id": state["campaign_id"],
        "campaign_name": state["campaign_name"],
        "campaign_description": state["campaign_description"],
        "hotel_name": state["hotel_name"],
        "theme": state["theme"],
        "start_date": state["start_date"],
        "end_date": state["end_date"]
    })

    if result.get("status") == "error":
        state["error_message"] = result.get("error", "Unknown error")
        state["status"] = "failed"
    else:
        state["landing_page_html"] = result.get("html", "")
        state["messages"] = [{"role": "assistant", "agent": "Creative Producer",
                              "content": "Landing page generated successfully"}]
    return state


async def deploy_preview_node(state: CampaignState) -> CampaignState:
    await publish_event(state["campaign_id"], "workflow_status", "Campaign Director",
                        "Deploying preview", {"step": "deploying_preview"})
    try:
        result = await call_a2a_agent(DELIVERY_MANAGER_URL, "deploy_preview", {
            "campaign_id": state["campaign_id"],
            "html_content": state["landing_page_html"],
            "namespace": DEV_NAMESPACE
        })
        if result.get("status") == "error":
            error_msg = result.get("error", "Unknown error")
            if "Kubernetes" in error_msg:
                state["preview_url"] = f"local://preview/{state['campaign_id']}"
                state["status"] = "preview_ready"
                state["messages"] = [{"role": "assistant", "agent": "Delivery Manager",
                                      "content": "Preview ready (local mode - K8s deployment skipped)"}]
            else:
                state["error_message"] = error_msg
                state["status"] = "failed"
        else:
            state["preview_url"] = result.get("preview_url", "")
            state["status"] = "preview_ready"
            state["messages"] = [{"role": "assistant", "agent": "Delivery Manager",
                                  "content": f"Preview deployed at {state['preview_url']}"}]
    except Exception:
        state["preview_url"] = f"local://preview/{state['campaign_id']}"
        state["status"] = "preview_ready"
        state["messages"] = [{"role": "assistant", "agent": "Delivery Manager",
                              "content": "Preview ready (local mode - K8s deployment skipped)"}]
    return state


async def retrieve_customers_node(state: CampaignState) -> CampaignState:
    await publish_event(state["campaign_id"], "workflow_status", "Campaign Director",
                        "Retrieving customers", {"step": "retrieving_customers"})

    result = await call_a2a_agent(CUSTOMER_ANALYST_URL, "get_target_customers", {
        "campaign_id": state["campaign_id"],
        "target_audience": state["target_audience"],
        "limit": 50
    })

    if result.get("status") == "error":
        state["error_message"] = result.get("error", "Unknown error")
        state["status"] = "failed"
    else:
        state["customer_list"] = result.get("customers", [])
        state["customer_count"] = result.get("count", 0)
        state["messages"] = [{"role": "assistant", "agent": "Customer Analyst",
                              "content": f"Retrieved {state['customer_count']} {result.get('recipient_type', 'customers')}"}]
    return state


async def generate_email_node(state: CampaignState) -> CampaignState:
    await publish_event(state["campaign_id"], "workflow_status", "Campaign Director",
                        "Generating email content", {"step": "generating_email"})

    result = await call_a2a_agent(DELIVERY_MANAGER_URL, "generate_email", {
        "campaign_id": state["campaign_id"],
        "campaign_name": state["campaign_name"],
        "campaign_description": state["campaign_description"],
        "hotel_name": state["hotel_name"],
        "campaign_url": state["preview_url"],
        "target_audience": state["target_audience"],
        "start_date": state["start_date"],
        "end_date": state["end_date"]
    })

    if result.get("status") == "error":
        state["error_message"] = result.get("error", "Unknown error")
        state["status"] = "failed"
    else:
        state["email_subject_en"] = result.get("email_subject_en", "")
        state["email_body_en"] = result.get("email_body_en", "")
        state["email_subject_zh"] = result.get("email_subject_zh", "")
        state["email_body_zh"] = result.get("email_body_zh", "")
        state["status"] = "email_ready"
        state["messages"] = [{"role": "assistant", "agent": "Delivery Manager",
                              "content": "Email content generated in English and Chinese"}]
    return state


async def deploy_production_node(state: CampaignState) -> CampaignState:
    await publish_event(state["campaign_id"], "workflow_status", "Campaign Director",
                        "Deploying to production", {"step": "deploying_production"})
    try:
        result = await call_a2a_agent(DELIVERY_MANAGER_URL, "deploy_production", {
            "campaign_id": state["campaign_id"],
            "html_content": state["landing_page_html"],
            "namespace": PROD_NAMESPACE
        })
        if result.get("status") == "error":
            error_msg = result.get("error", "Unknown error")
            if "Kubernetes" in error_msg:
                state["production_url"] = f"local://production/{state['campaign_id']}"
                state["messages"] = [{"role": "assistant", "agent": "Delivery Manager",
                                      "content": "Production ready (local mode)"}]
            else:
                state["error_message"] = error_msg
                state["status"] = "failed"
        else:
            state["production_url"] = result.get("production_url", "")
            state["messages"] = [{"role": "assistant", "agent": "Delivery Manager",
                                  "content": f"Production deployed at {state['production_url']}"}]
    except Exception:
        state["production_url"] = f"local://production/{state['campaign_id']}"
        state["messages"] = [{"role": "assistant", "agent": "Delivery Manager",
                              "content": "Production ready (local mode)"}]
    return state


async def send_emails_node(state: CampaignState) -> CampaignState:
    await publish_event(state["campaign_id"], "workflow_status", "Campaign Director",
                        "Sending emails", {"step": "sending_emails"})

    customers = [CustomerProfile(**c) for c in state["customer_list"]]
    result = await call_a2a_agent(DELIVERY_MANAGER_URL, "send_emails", {
        "campaign_id": state["campaign_id"],
        "customers": [c.model_dump() for c in customers],
        "email_subject_en": state["email_subject_en"],
        "email_body_en": state["email_body_en"],
        "email_subject_zh": state["email_subject_zh"],
        "email_body_zh": state["email_body_zh"]
    })

    if result.get("status") == "error":
        state["error_message"] = result.get("error", "Unknown error")
        state["status"] = "failed"
    else:
        state["status"] = "live"
        state["messages"] = [{"role": "assistant", "agent": "Delivery Manager",
                              "content": f"Sent {result.get('sent_count', 0)} emails (simulated)"}]
    return state


# ── Workflow Builders ──

def build_landing_page_workflow():
    workflow = StateGraph(CampaignState)
    workflow.add_node("generate_landing_page", generate_landing_page_node)
    workflow.add_node("deploy_preview", deploy_preview_node)
    workflow.add_edge(START, "generate_landing_page")
    workflow.add_edge("generate_landing_page", "deploy_preview")
    workflow.add_edge("deploy_preview", END)
    return workflow.compile()

def build_email_preview_workflow():
    workflow = StateGraph(CampaignState)
    workflow.add_node("retrieve_customers", retrieve_customers_node)
    workflow.add_node("generate_email", generate_email_node)
    workflow.add_edge(START, "retrieve_customers")
    workflow.add_edge("retrieve_customers", "generate_email")
    workflow.add_edge("generate_email", END)
    return workflow.compile()

def build_go_live_workflow():
    workflow = StateGraph(CampaignState)
    workflow.add_node("deploy_production", deploy_production_node)
    workflow.add_node("send_emails", send_emails_node)
    workflow.add_edge(START, "deploy_production")
    workflow.add_edge("deploy_production", "send_emails")
    workflow.add_edge("send_emails", END)
    return workflow.compile()


# ── Background Workflow Runners ──

async def _run_landing_page_workflow(campaign_id: str, campaign):
    try:
        initial_state: CampaignState = {
            "campaign_id": campaign_id,
            "campaign_name": campaign.campaign_name,
            "campaign_description": campaign.campaign_description,
            "hotel_name": campaign.hotel_name,
            "target_audience": campaign.target_audience,
            "theme": campaign.theme,
            "start_date": campaign.start_date,
            "end_date": campaign.end_date,
            "status": "generating",
            "landing_page_html": "", "preview_url": "", "production_url": "",
            "email_subject_en": "", "email_body_en": "",
            "email_subject_zh": "", "email_body_zh": "",
            "customer_list": [], "customer_count": 0,
            "error_message": "", "messages": []
        }
        workflow = build_landing_page_workflow()
        final_state = await workflow.ainvoke(initial_state)
        campaign.landing_page_html = final_state.get("landing_page_html", "")
        campaign.preview_url = final_state.get("preview_url", "")
        campaign.status = CampaignStatus(final_state.get("status", "preview_ready"))
        campaign.error_message = final_state.get("error_message")
    except Exception as e:
        print(f"[Campaign Director] Landing page workflow error: {type(e).__name__}: {e}\n{traceback.format_exc()}")
        campaign.status = CampaignStatus.FAILED
        campaign.error_message = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__


async def _run_email_preview_workflow(campaign_id: str, campaign):
    try:
        initial_state: CampaignState = {
            "campaign_id": campaign_id,
            "campaign_name": campaign.campaign_name,
            "campaign_description": campaign.campaign_description,
            "hotel_name": campaign.hotel_name,
            "target_audience": campaign.target_audience,
            "theme": campaign.theme,
            "start_date": campaign.start_date,
            "end_date": campaign.end_date,
            "status": campaign.status.value,
            "landing_page_html": campaign.landing_page_html or "",
            "preview_url": campaign.preview_url or "",
            "production_url": campaign.production_url or "",
            "email_subject_en": "", "email_body_en": "",
            "email_subject_zh": "", "email_body_zh": "",
            "customer_list": [], "customer_count": 0,
            "error_message": "", "messages": []
        }
        workflow = build_email_preview_workflow()
        final_state = await workflow.ainvoke(initial_state)
        campaign.email_subject_en = final_state.get("email_subject_en", "")
        campaign.email_body_en = final_state.get("email_body_en", "")
        campaign.email_subject_zh = final_state.get("email_subject_zh", "")
        campaign.email_body_zh = final_state.get("email_body_zh", "")
        campaign.customer_list = [CustomerProfile(**c) for c in final_state.get("customer_list", [])]
        campaign.customer_count = final_state.get("customer_count", 0)
        campaign.status = CampaignStatus(final_state.get("status", "email_ready"))
        campaign.error_message = final_state.get("error_message")
    except Exception as e:
        print(f"[Campaign Director] Email preview workflow error: {type(e).__name__}: {e}\n{traceback.format_exc()}")
        campaign.status = CampaignStatus.FAILED
        campaign.error_message = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__


async def _run_go_live_workflow(campaign_id: str, campaign):
    try:
        initial_state: CampaignState = {
            "campaign_id": campaign_id,
            "campaign_name": campaign.campaign_name,
            "campaign_description": campaign.campaign_description,
            "hotel_name": campaign.hotel_name,
            "target_audience": campaign.target_audience,
            "theme": campaign.theme,
            "start_date": campaign.start_date,
            "end_date": campaign.end_date,
            "status": "approved",
            "landing_page_html": campaign.landing_page_html or "",
            "preview_url": campaign.preview_url or "",
            "production_url": "",
            "email_subject_en": campaign.email_subject_en or "",
            "email_body_en": campaign.email_body_en or "",
            "email_subject_zh": campaign.email_subject_zh or "",
            "email_body_zh": campaign.email_body_zh or "",
            "customer_list": [c.model_dump() for c in campaign.customer_list],
            "customer_count": campaign.customer_count,
            "error_message": "", "messages": []
        }
        workflow = build_go_live_workflow()
        final_state = await workflow.ainvoke(initial_state)
        campaign.production_url = final_state.get("production_url", "")
        campaign.status = CampaignStatus(final_state.get("status", "live"))
        campaign.error_message = final_state.get("error_message")
    except Exception as e:
        print(f"[Campaign Director] Go live workflow error: {type(e).__name__}: {e}\n{traceback.format_exc()}")
        campaign.status = CampaignStatus.FAILED
        campaign.error_message = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__


class CampaignDirectorAgent:
    """Handles campaign management and workflow orchestration."""

    async def handle_skill(self, skill: str, params: dict) -> dict:
        if skill == "create_campaign":
            return await self._create_campaign(params)
        elif skill == "generate_landing_page":
            return await self._generate_landing_page(params)
        elif skill == "prepare_email_preview":
            return await self._prepare_email_preview(params)
        elif skill == "go_live":
            return await self._go_live(params)
        else:
            return {"error": f"Unknown skill: {skill}"}

    async def _create_campaign(self, params: dict) -> dict:
        req = CampaignRequest(**params)
        campaign_id = str(uuid.uuid4())[:8]
        campaign = CampaignData(
            id=campaign_id,
            campaign_name=req.campaign_name,
            campaign_description=req.campaign_description,
            hotel_name=req.hotel_name,
            target_audience=req.target_audience,
            theme=req.theme.value if hasattr(req.theme, 'value') else req.theme,
            start_date=req.start_date,
            end_date=req.end_date,
            status=CampaignStatus.DRAFT
        )
        campaigns_store[campaign_id] = campaign
        await publish_event(campaign_id, "campaign_created", "Campaign Director",
                            "Campaign created", {"campaign_id": campaign_id})
        return {"campaign_id": campaign_id, "status": "created"}

    async def _generate_landing_page(self, params: dict) -> dict:
        campaign_id = params.get("campaign_id")
        if not campaign_id or campaign_id not in campaigns_store:
            return {"error": "Campaign not found"}
        campaign = campaigns_store[campaign_id]
        campaign.status = CampaignStatus.GENERATING
        asyncio.create_task(_run_landing_page_workflow(campaign_id, campaign))
        return {"campaign_id": campaign_id, "status": "generating", "preview_url": "", "error": None}

    async def _prepare_email_preview(self, params: dict) -> dict:
        campaign_id = params.get("campaign_id")
        if not campaign_id or campaign_id not in campaigns_store:
            return {"error": "Campaign not found"}
        campaign = campaigns_store[campaign_id]
        asyncio.create_task(_run_email_preview_workflow(campaign_id, campaign))
        return {"campaign_id": campaign_id, "status": "preparing_email", "customer_count": 0, "error": None}

    async def _go_live(self, params: dict) -> dict:
        campaign_id = params.get("campaign_id")
        if not campaign_id or campaign_id not in campaigns_store:
            return {"error": "Campaign not found"}
        campaign = campaigns_store[campaign_id]
        campaign.status = CampaignStatus.APPROVED
        asyncio.create_task(_run_go_live_workflow(campaign_id, campaign))
        return {"campaign_id": campaign_id, "status": "deploying", "production_url": "", "emails_sent": 0, "error": None}
