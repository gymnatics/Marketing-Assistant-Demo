"""
Customer Analyst A2A AgentExecutor - Bridge between a2a-sdk and business logic.
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

    def __init__(self):
        self.agent = CustomerAnalystAgent()

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if task is None:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)

        await updater.update_status(
            TaskState.working,
            message=new_agent_text_message("Retrieving customer profiles...", task.context_id, task.id),
        )

        try:
            user_input = context.get_user_input()
            params = json.loads(user_input)
            result = await self.agent.get_customers(params)
            result_json = json.dumps(result, ensure_ascii=False, default=str)

            parts: list[Part] = [Part(root=TextPart(text=result_json))]
            await updater.add_artifact(parts)
            await updater.update_status(
                TaskState.completed,
                message=new_agent_text_message("Customer retrieval complete.", task.context_id, task.id),
            )
        except Exception:
            tb = traceback.format_exc()
            print(f"[Customer Analyst Executor] Error: {tb}")
            await updater.update_status(
                TaskState.failed,
                message=new_agent_text_message(f"Customer retrieval failed: {tb}", task.context_id, task.id),
            )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("Cancel not supported")
