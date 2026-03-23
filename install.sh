#!/usr/bin/env bash
# install.sh — set up rhizome-alkahest on a new machine
#
# What this does:
#   1. Checks prerequisites (PostgreSQL, pgvector, Python 3)
#   2. Creates the database and loads the schema
#   3. Links the edge CLI into ~/utils (or a bin of your choice)
#   4. Links the Claude skill into ~/.claude/skills/rhizome/
#   5. Installs the Python package
#   6. Registers the MCP server in ~/.claude/settings.json
#
# Usage:
#   ./install.sh              # installs to ~/utils
#   ./install.sh ~/bin        # installs to ~/bin

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${1:-$HOME/utils}"
SKILL_TARGET="$HOME/.claude/skills/rhizome"
CLAUDE_SETTINGS="$HOME/.claude/settings.json"

# ── Detect platform ──────────────────────────────────────────────────────────

OS="$(uname -s)"
case "$OS" in
  Darwin) PLATFORM="mac" ;;
  Linux)  PLATFORM="linux" ;;
  *)      echo "Unsupported platform: $OS"; exit 1 ;;
esac

echo "==> rhizome-alkahest install"
echo "    platform: $PLATFORM"
echo "    repo:     $REPO_DIR"
echo "    bin:      $BIN_DIR"
echo "    skill:    $SKILL_TARGET"
echo ""

# ── Check prerequisites ──────────────────────────────────────────────────────

check_postgres() {
  if ! command -v psql &>/dev/null; then
    echo "ERROR: psql not found. Install PostgreSQL first."
    if [[ "$PLATFORM" == "mac" ]]; then
      echo "  brew install postgresql@17 pgvector"
      echo "  brew services start postgresql@17"
      echo "  export PATH=\"/opt/homebrew/opt/postgresql@17/bin:\$PATH\""
    else
      echo "  sudo apt install postgresql postgresql-contrib  # Debian/Ubuntu"
      echo "  sudo systemctl start postgresql"
      echo "  # pgvector: https://github.com/pgvector/pgvector#installation"
    fi
    exit 1
  fi
}

check_python() {
  if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Install Python 3.10+ first."
    if [[ "$PLATFORM" == "mac" ]]; then
      echo "  brew install python"
    else
      echo "  sudo apt install python3 python3-pip"
    fi
    exit 1
  fi
  PYTHON="$(command -v python3)"
}

check_postgres
check_python

# ── Database ─────────────────────────────────────────────────────────────────

echo "==> Setting up database..."
if createdb rhizome-alkahest 2>/dev/null; then
  echo "    created database rhizome-alkahest"
else
  echo "    database rhizome-alkahest already exists, skipping"
fi
psql -q rhizome-alkahest < "$REPO_DIR/schema.sql"
echo "    schema loaded"

# ── edge CLI ─────────────────────────────────────────────────────────────────

echo "==> Linking edge CLI..."
mkdir -p "$BIN_DIR"
chmod +x "$REPO_DIR/edge"
ln -sf "$REPO_DIR/edge" "$BIN_DIR/edge"
echo "    edge -> $BIN_DIR/edge"

# Remind if BIN_DIR isn't on PATH
if ! echo "$PATH" | tr ':' '\n' | grep -qx "$BIN_DIR"; then
  echo ""
  echo "    NOTE: $BIN_DIR is not on your PATH."
  echo "    Add this to your shell profile (~/.zshrc or ~/.bashrc):"
  echo "      export PATH=\"$BIN_DIR:\$PATH\""
  echo ""
fi

# ── Claude skill ─────────────────────────────────────────────────────────────

echo "==> Linking Claude skill..."
mkdir -p "$(dirname "$SKILL_TARGET")"
SKILL_SRC="$REPO_DIR/.claude/skills/rhizome"
if [[ -d "$SKILL_SRC" ]]; then
  ln -sf "$SKILL_SRC" "$SKILL_TARGET"
  echo "    skill -> $SKILL_TARGET"
else
  echo "    (skill directory not found, skipping)"
fi

# ── Python package ───────────────────────────────────────────────────────────

echo "==> Installing Python package..."
"$PYTHON" -m pip install -e "$REPO_DIR" -q
echo "    rhizome-alkahest installed (editable)"

# ── MCP server registration ──────────────────────────────────────────────────

echo "==> Registering MCP server in Claude settings..."
mkdir -p "$(dirname "$CLAUDE_SETTINGS")"
if [[ ! -f "$CLAUDE_SETTINGS" ]]; then
  echo '{}' > "$CLAUDE_SETTINGS"
fi

"$PYTHON" - <<EOF
import json
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

# ── Done ─────────────────────────────────────────────────────────────────────

echo ""
echo "Done. Restart Claude Code to load the MCP server."
echo ""
echo "Try it:"
echo "  edge iam you"
echo "  edge true something you know"
echo "  edge true something else you_know"
echo "  edge true a_third thing from_here"
echo "  edge add subject predicate object"
echo ""
