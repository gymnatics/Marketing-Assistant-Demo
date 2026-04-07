#!/usr/bin/env python3
"""
A2A Client (Director) with MLflow tracing.

Calls the A2A server with traceparent header propagation.
Director creates a trace, wraps the A2A call in a span,
passes traceparent so producer spans nest correctly.

Usage:
    python a2a_client.py               # calls localhost:8091
    python a2a_client.py 8091          # specify port
    python a2a_client.py 8091 3        # specify port and number of calls

Make sure a2a_server.py is running first.
"""

import asyncio
import json
import os
import sys
import uuid

import httpx
import mlflow
from mlflow.tracing import get_tracing_context_headers_for_http_request
from a2a.client import A2AClient
from a2a.types import MessageSendParams, SendMessageRequest


PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8091
NUM_CALLS = int(sys.argv[2]) if len(sys.argv) > 2 else 1
PRODUCER_URL = f"http://localhost:{PORT}"
MLFLOW_URI = os.environ.get(
    "MLFLOW_TRACKING_URI",
    f"sqlite:///{os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_a2a.db')}"
)
EXPERIMENT = os.environ.get("MLFLOW_EXPERIMENT_NAME", "a2a-tracing-test")


async def call_a2a_agent(agent_url: str, params: dict) -> dict:
    """Call A2A agent — mirrors campaign-director's call_a2a_agent.
    
    Passes traceparent via HTTP headers (exactly like Liming's real director).
    """
    message_params = MessageSendParams(
        message={
            "role": "user",
            "parts": [{"kind": "text", "text": json.dumps(params)}],
            "messageId": uuid.uuid4().hex,
        }
    )
    request = SendMessageRequest(id=str(uuid.uuid4()), params=message_params)

    timeout = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)

    # Pass traceparent as HTTP header (same as Liming's real director)
    headers = {}
    trace_headers = get_tracing_context_headers_for_http_request()
    headers.update(trace_headers)

    async with httpx.AsyncClient(timeout=timeout, headers=headers) as httpx_client:
        client = A2AClient(httpx_client=httpx_client, url=agent_url)
        response = await client.send_message(request)

    resp = response.root
    if hasattr(resp, "error") and resp.error:
        return {"status": "error", "error": f"A2A error: {resp.error.message}"}

    task_result = resp.result if hasattr(resp, "result") else None
    if task_result and hasattr(task_result, "artifacts") and task_result.artifacts:
        for artifact in task_result.artifacts:
            for part in (artifact.parts or []):
                text = None
                if hasattr(part, "root") and hasattr(part.root, "text"):
                    text = part.root.text
                elif hasattr(part, "text"):
                    text = part.text
                if text:
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        return {"status": "success", "content": text}

    return {"status": "error", "error": "No artifact returned from agent"}


@mlflow.trace(name="director_workflow")
async def run_director(call_num: int):
    """Director workflow: creates trace, calls producer via A2A."""
    mlflow.update_current_trace(tags={
        "mlflow.trace.session": f"test-session-{call_num:03d}",
        "workflow": "landing_page",
    })

    with mlflow.start_span(name="a2a_call_creative_producer", span_type="AGENT") as span:
        span.set_inputs({"skill": "generate_landing_page", "call_num": call_num})

        result = await call_a2a_agent(
            PRODUCER_URL,
            {
                "campaign_name": f"Summer Luxury Escape #{call_num}",
                "campaign_description": "Premium summer getaway package",
                "hotel_name": "Simon Casino Resort",
                "theme": "luxury_gold",
            },
        )

        span.set_outputs(result)
        print(f"  [Director] Result: {result.get('status')}")

    return result


def print_trace_tree(trace_id: str):
    trace = mlflow.get_trace(trace_id)
    if not trace or not trace.data or not trace.data.spans:
        print("  (no spans found)")
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
        print(f"  {indent}{connector}{span.name} ({stype}, {duration:.0f}ms)")
        for child in sorted(children.get(span.span_id, []),
                            key=lambda x: getattr(x, "start_time_ns", 0) or 0):
            print_span(child, depth + 1)

    for root in children.get("ROOT", []):
        print_span(root)


async def main():
    mlflow.set_tracking_uri(MLFLOW_URI)
    mlflow.set_experiment(EXPERIMENT)

    print("=" * 60)
    print("A2A Client (Director)")
    print(f"MLflow URI: {MLFLOW_URI}")
    print(f"Producer:   {PRODUCER_URL}")
    print(f"Calls:      {NUM_CALLS}")
    print("=" * 60)

    for i in range(1, NUM_CALLS + 1):
        print(f"\n▸ Call {i}/{NUM_CALLS}")
        await run_director(i)

        trace_id = mlflow.get_last_active_trace_id()
        if trace_id:
            print(f"  ✓ Trace: {trace_id}")
            print_trace_tree(trace_id)
        else:
            print(f"  ✗ No trace captured")

    print(f"\n{'=' * 60}")
    print("Done. Open MLflow UI:")
    print(f"  mlflow ui --backend-store-uri {MLFLOW_URI} --port 5050")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())
