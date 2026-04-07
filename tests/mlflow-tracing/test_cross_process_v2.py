#!/usr/bin/env python3
"""
Cross-process trace propagation test v2.

Simulates the REAL scenario with separate trace contexts (like separate pods):
  1. Director creates a trace, extracts traceparent
  2. Simulates an HTTP call boundary (clears context)
  3. Producer receives traceparent in a clean context, creates spans

This is what actually happens when director → producer are separate pods.
"""

import asyncio
import threading
import mlflow
from mlflow.tracing import (
    get_tracing_context_headers_for_http_request,
    set_tracing_context_from_http_request_headers,
)


EXPERIMENT = "cross-process-v2"


def run_producer_in_thread(traceparent_headers: dict, results: dict):
    """
    Run producer work in a separate thread with clean context.
    This simulates a separate process receiving an HTTP request with traceparent.
    """
    mlflow.set_tracking_uri("mlruns")
    mlflow.set_experiment(EXPERIMENT)

    try:
        with set_tracing_context_from_http_request_headers(traceparent_headers):
            with mlflow.start_span(name="producer_generate", span_type="AGENT") as span:
                span.set_inputs({"skill": "generate_landing_page"})

                with mlflow.start_span(name="hero_image_gen", span_type="TOOL") as img:
                    import time; time.sleep(0.3)
                    img.set_outputs({"url": "http://img.png"})

                with mlflow.start_span(name="html_generation", span_type="LLM") as llm:
                    import time; time.sleep(0.5)
                    llm.set_outputs({"html_length": 5000})

                span.set_outputs({"status": "success", "html": "<html>...</html>"})

        results["status"] = "success"
        print(f"  [Producer thread] Done, spans created under traceparent context")
    except Exception as e:
        results["status"] = "error"
        results["error"] = str(e)
        print(f"  [Producer thread] ERROR: {e}")


@mlflow.trace(name="director_workflow")
async def test_director_calls_producer():
    """
    Director creates trace, gets traceparent, spawns producer in separate thread.
    """
    with mlflow.start_span(name="a2a_call_creative_producer", span_type="AGENT") as span:
        span.set_inputs({"skill": "generate_landing_page"})

        # Get traceparent for the current span
        headers = get_tracing_context_headers_for_http_request()
        print(f"  [Director] traceparent: {headers}")

        # Run producer in a separate thread (simulates separate process)
        results = {}
        producer_thread = threading.Thread(
            target=run_producer_in_thread,
            args=(headers, results)
        )
        producer_thread.start()
        producer_thread.join(timeout=10)

        span.set_outputs(results)

    return results


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


async def main():
    mlflow.set_tracking_uri("mlruns")
    mlflow.set_experiment(EXPERIMENT)

    print("=" * 70)
    print("Cross-Process Trace Test (thread-isolated)")
    print("=" * 70)

    print("\n▸ Director calls producer (producer in separate thread)")
    result = await test_director_calls_producer()

    trace_id = mlflow.get_last_active_trace_id()
    if trace_id:
        print(f"\n  ✓ Director trace: {trace_id}")
        print_trace_tree(trace_id)
    else:
        print(f"\n  ✗ No director trace captured")

    # Search ALL traces to see if producer created a separate one
    client = mlflow.MlflowClient()
    exp = client.get_experiment_by_name(EXPERIMENT)
    if exp:
        traces = client.search_traces(experiment_ids=[exp.experiment_id])
        print(f"\n  Total traces in experiment: {len(traces)}")
        for t in traces:
            info = t.info
            span_count = len(t.data.spans) if t.data and t.data.spans else 0
            print(f"    {info.request_id}  status={info.status}  spans={span_count}")
            if t.data and t.data.spans:
                for s in sorted(t.data.spans, key=lambda x: getattr(x, "start_time_ns", 0)):
                    stype = getattr(s, "span_type", "?")
                    pid = (s.parent_id or "ROOT")[:8]
                    print(f"      {s.name:45s} type={stype:10s} parent={pid}")

    print(f"\n{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(main())
