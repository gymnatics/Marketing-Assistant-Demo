#!/usr/bin/env python3
"""
Cross-process trace propagation test v3.

Uses subprocess to truly simulate separate processes (like separate pods).
Uses sqlite backend for proper DB storage (closer to PostgreSQL in prod).
"""

import asyncio
import subprocess
import sys
import os
import mlflow
from mlflow.tracing import get_tracing_context_headers_for_http_request

DB_URI = f"sqlite:///{os.path.join(os.path.dirname(__file__), 'test.db')}"
EXPERIMENT = "cross-process-v3"


# ── Producer script (runs as a separate process) ──

PRODUCER_SCRIPT = '''
import sys, os, time
import mlflow
from mlflow.tracing import set_tracing_context_from_http_request_headers

DB_URI = sys.argv[1]
EXPERIMENT = sys.argv[2]
traceparent = sys.argv[3]

mlflow.set_tracking_uri(DB_URI)
mlflow.set_experiment(EXPERIMENT)

headers = {"traceparent": traceparent}
print(f"[Producer] Using traceparent: {traceparent}")

with set_tracing_context_from_http_request_headers(headers):
    with mlflow.start_span(name="producer_generate", span_type="AGENT") as span:
        span.set_inputs({"skill": "generate_landing_page"})

        with mlflow.start_span(name="hero_image_gen", span_type="TOOL") as img:
            img.set_inputs({"mcp": "imagegen"})
            time.sleep(0.3)
            img.set_outputs({"url": "http://img.png"})

        with mlflow.start_span(name="html_generation", span_type="LLM") as llm:
            llm.set_inputs({"model": "qwen-coder"})
            time.sleep(0.5)
            llm.set_outputs({"html_length": 5000})

        span.set_outputs({"status": "success"})

print("[Producer] Done")
'''


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


@mlflow.trace(name="director_workflow")
async def run_director():
    """Director: creates trace, calls producer as subprocess."""
    with mlflow.start_span(name="a2a_call_creative_producer", span_type="AGENT") as span:
        span.set_inputs({"skill": "generate_landing_page"})

        headers = get_tracing_context_headers_for_http_request()
        traceparent = headers.get("traceparent", "")
        print(f"  [Director] traceparent: {traceparent}")

        # Run producer as a SEPARATE PROCESS (truly isolated, like separate pods)
        producer_script_path = os.path.join(os.path.dirname(__file__), "_producer_tmp.py")
        with open(producer_script_path, "w") as f:
            f.write(PRODUCER_SCRIPT)

        proc = await asyncio.create_subprocess_exec(
            sys.executable, producer_script_path, DB_URI, EXPERIMENT, traceparent,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        print(f"  [Director] Producer stdout: {stdout.decode().strip()}")
        if stderr.strip():
            # Filter warnings
            for line in stderr.decode().splitlines():
                if "WARNING" not in line and "FutureWarning" not in line:
                    print(f"  [Director] Producer stderr: {line}")

        os.unlink(producer_script_path)
        span.set_outputs({"producer_exit": proc.returncode})

    return {"status": "done"}


async def main():
    # Clean up
    db_path = os.path.join(os.path.dirname(__file__), "test.db")
    if os.path.exists(db_path):
        os.unlink(db_path)

    mlflow.set_tracking_uri(DB_URI)
    mlflow.set_experiment(EXPERIMENT)
    mlflow.langchain.autolog(log_traces=True, run_tracer_inline=True)

    print("=" * 70)
    print("Cross-Process Trace Test v3 (subprocess isolation + sqlite)")
    print(f"DB: {DB_URI}")
    print("=" * 70)

    # ── Test: Director + Producer in truly separate processes ──
    print("\n▸ Director calls producer (producer in separate subprocess)")
    await run_director()

    trace_id = mlflow.get_last_active_trace_id()
    if trace_id:
        print(f"\n  ✓ Director trace: {trace_id}")
        print_trace_tree(trace_id)
    else:
        print(f"\n  ✗ No director trace captured via get_last_active_trace_id()")

    # Check ALL traces in the DB
    client = mlflow.MlflowClient()
    exp = client.get_experiment_by_name(EXPERIMENT)
    if exp:
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
                    print(f"      {s.name:45s} type={stype:10s} parent={pid}")

    print(f"\n{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(main())
