# tests/test_integration.py
import asyncio
import pytest
from agentbus.bus import AgentBus
from agentbus.handlers.base import BaseHandler
from agentbus.message import AgentMessage


class CollectingHandler(BaseHandler):
    def __init__(self):
        self.received: list[AgentMessage] = []
        self._event = asyncio.Event()

    async def handle(self, msg: AgentMessage) -> None:
        self.received.append(msg)
        self._event.set()

    async def wait_for_message(self, timeout: float = 3.0) -> None:
        await asyncio.wait_for(self._event.wait(), timeout=timeout)
        self._event.clear()


@pytest.mark.asyncio
async def test_send_receive_roundtrip(mosquitto_broker):
    host, port = mosquitto_broker
    handler = CollectingHandler()

    receiver = AgentBus(agent_id="sparrow", broker=host, port=port, retain=False)
    receiver.register_handler(handler)

    sender = AgentBus(agent_id="wren", broker=host, port=port, retain=False)

    listen_task = asyncio.create_task(receiver.listen())
    await asyncio.sleep(0.2)  # let subscription establish

    await sender.send(to="sparrow", subject="ping", body="hello from wren")
    await handler.wait_for_message(timeout=3.0)

    listen_task.cancel()
    try:
        await listen_task
    except (asyncio.CancelledError, Exception):
        pass

    assert len(handler.received) == 1
    msg = handler.received[0]
    assert msg.from_agent == "wren"
    assert msg.subject == "ping"
    assert msg.body == "hello from wren"


@pytest.mark.asyncio
async def test_markdown_body_preserved(mosquitto_broker):
    host, port = mosquitto_broker
    handler = CollectingHandler()

    receiver = AgentBus(agent_id="sparrow", broker=host, port=port, retain=False)
    receiver.register_handler(handler)
    sender = AgentBus(agent_id="wren", broker=host, port=port, retain=False)

    body = "# Report\n```python\nprint('hi')\n```\n> Note: tested."

    listen_task = asyncio.create_task(receiver.listen())
    await asyncio.sleep(0.2)

    await sender.send(
        to="sparrow", subject="report",
        body=body, content_type="text/markdown",
    )
    await handler.wait_for_message(timeout=3.0)

    listen_task.cancel()
    try:
        await listen_task
    except (asyncio.CancelledError, Exception):
        pass

    assert handler.received[0].body == body
    assert handler.received[0].content_type == "text/markdown"
