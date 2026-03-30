"""
Delivery Manager A2A Server entry point.

Exposes four skills over the A2A protocol:
  - generate_email
  - deploy_preview
  - deploy_production
  - send_emails
"""
import os
import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.types import AgentCard, AgentSkill

from agent_executor import DeliveryManagerExecutor

PORT = int(os.environ.get("PORT", 8083))

SKILLS = [
    AgentSkill(
        id="generate_email",
        name="Generate Email",
        description="Generate marketing email content in English and Chinese",
        tags=["email", "marketing", "bilingual"],
        examples=[],
    ),
    AgentSkill(
        id="deploy_preview",
        name="Deploy Preview",
        description="Deploy campaign landing page to preview environment",
        tags=["deploy", "preview", "openshift"],
        examples=[],
    ),
    AgentSkill(
        id="deploy_production",
        name="Deploy Production",
        description="Deploy campaign landing page to production",
        tags=["deploy", "production", "openshift"],
        examples=[],
    ),
    AgentSkill(
        id="send_emails",
        name="Send Emails",
        description="Send marketing emails to customer list (simulated)",
        tags=["email", "send", "simulated"],
        examples=[],
    ),
]

AGENT_CARD = AgentCard(
    name="Delivery Manager",
    description="Generates marketing emails and deploys campaigns to OpenShift",
    version="1.0.0",
    url=f"http://localhost:{PORT}",
    skills=SKILLS,
    defaultInputModes=["text"],
    defaultOutputModes=["text"],
)


def build_app():
    executor = DeliveryManagerExecutor()
    handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=None,
    )
    app = A2AStarletteApplication(
        agent_card=AGENT_CARD,
        http_handler=handler,
    )

    starlette_app = app.build()

    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def health_check(request):
        return JSONResponse({"status": "healthy", "agent": "Delivery Manager"})

    starlette_app.routes.append(Route("/health", health_check))

    return starlette_app


if __name__ == "__main__":
    app = build_app()
    uvicorn.run(app, host="0.0.0.0", port=PORT)
