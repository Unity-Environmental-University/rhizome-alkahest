"""
Frame pointer — scoped to git root or CWD.

Both the CLI and MCP server use this to find/store the current frame token.
Replaces the old global ~/.edge_frame with per-repo .edge/frame.
"""

import hashlib
import os
import subprocess
from pathlib import Path


def _git_root() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return None


def frame_dir() -> Path:
    """Return the directory for frame state (.edge/ under git root, or CWD-hashed)."""
    root = _git_root()
    if root:
        d = Path(root) / ".edge"
    else:
        h = hashlib.md5(os.getcwd().encode()).hexdigest()
        d = Path.home() / ".edge_frames" / h
    d.mkdir(parents=True, exist_ok=True)
    return d


def frame_file() -> Path:
    return frame_dir() / "frame"


def read_token() -> str | None:
    f = frame_file()
    if not f.exists():
        return None
    token = f.read_text().strip()
    return token or None


def write_token(token: str):
    frame_file().write_text(token)


def git_context() -> dict:
    """Return git repo/branch/cwd context for positionality."""
    def _run(cmd):
        try:
            return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()
        except Exception:
            return ""
    return {
        "cwd": os.getcwd(),
        "repo": _run(["git", "remote", "get-url", "origin"]).split("/")[-1].removesuffix(".git"),
        "branch": _run(["git", "branch", "--show-current"]),
    }
