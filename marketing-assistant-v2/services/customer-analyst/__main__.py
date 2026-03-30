"""
Customer Analyst A2A Agent - Entry point with AgentCard and health check.
"""
import os
import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from a2a.server.apps import A2AStarletteApplication
from a2a.types import AgentCard, AgentSkill

from agent_executor import CustomerAnalystExecutor


def build_agent_card(host: str, port: int) -> AgentCard:
    return AgentCard(
        name="Customer Analyst",
        description="Retrieves VIP customer profiles for marketing campaign targeting via MCP",
        version="1.0.0",
        url=f"http://{host}:{port}",
        skills=[
            AgentSkill(
                id="get_target_customers",
                name="Get Target Customers",
                description="Retrieve customers matching target audience criteria",
                tags=["customers", "targeting", "vip"],
            )
        ],
    )


async def health_check(request):
    return JSONResponse({"status": "healthy", "agent": "Customer Analyst"})


def main():
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8082"))

    agent_card = build_agent_card(host, port)
    executor = CustomerAnalystExecutor()

    a2a_app = A2AStarletteApplication(
        agent_card=agent_card,
        agent_executor=executor,
    )

    routes = a2a_app.routes() + [
        Route("/health", health_check, methods=["GET"]),
    ]

    app = Starlette(routes=routes)

    print(f"[Customer Analyst] Starting on {host}:{port}")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
