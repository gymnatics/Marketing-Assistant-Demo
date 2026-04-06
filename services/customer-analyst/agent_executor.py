"""
Customer Analyst A2A AgentExecutor - Bridge between a2a-sdk and business logic.
"""
import json
import logging
import os
import traceback

logger = logging.getLogger(__name__)

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

        headers = {}
        MONGODB_TOKEN = os.environ.get("MONGODB_TOKEN", "")
        if MONGODB_TOKEN:
            headers["Authorization"] = f"Bearer {MONGODB_TOKEN}"
        elif context.call_context and (context.call_context.state or {}).get("headers", {}).get("authorization"):
            headers["Authorization"] = context.call_context.state["headers"]["authorization"]
            logger.info(f"Authorization={headers['Authorization']}")
        else:
            logger.warning(
                "No MONGODB_TOKEN or inbound Authorization header; outbound requests will be unauthenticated"
            )

        self.agent.headers = headers

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
            try:
                params = json.loads(user_input)
            except (json.JSONDecodeError, TypeError):
                params = {"target_audience": user_input, "campaign_id": "chat"}
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
            logger.exception(f"Customer Analyst executor failed {tb}")
            await updater.update_status(
                TaskState.failed,
                message=new_agent_text_message(f"Customer retrieval failed: {tb}", task.context_id, task.id),
            )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("Cancel not supported")
