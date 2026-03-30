"""
Customer Analyst A2A AgentExecutor - Bridges A2A SDK with business logic.
"""
import json
import traceback

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import TaskState, Part, TextPart
from a2a.utils import new_task, new_agent_text_message

from agent import CustomerAnalystAgent


class CustomerAnalystExecutor(AgentExecutor):
    """A2A executor that delegates to CustomerAnalystAgent business logic."""

    def __init__(self):
        self.agent = CustomerAnalystAgent()

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task or new_task(context.message)
        updater = TaskUpdater(event_queue, task.id, task.contextId)

        updater.start_work()

        try:
            user_input = context.get_user_input()
            params = json.loads(user_input)
        except (json.JSONDecodeError, TypeError) as e:
            error_msg = f"Invalid input: expected JSON with campaign_id, target_audience, limit. Error: {e}"
            updater.update_status(
                TaskState.failed,
                new_agent_text_message(error_msg),
            )
            return

        try:
            result = await self.agent.get_customers(params)
            result_json = json.dumps(result, ensure_ascii=False, default=str)

            parts: list[Part] = [TextPart(text=result_json)]
            updater.add_artifact(parts)
            updater.complete()

        except Exception:
            tb = traceback.format_exc()
            print(f"[Customer Analyst Executor] Error: {tb}")
            updater.update_status(
                TaskState.failed,
                new_agent_text_message(f"Customer retrieval failed: {tb}"),
            )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task or new_task(context.message)
        updater = TaskUpdater(event_queue, task.id, task.contextId)
        updater.update_status(
            TaskState.canceled,
            new_agent_text_message("Customer retrieval cancelled"),
        )
