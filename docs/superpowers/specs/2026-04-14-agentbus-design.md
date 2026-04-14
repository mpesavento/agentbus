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

Cross-machine: change `broker="localhost"` → `broker="broker-host.your-tailnet.ts.net"`. Everything else is identical. Tailscale handles auth/encryption at the network layer.

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
  "content_type": "text/plain",
  "priority": "normal",
  "reply_to": null
}
```

- `id`: UUID4, generated on send
- `priority`: `"normal"` | `"urgent"`
- `reply_to`: message `id` of the message being replied to, or `null`
- `content_type`: `"text/plain"` | `"text/markdown"` | `"text/x-code;lang=python"` | `"application/json"`. Body is always a raw string — the transport layer never transforms it. Content type is a hint for the receiver. Nested markdown containing code blocks is valid `text/markdown` with no special handling needed.
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
│   ├── setup-mosquitto.sh      # install + configure mosquitto as systemd service
│   └── setup-cc-plugin.sh      # write agentbus MCP entry to .claude/settings.json
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
Shells out to a configurable command on message arrival. Body is passed via **stdin** or a temp file — never interpolated into a shell string. Envelope fields are exposed as env vars (`AGENTBUS_FROM`, `AGENTBUS_SUBJECT`, `AGENTBUS_CONTENT_TYPE`, etc.). Default: `subprocess.run(["claude", "-p", prompt_file], input=body.encode())`.

### PersistentListenerHandler
Manages a long-running listener process: reconnect loop with exponential backoff, configurable heartbeat, presence announcements on reconnect. Suitable for always-on agents.

### SQLiteArchive
Logs all messages (sent and received) to SQLite. Schema: `messages(id, from, to, ts, subject, body, priority, reply_to, direction, error)`. Optional — plugs in as a handler.

---

## MCP Sidecar

`agentbus mcp-server --agent-id sparrow --broker localhost`

Exposes four MCP tools:

| Tool | Description |
|---|---|
| `send_message` | Publish a message to another agent's inbox |
| `read_inbox` | Read queued messages for this agent (poll) |
| `watch_inbox` | Long-poll — blocks until a new message arrives, then returns it. CC calls this to get push-style delivery. |
| `list_agents` | List agents currently announcing presence |

Per-agent, not central. Each agent that wants MCP access runs its own sidecar. Stateless — reads from MQTT, no local DB required (unless archive is enabled).

**Claude Code plugin registration** (`.claude/settings.json`):
```json
{
  "mcpServers": {
    "agentbus": {
      "command": "agentbus",
      "args": ["mcp-server", "--agent-id", "sparrow", "--broker", "localhost"]
    }
  }
}
```

`scripts/setup-cc-plugin.sh` writes this entry automatically.

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

## Security

| Surface | Mitigation |
|---|---|
| Agent ID injection in topic paths | Validated at `AgentBus` construction: `[a-z0-9_-]+` only, max 64 chars. Rejected with clear error. |
| Command injection in DirectInvocationHandler | Body passed via stdin or temp file only. Never interpolated into shell strings. `subprocess.run()` with explicit arg list, not `shell=True`. |
| Message size | Configurable `max_body_bytes` (default 64KB). Messages over limit are logged and discarded. |
| Rate limiting | Configurable `max_msg_per_second` per sender (default 10). Excess messages dropped and logged. |
| Network exposure | Off by default (`bind_host = "127.0.0.1"`). For network deployments, document mosquitto password auth as opt-in hardening. Tailscale handles encryption for cross-machine setups. |

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
- [ ] `scripts/setup-cc-plugin.sh` — register MCP sidecar in .claude/settings.json
- [ ] `message.py` — AgentMessage + Pydantic validation
- [ ] `bus.py` — AgentBus core (connect, send, listen, presence, LWT)
- [ ] `handlers/base.py` — BaseHandler ABC
- [ ] `handlers/file_bridge.py`
- [ ] `handlers/direct_invoke.py`
- [ ] `handlers/persistent.py`
- [ ] `archive.py` — SQLiteArchive handler
- [ ] `cli.py` — click CLI (send, listen, start, mcp-server)
- [ ] `mcp_server.py` — MCP sidecar (send_message, read_inbox, watch_inbox, list_agents)
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

---

# Addendum — shipped beyond this spec (post-v1.0)

This spec is frozen as the design-intent record. Everything below reflects
features / docs / scripts that shipped once agentbus was in use and
surfaced needs the original spec didn't anticipate. Full change history:
[CHANGELOG.md](../../../CHANGELOG.md). Live task queue for open items:
[docs/post-ship-backlog.md](../../post-ship-backlog.md).

## CLI surface additions

The spec committed to `send` / `listen` / `mcp-server` / `start`. Shipped
in addition:

- `agentbus read` — non-blocking MQTT drain, returns retained queue.
- `agentbus watch` — long-poll MQTT for one new message, block then exit.
- `agentbus list` — enumerate online peers (MQTT-native).
- `agentbus tail` — cursor-based file consumer for the daemon's inbox
  file. The correct read path when a listener daemon is running —
  avoids the race between an active daemon and a separate `agentbus
  read` on the same id.

All four have CLI parity with the MCP tool surface and share the same
underlying implementation on `AgentBus`.

## Envelope & archive

- `--outbox <path>` on `agentbus send`, plus `AGENTBUS_OUTBOX` (with
  `{agent_id}` template) and agent-scoped `AGENTBUS_OUTBOX_<ID>` env
  vars — symmetric outbound archive to match the inbox file.
- `--reply-to` on CLI (the envelope field existed; CLI didn't expose it).
- `--priority {low,normal,high}` on CLI (same).
- `priority` envelope field loosened from `Literal` to `str` after a
  silent-discard incident during rolling upgrade. Wire-compat discipline
  now codified in `CHANGELOG.md`.

## Wake wrappers (reactive push)

Not in the spec; emerged from the "archive is not notification" realization
during deployment.

- `examples/openclaw-wake.sh <openclaw-agent-id>` — wraps
  `openclaw agent --message` so a priority=high inbound spawns a real
  OpenClaw reasoning turn.
- `examples/claude-code-wake.sh <agent-id>` — equivalent via
  `claude --print` for Claude Code peers.

Both sanitize envelope fields and render bodies under explicit
`[UNTRUSTED PEER METADATA]` / `[UNTRUSTED PEER BODY]` framing to block
prompt injection via subject/from/reply_to.

## Deployment docs + scripts

- `docs/cross-machine-tailscale.md` — full Tailscale walkthrough
  (topology, verification, security, failure modes, preflight).
- `docs/notification-patterns.md` — 4-tier notification protocol
  (archive always / narrate mid-chat / push on priority=high / silent
  otherwise) with per-agent-system recipes.
- `scripts/setup-mosquitto.sh` gained `--tailscale` and
  `--tailscale-only` modes.
- `scripts/setup-openclaw-plugin.sh` and `scripts/setup-cc-plugin.sh` —
  per-host installers.
- `scripts/inbox-watch.sh` — cron-driven Telegram summariser for new
  inbox entries (works independently of wake wrappers; complementary
  under the 4-tier protocol).

## Operational & protocol discipline

- Persistent MQTT sessions (`--persistent` on `agentbus start`, default
  on) — broker queues QoS1 messages for a disconnected daemon until
  reconnect.
- Daemons move to systemd user units with `loginctl enable-linger` —
  survive logout, auto-restart, proper logs. The `nohup` pattern we
  shipped on day one was too fragile (SIGHUP on logout killed it silent).
- CHANGELOG.md with explicit "wire-compat" bullet per release. Any
  envelope shape / topic layout / retain-QoS default / MCP tool
  contract change is called out so a rolling fleet knows whether a
  full restart is needed.
