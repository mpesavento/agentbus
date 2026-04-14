# agentbus — Design Spec

*Date: 2026-04-14*
*Authors: Mike Pesavento + Sparrow*
*Status: Approved — ready for implementation*

---

## What We're Building

A lightweight, reactive pub/sub messaging layer for AI agents. Agents communicate as peers through an MQTT broker. No polling, no central server, no framework lock-in.

**One-line architecture:** agentbus is a thin MQTT adapter per agent. The broker is infrastructure. Agents are peers. No hub.

---

## Core Principles

1. **Mesh, not hub.** Every agent is a peer. The broker routes; it doesn't own logic or state.
2. **Broker is infrastructure.** mosquitto runs as a system service, like a network switch. agentbus doesn't manage it.
3. **Transport-only bus.** `AgentBus` handles connect/send/subscribe/presence. Business logic lives in handlers.
4. **Async core, sync shim.** Built on aiomqtt. `bus.run()` provides a sync entry point via `asyncio.run()`.
5. **Per-agent, not per-system.** Each agent runs its own AgentBus instance. The MCP server is a per-agent sidecar, not a central API.

---

## Topology

```
Agent A (e.g. Sparrow)        Agent B (e.g. Wren)
  AgentBus(embedded)            AgentBus(embedded)
       │                              │
       └──────────────┬───────────────┘
                  mosquitto
              (system service)
```

Cross-machine: change `broker="localhost"` → `broker="clawd-rpi.ts.net"`. Everything else is identical. Tailscale handles auth/encryption at the network layer.

---

## Topic Schema

```
agents/{agent-id}/inbox      # directed messages TO this agent
agents/{agent-id}/presence   # online/offline announcements
agents/broadcast             # all-agents messages
```

**QoS:**
- Inbox: QoS 1 (at-least-once), `retain=True` (agent gets last message on reconnect)
- Presence: QoS 0 (fire-and-forget)
- Broadcast: QoS 1

**LWT (Last Will and Testament):** Registered at connect time. Broker publishes `agents/{id}/presence = {"status": "offline"}` automatically if agent disconnects unexpectedly. No code required.

---

## Message Envelope

```json
{
  "id": "uuid4",
  "from": "sparrow",
  "to": "wren",
  "ts": "2026-04-14T05:00:00Z",
  "subject": "status update",
  "body": "...",
  "priority": "normal",
  "reply_to": null
}
```

- `id`: UUID4, generated on send
- `priority`: `"normal"` | `"urgent"`
- `reply_to`: message `id` of the message being replied to, or `null`
- Validated with Pydantic on receive. Invalid envelopes are logged and discarded.

---

## Package Structure

```
agentbus/
├── src/
│   └── agentbus/
│       ├── __init__.py         # public API surface
│       ├── message.py          # AgentMessage dataclass + Pydantic validation
│       ├── bus.py              # AgentBus — connect, send, listen, presence
│       ├── handlers/
│       │   ├── __init__.py
│       │   ├── base.py         # BaseHandler ABC: async handle(msg) -> None
│       │   ├── file_bridge.py  # writes received messages to inbox.md
│       │   ├── direct_invoke.py # shells out to claude -p or custom command
│       │   └── persistent.py   # reconnect loop, heartbeat, long-running listener
│       ├── archive.py          # SQLiteArchive — implements BaseHandler, logs all messages
│       ├── cli.py              # click CLI: agentbus send / listen / mcp-server / start
│       └── mcp_server.py       # MCP sidecar: send_message, read_inbox, list_agents tools
├── tests/
│   ├── conftest.py             # mosquitto fixture for integration tests
│   ├── test_message.py
│   ├── test_bus.py
│   └── handlers/
│       ├── test_file_bridge.py
│       ├── test_direct_invoke.py
│       └── test_persistent.py
├── examples/
│   ├── sparrow_wren_local.py   # two agents, one Pi
│   └── cross_machine.py        # two agents, Tailscale
├── scripts/
│   └── setup-mosquitto.sh      # install + configure mosquitto as systemd service
├── pyproject.toml              # uv-managed, Python 3.9+
└── README.md
```

---

## AgentBus API

```python
from agentbus import AgentBus, FileBridgeHandler, DirectInvocationHandler, PersistentListenerHandler, SQLiteArchive

# Construct
bus = AgentBus(
    agent_id="sparrow",
    broker="localhost",       # or remote host
    port=1883,
    retain=True,
)

# Register handlers (any combination)
bus.register_handler(FileBridgeHandler(inbox_path="~/sparrow-workspace/sync/inbox.md"))
bus.register_handler(DirectInvocationHandler(command="claude -p '{body}' --session-id agent-inbox"))
bus.register_handler(PersistentListenerHandler())
bus.register_handler(SQLiteArchive(db_path="~/.agentbus/archive.db"))  # optional, logs everything

# Async usage
await bus.connect()                                    # connects, announces presence
await bus.send(to="wren", subject="hello", body="...")
await bus.listen()                                     # blocks, dispatches to handlers
await bus.disconnect()                                 # offline presence, clean disconnect

# Sync shim
bus.run()  # asyncio.run(bus.listen())
```

---

## Handlers

### BaseHandler (ABC)
```python
class BaseHandler:
    async def handle(self, msg: AgentMessage) -> None:
        raise NotImplementedError
```

### FileBridgeHandler
Appends received message to a file in a format compatible with existing `sync/inbox.md` tooling. Backward-compatible migration path.

### DirectInvocationHandler
Shells out to a configurable command on message arrival. Default template: `claude -p '{body}'`. Command receives full message envelope as env vars (`AGENTBUS_FROM`, `AGENTBUS_SUBJECT`, etc.) and body via stdin.

### PersistentListenerHandler
Manages a long-running listener process: reconnect loop with exponential backoff, configurable heartbeat, presence announcements on reconnect. Suitable for always-on agents.

### SQLiteArchive
Logs all messages (sent and received) to SQLite. Schema: `messages(id, from, to, ts, subject, body, priority, reply_to, direction, error)`. Optional — plugs in as a handler.

---

## MCP Sidecar

`agentbus mcp-server --agent-id sparrow --broker localhost`

Exposes three MCP tools:

| Tool | Description |
|---|---|
| `send_message` | Publish a message to another agent's inbox |
| `read_inbox` | Read queued messages for this agent |
| `list_agents` | List agents currently announcing presence |

Per-agent, not central. Each agent that wants MCP access runs its own sidecar. Stateless — reads from MQTT, no local DB required (unless archive is enabled).

---

## Deployment Configurations

| Config | Command | Use case |
|---|---|---|
| Embedded | `AgentBus(...).run()` | Python agent owns its own lifecycle |
| Local daemon | `agentbus start` | Always-on agent process, local only |
| Network daemon | `agentbus start --bind 0.0.0.0` | Accessible over Tailscale/LAN |
| MCP sidecar | `agentbus mcp-server` | Expose to any MCP-compatible agent |

One config file (`~/.agentbus/config.toml` or per-project `.agentbus.toml`):

```toml
[agentbus]
agent_id = "sparrow"
broker = "localhost"
port = 1883
bind_host = "127.0.0.1"

[interfaces]
mcp_server = true
mcp_port = 7890

[handlers]
file_bridge = "~/sparrow-workspace/sync/inbox.md"
archive = "~/.agentbus/archive.db"
```

---

## Error Handling

| Scenario | Behavior |
|---|---|
| Broker unreachable at start | Fail fast, clear error message |
| Broker disconnect during listen | Auto-reconnect with exponential backoff (aiomqtt native) |
| Unexpected disconnect | LWT fires, broker publishes offline presence |
| Handler exception | Caught, logged, bus continues. Other handlers unaffected. |
| Invalid message envelope | Pydantic validation error logged, message discarded, bus continues |
| Archive write failure | Logged, message processing continues |

---

## Testing Strategy

**Unit tests** (no broker required):
- `test_message.py` — envelope serialization, Pydantic validation, edge cases
- `test_bus.py` — routing logic, handler dispatch, with mocked aiomqtt
- `handlers/test_*.py` — each handler independently with mock `AgentMessage` input

**Integration tests** (requires mosquitto):
- `conftest.py` provides a pytest fixture that spins up a local mosquitto instance
- Full send→receive→handler pipeline
- Reconnect behavior
- Presence announcements

**Smoke tests:**
- `examples/sparrow_wren_local.py` runs in CI against the test broker
- Validates the full user-facing API end-to-end

---

## Build Roadmap

- [ ] `scripts/setup-mosquitto.sh` — install + systemd service
- [ ] `message.py` — AgentMessage + Pydantic validation
- [ ] `bus.py` — AgentBus core (connect, send, listen, presence, LWT)
- [ ] `handlers/base.py` — BaseHandler ABC
- [ ] `handlers/file_bridge.py`
- [ ] `handlers/direct_invoke.py`
- [ ] `handlers/persistent.py`
- [ ] `archive.py` — SQLiteArchive handler
- [ ] `cli.py` — click CLI (send, listen, start, mcp-server)
- [ ] `mcp_server.py` — MCP sidecar (send_message, read_inbox, list_agents)
- [ ] Unit tests
- [ ] Integration tests (mosquitto fixture)
- [ ] `examples/sparrow_wren_local.py`
- [ ] `examples/cross_machine.py`
- [ ] PyPI packaging

---

## Dependencies

```toml
[project]
name = "agentbus"
version = "0.1.0"
requires-python = ">=3.9"
dependencies = [
    "aiomqtt>=2.0",
    "pydantic>=2.0",
    "click>=8.0",
]

[project.optional-dependencies]
archive = ["aiosqlite>=0.19"]
mcp = ["mcp>=1.0"]

[project.scripts]
agentbus = "agentbus.cli:main"
```
