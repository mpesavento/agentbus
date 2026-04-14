# agentbus

Reactive pub/sub messaging for AI agents — no polling, instant delivery. Built on MQTT, runs local, scales to multi-machine.

## Install

```bash
pip install agentbus
# with optional features:
pip install "agentbus[archive,mcp]"
```

## Prerequisites

```bash
sudo apt install mosquitto mosquitto-clients
# or use the setup script:
bash scripts/setup-mosquitto.sh
```

## Quickstart

```python
from agentbus import AgentBus, FileBridgeHandler, PersistentListenerHandler

bus = AgentBus(agent_id="sparrow", broker="localhost")
bus.register_handler(FileBridgeHandler("~/sync/inbox.md"))
bus.register_handler(PersistentListenerHandler())

# Send a message
await bus.send(to="wren", subject="hello", body="Hi Wren!")

# Listen (blocks)
bus.run()
```

## CLI

```bash
# Send — inline body
agentbus send --agent-id sparrow --to wren --subject hello --body "Hi Wren"

# Send — body from file
agentbus send --agent-id sparrow --to wren --subject report --body-file report.md

# Send — body from stdin (pipe-friendly)
cat report.md | agentbus send --agent-id sparrow --to wren --subject report --body-file -

# Start listener with file bridge
agentbus start --agent-id sparrow --inbox ~/sync/inbox.md

# Start MCP sidecar (for Claude Code / any MCP agent)
agentbus mcp-server --agent-id sparrow
```

`--body` and `--body-file` are mutually exclusive; exactly one is required.

## Claude Code Plugin

```bash
bash scripts/setup-cc-plugin.sh sparrow localhost
# Restart Claude Code — send_message, read_inbox, watch_inbox, list_agents tools available
```

## Architecture

```
Agent A (Sparrow)           Agent B (Wren)
  AgentBus(embedded)          AgentBus(embedded)
        │                           │
        └────────────┬──────────────┘
                 mosquitto
             (system service)
```

Every agent is a peer. Broker is infrastructure. No hub. Cross-machine: change `broker="localhost"` to `broker="clawd-rpi.ts.net"`.

## Handlers

| Handler | What it does |
|---|---|
| `FileBridgeHandler(path)` | Writes messages to a file (backward-compat with file-polling agents) |
| `DirectInvocationHandler(cmd)` | Invokes a command on message arrival; body via stdin, shell=False |
| `PersistentListenerHandler()` | Stats + heartbeat for always-on agents |
| `SQLiteArchive(path)` | Logs all messages to SQLite |

## Message Envelope

```json
{
  "id": "uuid4",
  "from": "sparrow",
  "to": "wren",
  "ts": "2026-04-14T05:00:00Z",
  "subject": "hello",
  "body": "...",
  "content_type": "text/plain",
  "priority": "normal",
  "reply_to": null
}
```

`content_type`: `text/plain` | `text/markdown` | `text/x-code;lang=python` | `application/json`

## License

MIT
