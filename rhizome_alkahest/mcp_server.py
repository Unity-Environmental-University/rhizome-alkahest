"""
rhizome MCP server — exposes the knowledge graph as Claude tools.

No bash required. Claude can record and query edges directly.

Frame state persists in ~/.edge_frame (same file as the bash CLI),
so sessions started in the CLI are visible here and vice versa.
"""

import json
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .db import connect
from .edge import Edge
from .frame import Frame
from .graph import Graph

FRAME_FILE = Path.home() / ".edge_frame"
mcp = FastMCP("rhizome")


# ---------------------------------------------------------------------------
# Frame helpers
# ---------------------------------------------------------------------------

def _load_frame() -> Frame | None:
    if not FRAME_FILE.exists():
        return None
    token = FRAME_FILE.read_text().strip()
    if not token:
        return None
    conn = connect()
    with conn.cursor() as cur:
        cur.execute("SELECT token, who, cwd, truths FROM frames WHERE token = %s", (token,))
        row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return Frame(token=row[0], who=row[1], cwd=row[2], truths=row[3])


def _save_token(token: str):
    FRAME_FILE.write_text(token)


def _fmt_edge(e: Edge) -> str:
    return f"({e.subject} --{e.predicate}--> {e.object}) [{e.confidence:.2f}, {e.phase}, @{e.observer}]"


def _fmt_edges(edges: list[Edge]) -> str:
    if not edges:
        return "no edges found"
    return "\n".join(_fmt_edge(e) for e in edges)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def edge_iam(
    who: str,
    speaks_as: list[str] | None = None,
    speaks_for: list[str] | None = None,
) -> str:
    """
    Start a new reference frame. Must call edge_true three times afterward
    before recording edges.

    For composite frames (speaking as multiple voices or on behalf of another):
      speaks_as=["claude", "hallie"], speaks_for=["chris"]
    derives name "claude+hallie-reading-chris" and auto-registers
    speaks-as and speaks-for edges once the frame is ready.
    """
    import hashlib, time

    if speaks_as or speaks_for:
        as_part = "+".join(speaks_as or [])
        for_part = "+".join(speaks_for or [])
        if as_part and for_part:
            who = f"{as_part}-reading-{for_part}"
        elif as_part:
            who = as_part

    cwd = os.getcwd()
    short = hashlib.sha1(f"{who}:{time.time()}".encode()).hexdigest()[:8]
    token = f"{who}:{short}"

    conn = connect()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO frames (token, who, cwd) VALUES (%s, %s, %s)",
            (token, who, cwd),
        )
    conn.commit()
    conn.close()

    _save_token(token)

    # Store composite metadata for post-truth registration
    composite_file = Path(str(FRAME_FILE) + ".composite")
    if speaks_as or speaks_for:
        composite_file.write_text(json.dumps({
            "as": speaks_as or [],
            "for": speaks_for or [],
        }))
    else:
        composite_file.unlink(missing_ok=True)

    return (
        f"I am {who}. Frame: {token}\n"
        "Establish your reference frame. Say three true things:\n"
        "  edge_true(subject, predicate, object)"
    )


@mcp.tool()
def edge_true(subject: str, predicate: str, object: str) -> str:
    """
    Say a true thing from your current position.
    Must be called three times to establish a reference frame.
    """
    token = FRAME_FILE.read_text().strip() if FRAME_FILE.exists() else None
    if not token:
        return "No frame started. Call edge_iam first."

    conn = connect()
    truth = {"s": subject, "p": predicate, "o": object}
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE frames SET truths = truths || %s::jsonb WHERE token = %s",
            (json.dumps(truth), token),
        )
        cur.execute("SELECT jsonb_array_length(truths), who FROM frames WHERE token = %s", (token,))
        n, who = cur.fetchone()
    conn.commit()

    result = f"truth {n}/3: ({subject} --{predicate}--> {object})"

    if n >= 3:
        result += "\nReference frame established. You can now record edges."

        # Auto-register composite speaks-as/speaks-for
        composite_file = Path(str(FRAME_FILE) + ".composite")
        if composite_file.exists():
            composite = json.loads(composite_file.read_text())
            registered = []
            for speaks_as in composite.get("as", []):
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO edges (subject, predicate, object, confidence, phase, observer, notes)
                           VALUES (%s, 'speaks-as', %s, 1.0, 'salt', %s, 'auto-registered on frame creation')
                           ON CONFLICT DO NOTHING""",
                        (who, speaks_as, token),
                    )
                registered.append(f"({who} --speaks-as--> {speaks_as}) [1.0, salt]")
            for speaks_for in composite.get("for", []):
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO edges (subject, predicate, object, confidence, phase, observer, notes)
                           VALUES (%s, 'speaks-for', %s, 0.7, 'fluid', %s, 'auto-registered on frame creation')
                           ON CONFLICT DO NOTHING""",
                        (who, speaks_for, token),
                    )
                registered.append(f"({who} --speaks-for--> {speaks_for}) [0.7, fluid]")
            conn.commit()
            composite_file.unlink(missing_ok=True)
            if registered:
                result += "\n" + "\n".join(f"+ {r}" for r in registered)

    conn.close()
    return result


@mcp.tool()
def edge_add(
    subject: str,
    predicate: str,
    object: str,
    confidence: float = 0.7,
    phase: str = "fluid",
    note: str = "",
) -> str:
    """Record an edge from the current frame."""
    frame = _load_frame()
    if not frame:
        return "No frame. Call edge_iam first."
    if not frame.ready:
        return f"Frame incomplete ({len(frame.truths)}/3 truths). Call edge_true."

    g = Graph(frame)
    edge = g.add(subject, predicate, object, confidence, phase, note)
    result = f"+ {_fmt_edge(edge)}"
    if note:
        result += f"\n  note: {note}"
    return result


@mcp.tool()
def edge_about(subject: str) -> str:
    """All living edges with this subject."""
    frame = _load_frame()
    if not frame or not frame.ready:
        return "No active frame. Call edge_iam + edge_true (x3) first."
    g = Graph(frame)
    return _fmt_edges(g.about(subject))


@mcp.tool()
def edge_find(term: str) -> str:
    """Search subject, predicate, and object for a term."""
    frame = _load_frame()
    if not frame or not frame.ready:
        return "No active frame. Call edge_iam + edge_true (x3) first."
    g = Graph(frame)
    return _fmt_edges(g.find(term))


@mcp.tool()
def edge_from(who: str) -> str:
    """All living edges recorded by this observer (across all their frames)."""
    frame = _load_frame()
    if not frame or not frame.ready:
        return "No active frame. Call edge_iam + edge_true (x3) first."
    g = Graph(frame)
    return _fmt_edges(g.from_observer(who))


@mcp.tool()
def edge_parallax(
    subject: str | None = None,
    predicate: str | None = None,
    object: str | None = None,
) -> str:
    """
    Where observers disagree. Returns triples with spread between
    min and max confidence across distinct observers.
    Optionally filter to a specific subject/predicate/object.
    """
    frame = _load_frame()
    if not frame or not frame.ready:
        return "No active frame. Call edge_iam + edge_true (x3) first."
    g = Graph(frame)
    rows = g.parallax(subject, predicate, object)
    if not rows:
        return "no parallax — all observers agree (or only one observer)"
    lines = []
    for r in rows:
        lines.append(
            f"({r['subject']} --{r['predicate']}--> {r['object']}) "
            f"spread={r['spread']:.3f} observers={r['observers']} "
            f"[{r['min_confidence']:.2f}–{r['max_confidence']:.2f}] "
            f"who={r['who']}"
        )
    return "\n".join(lines)


@mcp.tool()
def edge_dissolve(subject: str, predicate: str, object: str) -> str:
    """Soft-delete all living edges matching this triple."""
    frame = _load_frame()
    if not frame or not frame.ready:
        return "No active frame. Call edge_iam + edge_true (x3) first."
    g = Graph(frame)
    n = g.dissolve(subject, predicate, object)
    return f"dissolved {n} edge(s): ({subject} --{predicate}--> {object})"


@mcp.tool()
def edge_whoami() -> str:
    """Show the current reference frame."""
    frame = _load_frame()
    if not frame:
        return "No frame. Call edge_iam first."
    status = "ready" if frame.ready else f"{len(frame.truths)}/3 truths"
    return f"{frame.who} ({status})\ntoken: {frame.token}"


@mcp.tool()
def edge_count() -> str:
    """Summary stats by phase and total."""
    frame = _load_frame()
    if not frame or not frame.ready:
        return "No active frame. Call edge_iam + edge_true (x3) first."
    g = Graph(frame)
    stats = g.count()
    lines = [f"total: {stats['total']}"]
    for phase, data in stats["phases"].items():
        lines.append(f"  {phase}: {data['n']} edges, avg confidence {data['avg_confidence']:.2f}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Thread tools — cross-Claude conversation threads
# ---------------------------------------------------------------------------

def _git_context() -> dict:
    import subprocess
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


@mcp.tool()
def thread_ls() -> str:
    """List Claude-to-Claude conversation threads with read/unread status."""
    frame = _load_frame()
    if not frame or not frame.ready:
        return "No active frame. Call edge_iam + edge_true (x3) first."

    conn = connect()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT e.object AS slug,
                (SELECT notes FROM edges
                 WHERE subject = e.object AND predicate = 'thread-title'
                   AND dissolved_at IS NULL LIMIT 1) AS title,
                MAX(e.created_at) AS last_message
            FROM edges e
            WHERE e.predicate = 'thread-wrote' AND e.dissolved_at IS NULL
            GROUP BY e.object ORDER BY last_message DESC
        """)
        threads = cur.fetchall()

    if not threads:
        return "(no threads)"

    lines = []
    unread = 0
    for slug, title, last_msg in threads:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT MAX(created_at) FROM edges
                WHERE subject = %s AND predicate = 'thread-read'
                  AND object = %s AND dissolved_at IS NULL
            """, (frame.token, slug))
            last_read = cur.fetchone()[0]

        display = slug.removeprefix("thread:")
        label = title or display
        if not last_read or last_msg > last_read:
            lines.append(f"[UNREAD]  {display:<40}  {label}")
            unread += 1
        else:
            lines.append(f"[read]    {display:<40}  {label}")

    conn.close()
    lines.append(f"\n{unread} unread")
    return "\n".join(lines)


@mcp.tool()
def thread_cat(slug: str) -> str:
    """Read a thread by slug and mark it as read."""
    frame = _load_frame()
    if not frame or not frame.ready:
        return "No active frame. Call edge_iam + edge_true (x3) first."

    full_slug = f"thread:{slug}"
    conn = connect()

    with conn.cursor() as cur:
        cur.execute("""
            SELECT notes FROM edges
            WHERE subject = %s AND predicate = 'thread-title' AND dissolved_at IS NULL
            LIMIT 1
        """, (full_slug,))
        row = cur.fetchone()
    title = row[0] if row else slug

    with conn.cursor() as cur:
        cur.execute("""
            SELECT e.notes, f.who, e.created_at,
                   e.positionality->>'repo' AS repo,
                   e.positionality->>'branch' AS branch,
                   e.positionality->>'cwd' AS cwd
            FROM edges e
            JOIN frames f ON e.observer = f.token
            WHERE e.object = %s AND e.predicate = 'thread-wrote' AND e.dissolved_at IS NULL
            ORDER BY e.created_at ASC
        """, (full_slug,))
        messages = cur.fetchall()

    lines = [f"# {title}", ""]
    for body, who, created_at, repo, branch, cwd in messages:
        ctx_parts = [p for p in [repo, branch, cwd] if p]
        ctx = ", ".join(ctx_parts)
        lines.append("---")
        lines.append("")
        header = f"**{who}** — {str(created_at)[:16]}"
        if ctx:
            header += f" — _{ctx}_"
        lines.append(header)
        lines.append("")
        lines.append(body or "")
        lines.append("")
    lines.append("---")

    # mark read
    import json as _json
    pos = _git_context()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO edges (subject, predicate, object, confidence, phase, observer, positionality)
            VALUES (%s, 'thread-read', %s, 1.0, 'volatile', %s, %s)
            ON CONFLICT DO NOTHING
        """, (frame.token, full_slug, frame.token, _json.dumps(pos)))
    conn.commit()
    conn.close()

    return "\n".join(lines)


@mcp.tool()
def thread_reply(slug: str, body: str) -> str:
    """Append a message to a thread."""
    frame = _load_frame()
    if not frame or not frame.ready:
        return "No active frame. Call edge_iam + edge_true (x3) first."
    if not body.strip():
        return "Empty body — nothing added."

    import json as _json
    full_slug = f"thread:{slug}"
    pos = _git_context()
    conn = connect()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO edges (subject, predicate, object, confidence, phase, observer, notes, positionality)
            VALUES (%s, 'thread-wrote', %s, 1.0, 'fluid', %s, %s, %s)
        """, (frame.token, full_slug, frame.token, body, _json.dumps(pos)))
        # mark as read
        cur.execute("""
            INSERT INTO edges (subject, predicate, object, confidence, phase, observer, positionality)
            VALUES (%s, 'thread-read', %s, 1.0, 'volatile', %s, %s)
            ON CONFLICT DO NOTHING
        """, (frame.token, full_slug, frame.token, _json.dumps(pos)))
    conn.commit()
    conn.close()
    return f"reply added to: {slug}\nby: {frame.who}"


@mcp.tool()
def thread_new(slug: str, title: str = "") -> str:
    """Create a new thread."""
    frame = _load_frame()
    if not frame or not frame.ready:
        return "No active frame. Call edge_iam + edge_true (x3) first."

    import json as _json
    full_slug = f"thread:{slug}"
    label = title or slug
    pos = _git_context()
    conn = connect()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO edges (subject, predicate, object, confidence, phase, observer, notes, positionality)
            VALUES (%s, 'thread-title', %s, 1.0, 'fluid', %s, %s, %s)
            ON CONFLICT DO NOTHING
        """, (full_slug, slug, frame.token, label, _json.dumps(pos)))
    conn.commit()
    conn.close()
    return f"thread created: {slug}\ntitle: {label}\nuse: thread_reply('{slug}', body)"


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
