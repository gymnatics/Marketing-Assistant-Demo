#!/usr/bin/env python3
"""
A2A Server (Producer) with MLflow tracing.

Receives traceparent via params, continues the trace with
set_tracing_context_from_http_request_headers, creates spans.

Usage:
    export OTEL_INSTRUMENTATION_A2A_SDK_ENABLED=false
    python a2a_server.py

Server runs on port 8091 by default. Change with --port flag.
"""

import asyncio
import json
import os
import sys
import uuid
from contextlib import nullcontext

import mlflow
from mlflow.tracing import set_tracing_context_from_http_request_headers

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import (
    AgentCard, AgentSkill, AgentCapabilities,
    Artifact, Part, TextPart,
)
from a2a.server.tasks import InMemoryTaskStore
import uvicorn


PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8091
MLFLOW_URI = os.environ.get(
    "MLFLOW_TRACKING_URI",
    f"sqlite:///{os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_a2a.db')}"
)
EXPERIMENT = os.environ.get("MLFLOW_EXPERIMENT_NAME", "a2a-tracing-test")


class ProducerAgent:
    async def generate(self, params: dict) -> dict:
        with mlflow.start_span(name="producer_generate", span_type="AGENT") as span:
            span.set_inputs(params)

            with mlflow.start_span(name="hero_image_gen", span_type="TOOL") as img:
                img.set_inputs({"mcp": "imagegen", "theme": params.get("theme", "luxury_gold")})
                await asyncio.sleep(0.5)
                img.set_outputs({"url": "http://imagegen-mcp:8091/images/hero.png"})

            with mlflow.start_span(name="html_generation", span_type="LLM") as llm:
                llm.set_inputs({"model": "qwen25-coder-32b", "campaign": params.get("campaign_name", "")})
                await asyncio.sleep(1.0)
                html = "<html><body><h1>Campaign Landing Page</h1></body></html>"
                llm.set_outputs({"html_length": len(html)})

            result = {"html": html, "status": "success"}
            span.set_outputs(result)
        return result


class ProducerExecutor(AgentExecutor):
    def __init__(self):
        self.agent = ProducerAgent()

    async def execute(self, context: RequestContext, event_queue: EventQueue):
        user_msg = context.get_user_input()
        print(f"[Producer] Received: {user_msg[:200]}")

        try:
            params = json.loads(user_msg)
        except json.JSONDecodeError:
            params = {"text": user_msg}

        # Get traceparent from HTTP headers (stored by A2A SDK in call_context.state)
        http_headers = {}
        if context.call_context and context.call_context.state:
            http_headers = context.call_context.state.get("headers", {})
        traceparent = http_headers.get("traceparent")

        if traceparent:
            print(f"[Producer] traceparent from HTTP header: {traceparent}")
            ctx = set_tracing_context_from_http_request_headers({"traceparent": traceparent})
        else:
            print("[Producer] No traceparent in HTTP headers")
            ctx = nullcontext()

        with ctx:
            result = await self.agent.generate(params)

        event_queue.enqueue_event(
            Artifact(
                artifactId=str(uuid.uuid4()),
                parts=[Part(root=TextPart(text=json.dumps(result)))],
            )
        )
        print(f"[Producer] Done: {result['status']}")

    async def cancel(self, context: RequestContext, event_queue: EventQueue):
        pass


def main():
    mlflow.set_tracking_uri(MLFLOW_URI)
    mlflow.set_experiment(EXPERIMENT)
    print(f"[Producer] MLflow URI: {MLFLOW_URI}")
    print(f"[Producer] Experiment: {EXPERIMENT}")
    print(f"[Producer] OTEL_INSTRUMENTATION_A2A_SDK_ENABLED={os.environ.get('OTEL_INSTRUMENTATION_A2A_SDK_ENABLED', 'not set')}")

    agent_card = AgentCard(
        name="Test Creative Producer",
        description="A2A test producer with MLflow tracing",
        url=f"http://localhost:{PORT}/",
        version="1.0.0",
        defaultInputModes=["text", "text/plain"],
        defaultOutputModes=["text", "text/plain"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[AgentSkill(
            id="generate_landing_page",
            name="Generate Landing Page",
            description="Generate a campaign landing page",
            tags=["creative"],
        )],
    )

    handler = DefaultRequestHandler(
        agent_executor=ProducerExecutor(),
        task_store=InMemoryTaskStore(),
    )
    server = A2AStarletteApplication(agent_card=agent_card, http_handler=handler)
    app = server.build()

    print(f"[Producer] Starting on port {PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")


if __name__ == "__main__":
    main()
