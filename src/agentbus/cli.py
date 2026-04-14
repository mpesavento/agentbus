from __future__ import annotations

import asyncio
import click

from .bus import AgentBus
from .handlers.file_bridge import FileBridgeHandler
from .handlers.direct_invoke import DirectInvocationHandler
from .handlers.persistent import PersistentListenerHandler


@click.group()
def main() -> None:
    """agentbus — reactive MQTT messaging for AI agents."""


@main.command()
@click.option("--agent-id", required=True, help="This agent's ID")
@click.option("--to", "to_agent", required=True, help="Target agent ID")
@click.option("--subject", required=True, help="Message subject")
@click.option("--body", required=True, help="Message body")
@click.option("--broker", default="localhost", show_default=True)
@click.option("--port", default=1883, show_default=True)
@click.option("--content-type", default="text/plain", show_default=True)
def send(
    agent_id: str,
    to_agent: str,
    subject: str,
    body: str,
    broker: str,
    port: int,
    content_type: str,
) -> None:
    """Send a message to another agent."""
    bus = AgentBus(agent_id=agent_id, broker=broker, port=port)
    asyncio.run(bus.send(
        to=to_agent,
        subject=subject,
        body=body,
        content_type=content_type,
    ))
    click.echo(f"Sent to {to_agent}")


@main.command()
@click.option("--agent-id", required=True, help="This agent's ID")
@click.option("--broker", default="localhost", show_default=True)
@click.option("--port", default=1883, show_default=True)
@click.option("--inbox", default=None, help="Path for file bridge (inbox.md)")
@click.option("--invoke", "invoke_cmd", default=None, help="Command to invoke on message")
def start(
    agent_id: str,
    broker: str,
    port: int,
    inbox: str | None,
    invoke_cmd: str | None,
) -> None:
    """Start the agentbus listener daemon."""
    bus = AgentBus(agent_id=agent_id, broker=broker, port=port)

    if inbox:
        bus.register_handler(FileBridgeHandler(inbox))
    if invoke_cmd:
        bus.register_handler(DirectInvocationHandler(command=invoke_cmd.split()))

    persistent = PersistentListenerHandler()
    bus.register_handler(persistent)

    click.echo(f"[agentbus] {agent_id} listening on {broker}:{port}")
    try:
        bus.run()
    except KeyboardInterrupt:
        click.echo("\n[agentbus] shutting down")


@main.command("mcp-server")
@click.option("--agent-id", required=True, help="This agent's ID")
@click.option("--broker", default="localhost", show_default=True)
@click.option("--port", default=1883, show_default=True)
def mcp_server(agent_id: str, broker: str, port: int) -> None:
    """Start the MCP sidecar for this agent."""
    from .mcp_server import run_mcp_server
    run_mcp_server(agent_id=agent_id, broker=broker, port=port)
