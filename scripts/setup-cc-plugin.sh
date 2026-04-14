#!/usr/bin/env bash
# scripts/setup-cc-plugin.sh
# Register agentbus MCP sidecar in Claude Code settings.json and install the
# behavioral skill that teaches Claude when/how to use the MCP tools.
set -euo pipefail

AGENT_ID="${1:-}"
BROKER="${2:-localhost}"

if [ -z "$AGENT_ID" ]; then
  echo "Usage: $0 <agent-id> [broker-host]"
  echo "  Example: $0 planner localhost"
  exit 1
fi

SETTINGS_FILE="${HOME}/.claude/settings.json"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SKILL_SRC="$REPO_ROOT/skills/using-agentbus"
SKILL_DST="$HOME/.claude/skills/using-agentbus"

if [ ! -f "$SETTINGS_FILE" ]; then
  mkdir -p "$(dirname "$SETTINGS_FILE")"
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
EOF

# Install the behavioral skill so Claude Code knows when/how to use the tools.
if [ -d "$SKILL_SRC" ]; then
  mkdir -p "$(dirname "$SKILL_DST")"
  cp -r "$SKILL_SRC" "$SKILL_DST"
  echo "[agentbus] Installed skill at $SKILL_DST"
else
  echo "[agentbus] WARNING: skill source not found at $SKILL_SRC — MCP tools will work but Claude won't have usage guidance"
fi

echo "[agentbus] Restart Claude Code to pick up the new MCP server + skill."
