"""
Delivery Manager A2A Server - Entry point.
"""
import os

import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCard, AgentSkill, AgentCapabilities
from starlette.routing import Route
from starlette.responses import JSONResponse

from agent_executor import DeliveryManagerExecutor

host = "0.0.0.0"
port = int(os.environ.get("PORT", 8083))

agent_card = AgentCard(
    name="Delivery Manager",
    description="Generates marketing emails and deploys campaigns to OpenShift",
    url=f"http://{host}:{port}/",
    version="1.0.0",
    defaultInputModes=["text", "text/plain"],
    defaultOutputModes=["text", "text/plain"],
    capabilities=AgentCapabilities(streaming=True),
    skills=[
        AgentSkill(id="generate_email", name="Generate Email",
                   description="Generate marketing email content in English and Chinese",
                   tags=["email", "marketing", "bilingual"]),
        AgentSkill(id="deploy_preview", name="Deploy Preview",
                   description="Deploy campaign landing page to preview environment",
                   tags=["deploy", "preview", "openshift"]),
        AgentSkill(id="deploy_production", name="Deploy Production",
                   description="Deploy campaign landing page to production",
                   tags=["deploy", "production", "openshift"]),
        AgentSkill(id="send_emails", name="Send Emails",
                   description="Send marketing emails to customer list (simulated)",
                   tags=["email", "send", "simulated"]),
    ],
)

http_handler = DefaultRequestHandler(
    agent_executor=DeliveryManagerExecutor(),
    task_store=InMemoryTaskStore(),
)

server = A2AStarletteApplication(agent_card=agent_card, http_handler=http_handler)
app = server.build()


async def health_check(request):
    return JSONResponse({"status": "healthy", "agent": "Delivery Manager"})


app.routes.insert(0, Route("/health", health_check, methods=["GET"]))

if __name__ == "__main__":
    uvicorn.run(app, host=host, port=port)
