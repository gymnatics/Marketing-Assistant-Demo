"""
LangGraph Orchestrator - Multi-agent workflow for campaign creation.

Coordinates the flow between:
1. Coder Agent - Generate HTML/CSS/JS
2. K8s Agent - Deploy to OpenShift
3. Marketing Agent - Generate email content
4. Customer Agent - Retrieve customer data
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import Literal
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from src.state import CampaignState, create_initial_state, CAMPAIGN_THEMES
from src.agents.coder_agent import coder_agent
from src.agents.k8s_agent import k8s_agent_deploy_preview, k8s_agent_promote_production
from src.agents.marketing_agent import marketing_agent, simulate_email_send
from src.agents.customer_agent import customer_agent


def select_theme_node(state: CampaignState) -> CampaignState:
    """Node to handle theme selection (usually done via UI)."""
    print(f"[Orchestrator] Theme selected: {state.get('selected_theme', 'not set')}")
    
    # Validate theme
    if state.get("selected_theme") not in CAMPAIGN_THEMES:
        state["selected_theme"] = "luxury_gold"  # Default
    
    theme_data = CAMPAIGN_THEMES[state["selected_theme"]]
    state["theme_colors"] = theme_data["colors"]
    state["current_step"] = "theme_selected"
    
    return state


def human_approval_node(state: CampaignState) -> CampaignState:
    """Node that waits for human approval (handled by UI interrupt)."""
    print(f"[Orchestrator] Waiting for human approval...")
    state["awaiting_approval"] = True
    state["current_step"] = "awaiting_approval"
    return state


def route_after_approval(state: CampaignState) -> Literal["select_theme", "deploy_production"]:
    """Route based on user decision after preview."""
    decision = state.get("user_decision", "")
    print(f"[Orchestrator] User decision: {decision}")
    
    if decision == "edit":
        return "select_theme"
    else:
        return "deploy_production"


def check_for_errors(state: CampaignState) -> Literal["continue", "error"]:
    """Check if there are any errors in the state."""
    if state.get("error_message"):
        return "error"
    return "continue"


def error_handler_node(state: CampaignState) -> CampaignState:
    """Handle errors in the workflow."""
    print(f"[Orchestrator] Error: {state.get('error_message')}")
    state["current_step"] = "error"
    return state


def build_campaign_graph() -> StateGraph:
    """Build the LangGraph workflow for campaign creation."""
    
    # Create the graph
    workflow = StateGraph(CampaignState)
    
    # Add nodes
    workflow.add_node("select_theme", select_theme_node)
    workflow.add_node("generate_code", coder_agent)
    workflow.add_node("deploy_preview", k8s_agent_deploy_preview)
    workflow.add_node("human_approval", human_approval_node)
    workflow.add_node("deploy_production", k8s_agent_promote_production)
    workflow.add_node("get_customers", customer_agent)
    workflow.add_node("generate_email", marketing_agent)
    workflow.add_node("send_emails", simulate_email_send)
    workflow.add_node("error_handler", error_handler_node)
    
    # Define edges - Main flow
    workflow.add_edge(START, "select_theme")
    workflow.add_edge("select_theme", "generate_code")
    
    # After code generation, check for errors
    workflow.add_conditional_edges(
        "generate_code",
        check_for_errors,
        {
            "continue": "deploy_preview",
            "error": "error_handler"
        }
    )
    
    # After preview deployment, check for errors
    workflow.add_conditional_edges(
        "deploy_preview",
        check_for_errors,
        {
            "continue": "human_approval",
            "error": "error_handler"
        }
    )
    
    # Human approval routes to either edit or production
    workflow.add_conditional_edges(
        "human_approval",
        route_after_approval,
        {
            "select_theme": "select_theme",
            "deploy_production": "deploy_production"
        }
    )
    
    # After production deployment
    workflow.add_conditional_edges(
        "deploy_production",
        check_for_errors,
        {
            "continue": "get_customers",
            "error": "error_handler"
        }
    )
    
    # Get customers then generate email
    workflow.add_edge("get_customers", "generate_email")
    
    # After email generation
    workflow.add_conditional_edges(
        "generate_email",
        check_for_errors,
        {
            "continue": "send_emails",
            "error": "error_handler"
        }
    )
    
    # End after sending emails
    workflow.add_edge("send_emails", END)
    
    # Error handler ends the workflow
    workflow.add_edge("error_handler", END)
    
    return workflow


def compile_workflow(checkpointer=None):
    """Compile the workflow with optional checkpointer."""
    workflow = build_campaign_graph()
    
    if checkpointer is None:
        checkpointer = MemorySaver()
    
    return workflow.compile(checkpointer=checkpointer)


# Global app instance
_app = None
_checkpointer = None


def get_app():
    """Get or create the compiled workflow app."""
    global _app, _checkpointer
    
    if _app is None:
        _checkpointer = MemorySaver()
        _app = compile_workflow(_checkpointer)
    
    return _app


def run_campaign_workflow(
    campaign_name: str,
    campaign_description: str,
    hotel_name: str = "Grand Luxe Hotel & Casino",
    target_audience: str = "VIP members",
    selected_theme: str = "luxury_gold",
    start_date: str = "",
    end_date: str = "",
    thread_id: str = None
) -> CampaignState:
    """
    Run the campaign creation workflow.
    
    This runs until it hits the human_approval node, then returns.
    Call resume_after_approval() to continue.
    """
    import uuid
    
    app = get_app()
    
    # Create initial state
    initial_state = create_initial_state(
        campaign_name=campaign_name,
        campaign_description=campaign_description,
        hotel_name=hotel_name,
        target_audience=target_audience,
        start_date=start_date,
        end_date=end_date
    )
    initial_state["selected_theme"] = selected_theme
    
    # Generate thread ID if not provided
    if thread_id is None:
        thread_id = f"thread-{uuid.uuid4().hex[:8]}"
    
    config = {"configurable": {"thread_id": thread_id}}
    
    print(f"\n{'='*60}")
    print(f"Starting Campaign Workflow: {campaign_name}")
    print(f"Thread ID: {thread_id}")
    print(f"{'='*60}\n")
    
    # Run until interrupt (human_approval)
    result = None
    for event in app.stream(initial_state, config):
        # Get the latest state
        for node_name, node_state in event.items():
            result = node_state
            print(f"[{node_name}] Step: {node_state.get('current_step', 'unknown')}")
        
        # Check if we're waiting for approval
        if result and result.get("awaiting_approval"):
            print("\n[Orchestrator] Workflow paused - awaiting human approval")
            break
    
    return result, thread_id


def resume_after_approval(
    thread_id: str,
    user_decision: str  # "edit" or "approve"
) -> CampaignState:
    """
    Resume the workflow after human approval.
    
    Args:
        thread_id: The thread ID from run_campaign_workflow
        user_decision: Either "edit" (go back to theme selection) or "approve" (go live)
    """
    app = get_app()
    config = {"configurable": {"thread_id": thread_id}}
    
    # Get current state
    current_state = app.get_state(config)
    
    if current_state is None:
        raise ValueError(f"No state found for thread: {thread_id}")
    
    # Update state with user decision
    updated_state = dict(current_state.values)
    updated_state["user_decision"] = user_decision
    updated_state["awaiting_approval"] = False
    
    print(f"\n{'='*60}")
    print(f"Resuming Workflow - Decision: {user_decision}")
    print(f"{'='*60}\n")
    
    # Update the state
    app.update_state(config, updated_state)
    
    # Continue execution
    result = None
    for event in app.stream(None, config):
        for node_name, node_state in event.items():
            result = node_state
            print(f"[{node_name}] Step: {node_state.get('current_step', 'unknown')}")
    
    return result


# For testing
if __name__ == "__main__":
    print("Testing Campaign Workflow (without actual model calls)...")
    print("Note: This will fail without model endpoints. Use the Streamlit UI for full testing.")
    
    # Show workflow structure
    workflow = build_campaign_graph()
    print("\nWorkflow nodes:")
    for node in workflow.nodes:
        print(f"  - {node}")
