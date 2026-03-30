"""
Delivery Manager A2A AgentExecutor bridge.

Translates A2A protocol requests into DeliveryManagerAgent method calls
and returns results as A2A artifacts.
"""
import json
import traceback

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import TaskState, Part, TextPart
from a2a.utils import new_agent_text_message

from agent import DeliveryManagerAgent


SKILL_DISPATCH = {
    "generate_email": "generate_email",
    "deploy_preview": "deploy_preview",
    "deploy_production": "deploy_production",
    "send_emails": "send_emails",
}


class DeliveryManagerExecutor(AgentExecutor):
    """Bridges A2A protocol to DeliveryManagerAgent business logic."""

    def __init__(self):
        self.agent = DeliveryManagerAgent()

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        updater.start_work()

        try:
            raw_input = context.get_user_input()
            params = json.loads(raw_input)
        except (json.JSONDecodeError, TypeError) as e:
            updater.update_status(
                TaskState.failed,
                message=new_agent_text_message(
                    f"Invalid JSON input: {e}",
                    context.task_id,
                    context.context_id,
                ),
            )
            return

        skill = params.get("skill", "")
        method_name = SKILL_DISPATCH.get(skill)

        if not method_name:
            updater.update_status(
                TaskState.failed,
                message=new_agent_text_message(
                    f"Unknown skill: {skill}. "
                    f"Available: {list(SKILL_DISPATCH.keys())}",
                    context.task_id,
                    context.context_id,
                ),
            )
            return

        try:
            method = getattr(self.agent, method_name)
            result = await method(params.get("params", params))

            result_json = json.dumps(result)
            parts: list[Part] = [TextPart(text=result_json)]
            updater.add_artifact(parts)
            updater.complete()

        except Exception as e:
            traceback.print_exc()
            updater.update_status(
                TaskState.failed,
                message=new_agent_text_message(
                    f"Error executing {skill}: {e}",
                    context.task_id,
                    context.context_id,
                ),
            )

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        updater.update_status(
            TaskState.canceled,
            message=new_agent_text_message(
                "Task cancelled.",
                context.task_id,
                context.context_id,
            ),
        )
