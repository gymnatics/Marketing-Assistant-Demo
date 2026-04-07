"""
Campaign Director A2A Server - Entry point.

Serves both A2A protocol (agent card, JSON-RPC) and REST endpoints for campaign management.
"""
import os
import json

import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCard, AgentSkill, AgentCapabilities, SecurityScheme, HTTPAuthSecurityScheme
from starlette.routing import Route
from starlette.responses import JSONResponse
from starlette.requests import Request

from shared.mlflow_bootstrap import ensure_mlflow_initialized
from agent_executor import CampaignDirectorExecutor
from agent import campaigns_store

ensure_mlflow_initialized()

host = "0.0.0.0"
port = int(os.environ.get("PORT", 8080))

agent_card = AgentCard(
    name="Campaign Director",
    description="Orchestrates marketing campaign creation workflow using LangGraph",
    url=os.getenv("AGENT_ENDPOINT", f"http://{host}:{port}").rstrip("/") + "/",
    version="1.0.0",
    defaultInputModes=["text", "text/plain"],
    defaultOutputModes=["text", "text/plain"],
    capabilities=AgentCapabilities(streaming=True),
    skills=[
        AgentSkill(
            id="create_campaign",
            name="Create Campaign",
            description="Create a new marketing campaign",
            tags=["campaign", "create"],
            examples=["Create a new Chinese New Year VIP campaign"],
        ),
        AgentSkill(
            id="generate_landing_page",
            name="Generate Landing Page",
            description="Generate landing page for an existing campaign",
            tags=["campaign", "landing-page", "generate"],
        ),
        AgentSkill(
            id="prepare_email_preview",
            name="Prepare Email Preview",
            description="Retrieve customers and generate email content for preview",
            tags=["campaign", "email", "preview"],
        ),
        AgentSkill(
            id="go_live",
            name="Go Live",
            description="Deploy campaign to production and send emails",
            tags=["campaign", "deploy", "launch"],
        ),
    ],
    securitySchemes={
        "Bearer": SecurityScheme(root=HTTPAuthSecurityScheme(
            type="http", scheme="bearer", bearerFormat="JWT", description="OAuth 2.0 JWT token"
        ))
    },
)

http_handler = DefaultRequestHandler(
    agent_executor=CampaignDirectorExecutor(),
    task_store=InMemoryTaskStore(),
)

server = A2AStarletteApplication(agent_card=agent_card, http_handler=http_handler)
app = server.build()


# ── Custom REST routes for campaign management (used by Campaign API) ──

async def health_check(request: Request):
    return JSONResponse({"status": "healthy", "agent": "Campaign Director"})

async def list_campaigns(request: Request):
    return JSONResponse([c.model_dump(mode="json") for c in campaigns_store.values()])

async def get_campaign(request: Request):
    campaign_id = request.path_params["campaign_id"]
    if campaign_id not in campaigns_store:
        return JSONResponse({"error": "Campaign not found"}, status_code=404)
    return JSONResponse(campaigns_store[campaign_id].model_dump(mode="json"))


app.routes.insert(0, Route("/.well-known/agent-card.json", server._handle_get_agent_card, methods=["GET"]))
app.routes.insert(1, Route("/healthz", health_check, methods=["GET"]))
app.routes.insert(1, Route("/readyz", health_check, methods=["GET"]))
app.routes.insert(2, Route("/campaigns", list_campaigns, methods=["GET"]))
app.routes.insert(3, Route("/campaigns/{campaign_id}", get_campaign, methods=["GET"]))

if __name__ == "__main__":
    uvicorn.run(app, host=host, port=port)
