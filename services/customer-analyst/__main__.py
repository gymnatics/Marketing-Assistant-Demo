"""
Customer Analyst A2A Server - Entry point.
"""
import logging
import os

import uvicorn

_log_level = getattr(
    logging,
    os.environ.get("LOG_LEVEL", "INFO").upper(),
    logging.INFO,
)
logging.basicConfig(
    level=_log_level,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCard, AgentSkill, AgentCapabilities, SecurityScheme, HTTPAuthSecurityScheme
from starlette.routing import Route
from starlette.responses import JSONResponse

from agent_executor import CustomerAnalystExecutor

host = "0.0.0.0"
port = int(os.environ.get("PORT", 8082))

agent_card = AgentCard(
    name="Customer Analyst",
    description="Retrieves VIP customer profiles for marketing campaign targeting via MCP",
    url=os.getenv("AGENT_ENDPOINT", f"http://{host}:{port}").rstrip("/") + "/",
    version="1.0.0",
    defaultInputModes=["text", "text/plain"],
    defaultOutputModes=["text", "text/plain"],
    capabilities=AgentCapabilities(streaming=True),
    skills=[
        AgentSkill(
            id="get_target_customers",
            name="Get Target Customers",
            description="Retrieve customers matching target audience criteria",
            tags=["customers", "targeting", "vip"],
            examples=["Get all Platinum tier VIP customers"],
        )
    ],
    securitySchemes={
        "Bearer": SecurityScheme(root=HTTPAuthSecurityScheme(
            type="http", scheme="bearer", bearerFormat="JWT", description="OAuth 2.0 JWT token"
        ))
    },
)

http_handler = DefaultRequestHandler(
    agent_executor=CustomerAnalystExecutor(),
    task_store=InMemoryTaskStore(),
)

server = A2AStarletteApplication(agent_card=agent_card, http_handler=http_handler)
app = server.build()


async def health_check(request):
    return JSONResponse({"status": "healthy", "agent": "Customer Analyst"})


app.routes.insert(0, Route("/.well-known/agent-card.json", server._handle_get_agent_card, methods=["GET"]))
app.routes.insert(1, Route("/healthz", health_check, methods=["GET"]))
app.routes.insert(1, Route("/readyz", health_check, methods=["GET"]))

if __name__ == "__main__":
    uvicorn.run(app, host=host, port=port)
