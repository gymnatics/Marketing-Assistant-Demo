"""Policy Guardian Agent Executor — A2A bridge."""
import json
import traceback

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import TaskState, Part, TextPart

from agent import PolicyGuardianAgent


class PolicyGuardianExecutor(AgentExecutor):
    def __init__(self):
        self.agent = PolicyGuardianAgent()

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        user_input = context.get_user_input()
        params = json.loads(user_input)

        updater = TaskUpdater(event_queue)
        updater.start_work()

        try:
            result = await self.agent.validate(params)
            updater.add_artifact(
                parts=[Part(root=TextPart(text=json.dumps(result)))]
            )
            updater.complete()
        except Exception as e:
            updater.failed(str(e))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("Cancel not supported")
