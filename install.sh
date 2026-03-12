#!/usr/bin/env bash
# install.sh — set up rhizome-alkahest on a new machine
#
# What this does:
#   1. Creates the database and loads the schema
#   2. Links the edge CLI into ~/utils (or a bin of your choice)
#   3. Links the Claude skill into ~/.claude/skills/rhizome/
#      so any Claude on this machine can navigate the graph

set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${1:-$HOME/utils}"
SKILL_TARGET="$HOME/.claude/skills/rhizome"

CLAUDE_SETTINGS="$HOME/.claude/settings.json"
PYTHON="$(which python3)"

echo "==> rhizome-alkahest install"
echo "    repo:    $REPO_DIR"
echo "    bin:     $BIN_DIR"
echo "    skill:   $SKILL_TARGET"
echo "    python:  $PYTHON"
echo "    claude:  $CLAUDE_SETTINGS"
echo ""

# 1. Database
echo "==> Setting up database..."
if createdb rhizome-alkahest 2>/dev/null; then
    echo "    created database rhizome-alkahest"
else
    echo "    database rhizome-alkahest already exists, skipping"
fi
psql -q rhizome-alkahest < "$REPO_DIR/schema.sql"
echo "    schema loaded"

# 2. edge CLI
echo "==> Linking edge CLI..."
mkdir -p "$BIN_DIR"
chmod +x "$REPO_DIR/edge"
ln -sf "$REPO_DIR/edge" "$BIN_DIR/edge"
echo "    edge -> $BIN_DIR/edge"

# 3. Claude skill
echo "==> Linking Claude skill..."
mkdir -p "$(dirname "$SKILL_TARGET")"
ln -sf "$REPO_DIR/.claude/skills/rhizome" "$SKILL_TARGET"
echo "    skill -> $SKILL_TARGET"

# 4. Install Python package
echo "==> Installing Python package..."
pip3 install -e "$REPO_DIR" -q
echo "    rhizome-alkahest installed"

# 5. Register MCP server in ~/.claude/settings.json
echo "==> Registering MCP server..."
mkdir -p "$(dirname "$CLAUDE_SETTINGS")"
if [[ ! -f "$CLAUDE_SETTINGS" ]]; then
    echo '{}' > "$CLAUDE_SETTINGS"
fi
# Use python to safely merge into existing JSON
$PYTHON - <<EOF
import json, sys
from pathlib import Path

settings_path = Path("$CLAUDE_SETTINGS")
settings = json.loads(settings_path.read_text())
settings.setdefault("mcpServers", {})
settings["mcpServers"]["rhizome"] = {
    "command": "$PYTHON",
    "args": ["-m", "rhizome_alkahest.mcp_server"],
    "cwd": "$REPO_DIR",
}
settings_path.write_text(json.dumps(settings, indent=2))
print("    registered rhizome MCP server")
EOF

echo ""
echo "Done. Restart Claude Code to load the MCP server."
echo ""
echo "Then try (no bash needed):"
echo "  edge_iam(who='you')"
echo "  edge_true('something', 'you', 'know')  # three times"
echo "  edge_add('subject', 'predicate', 'object')"
echo ""
echo "Or use the bash CLI: edge iam <you>"
