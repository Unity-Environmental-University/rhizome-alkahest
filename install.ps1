# install.ps1 — set up rhizome-alkahest on Windows
#
# Prerequisites (install these first):
#   - PostgreSQL 17: https://www.postgresql.org/download/windows/
#   - pgvector: https://github.com/pgvector/pgvector#windows
#   - Python 3.10+: https://www.python.org/downloads/
#   - Claude Code: https://claude.ai/download
#
# Usage (run from repo root in PowerShell as your normal user):
#   .\install.ps1
#   .\install.ps1 -BinDir "$HOME\bin"

param(
    [string]$BinDir = "$HOME\utils"
)

$ErrorActionPreference = "Stop"
$RepoDir = $PSScriptRoot

Write-Host "==> rhizome-alkahest install (Windows)"
Write-Host "    repo:  $RepoDir"
Write-Host "    bin:   $BinDir"
Write-Host ""

# ── Check prerequisites ──────────────────────────────────────────────────────

if (-not (Get-Command psql -ErrorAction SilentlyContinue)) {
    Write-Error @"
psql not found. Install PostgreSQL 17 first:
  https://www.postgresql.org/download/windows/

Then ensure psql.exe is on your PATH (usually C:\Program Files\PostgreSQL\17\bin).
"@
    exit 1
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error @"
python not found. Install Python 3.10+ first:
  https://www.python.org/downloads/

Check "Add Python to PATH" during installation.
"@
    exit 1
}

$Python = (Get-Command python).Source

# ── Database ─────────────────────────────────────────────────────────────────

Write-Host "==> Setting up database..."
$createResult = & createdb rhizome-alkahest 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "    created database rhizome-alkahest"
} else {
    Write-Host "    database rhizome-alkahest already exists, skipping"
}
& psql -q rhizome-alkahest -f "$RepoDir\schema.sql"
Write-Host "    schema loaded"

# ── edge CLI ─────────────────────────────────────────────────────────────────

Write-Host "==> Installing edge CLI..."
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null

# On Windows, edge is a bash script — it needs Git Bash or WSL.
# We create a small .cmd shim that invokes it via bash.
$shimPath = "$BinDir\edge.cmd"
$edgePath = "$RepoDir\edge" -replace '\\', '/'
@"
@echo off
bash "$edgePath" %*
"@ | Set-Content -Path $shimPath
Write-Host "    edge.cmd -> $shimPath"
Write-Host "    (requires Git Bash or WSL on PATH)"

# ── Python package ───────────────────────────────────────────────────────────

Write-Host "==> Installing Python package..."
& $Python -m pip install -e $RepoDir -q
Write-Host "    rhizome-alkahest installed (editable)"

# ── MCP server registration ──────────────────────────────────────────────────

Write-Host "==> Registering MCP server in Claude settings..."
$ClaudeSettings = "$HOME\.claude\settings.json"
New-Item -ItemType Directory -Force -Path (Split-Path $ClaudeSettings) | Out-Null
if (-not (Test-Path $ClaudeSettings)) {
    '{}' | Set-Content -Path $ClaudeSettings
}

$script = @"
import json
from pathlib import Path

settings_path = Path(r'$ClaudeSettings')
settings = json.loads(settings_path.read_text())
settings.setdefault('mcpServers', {})
settings['mcpServers']['rhizome'] = {
    'command': r'$Python',
    'args': ['-m', 'rhizome_alkahest.mcp_server'],
    'cwd': r'$RepoDir',
}
settings_path.write_text(json.dumps(settings, indent=2))
print('    registered rhizome MCP server')
"@
& $Python -c $script

# ── Claude skill ─────────────────────────────────────────────────────────────

Write-Host "==> Linking Claude skill..."
$SkillSrc = "$RepoDir\.claude\skills\rhizome"
$SkillTarget = "$HOME\.claude\skills\rhizome"
if (Test-Path $SkillSrc) {
    New-Item -ItemType Directory -Force -Path (Split-Path $SkillTarget) | Out-Null
    if (Test-Path $SkillTarget) { Remove-Item $SkillTarget -Recurse -Force }
    # Junction (directory symlink) — no admin required on Windows 10+
    New-Item -ItemType Junction -Path $SkillTarget -Target $SkillSrc | Out-Null
    Write-Host "    skill -> $SkillTarget"
} else {
    Write-Host "    (skill directory not found, skipping)"
}

# ── Done ─────────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "Done. Restart Claude Code to load the MCP server."
Write-Host ""
Write-Host "Try it (in Git Bash or WSL):"
Write-Host "  edge iam you"
Write-Host "  edge true something you know"
Write-Host "  edge add subject predicate object"
Write-Host ""
Write-Host "NOTE: The edge CLI is a bash script. On Windows it runs via Git Bash."
Write-Host "      If you use WSL, you may prefer running install.sh inside WSL instead."
Write-Host ""
