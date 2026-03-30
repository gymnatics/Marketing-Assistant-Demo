"""
Campaign Director A2A Agent - Orchestrates the campaign creation workflow.

Uses LangGraph for workflow orchestration and A2A protocol to communicate
with specialized agents (Creative Producer, Customer Analyst, Delivery Manager).
"""
import os
import uuid
import asyncio
import httpx
from typing import TypedDict, Annotated, List, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import operator

from langgraph.graph import StateGraph, START, END

import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from shared.models import (
    CampaignRequest,
    CampaignData,
    CampaignStatus,
    CustomerProfile,
    CAMPAIGN_THEMES
)


app = FastAPI(title="Campaign Director Agent")

AGENT_CARD = {
    "name": "Campaign Director",
    "description": "Orchestrates marketing campaign creation workflow",
    "version": "1.0.0",
    "protocol_version": "0.3.0",
    "skills": [
        {
            "name": "create_campaign",
            "description": "Create a new marketing campaign through the full workflow",
            "input_schema": CampaignRequest.model_json_schema()
        },
        {
            "name": "generate_landing_page",
            "description": "Generate landing page for an existing campaign"
        },
        {
            "name": "prepare_email_preview",
            "description": "Retrieve customers and generate email content for preview"
        },
        {
            "name": "go_live",
            "description": "Deploy campaign to production and send emails"
        }
    ]
}

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


class InvokeRequest(BaseModel):
    skill: str
    params: dict


async def call_a2a_agent(agent_url: str, skill: str, params: dict) -> dict:
    """Call an A2A agent's skill."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(
            f"{agent_url}/a2a/invoke",
            json={"skill": skill, "params": params}
        )
        if response.status_code != 200:
            raise Exception(f"A2A call failed: {response.status_code} - {response.text}")
        return response.json()


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


async def generate_landing_page_node(state: CampaignState) -> CampaignState:
    """Generate landing page via Creative Producer agent."""
    await publish_event(
        campaign_id=state["campaign_id"],
        event_type="workflow_status",
        agent="Campaign Director",
        task="Delegating to Creative Producer",
        data={"step": "generating_landing_page"}
    )
    
    result = await call_a2a_agent(
        CREATIVE_PRODUCER_URL,
        "generate_landing_page",
        {
            "campaign_id": state["campaign_id"],
            "campaign_name": state["campaign_name"],
            "campaign_description": state["campaign_description"],
            "hotel_name": state["hotel_name"],
            "theme": state["theme"],
            "start_date": state["start_date"],
            "end_date": state["end_date"]
        }
    )
    
    if result.get("status") == "error":
        state["error_message"] = result.get("error", "Unknown error")
        state["status"] = "failed"
    else:
        state["landing_page_html"] = result.get("html", "")
        state["messages"] = [{
            "role": "assistant",
            "agent": "Creative Producer",
            "content": "Landing page generated successfully"
        }]
    
    return state


async def deploy_preview_node(state: CampaignState) -> CampaignState:
    """Deploy landing page to preview via Delivery Manager."""
    await publish_event(
        campaign_id=state["campaign_id"],
        event_type="workflow_status",
        agent="Campaign Director",
        task="Deploying preview",
        data={"step": "deploying_preview"}
    )
    
    try:
        result = await call_a2a_agent(
            DELIVERY_MANAGER_URL,
            "deploy_preview",
            {
                "campaign_id": state["campaign_id"],
                "html_content": state["landing_page_html"],
                "namespace": DEV_NAMESPACE
            }
        )
        
        if result.get("status") == "error":
            error_msg = result.get("error", "Unknown error")
            if "Could not configure Kubernetes" in error_msg or "Kubernetes" in error_msg:
                state["preview_url"] = f"local://preview/{state['campaign_id']}"
                state["status"] = "preview_ready"
                state["messages"] = [{
                    "role": "assistant",
                    "agent": "Delivery Manager",
                    "content": "Preview ready (local mode - K8s deployment skipped)"
                }]
            else:
                state["error_message"] = error_msg
                state["status"] = "failed"
        else:
            state["preview_url"] = result.get("preview_url", "")
            state["status"] = "preview_ready"
            state["messages"] = [{
                "role": "assistant",
                "agent": "Delivery Manager",
                "content": f"Preview deployed at {state['preview_url']}"
            }]
    except Exception as e:
        state["preview_url"] = f"local://preview/{state['campaign_id']}"
        state["status"] = "preview_ready"
        state["messages"] = [{
            "role": "assistant",
            "agent": "Delivery Manager",
            "content": "Preview ready (local mode - K8s deployment skipped)"
        }]
    
    return state


async def retrieve_customers_node(state: CampaignState) -> CampaignState:
    """Retrieve target customers via Customer Analyst."""
    await publish_event(
        campaign_id=state["campaign_id"],
        event_type="workflow_status",
        agent="Campaign Director",
        task="Retrieving customers",
        data={"step": "retrieving_customers"}
    )
    
    result = await call_a2a_agent(
        CUSTOMER_ANALYST_URL,
        "get_target_customers",
        {
            "campaign_id": state["campaign_id"],
            "target_audience": state["target_audience"],
            "limit": 50
        }
    )
    
    if result.get("status") == "error":
        state["error_message"] = result.get("error", "Unknown error")
        state["status"] = "failed"
    else:
        state["customer_list"] = result.get("customers", [])
        state["customer_count"] = result.get("count", 0)
        state["messages"] = [{
            "role": "assistant",
            "agent": "Customer Analyst",
            "content": f"Retrieved {state['customer_count']} {result.get('recipient_type', 'customers')}"
        }]
    
    return state


async def generate_email_node(state: CampaignState) -> CampaignState:
    """Generate email content via Delivery Manager."""
    await publish_event(
        campaign_id=state["campaign_id"],
        event_type="workflow_status",
        agent="Campaign Director",
        task="Generating email content",
        data={"step": "generating_email"}
    )
    
    result = await call_a2a_agent(
        DELIVERY_MANAGER_URL,
        "generate_email",
        {
            "campaign_id": state["campaign_id"],
            "campaign_name": state["campaign_name"],
            "campaign_description": state["campaign_description"],
            "hotel_name": state["hotel_name"],
            "campaign_url": state["preview_url"],
            "target_audience": state["target_audience"],
            "start_date": state["start_date"],
            "end_date": state["end_date"]
        }
    )
    
    if result.get("status") == "error":
        state["error_message"] = result.get("error", "Unknown error")
        state["status"] = "failed"
    else:
        state["email_subject_en"] = result.get("email_subject_en", "")
        state["email_body_en"] = result.get("email_body_en", "")
        state["email_subject_zh"] = result.get("email_subject_zh", "")
        state["email_body_zh"] = result.get("email_body_zh", "")
        state["status"] = "email_ready"
        state["messages"] = [{
            "role": "assistant",
            "agent": "Delivery Manager",
            "content": "Email content generated in English and Chinese"
        }]
    
    return state


async def deploy_production_node(state: CampaignState) -> CampaignState:
    """Deploy to production via Delivery Manager."""
    await publish_event(
        campaign_id=state["campaign_id"],
        event_type="workflow_status",
        agent="Campaign Director",
        task="Deploying to production",
        data={"step": "deploying_production"}
    )
    
    try:
        result = await call_a2a_agent(
            DELIVERY_MANAGER_URL,
            "deploy_production",
            {
                "campaign_id": state["campaign_id"],
                "html_content": state["landing_page_html"],
                "namespace": PROD_NAMESPACE
            }
        )
        
        if result.get("status") == "error":
            error_msg = result.get("error", "Unknown error")
            if "Could not configure Kubernetes" in error_msg or "Kubernetes" in error_msg:
                state["production_url"] = f"local://production/{state['campaign_id']}"
                state["messages"] = [{
                    "role": "assistant",
                    "agent": "Delivery Manager",
                    "content": "Production ready (local mode - K8s deployment skipped)"
                }]
            else:
                state["error_message"] = error_msg
                state["status"] = "failed"
        else:
            state["production_url"] = result.get("production_url", "")
            state["messages"] = [{
                "role": "assistant",
                "agent": "Delivery Manager",
                "content": f"Production deployed at {state['production_url']}"
            }]
    except Exception as e:
        state["production_url"] = f"local://production/{state['campaign_id']}"
        state["messages"] = [{
            "role": "assistant",
            "agent": "Delivery Manager",
            "content": "Production ready (local mode - K8s deployment skipped)"
        }]
    
    return state


async def send_emails_node(state: CampaignState) -> CampaignState:
    """Send emails via Delivery Manager."""
    await publish_event(
        campaign_id=state["campaign_id"],
        event_type="workflow_status",
        agent="Campaign Director",
        task="Sending emails",
        data={"step": "sending_emails"}
    )
    
    customers = [CustomerProfile(**c) for c in state["customer_list"]]
    
    result = await call_a2a_agent(
        DELIVERY_MANAGER_URL,
        "send_emails",
        {
            "campaign_id": state["campaign_id"],
            "customers": [c.model_dump() for c in customers],
            "email_subject_en": state["email_subject_en"],
            "email_body_en": state["email_body_en"],
            "email_subject_zh": state["email_subject_zh"],
            "email_body_zh": state["email_body_zh"]
        }
    )
    
    if result.get("status") == "error":
        state["error_message"] = result.get("error", "Unknown error")
        state["status"] = "failed"
    else:
        state["status"] = "live"
        state["messages"] = [{
            "role": "assistant",
            "agent": "Delivery Manager",
            "content": f"Sent {result.get('sent_count', 0)} emails (simulated)"
        }]
    
    return state


def build_landing_page_workflow():
    """Build workflow for generating landing page and deploying preview."""
    workflow = StateGraph(CampaignState)
    
    workflow.add_node("generate_landing_page", generate_landing_page_node)
    workflow.add_node("deploy_preview", deploy_preview_node)
    
    workflow.add_edge(START, "generate_landing_page")
    workflow.add_edge("generate_landing_page", "deploy_preview")
    workflow.add_edge("deploy_preview", END)
    
    return workflow.compile()


def build_email_preview_workflow():
    """Build workflow for retrieving customers and generating email."""
    workflow = StateGraph(CampaignState)
    
    workflow.add_node("retrieve_customers", retrieve_customers_node)
    workflow.add_node("generate_email", generate_email_node)
    
    workflow.add_edge(START, "retrieve_customers")
    workflow.add_edge("retrieve_customers", "generate_email")
    workflow.add_edge("generate_email", END)
    
    return workflow.compile()


def build_go_live_workflow():
    """Build workflow for deploying to production and sending emails."""
    workflow = StateGraph(CampaignState)
    
    workflow.add_node("deploy_production", deploy_production_node)
    workflow.add_node("send_emails", send_emails_node)
    
    workflow.add_edge(START, "deploy_production")
    workflow.add_edge("deploy_production", "send_emails")
    workflow.add_edge("send_emails", END)
    
    return workflow.compile()


async def _run_landing_page_workflow(campaign_id: str, campaign):
    """Background task: generate landing page and deploy preview."""
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
        print(f"[Campaign Director] Landing page workflow error: {e}")
        campaign.status = CampaignStatus.FAILED
        campaign.error_message = str(e)


async def _run_email_preview_workflow(campaign_id: str, campaign):
    """Background task: retrieve customers and generate emails."""
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
        print(f"[Campaign Director] Email preview workflow error: {e}")
        campaign.status = CampaignStatus.FAILED
        campaign.error_message = str(e)


async def _run_go_live_workflow(campaign_id: str, campaign):
    """Background task: deploy to production and send emails."""
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
        print(f"[Campaign Director] Go live workflow error: {e}")
        campaign.status = CampaignStatus.FAILED
        campaign.error_message = str(e)


@app.get("/.well-known/agent-card.json")
async def get_agent_card():
    """Return agent capabilities for A2A discovery."""
    return JSONResponse(content=AGENT_CARD)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "agent": "Campaign Director"}


@app.get("/campaigns")
async def list_campaigns():
    """List all campaigns."""
    return list(campaigns_store.values())


@app.get("/campaigns/{campaign_id}")
async def get_campaign(campaign_id: str):
    """Get campaign by ID."""
    if campaign_id not in campaigns_store:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaigns_store[campaign_id]


@app.post("/a2a/invoke")
async def invoke_skill(request: InvokeRequest):
    """Invoke an agent skill via A2A protocol."""
    
    if request.skill == "create_campaign":
        try:
            params = CampaignRequest(**request.params)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid parameters: {e}")
        
        campaign_id = str(uuid.uuid4())[:8]
        
        campaign = CampaignData(
            id=campaign_id,
            campaign_name=params.campaign_name,
            campaign_description=params.campaign_description,
            hotel_name=params.hotel_name,
            target_audience=params.target_audience,
            theme=params.theme.value if hasattr(params.theme, 'value') else params.theme,
            start_date=params.start_date,
            end_date=params.end_date,
            status=CampaignStatus.DRAFT
        )
        
        campaigns_store[campaign_id] = campaign
        
        await publish_event(
            campaign_id=campaign_id,
            event_type="campaign_created",
            agent="Campaign Director",
            task="Campaign created",
            data={"campaign_id": campaign_id}
        )
        
        return {"campaign_id": campaign_id, "status": "created"}
    
    elif request.skill == "generate_landing_page":
        campaign_id = request.params.get("campaign_id")
        if not campaign_id or campaign_id not in campaigns_store:
            raise HTTPException(status_code=404, detail="Campaign not found")
        
        campaign = campaigns_store[campaign_id]
        campaign.status = CampaignStatus.GENERATING
        
        asyncio.create_task(_run_landing_page_workflow(campaign_id, campaign))
        
        return {
            "campaign_id": campaign_id,
            "status": "generating",
            "preview_url": "",
            "error": None
        }
    
    elif request.skill == "prepare_email_preview":
        campaign_id = request.params.get("campaign_id")
        if not campaign_id or campaign_id not in campaigns_store:
            raise HTTPException(status_code=404, detail="Campaign not found")
        
        campaign = campaigns_store[campaign_id]
        
        asyncio.create_task(_run_email_preview_workflow(campaign_id, campaign))
        
        return {
            "campaign_id": campaign_id,
            "status": "preparing_email",
            "customer_count": 0,
            "error": None
        }
    
    elif request.skill == "go_live":
        campaign_id = request.params.get("campaign_id")
        if not campaign_id or campaign_id not in campaigns_store:
            raise HTTPException(status_code=404, detail="Campaign not found")
        
        campaign = campaigns_store[campaign_id]
        campaign.status = CampaignStatus.APPROVED
        
        asyncio.create_task(_run_go_live_workflow(campaign_id, campaign))
        
        return {
            "campaign_id": campaign_id,
            "status": "deploying",
            "production_url": "",
            "emails_sent": 0,
            "error": None
        }
    
    else:
        raise HTTPException(status_code=400, detail=f"Unknown skill: {request.skill}")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
