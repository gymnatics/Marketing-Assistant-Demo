"""
Creative Producer A2A Server - Entry point.
"""
import os

import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCard, AgentSkill, AgentCapabilities, SecurityScheme, HTTPAuthSecurityScheme
from starlette.routing import Route
from starlette.responses import JSONResponse

from agent_executor import CreativeProducerExecutor

host = "0.0.0.0"
port = int(os.environ.get("PORT", 8081))

agent_card = AgentCard(
    name="Creative Producer",
    description="Generates luxury marketing landing pages with HTML/CSS/JS",
    url=os.getenv("AGENT_ENDPOINT", f"http://{host}:{port}").rstrip("/") + "/",
    version="1.0.0",
    defaultInputModes=["text", "text/plain"],
    defaultOutputModes=["text", "text/plain"],
    capabilities=AgentCapabilities(streaming=True),
    skills=[
        AgentSkill(
            id="generate_landing_page",
            name="Generate Landing Page",
            description="Create a luxury marketing landing page for casino campaigns",
            tags=["html", "landing-page", "marketing"],
            examples=["Generate a Luxury Gold themed landing page for Simon Casino Resort"],
        )
    ],
    securitySchemes={
        "Bearer": SecurityScheme(root=HTTPAuthSecurityScheme(
            type="http", scheme="bearer", bearerFormat="JWT", description="OAuth 2.0 JWT token"
        ))
    },
)

http_handler = DefaultRequestHandler(
    agent_executor=CreativeProducerExecutor(),
    task_store=InMemoryTaskStore(),
)

server = A2AStarletteApplication(agent_card=agent_card, http_handler=http_handler)
app = server.build()


async def health_check(request):
    return JSONResponse({"status": "healthy", "agent": "Creative Producer"})


app.routes.insert(0, Route("/.well-known/agent-card.json", server._handle_get_agent_card, methods=["GET"]))
app.routes.insert(1, Route("/healthz", health_check, methods=["GET"]))
app.routes.insert(1, Route("/readyz", health_check, methods=["GET"]))

if __name__ == "__main__":
    uvicorn.run(app, host=host, port=port)
