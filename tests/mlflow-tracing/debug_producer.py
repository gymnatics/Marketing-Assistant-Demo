#!/usr/bin/env python3
"""Quick debug: start producer, call it, inspect response."""
import asyncio
import json
import os
import subprocess
import sys
import time
import uuid

import httpx
from a2a.client import A2AClient
from a2a.types import MessageSendParams, SendMessageRequest

PRODUCER_CODE = r'''
import asyncio, json, os, sys, time
import mlflow
from mlflow.tracing import set_tracing_context_from_http_request_headers
from contextlib import nullcontext

DB_URI = sys.argv[1]
PORT = int(sys.argv[2])

mlflow.set_tracking_uri(DB_URI)
mlflow.set_experiment("debug")

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.agent_execution import AgentExecutor
from a2a.server.events import EventQueue
from a2a.types import AgentCard, AgentSkill, AgentCapabilities, Artifact, Part, TextPart
from a2a.server.tasks import InMemoryTaskStore
import uvicorn

class MyExecutor(AgentExecutor):
    async def execute(self, context, event_queue: EventQueue):
        user_msg = context.get_user_input()
        print(f"[Producer] Got message: {user_msg[:200]}")
        try:
            params = json.loads(user_msg)
        except:
            params = {"text": user_msg}

        traceparent = params.pop("_traceparent", None)
        if traceparent:
            ctx = set_tracing_context_from_http_request_headers({"traceparent": traceparent})
        else:
            ctx = nullcontext()

        with ctx:
            with mlflow.start_span(name="producer_work", span_type="AGENT") as span:
                span.set_inputs(params)
                await asyncio.sleep(0.5)
                result = {"html": "<html>test</html>", "status": "success"}
                span.set_outputs(result)

        event_queue.enqueue_event(
            Artifact(parts=[Part(root=TextPart(text=json.dumps(result)))])
        )
        print(f"[Producer] Enqueued artifact")

    async def cancel(self, context, event_queue):
        pass

card = AgentCard(
    name="Debug Producer", description="test", url=f"http://localhost:{PORT}/",
    version="1.0.0", defaultInputModes=["text"], defaultOutputModes=["text"],
    capabilities=AgentCapabilities(streaming=True),
    skills=[AgentSkill(id="gen", name="Gen", description="Gen", tags=["test"])]
)
handler = DefaultRequestHandler(agent_executor=MyExecutor(), task_store=InMemoryTaskStore())
server = A2AStarletteApplication(agent_card=card, http_handler=handler)
app = server.build()
uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
'''


async def main():
    port = 19878
    script = os.path.join(os.path.dirname(__file__), "_debug_producer.py")
    db = f"sqlite:///{os.path.join(os.path.dirname(os.path.abspath(__file__)), 'debug.db')}"

    with open(script, "w") as f:
        f.write(PRODUCER_CODE)

    env = os.environ.copy()
    env["OTEL_INSTRUMENTATION_A2A_SDK_ENABLED"] = "false"

    proc = subprocess.Popen(
        [sys.executable, script, db, str(port)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )

    # Wait for server
    for _ in range(20):
        try:
            async with httpx.AsyncClient() as c:
                r = await c.get(f"http://127.0.0.1:{port}/.well-known/agent.json", timeout=1)
                if r.status_code == 200:
                    break
        except:
            pass
        await asyncio.sleep(0.5)
    else:
        print("Server didn't start!")
        proc.terminate()
        proc.wait()
        print(proc.stderr.read().decode()[:1000])
        return

    print("Producer ready, sending request...")

    msg = MessageSendParams(message={
        "role": "user",
        "parts": [{"kind": "text", "text": json.dumps({
            "campaign_name": "Test",
            "_traceparent": "00-aaaabbbbccccddddeeee111122223333-1234567890abcdef-01"
        })}],
        "messageId": uuid.uuid4().hex,
    })
    req = SendMessageRequest(id=str(uuid.uuid4()), params=msg)

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as hc:
        client = A2AClient(httpx_client=hc, url=f"http://127.0.0.1:{port}")
        resp = await client.send_message(req)

    r = resp.root
    print(f"\nResponse type: {type(r).__name__}")

    if hasattr(r, "error") and r.error:
        print(f"A2A Error: {r.error}")

    result = getattr(r, "result", None)
    if result:
        print(f"Result type: {type(result).__name__}")
        print(f"Result fields: {[f for f in dir(result) if not f.startswith('_')]}")
        artifacts = getattr(result, "artifacts", None)
        print(f"Artifacts: {artifacts}")
        history = getattr(result, "history", None)
        if history:
            for msg in history:
                print(f"  History msg: {msg}")

    proc.terminate()
    proc.wait()
    print(f"\nProducer stdout:\n{proc.stdout.read().decode()}")
    stderr = proc.stderr.read().decode()
    if stderr:
        # Filter noise
        for line in stderr.splitlines():
            if "WARNING" not in line and "FutureWarning" not in line and "DeprecationWarning" not in line:
                print(f"  stderr: {line}")

    os.unlink(script)


if __name__ == "__main__":
    asyncio.run(main())
