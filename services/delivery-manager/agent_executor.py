"""
Delivery Manager A2A AgentExecutor - Bridge between a2a-sdk and business logic.
"""
import json
import traceback

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import TaskState, Part, TextPart
from a2a.utils import new_task, new_agent_text_message

from agent import DeliveryManagerAgent

SKILL_DISPATCH = {
    "generate_email": "generate_email",
    "deploy_preview": "deploy_preview",
    "deploy_production": "deploy_production",
    "send_emails": "send_emails",
}


class DeliveryManagerExecutor(AgentExecutor):

    def __init__(self):
        self.agent = DeliveryManagerAgent()

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if task is None:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)

        raw_input = context.get_user_input()
        try:
            params = json.loads(raw_input)
        except (json.JSONDecodeError, TypeError):
            parts = [Part(root=TextPart(text="I'm the Delivery Manager agent. I handle email generation and campaign deployment. Please send structured task parameters via the Campaign Director."))]
            await updater.add_artifact(parts)
            await updater.complete()
            return

        skill = params.pop("skill", "")
        method_name = SKILL_DISPATCH.get(skill)

        if not method_name:
            await updater.update_status(
                TaskState.failed,
                message=new_agent_text_message(
                    f"Unknown skill: {skill}. Available: {list(SKILL_DISPATCH.keys())}",
                    task.context_id, task.id,
                ),
            )
            return

        await updater.update_status(
            TaskState.working,
            message=new_agent_text_message(f"Executing {skill}...", task.context_id, task.id),
        )

        try:
            method = getattr(self.agent, method_name)
            result = await method(params)

            result_json = json.dumps(result)
            parts: list[Part] = [Part(root=TextPart(text=result_json))]
            await updater.add_artifact(parts)
            await updater.update_status(
                TaskState.completed,
                message=new_agent_text_message(f"{skill} completed.", task.context_id, task.id),
            )
        except Exception as e:
            traceback.print_exc()
            await updater.update_status(
                TaskState.failed,
                message=new_agent_text_message(f"Error executing {skill}: {e}", task.context_id, task.id),
            )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("Cancel not supported")
