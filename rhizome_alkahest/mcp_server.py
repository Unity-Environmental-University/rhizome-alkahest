"""
rhizome MCP server — exposes the knowledge graph as Claude tools.

No bash required. Claude can record and query edges directly.

Frame state persists in .edge/frame (scoped to git root),
so sessions started in the CLI are visible here and vice versa.
"""

import json
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .db import connect
from .edge import Edge
from .frame import Frame
from .frame_pointer import frame_dir, read_token, write_token, git_context
from .graph import Graph

mcp = FastMCP("rhizome")


# ---------------------------------------------------------------------------
# Frame helpers
# ---------------------------------------------------------------------------

def _load_frame() -> Frame | None:
    token = read_token()
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


def _fmt_edge(e: Edge) -> str:
    return f"({e.subject} --{e.predicate}--> {e.object}) [{e.confidence:.2f}, {e.phase}, @{e.observer}]"


def _fmt_edges(edges: list[Edge]) -> str:
    if not edges:
        return "no edges found"
    return "\n".join(_fmt_edge(e) for e in edges)


# ---------------------------------------------------------------------------
# Tools — Frame
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
    ctx = git_context()
    short = hashlib.sha1(f"{who}:{time.time()}".encode()).hexdigest()[:8]
    token = f"{who}:{short}"

    conn = connect()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO frames (token, who, cwd, context) VALUES (%s, %s, %s, %s)",
            (token, who, cwd, json.dumps(ctx)),
        )
    conn.commit()
    conn.close()

    write_token(token)

    # Store composite metadata for post-truth registration
    composite_file = frame_dir() / "frame.composite"
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
    token = read_token()
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

        # Auto-generate starmap
        from .cli import _starmap_inner
        try:
            _starmap_inner(quiet=True)
            starmap_path = frame_dir() / "starmap"
            if starmap_path.exists():
                result += f"\nStarmap ready: {starmap_path}"
        except Exception:
            pass

        # Auto-register composite speaks-as/speaks-for
        composite_file = frame_dir() / "frame.composite"
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


# ---------------------------------------------------------------------------
# Tools — Record & Query
# ---------------------------------------------------------------------------

@mcp.tool()
def edge_add(
    subject: str,
    predicate: str,
    object: str,
    confidence: float = 0.7,
    phase: str = "fluid",
    note: str = "",
    slug: str = "",
) -> str:
    """Record an edge from the current frame. Use --slug to name it. Use e[slug] as subject to reference another edge."""
    frame = _load_frame()
    if not frame:
        return "No frame. Call edge_iam first."
    if not frame.ready:
        return f"Frame incomplete ({len(frame.truths)}/3 truths). Call edge_true."

    g = Graph(frame)
    # Resolve e[slug], e[hash], or e[s p o] notation
    if subject.startswith("e[") and subject.endswith("]"):
        inner = subject[2:-1]
        parts = inner.split()
        if len(parts) == 3:
            ref = g.resolve_triple(parts[0], parts[1], parts[2])
            if ref is None:
                return f"error: no live edge matching ({parts[0]} --{parts[1]}--> {parts[2]})"
        else:
            ref = g.resolve_slug(inner)
            if ref is None:
                return f"error: no live edge with slug/hash '{inner}'"
        subject = f"e:{ref.subject}/{ref.predicate}/{ref.object}"

    edge = g.add(subject, predicate, object, confidence, phase, note, slug=slug or None)
    result = f"+ {_fmt_edge(edge)}"
    result += f"\n  #{edge.hash}"
    if slug:
        result += f"\n  slug: {slug}"
    if note:
        result += f"\n  note: {note}"
    return result


@mcp.tool()
def edge_about(subject: str) -> str:
    """All living edges with this subject. No frame required."""
    conn = connect()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT e.subject, e.predicate, e.object, e.confidence, e.phase, f.who
            FROM live_edges e JOIN frames f ON e.observer = f.token
            WHERE e.subject = %s ORDER BY e.confidence DESC
        """, (subject,))
        rows = cur.fetchall()
    conn.close()
    if not rows:
        return "no edges found"
    return "\n".join(
        f"({s} --{p}--> {o}) [{c:.2f}, {ph}, @{w}]"
        for s, p, o, c, ph, w in rows
    )


@mcp.tool()
def edge_find(term: str) -> str:
    """Search subject, predicate, and object for a term. No frame required."""
    conn = connect()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT e.subject, e.predicate, e.object, e.confidence, e.phase, f.who
            FROM live_edges e JOIN frames f ON e.observer = f.token
            WHERE e.subject ILIKE %s OR e.predicate ILIKE %s OR e.object ILIKE %s
            ORDER BY e.confidence DESC
        """, (f"%{term}%", f"%{term}%", f"%{term}%"))
        rows = cur.fetchall()
    conn.close()
    if not rows:
        return "no edges found"
    return "\n".join(
        f"({s} --{p}--> {o}) [{c:.2f}, {ph}, @{w}]"
        for s, p, o, c, ph, w in rows
    )


@mcp.tool()
def edge_from(who: str) -> str:
    """All living edges recorded by this observer (across all their frames). No frame required."""
    conn = connect()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT e.subject, e.predicate, e.object, e.confidence, e.phase
            FROM live_edges e JOIN frames f ON e.observer = f.token
            WHERE f.who = %s ORDER BY e.updated_at DESC
        """, (who,))
        rows = cur.fetchall()
    conn.close()
    if not rows:
        return "no edges found"
    return "\n".join(
        f"({s} --{p}--> {o}) [{c:.2f}, {ph}]"
        for s, p, o, c, ph in rows
    )


@mcp.tool()
def edge_parallax(
    subject: str | None = None,
    predicate: str | None = None,
    object: str | None = None,
) -> str:
    """
    Where observers disagree. No frame required.
    Returns triples with spread between min and max confidence across distinct observers.
    """
    conn = connect()
    query = "SELECT * FROM parallax"
    params: list = []
    conditions = []
    if subject:
        conditions.append("subject = %s"); params.append(subject)
    if predicate:
        conditions.append("predicate = %s"); params.append(predicate)
    if object:
        conditions.append("object = %s"); params.append(object)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY spread DESC"
    with conn.cursor() as cur:
        cur.execute(query, params)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    conn.close()
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
    result = f"{frame.who} ({status})\ntoken: {frame.token}"
    if frame.truths:
        for t in frame.truths:
            result += f"\ntruth: ({t['s']} --{t['p']}--> {t['o']})"
    return result


@mcp.tool()
def edge_count() -> str:
    """Summary stats by phase and total. No frame required."""
    conn = connect()
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM phase_summary")
        phases = cur.fetchall()
        cur.execute("SELECT count(*) FROM live_edges")
        total = cur.fetchone()[0]
    conn.close()
    lines = [f"total: {total}"]
    for phase, n, avg_c in phases:
        lines.append(f"  {phase}: {n} edges, avg confidence {avg_c:.2f}")
    return "\n".join(lines)


@mcp.tool()
def edge_ls(phase: str | None = None) -> str:
    """List living edges, optionally filtered by phase."""
    conn = connect()
    with conn.cursor() as cur:
        if phase:
            cur.execute("""
                SELECT e.subject, e.predicate, e.object, e.confidence, f.who
                FROM live_edges e JOIN frames f ON e.observer = f.token
                WHERE e.phase = %s ORDER BY e.updated_at DESC
            """, (phase,))
        else:
            cur.execute("""
                SELECT e.subject, e.predicate, e.object, e.confidence, e.phase, f.who
                FROM live_edges e JOIN frames f ON e.observer = f.token
                ORDER BY e.updated_at DESC
            """)
        rows = cur.fetchall()
    conn.close()

    if not rows:
        return "no edges found"

    lines = []
    for row in rows:
        if phase:
            s, p, o, c, w = row
            lines.append(f"({s} --{p}--> {o}) [{c:.2f}, {phase}, @{w}]")
        else:
            s, p, o, c, ph, w = row
            lines.append(f"({s} --{p}--> {o}) [{c:.2f}, {ph}, @{w}]")
    return "\n".join(lines)


@mcp.tool()
def edge_frames() -> str:
    """List all reference frames."""
    conn = connect()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT f.token, f.who, f.cwd, f.created_at,
                   (SELECT count(*) FROM live_edges e WHERE e.observer = f.token) as edges
            FROM frames f ORDER BY f.created_at DESC
        """)
        rows = cur.fetchall()
    conn.close()

    if not rows:
        return "no frames"
    lines = []
    for token, who, cwd, created_at, n_edges in rows:
        lines.append(f"{who:<30} {n_edges:>4} edges  {str(created_at)[:16]}  {token}")
    return "\n".join(lines)


@mcp.tool()
def edge_orient(days: int = 7) -> str:
    """
    Orientation map — shows what's entering, glowing, sailing toward/away,
    now oriented toward, and signal traveling back through.
    """
    from datetime import date
    repo = os.path.basename(os.getcwd())
    width = 60

    lines = [
        "",
        f"  ORIENTATION MAP  —  {repo}  —  {date.today().isoformat()}",
        f"  {'─' * width}",
        "",
    ]

    conn = connect()
    sections = [
        ("ENTERING", "enters", "{subject} → {object}", 6, True),
        ("GLOWING", "glows-because", "{subject}\n      {object}", 8, True),
        ("SAILING TOWARD", "sails-toward", "{subject} → {object}", 6, True),
        ("SAILING AWAY FROM", "sails-away-from", "{subject} ← {object}", 6, True),
        ("NOW ORIENTED TOWARD", "now-oriented-toward", "{object}", 5, True),
        ("SIGNAL TRAVELS BACK THROUGH", "travels-back-through", "{object}", 8, False),
    ]

    for title, predicate, fmt, limit, use_time_filter in sections:
        lines.append(f"  {title}")
        time_clause = f"AND e.created_at > now() - interval '{days} days'" if use_time_filter else ""
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT e.subject, e.object FROM live_edges e
                WHERE e.predicate = %s {time_clause}
                ORDER BY e.created_at DESC LIMIT %s
            """, (predicate, limit))
            rows = cur.fetchall()
        for subject, obj in rows:
            lines.append("    " + fmt.format(subject=subject, object=obj))
        lines.append("")

    lines.append(f"  {'─' * width}")
    lines.append("")
    conn.close()

    return "\n".join(lines)


@mcp.tool()
def edge_starmap() -> str:
    """
    Build a starmap document — nearby graph from current frame's truths.
    Written to .edge/starmap as readable markdown.
    """
    from .cli import _starmap_inner
    import io, contextlib

    f = io.StringIO()
    with contextlib.redirect_stdout(f):
        _starmap_inner(quiet=False)
    return f.getvalue() or "no starmap generated (missing frame or truths)"


@mcp.tool()
def edge_ran(movement: str) -> str:
    """
    Register a movement run and show prior deposits from other instances.
    """
    # Record the run
    frame = _load_frame()
    if not frame or not frame.ready:
        return "No active frame. Call edge_iam + edge_true (x3) first."

    g = Graph(frame)
    g.add("this-session", "ran", movement)

    # Fetch prior deposits
    conn = connect()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COALESCE(e.notes, ''),
                   e.subject || ' --' || e.predicate || '--> ' || e.object,
                   f.who,
                   to_char(e.created_at, 'YYYY-MM-DD')
            FROM live_edges e
            JOIN frames f ON e.observer = f.token
            WHERE (e.subject = %s OR e.object = %s OR e.predicate ILIKE %s)
              AND e.subject != 'this-session'
            ORDER BY e.created_at DESC LIMIT 20
        """, (movement, movement, f"%{movement}%"))
        rows = cur.fetchall()
    conn.close()

    lines = [
        f"  + (this-session --ran--> {movement}) [{frame.who}]",
        "",
        f"  PRIOR DEPOSITS  —  {movement}",
        "  ────────────────────────────────────────",
    ]
    for notes, edge_str, who, dt in rows:
        parts = [p for p in [notes, edge_str, who, dt] if p]
        lines.append(" | ".join(parts))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Thread tools — cross-Claude conversation threads
# ---------------------------------------------------------------------------

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
    pos = git_context()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO edges (subject, predicate, object, confidence, phase, observer, positionality)
            VALUES (%s, 'thread-read', %s, 1.0, 'volatile', %s, %s)
            ON CONFLICT DO NOTHING
        """, (frame.token, full_slug, frame.token, json.dumps(pos)))
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

    full_slug = f"thread:{slug}"
    pos = git_context()
    conn = connect()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO edges (subject, predicate, object, confidence, phase, observer, notes, positionality)
            VALUES (%s, 'thread-wrote', %s, 1.0, 'fluid', %s, %s, %s)
        """, (frame.token, full_slug, frame.token, body, json.dumps(pos)))
        # mark as read
        cur.execute("""
            INSERT INTO edges (subject, predicate, object, confidence, phase, observer, positionality)
            VALUES (%s, 'thread-read', %s, 1.0, 'volatile', %s, %s)
            ON CONFLICT DO NOTHING
        """, (frame.token, full_slug, frame.token, json.dumps(pos)))
    conn.commit()
    conn.close()
    return f"reply added to: {slug}\nby: {frame.who}"


@mcp.tool()
def thread_new(slug: str, title: str = "") -> str:
    """Create a new thread."""
    frame = _load_frame()
    if not frame or not frame.ready:
        return "No active frame. Call edge_iam + edge_true (x3) first."

    full_slug = f"thread:{slug}"
    label = title or slug
    pos = git_context()
    conn = connect()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO edges (subject, predicate, object, confidence, phase, observer, notes, positionality)
            VALUES (%s, 'thread-title', %s, 1.0, 'fluid', %s, %s, %s)
            ON CONFLICT DO NOTHING
        """, (full_slug, slug, frame.token, label, json.dumps(pos)))
    conn.commit()
    conn.close()
    return f"thread created: {slug}\ntitle: {label}\nuse: thread_reply('{slug}', body)"


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
