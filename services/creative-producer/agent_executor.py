"""
Creative Producer A2A AgentExecutor - Bridge between a2a-sdk and business logic.
"""
import json

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import TaskState, Part, TextPart
from a2a.utils import new_task, new_agent_text_message

from agent import CreativeProducerAgent


class CreativeProducerExecutor(AgentExecutor):

    def __init__(self):
        self.agent = CreativeProducerAgent()

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        user_input = context.get_user_input()
        try:
            params = json.loads(user_input)
        except (json.JSONDecodeError, TypeError):
            params = {"campaign_name": "Chat Request", "campaign_description": user_input,
                      "hotel_name": "Simon Casino Resort", "theme": "luxury_gold",
                      "start_date": "2026-05-01", "end_date": "2026-06-01"}

        task = context.current_task
        if task is None:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)

        await updater.update_status(
            TaskState.working,
            message=new_agent_text_message(
                f"Generating landing page for '{params.get('campaign_name', 'campaign')}'...",
                task.context_id, task.id,
            ),
        )

        result = await self.agent.generate(params)

        result_json = json.dumps(result)
        parts: list[Part] = [Part(root=TextPart(text=result_json))]

        await updater.add_artifact(parts)
        await updater.update_status(
            TaskState.completed,
            message=new_agent_text_message("Landing page generation complete.", task.context_id, task.id),
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("Cancel not supported")
