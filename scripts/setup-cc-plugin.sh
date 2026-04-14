#!/usr/bin/env bash
# scripts/setup-cc-plugin.sh
# Register agentbus MCP sidecar in Claude Code settings.json.
set -euo pipefail

AGENT_ID="${1:-}"
BROKER="${2:-localhost}"

if [ -z "$AGENT_ID" ]; then
  echo "Usage: $0 <agent-id> [broker-host]"
  echo "  Example: $0 sparrow localhost"
  exit 1
fi

SETTINGS_FILE="${HOME}/.claude/settings.json"

if [ ! -f "$SETTINGS_FILE" ]; then
  echo '{}' > "$SETTINGS_FILE"
fi

python3 - "$SETTINGS_FILE" "$AGENT_ID" "$BROKER" <<'EOF'
import json, sys

settings_path, agent_id, broker = sys.argv[1], sys.argv[2], sys.argv[3]

with open(settings_path) as f:
    settings = json.load(f)

settings.setdefault("mcpServers", {})
settings["mcpServers"]["agentbus"] = {
    "command": "agentbus",
    "args": ["mcp-server", "--agent-id", agent_id, "--broker", broker]
}

with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)

print(f"[agentbus] Registered MCP sidecar in {settings_path}")
print(f"[agentbus] agent-id: {agent_id}, broker: {broker}")
print("[agentbus] Restart Claude Code to pick up the new MCP server.")
EOF
