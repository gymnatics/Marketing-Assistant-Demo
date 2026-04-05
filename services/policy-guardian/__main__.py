"""Policy Guardian Agent — Entry point with A2A AgentCard."""
import os
import uvicorn
from starlette.routing import Route
from starlette.responses import JSONResponse

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCard, AgentSkill, AgentCapabilities, SecurityScheme, HTTPAuthSecurityScheme

from agent_executor import PolicyGuardianExecutor

port = int(os.environ.get("PORT", 8084))
host = "0.0.0.0"

agent_card = AgentCard(
    name="Policy Guardian",
    description="Validates marketing campaign content against business policies using LLM reasoning",
    url=os.getenv("AGENT_ENDPOINT", f"http://{host}:{port}").rstrip("/") + "/",
    version="1.0.0",
    defaultInputModes=["text", "text/plain"],
    defaultOutputModes=["text", "text/plain"],
    capabilities=AgentCapabilities(streaming=False),
    skills=[
        AgentSkill(
            id="validate_campaign",
            name="Validate Campaign",
            description="Check campaign name and description against business policies",
            tags=["policy", "guardrails", "validation"],
        ),
    ],
    securitySchemes={
        "Bearer": SecurityScheme(root=HTTPAuthSecurityScheme(
            type="http", scheme="bearer", bearerFormat="JWT", description="OAuth 2.0 JWT token"
        ))
    },
)

handler = DefaultRequestHandler(
    agent_executor=PolicyGuardianExecutor(),
    task_store=InMemoryTaskStore(),
)

server = A2AStarletteApplication(agent_card=agent_card, http_handler=handler)
app = server.build()


async def health_check(request):
    return JSONResponse({"status": "healthy", "agent": "Policy Guardian"})


app.routes.insert(0, Route("/.well-known/agent-card.json", server._handle_get_agent_card, methods=["GET"]))
app.routes.insert(1, Route("/healthz", health_check, methods=["GET"]))
app.routes.insert(1, Route("/readyz", health_check, methods=["GET"]))

if __name__ == "__main__":
    uvicorn.run(app, host=host, port=port)
