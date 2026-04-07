#!/usr/bin/env python3
"""
Test cross-process trace propagation via traceparent header.

Simulates the exact scenario:
  1. Director creates a trace, gets traceparent header
  2. Producer receives traceparent, uses set_tracing_context_from_http_request_headers
  3. Producer creates spans under the director's trace

This tests what Liming is hitting: does the producer's use of
set_tracing_context_from_http_request_headers cause issues?

Run:  python test_cross_process.py
"""

import asyncio
import mlflow
from mlflow.tracing import (
    get_tracing_context_headers_for_http_request,
    set_tracing_context_from_http_request_headers,
)


EXPERIMENT = "cross-process-test"


async def simulate_producer_work(traceparent_headers: dict, test_name: str):
    """Simulate what the creative-producer does when receiving traceparent."""
    print(f"  [Producer] Received headers: {traceparent_headers}")

    with set_tracing_context_from_http_request_headers(traceparent_headers):
        with mlflow.start_span(name="producer_generate", span_type="AGENT") as span:
            span.set_inputs({"test": test_name})

            with mlflow.start_span(name="hero_image_gen", span_type="TOOL") as img:
                img.set_inputs({"mcp": "imagegen"})
                await asyncio.sleep(0.3)
                img.set_outputs({"url": "http://example.com/img.png"})

            with mlflow.start_span(name="html_generation", span_type="LLM") as llm:
                llm.set_inputs({"model": "qwen-coder"})
                await asyncio.sleep(0.5)
                llm.set_outputs({"html_length": 5000})

            span.set_outputs({"status": "success"})

    print(f"  [Producer] Done")


# ─── Test 1: traceparent from @mlflow.trace decorated function ───

@mlflow.trace(name="director_workflow_test1")
async def test1_trace_decorator():
    """Director uses @mlflow.trace, gets traceparent, passes to producer."""
    headers = get_tracing_context_headers_for_http_request()
    print(f"  [Director] traceparent headers: {headers}")

    # Simulate calling producer with these headers
    await simulate_producer_work(headers, "test1_decorator")
    return {"status": "done"}


# ─── Test 2: traceparent from inside LangGraph node ───

async def test2_langgraph_with_traceparent():
    """Director runs LangGraph, node gets traceparent and passes to producer."""
    from typing import TypedDict, Annotated
    import operator
    from langgraph.graph import StateGraph, START, END

    class State(TypedDict):
        result: str
        messages: Annotated[list, operator.add]

    async def generate_node(state: State) -> State:
        # Inside a LangGraph node, get traceparent
        headers = get_tracing_context_headers_for_http_request()
        print(f"  [Director/node] traceparent headers: {headers}")

        with mlflow.start_span(name="a2a_call_producer", span_type="AGENT") as span:
            span.set_inputs({"skill": "generate_landing_page"})
            # Call producer with traceparent
            await simulate_producer_work(headers, "test2_langgraph")
            span.set_outputs({"status": "success"})

        state["result"] = "generated"
        state["messages"] = [{"content": "done"}]
        return state

    g = StateGraph(State)
    g.add_node("generate", generate_node)
    g.add_edge(START, "generate")
    g.add_edge("generate", END)
    workflow = g.compile()

    @mlflow.trace(name="director_workflow_test2")
    async def run():
        return await workflow.ainvoke(State(result="", messages=[]))

    return await run()


# ─── Test 3: Producer creates its OWN trace (no traceparent) ───

@mlflow.trace(name="director_workflow_test3")
async def test3_separate_traces():
    """Director and producer each create their own trace (no traceparent sharing)."""
    # Director just records its own span
    with mlflow.start_span(name="a2a_call_producer", span_type="AGENT") as span:
        span.set_inputs({"skill": "generate"})

        # Producer creates a completely independent trace
        @mlflow.trace(name="producer_independent")
        async def producer_work():
            with mlflow.start_span(name="hero_image", span_type="TOOL") as s:
                await asyncio.sleep(0.3)
                s.set_outputs({"url": "img.png"})
            with mlflow.start_span(name="html_gen", span_type="LLM") as s:
                await asyncio.sleep(0.5)
                s.set_outputs({"length": 5000})
            return {"status": "success"}

        result = await producer_work()
        span.set_outputs(result)

    return {"status": "done"}


# ─── Test 4: What happens with empty/no traceparent ───

async def test4_no_traceparent():
    """Producer receives empty headers (no traceparent)."""
    @mlflow.trace(name="director_workflow_test4")
    async def run():
        # Empty headers - no traceparent
        with set_tracing_context_from_http_request_headers({}):
            with mlflow.start_span(name="producer_no_traceparent", span_type="AGENT") as span:
                await asyncio.sleep(0.2)
                span.set_outputs({"status": "success"})
        return {"status": "done"}

    return await run()


def print_trace_tree(trace_id: str):
    """Print the span tree for a trace."""
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
    mlflow.langchain.autolog(log_traces=True, run_tracer_inline=True)

    print("=" * 70)
    print("Cross-Process Trace Propagation Tests")
    print("=" * 70)

    tests = [
        ("Test 1: @mlflow.trace → traceparent → producer", test1_trace_decorator),
        ("Test 2: LangGraph node → traceparent → producer", test2_langgraph_with_traceparent),
        ("Test 3: Separate traces (no traceparent sharing)", test3_separate_traces),
        ("Test 4: Empty headers (no traceparent)", test4_no_traceparent),
    ]

    for label, test_fn in tests:
        print(f"\n▸ {label}")
        try:
            result = await test_fn()
            trace_id = mlflow.get_last_active_trace_id()
            if trace_id:
                print(f"  ✓ Trace: {trace_id}")
                print_trace_tree(trace_id)
            else:
                print("  ✗ No trace captured")
        except Exception as e:
            import traceback
            print(f"  ✗ FAILED: {type(e).__name__}: {e}")
            traceback.print_exc()

    # Check total traces created
    client = mlflow.MlflowClient()
    exp = client.get_experiment_by_name(EXPERIMENT)
    if exp:
        traces = client.search_traces(experiment_ids=[exp.experiment_id])
        print(f"\n{'=' * 70}")
        print(f"Total traces created: {len(traces)}")
        for t in traces:
            info = t.info
            span_count = len(t.data.spans) if t.data and t.data.spans else 0
            print(f"  {info.request_id}  status={info.status}  spans={span_count}")
        print(f"{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(main())
