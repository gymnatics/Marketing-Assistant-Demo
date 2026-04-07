#!/usr/bin/env python3
"""
A2A SDK + MLflow Tracing End-to-End Test
========================================

Spins up a real A2A agent (producer) on localhost, then has a director
call it via A2A SDK client with traceparent header propagation.

Tests whether the A2A SDK's internal OTEL instrumentation interferes
with MLflow's cross-process tracing.

Scenarios:
  A) A2A SDK OTEL enabled  (OTEL_INSTRUMENTATION_A2A_SDK_ENABLED=true)
  B) A2A SDK OTEL disabled (OTEL_INSTRUMENTATION_A2A_SDK_ENABLED=false)

Run:  python test_a2a_tracing.py
"""

import asyncio
import json
import os
import signal
import sys
import time
import subprocess
import mlflow
from mlflow.tracing import get_tracing_context_headers_for_http_request

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_a2a.db")
DB_URI = f"sqlite:///{DB_PATH}"
EXPERIMENT = "a2a-tracing-test"
PRODUCER_PORT = 19876


# ── Producer A2A Server (runs as separate process) ──

PRODUCER_SERVER_CODE = r'''
import asyncio
import json
import os
import sys
import time

# Configure MLflow BEFORE importing a2a (so OTEL env var takes effect)
otel_enabled = os.environ.get("OTEL_INSTRUMENTATION_A2A_SDK_ENABLED", "true")
print(f"[Producer] OTEL_INSTRUMENTATION_A2A_SDK_ENABLED={otel_enabled}")

import mlflow
from mlflow.tracing import set_tracing_context_from_http_request_headers

DB_URI = sys.argv[1]
EXPERIMENT = sys.argv[2]
PORT = int(sys.argv[3])

mlflow.set_tracking_uri(DB_URI)
mlflow.set_experiment(EXPERIMENT)

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.agent_execution import AgentExecutor
from a2a.server.events import EventQueue
from a2a.types import AgentCard, AgentSkill, AgentCapabilities
from a2a.server.tasks import InMemoryTaskStore
import uvicorn


class ProducerAgent:
    async def generate(self, params: dict) -> dict:
        """Simulate creative producer work with MLflow spans."""
        try:
            with mlflow.start_span(name="producer_generate", span_type="AGENT") as span:
                span.set_inputs(params)

                with mlflow.start_span(name="hero_image_gen", span_type="TOOL") as img:
                    img.set_inputs({"mcp": "imagegen"})
                    await asyncio.sleep(0.3)
                    img.set_outputs({"url": "http://example.com/hero.png"})

                with mlflow.start_span(name="html_generation", span_type="LLM") as llm:
                    llm.set_inputs({"model": "qwen-coder"})
                    await asyncio.sleep(0.5)
                    llm.set_outputs({"html_length": 5000})

                result = {"html": "<html>test</html>", "status": "success"}
                span.set_outputs(result)
            return result
        except Exception as e:
            print(f"[Producer] generate() error: {e}")
            import traceback; traceback.print_exc()
            return {"html": "", "status": "error", "error": str(e)}


class ProducerExecutor(AgentExecutor):
    def __init__(self):
        self.agent = ProducerAgent()

    async def execute(self, context, event_queue: EventQueue):
        user_msg = context.get_user_input()
        try:
            params = json.loads(user_msg)
        except json.JSONDecodeError:
            params = {"text": user_msg}

        # Extract traceparent from the request context if available
        # In real deployment, headers come from the HTTP request
        # Here we check if traceparent was passed in the params
        traceparent = params.pop("_traceparent", None)
        if traceparent:
            print(f"[Producer] Using traceparent: {traceparent}")
            ctx = set_tracing_context_from_http_request_headers(
                {"traceparent": traceparent}
            )
        else:
            print("[Producer] No traceparent received")
            from contextlib import nullcontext
            ctx = nullcontext()

        with ctx:
            result = await self.agent.generate(params)

        from a2a.types import Artifact, Part, TextPart, Message
        event_queue.enqueue_event(
            Artifact(parts=[Part(root=TextPart(text=json.dumps(result)))])
        )

    async def cancel(self, context, event_queue: EventQueue):
        pass


agent_card = AgentCard(
    name="Test Producer",
    description="Test creative producer for tracing",
    url=f"http://localhost:{PORT}/",
    version="1.0.0",
    defaultInputModes=["text", "text/plain"],
    defaultOutputModes=["text", "text/plain"],
    capabilities=AgentCapabilities(streaming=True),
    skills=[AgentSkill(id="generate", name="Generate", description="Generate landing page", tags=["test"])]
)

handler = DefaultRequestHandler(
    agent_executor=ProducerExecutor(),
    task_store=InMemoryTaskStore()
)
server = A2AStarletteApplication(agent_card=agent_card, http_handler=handler)
app = server.build()

print(f"[Producer] Starting on port {PORT}")
uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
'''


async def call_a2a_agent(agent_url: str, params: dict, traceparent: str = "") -> dict:
    """Call A2A agent - mirrors the real call_a2a_agent from campaign-director."""
    import uuid
    import httpx
    from a2a.client import A2AClient
    from a2a.types import MessageSendParams, SendMessageRequest

    # Include traceparent in the params so the producer can extract it
    if traceparent:
        params["_traceparent"] = traceparent

    message_params = MessageSendParams(
        message={
            "role": "user",
            "parts": [{"kind": "text", "text": json.dumps(params)}],
            "messageId": uuid.uuid4().hex,
        }
    )
    request = SendMessageRequest(id=str(uuid.uuid4()), params=message_params)

    timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
    headers = {}
    if traceparent:
        headers["traceparent"] = traceparent

    async with httpx.AsyncClient(timeout=timeout, headers=headers) as httpx_client:
        client = A2AClient(httpx_client=httpx_client, url=agent_url)
        response = await client.send_message(request)

    resp = response.root
    if hasattr(resp, 'error') and resp.error:
        return {"status": "error", "error": str(resp.error)}

    task_result = resp.result if hasattr(resp, 'result') else None
    if task_result and hasattr(task_result, 'artifacts') and task_result.artifacts:
        for artifact in task_result.artifacts:
            for part in (artifact.parts or []):
                text = None
                if hasattr(part, 'root') and hasattr(part.root, 'text'):
                    text = part.root.text
                elif hasattr(part, 'text'):
                    text = part.text
                if text:
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        return {"status": "success", "content": text}

    return {"status": "error", "error": "No artifact returned"}


def start_producer(otel_enabled: bool) -> subprocess.Popen:
    """Start the producer A2A server as a separate process."""
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_a2a_producer.py")
    with open(script_path, "w") as f:
        f.write(PRODUCER_SERVER_CODE)

    env = os.environ.copy()
    env["OTEL_INSTRUMENTATION_A2A_SDK_ENABLED"] = "true" if otel_enabled else "false"

    proc = subprocess.Popen(
        [sys.executable, script_path, DB_URI, EXPERIMENT, str(PRODUCER_PORT)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return proc


async def wait_for_server(url: str, timeout: float = 10.0):
    """Wait for A2A server to be ready."""
    import httpx
    start = time.time()
    while time.time() - start < timeout:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{url}/.well-known/agent.json", timeout=2.0)
                if resp.status_code == 200:
                    return True
        except Exception:
            pass
        await asyncio.sleep(0.3)
    return False


def print_trace_tree(trace_id: str):
    trace = mlflow.get_trace(trace_id)
    if not trace or not trace.data or not trace.data.spans:
        print("    (no spans found)")
        return

    spans = trace.data.spans
    children = {}
    for s in spans:
        pid = s.parent_id or "ROOT"
        children.setdefault(pid, []).append(s)

    def print_span(span, depth=0):
        indent = "  " * depth
        connector = "├── " if depth > 0 else ""
        dur_ns = getattr(span, "end_time_ns", 0) or 0
        start_ns = getattr(span, "start_time_ns", 0) or 0
        duration = (dur_ns - start_ns) / 1e6 if dur_ns and start_ns else 0
        stype = getattr(span, "span_type", "?")
        print(f"    {indent}{connector}{span.name} ({stype}, {duration:.0f}ms)")
        for child in sorted(children.get(span.span_id, []),
                            key=lambda x: getattr(x, "start_time_ns", 0) or 0):
            print_span(child, depth + 1)

    for root in children.get("ROOT", []):
        print_span(root)


def print_all_traces():
    client = mlflow.MlflowClient()
    exp = client.get_experiment_by_name(EXPERIMENT)
    if not exp:
        print("  (no experiment found)")
        return
    traces = client.search_traces(experiment_ids=[exp.experiment_id])
    print(f"\n  Total traces in DB: {len(traces)}")
    for t in traces:
        info = t.info
        span_count = len(t.data.spans) if t.data and t.data.spans else 0
        print(f"\n    === {info.request_id}  status={info.status}  spans={span_count} ===")
        if t.data and t.data.spans:
            for s in sorted(t.data.spans, key=lambda x: getattr(x, "start_time_ns", 0)):
                stype = getattr(s, "span_type", "?")
                pid = (s.parent_id or "ROOT")[:12]
                dur = 0
                if getattr(s, "end_time_ns", 0) and getattr(s, "start_time_ns", 0):
                    dur = (s.end_time_ns - s.start_time_ns) / 1e6
                print(f"      {s.name:45s} type={stype:10s} parent={pid:12s} {dur:.0f}ms")


async def run_test(otel_enabled: bool):
    """Run a single test scenario."""
    mode = "ENABLED" if otel_enabled else "DISABLED"
    print(f"\n{'─' * 70}")
    print(f"  A2A SDK OTEL: {mode}")
    print(f"{'─' * 70}")

    # Start producer
    proc = start_producer(otel_enabled)
    try:
        print(f"  Starting producer (OTEL={mode})...")
        ready = await wait_for_server(f"http://127.0.0.1:{PRODUCER_PORT}")
        if not ready:
            print("  ✗ Producer failed to start!")
            stdout, stderr = proc.communicate(timeout=5)
            print(f"  stdout: {stdout.decode()[:500]}")
            print(f"  stderr: {stderr.decode()[:500]}")
            return

        print(f"  ✓ Producer ready")

        # Director calls producer with tracing
        @mlflow.trace(name=f"director_workflow_{mode.lower()}")
        async def director_run():
            mlflow.update_current_trace(tags={
                "test_scenario": f"a2a_otel_{mode.lower()}",
            })
            with mlflow.start_span(name="a2a_call_producer", span_type="AGENT") as span:
                span.set_inputs({"skill": "generate_landing_page"})
                headers = get_tracing_context_headers_for_http_request()
                traceparent = headers.get("traceparent", "")
                print(f"  [Director] traceparent: {traceparent}")

                result = await call_a2a_agent(
                    f"http://127.0.0.1:{PRODUCER_PORT}",
                    {"campaign_name": "Test Campaign", "theme": "luxury_gold"},
                    traceparent=traceparent,
                )
                span.set_outputs(result)
            return result

        result = await director_run()
        print(f"  [Director] Result: {result.get('status')}")

        trace_id = mlflow.get_last_active_trace_id()
        if trace_id:
            # Give producer a moment to flush its trace
            await asyncio.sleep(1)
            print(f"\n  ✓ Director trace: {trace_id}")
            print_trace_tree(trace_id)
        else:
            print(f"\n  ✗ No trace captured")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        # Clean up temp file
        script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_a2a_producer.py")
        if os.path.exists(script_path):
            os.unlink(script_path)


async def main():
    if os.path.exists(DB_PATH):
        os.unlink(DB_PATH)

    mlflow.set_tracking_uri(DB_URI)
    mlflow.set_experiment(EXPERIMENT)
    mlflow.langchain.autolog(log_traces=True, run_tracer_inline=True)

    print("=" * 70)
    print("A2A SDK + MLflow Tracing Test")
    print(f"DB: {DB_URI}")
    print("=" * 70)

    # Test A: OTEL enabled (default A2A SDK behavior)
    await run_test(otel_enabled=True)

    # Test B: OTEL disabled
    await run_test(otel_enabled=False)

    # Print all traces
    print(f"\n{'=' * 70}")
    print("ALL TRACES IN DATABASE:")
    print_all_traces()
    print(f"\n{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(main())
