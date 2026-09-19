#!/usr/bin/env bash
# Prepare the Pi for Petronilo's agent brain (AGENT = True in 18_voice_active_crawler_gpt.py).
# Safe to re-run. On the Pi:  sudo bash ~/picrawler/examples/petronilo/setup_agent.sh
#
# The voice service stays root (servos, camera, audio). The Claude Code CLI it drives runs as
# AGENT_USER, a system account that owns nothing but its workspace and its own ~/.claude.
set -euo pipefail

AGENT_USER=${AGENT_USER:-petronilo}
OWNER=${SUDO_USER:?run with sudo from your own account}
OWNER_HOME=$(getent passwd "$OWNER" | cut -d: -f6)
EXAMPLES="$OWNER_HOME/picrawler/examples"

[ "$(id -u)" -eq 0 ] || { echo "needs sudo" >&2; exit 1; }

if ! id "$AGENT_USER" >/dev/null 2>&1; then
    useradd --system --create-home --shell /bin/bash "$AGENT_USER"
fi
AGENT_HOME=$(getent passwd "$AGENT_USER" | cut -d: -f6)
install -d -o "$AGENT_USER" -g "$AGENT_USER" -m 700 \
    "$AGENT_HOME" "$AGENT_HOME/workspace" "$AGENT_HOME/.claude" "$AGENT_HOME/.claude/skills"

# The service imports the SDK as root; the wheel bundles the Claude Code CLI.
pip3 install --quiet --break-system-packages claude-agent-sdk

# Keep the agent's user out of the keys and the family's memory: the agent's
# own file tools are limited by agent_policy, but an allowed command is not.
chmod 700 "$OWNER_HOME"
chmod 600 "$EXAMPLES"/secret.py 2>/dev/null || true
[ -f "$EXAMPLES/petronilo_mcp.json" ] && chmod 600 "$EXAMPLES/petronilo_mcp.json"

grep -q ANTHROPIC_API_KEY "$EXAMPLES/secret.py" 2>/dev/null \
    || echo "missing: ANTHROPIC_API_KEY = \"...\" in $EXAMPLES/secret.py"

cat <<EOF
$AGENT_USER is ready. Next:
  skills:  put SKILL.md folders in $AGENT_HOME/.claude/skills/ (owned by $AGENT_USER)
  MCP:     $EXAMPLES/petronilo_mcp.json, {"mcpServers": {...}}; servers start as $AGENT_USER
  CLI auth for allowed commands, e.g.:  sudo -u $AGENT_USER -H gh auth login
  then:    make deploy   (from the Mac)
EOF
