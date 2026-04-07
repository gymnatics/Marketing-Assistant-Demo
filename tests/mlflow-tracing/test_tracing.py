#!/usr/bin/env python3
"""
MLflow + LangGraph Tracing Test Suite
=====================================

Reproduces the exact tracing scenarios from the Campaign Director to determine
which patterns produce correct span nesting in MLflow.

Tests:
  1. Baseline: LangGraph autolog only (no manual spans)
  2. run_tracer_inline=True vs False
  3. mlflow.start_span() inside a LangGraph node
  4. Async "A2A-like" calls inside nodes with span wrapping
  5. Span types (UNKNOWN vs AGENT vs TOOL) to fix the ? icon

Run:
    pip install -r requirements.txt
    python test_tracing.py

Results are saved to ./mlruns/ (local MLflow tracking).
Open the UI with:  mlflow ui --port 5050
"""

import asyncio
import json
import time
import mlflow
from typing import TypedDict, Annotated, List
import operator
from langgraph.graph import StateGraph, START, END


EXPERIMENT_NAME = "tracing-tests"


# ── Simulated State (mirrors CampaignState) ──

class TestState(TypedDict):
    task_id: str
    status: str
    result: str
    error_message: str
    messages: Annotated[list, operator.add]


# ── Simulated async work (stands in for A2A calls) ──

async def fake_a2a_call(agent_name: str, skill: str, delay: float = 0.5) -> dict:
    """Simulate an A2A agent call with network delay."""
    await asyncio.sleep(delay)
    return {
        "status": "success",
        "agent": agent_name,
        "skill": skill,
        "data": f"Result from {agent_name}/{skill}",
    }


async def fake_llm_call(prompt: str, delay: float = 0.3) -> str:
    """Simulate a streaming LLM call."""
    await asyncio.sleep(delay)
    return f"LLM response to: {prompt[:50]}"


# ── Conditional edge ──

def check_failed(state: TestState) -> str:
    return "end" if state.get("status") == "failed" else "continue"


# ═══════════════════════════════════════════════════════
# TEST 1: Baseline - LangGraph autolog, no manual spans
# ═══════════════════════════════════════════════════════

async def node_generate_baseline(state: TestState) -> TestState:
    result = await fake_a2a_call("creative-producer", "generate_landing_page", delay=1.0)
    state["result"] = json.dumps(result)
    state["messages"] = [{"agent": "producer", "content": "done"}]
    return state

async def node_deploy_baseline(state: TestState) -> TestState:
    result = await fake_a2a_call("delivery-manager", "deploy_preview", delay=0.3)
    state["status"] = "preview_ready"
    state["messages"] = [{"agent": "deployer", "content": "deployed"}]
    return state

def build_baseline_workflow():
    g = StateGraph(TestState)
    g.add_node("generate", node_generate_baseline)
    g.add_node("deploy", node_deploy_baseline)
    g.add_edge(START, "generate")
    g.add_conditional_edges("generate", check_failed, {"continue": "deploy", "end": END})
    g.add_edge("deploy", END)
    return g.compile()


@mlflow.trace(name="test1_baseline")
async def test1_baseline():
    """LangGraph autolog only - no manual spans. Shows the default behavior."""
    workflow = build_baseline_workflow()
    initial = TestState(
        task_id="test1", status="generating", result="",
        error_message="", messages=[]
    )
    final = await workflow.ainvoke(initial)
    return final


# ═══════════════════════════════════════════════════════
# TEST 2: Manual span INSIDE node function body
# ═══════════════════════════════════════════════════════

async def node_generate_with_span(state: TestState) -> TestState:
    """A2A call wrapped with mlflow.start_span inside the node."""
    with mlflow.start_span(name="a2a_call_creative_producer", span_type="AGENT") as span:
        span.set_inputs({"skill": "generate_landing_page", "task_id": state["task_id"]})
        result = await fake_a2a_call("creative-producer", "generate_landing_page", delay=1.0)
        span.set_outputs(result)

    state["result"] = json.dumps(result)
    state["messages"] = [{"agent": "producer", "content": "done"}]
    return state

async def node_deploy_with_span(state: TestState) -> TestState:
    with mlflow.start_span(name="a2a_call_delivery_manager", span_type="AGENT") as span:
        span.set_inputs({"skill": "deploy_preview"})
        result = await fake_a2a_call("delivery-manager", "deploy_preview", delay=0.3)
        span.set_outputs(result)

    state["status"] = "preview_ready"
    state["messages"] = [{"agent": "deployer", "content": "deployed"}]
    return state

def build_span_in_node_workflow():
    g = StateGraph(TestState)
    g.add_node("generate", node_generate_with_span)
    g.add_node("deploy", node_deploy_with_span)
    g.add_edge(START, "generate")
    g.add_conditional_edges("generate", check_failed, {"continue": "deploy", "end": END})
    g.add_edge("deploy", END)
    return g.compile()


@mlflow.trace(name="test2_span_in_node")
async def test2_span_in_node():
    """mlflow.start_span() directly inside LangGraph node body."""
    workflow = build_span_in_node_workflow()
    initial = TestState(
        task_id="test2", status="generating", result="",
        error_message="", messages=[]
    )
    final = await workflow.ainvoke(initial)
    return final


# ═══════════════════════════════════════════════════════
# TEST 3: Manual span in a HELPER function called by node
# ═══════════════════════════════════════════════════════

async def call_a2a_with_span(agent_name: str, skill: str, params: dict) -> dict:
    """Helper that wraps the A2A call with its own span (like call_a2a_agent)."""
    with mlflow.start_span(name=f"a2a_call_{agent_name}", span_type="AGENT") as span:
        span.set_inputs({"agent": agent_name, "skill": skill, **params})
        result = await fake_a2a_call(agent_name, skill, delay=0.8)
        span.set_outputs(result)
    return result

async def node_generate_helper_span(state: TestState) -> TestState:
    result = await call_a2a_with_span(
        "creative-producer", "generate_landing_page",
        {"task_id": state["task_id"]}
    )
    state["result"] = json.dumps(result)
    state["messages"] = [{"agent": "producer", "content": "done"}]
    return state

async def node_deploy_helper_span(state: TestState) -> TestState:
    result = await call_a2a_with_span(
        "delivery-manager", "deploy_preview",
        {"task_id": state["task_id"]}
    )
    state["status"] = "preview_ready"
    state["messages"] = [{"agent": "deployer", "content": "deployed"}]
    return state

def build_helper_span_workflow():
    g = StateGraph(TestState)
    g.add_node("generate", node_generate_helper_span)
    g.add_node("deploy", node_deploy_helper_span)
    g.add_edge(START, "generate")
    g.add_conditional_edges("generate", check_failed, {"continue": "deploy", "end": END})
    g.add_edge("deploy", END)
    return g.compile()


@mlflow.trace(name="test3_helper_span")
async def test3_helper_span():
    """Span created in a helper function called FROM a node (not directly in node body)."""
    workflow = build_helper_span_workflow()
    initial = TestState(
        task_id="test3", status="generating", result="",
        error_message="", messages=[]
    )
    final = await workflow.ainvoke(initial)
    return final


# ═══════════════════════════════════════════════════════
# TEST 4: Multiple span types to check icon rendering
# ═══════════════════════════════════════════════════════

async def node_with_typed_spans(state: TestState) -> TestState:
    """Tests different span_type values for MLflow UI icon."""
    with mlflow.start_span(name="agent_call", span_type="AGENT") as s:
        s.set_inputs({"type_test": "AGENT"})
        await asyncio.sleep(0.1)
        s.set_outputs({"icon": "should show agent icon"})

    with mlflow.start_span(name="tool_call", span_type="TOOL") as s:
        s.set_inputs({"type_test": "TOOL"})
        await asyncio.sleep(0.1)
        s.set_outputs({"icon": "should show tool icon"})

    with mlflow.start_span(name="chain_call", span_type="CHAIN") as s:
        s.set_inputs({"type_test": "CHAIN"})
        await asyncio.sleep(0.1)
        s.set_outputs({"icon": "should show chain icon"})

    with mlflow.start_span(name="llm_call", span_type="LLM") as s:
        s.set_inputs({"type_test": "LLM"})
        await asyncio.sleep(0.1)
        s.set_outputs({"icon": "should show LLM icon"})

    with mlflow.start_span(name="unknown_call") as s:
        s.set_inputs({"type_test": "default/UNKNOWN"})
        await asyncio.sleep(0.1)
        s.set_outputs({"icon": "should show ? icon"})

    state["result"] = "span types tested"
    state["messages"] = [{"content": "typed spans done"}]
    return state

def build_typed_spans_workflow():
    g = StateGraph(TestState)
    g.add_node("typed_spans", node_with_typed_spans)
    g.add_edge(START, "typed_spans")
    g.add_edge("typed_spans", END)
    return g.compile()


@mlflow.trace(name="test4_span_types")
async def test4_span_types():
    """Various span_type values to verify icons in MLflow UI."""
    workflow = build_typed_spans_workflow()
    initial = TestState(
        task_id="test4", status="running", result="",
        error_message="", messages=[]
    )
    final = await workflow.ainvoke(initial)
    return final


# ═══════════════════════════════════════════════════════
# TEST 5: Multi-step workflow (full campaign simulation)
# ═══════════════════════════════════════════════════════

async def node_validate_policy(state: TestState) -> TestState:
    with mlflow.start_span(name="a2a_policy_guardian", span_type="AGENT") as span:
        span.set_inputs({"skill": "validate_campaign"})
        result = await fake_a2a_call("policy-guardian", "validate_campaign", delay=0.3)
        span.set_outputs(result)
    state["messages"] = [{"agent": "policy", "content": "approved"}]
    return state

async def node_generate_full(state: TestState) -> TestState:
    with mlflow.start_span(name="a2a_creative_producer", span_type="AGENT") as span:
        span.set_inputs({"skill": "generate_landing_page"})

        with mlflow.start_span(name="hero_image_generation", span_type="TOOL") as img_span:
            img_span.set_inputs({"mcp_tool": "generate_campaign_image"})
            img_result = await fake_a2a_call("imagegen-mcp", "generate_image", delay=0.5)
            img_span.set_outputs(img_result)

        with mlflow.start_span(name="html_generation", span_type="LLM") as llm_span:
            llm_span.set_inputs({"model": "qwen25-coder-32b"})
            llm_result = await fake_llm_call("Generate landing page HTML", delay=0.8)
            llm_span.set_outputs({"html_length": len(llm_result)})

        span.set_outputs({"status": "success", "html_length": len(llm_result)})

    state["result"] = llm_result
    state["messages"] = [{"agent": "producer", "content": "landing page ready"}]
    return state

async def node_deploy_full(state: TestState) -> TestState:
    with mlflow.start_span(name="a2a_delivery_manager", span_type="AGENT") as span:
        span.set_inputs({"skill": "deploy_preview"})
        result = await fake_a2a_call("delivery-manager", "deploy_preview", delay=0.2)
        span.set_outputs(result)
    state["status"] = "preview_ready"
    state["messages"] = [{"agent": "deployer", "content": "deployed"}]
    return state

def build_full_workflow():
    g = StateGraph(TestState)
    g.add_node("validate_policy", node_validate_policy)
    g.add_node("generate", node_generate_full)
    g.add_node("deploy", node_deploy_full)
    g.add_edge(START, "validate_policy")
    g.add_conditional_edges("validate_policy", check_failed, {"continue": "generate", "end": END})
    g.add_conditional_edges("generate", check_failed, {"continue": "deploy", "end": END})
    g.add_edge("deploy", END)
    return g.compile()


@mlflow.trace(name="test5_full_workflow")
async def test5_full_workflow():
    """Full campaign workflow with nested spans (policy → generate → deploy)."""
    mlflow.update_current_trace(tags={
        "mlflow.trace.session": "test-session-001",
        "workflow": "landing_page",
    })
    workflow = build_full_workflow()
    initial = TestState(
        task_id="test5", status="generating", result="",
        error_message="", messages=[]
    )
    final = await workflow.ainvoke(initial)
    return final


# ═══════════════════════════════════════════════════════
# TEST 6: asyncio.create_task (background task context)
# ═══════════════════════════════════════════════════════

async def node_with_background_task(state: TestState) -> TestState:
    """Tests if spans in background tasks attach to the correct parent."""
    async def background_work():
        with mlflow.start_span(name="background_a2a_call", span_type="AGENT") as span:
            span.set_inputs({"note": "created via asyncio.create_task"})
            result = await fake_a2a_call("creative-producer", "generate", delay=0.5)
            span.set_outputs(result)
        return result

    with mlflow.start_span(name="orchestrate_background", span_type="CHAIN") as span:
        task = asyncio.create_task(background_work())
        result = await task
        span.set_outputs({"background_result": "completed"})

    state["result"] = json.dumps(result)
    state["messages"] = [{"content": "background task done"}]
    return state

def build_background_workflow():
    g = StateGraph(TestState)
    g.add_node("background_test", node_with_background_task)
    g.add_edge(START, "background_test")
    g.add_edge("background_test", END)
    return g.compile()


@mlflow.trace(name="test6_background_task")
async def test6_background_task():
    """Tests asyncio.create_task context propagation (known MLflow issue)."""
    workflow = build_background_workflow()
    initial = TestState(
        task_id="test6", status="running", result="",
        error_message="", messages=[]
    )
    final = await workflow.ainvoke(initial)
    return final


# ═══════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════

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


async def run_all_tests():
    print("=" * 70)
    print("MLflow + LangGraph Tracing Test Suite")
    print("=" * 70)
    print(f"MLflow version: {mlflow.__version__}")
    print(f"Tracking URI: {mlflow.get_tracking_uri()}")
    print(f"Experiment: {EXPERIMENT_NAME}")
    print()

    tests = [
        ("Test 1: Baseline (autolog only, no manual spans)", test1_baseline),
        ("Test 2: mlflow.start_span() inside node body", test2_span_in_node),
        ("Test 3: mlflow.start_span() in helper function", test3_helper_span),
        ("Test 4: Span type icons (AGENT, TOOL, CHAIN, LLM, UNKNOWN)", test4_span_types),
        ("Test 5: Full workflow with nested spans", test5_full_workflow),
        ("Test 6: asyncio.create_task context propagation", test6_background_task),
    ]

    # Run each test twice: once with run_tracer_inline=False, once with True
    for inline_mode in [False, True]:
        mode_label = "INLINE" if inline_mode else "STANDARD"
        print(f"\n{'─' * 70}")
        print(f"  Mode: run_tracer_inline={inline_mode} ({mode_label})")
        print(f"{'─' * 70}")

        mlflow.langchain.autolog(log_traces=True, run_tracer_inline=inline_mode)

        for label, test_fn in tests:
            test_label = f"{label} [{mode_label}]"
            print(f"\n▸ {test_label}")
            try:
                result = await test_fn()
                trace_id = mlflow.get_last_active_trace_id()
                if trace_id:
                    print(f"  ✓ Trace: {trace_id}")
                    print_trace_tree(trace_id)
                else:
                    print("  ✗ No trace captured!")
            except Exception as e:
                print(f"  ✗ FAILED: {type(e).__name__}: {e}")

    print(f"\n{'=' * 70}")
    print("Done! Open MLflow UI to inspect traces visually:")
    print(f"  mlflow ui --port 5050 --backend-store-uri {mlflow.get_tracking_uri()}")
    print(f"{'=' * 70}")


def main():
    mlflow.set_tracking_uri("mlruns")
    mlflow.set_experiment(EXPERIMENT_NAME)
    asyncio.run(run_all_tests())


if __name__ == "__main__":
    main()
