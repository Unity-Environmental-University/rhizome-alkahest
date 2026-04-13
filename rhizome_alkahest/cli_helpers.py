"""Shared helpers for CLI command modules.

These are the common utilities that multiple command files need:
frame loading, edge formatting, etc.
"""

import sys

from .db import connect
from .frame import Frame
from .frame_pointer import read_token


def load_frame(conn=None):
    """Load the current frame from the pointer file."""
    token = read_token()
    if not token:
        return None
    c = conn or connect()
    with c.cursor() as cur:
        cur.execute("SELECT token, who, cwd, truths FROM frames WHERE token = %s", (token,))
        row = cur.fetchone()
    if conn is None:
        c.close()
    if not row:
        return None
    return Frame(token=row[0], who=row[1], cwd=row[2], truths=row[3])


def require_frame(conn=None):
    """Load frame, exit if missing or incomplete."""
    frame = load_frame(conn)
    if not frame:
        print("  no reference frame. run: edge iam <who>")
        sys.exit(1)
    if not frame.ready:
        print(f"  frame incomplete ({len(frame.truths)}/3 truths). run: edge true <s> <p> <o>")
        sys.exit(1)
    return frame


def fmt_edge(e):
    return f"({e.subject} --{e.predicate}--> {e.object}) [{e.confidence:.2f}, {e.phase}, @{e.observer}]"


def resolve_subject(subject: str, graph) -> str:
    """Resolve e[slug], e[hash], or e[s p o] notation to edge-as-subject text."""
    if subject.startswith("e[") and subject.endswith("]"):
        inner = subject[2:-1]
        parts = inner.split()
        if len(parts) == 3:
            edge = graph.resolve_triple(parts[0], parts[1], parts[2])
            if edge is None:
                print(f"  error: no live edge matching ({parts[0]} --{parts[1]}--> {parts[2]})")
                sys.exit(1)
        else:
            edge = graph.resolve_slug(inner)
            if edge is None:
                print(f"  error: no live edge with slug/hash '{inner}'")
                sys.exit(1)
        return f"e:{edge.subject}/{edge.predicate}/{edge.object}"
    return subject
