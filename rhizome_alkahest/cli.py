"""
edge CLI — single implementation for both CLI and MCP.

Usage: python -m rhizome_alkahest.cli <command> [args...]
"""

import json
import os
import sys
from datetime import date
from pathlib import Path

from .db import connect
from .edge import Edge
from .frame import Frame
from .frame_pointer import frame_dir, read_token, write_token, git_context
from .graph import Graph


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_frame(conn=None):
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


def _require_frame(conn=None):
    """Load frame, exit if missing or incomplete."""
    frame = _load_frame(conn)
    if not frame:
        print("  no reference frame. run: edge iam <who>")
        sys.exit(1)
    if not frame.ready:
        print(f"  frame incomplete ({len(frame.truths)}/3 truths). run: edge true <s> <p> <o>")
        sys.exit(1)
    return frame


def _fmt_edge(e):
    return f"({e.subject} --{e.predicate}--> {e.object}) [{e.confidence:.2f}, {e.phase}, @{e.observer}]"


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_iam(args):
    speaks_as = []
    speaks_for = []
    in_for = False
    for a in args:
        if a == "--for":
            in_for = True
        elif a == "--as":
            in_for = False
        elif in_for:
            speaks_for.append(a)
        else:
            speaks_as.append(a)

    if speaks_as and speaks_for:
        who = "+".join(speaks_as) + "-reading-" + "+".join(speaks_for)
    elif speaks_as:
        who = "+".join(speaks_as)
    else:
        print("usage: edge iam <who>")
        print("       edge iam <self> [<self2> ...] --for <other> [<other2> ...]")
        sys.exit(1)

    import hashlib, time
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
    print(f"  I am {who}. Frame: {token}")
    print("  Establish your reference frame. Say three true things:")
    print("    edge true <subject> <predicate> <object>")

    # Store composite lists for post-truth registration
    composite_file = frame_dir() / "frame.composite"
    if speaks_for:
        composite_file.write_text(f"as:{' '.join(speaks_as)}\nfor:{' '.join(speaks_for)}\n")
    else:
        composite_file.unlink(missing_ok=True)


def cmd_true(args):
    if len(args) < 3:
        print("usage: edge true <subject> <predicate> <object>")
        sys.exit(1)

    token = read_token()
    if not token:
        print("  no frame started. run: edge iam <who>")
        sys.exit(1)

    subject, predicate, obj = args[0], args[1], args[2]
    truth = {"s": subject, "p": predicate, "o": obj}

    conn = connect()
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE frames SET truths = truths || %s::jsonb WHERE token = %s",
            (json.dumps(truth), token),
        )
        cur.execute("SELECT jsonb_array_length(truths), who FROM frames WHERE token = %s", (token,))
        n, who = cur.fetchone()
    conn.commit()

    print(f"  truth {n}/3: ({subject} --{predicate}--> {obj})")

    if n >= 3:
        print("  Reference frame established. You can now record edges.")
        _starmap_inner(quiet=True)
        starmap_path = frame_dir() / "starmap"
        if starmap_path.exists():
            print(f"  Starmap ready: {starmap_path}  (run: edge starmap)")
        # Auto-register composite speaks-as/speaks-for
        composite_file = frame_dir() / "frame.composite"
        if composite_file.exists():
            text = composite_file.read_text()
            as_line = ""
            for_line = ""
            for line in text.strip().split("\n"):
                if line.startswith("as:"):
                    as_line = line[3:]
                elif line.startswith("for:"):
                    for_line = line[4:]
            for sa in as_line.split():
                if sa:
                    with conn.cursor() as cur:
                        cur.execute(
                            """INSERT INTO edges (subject, predicate, object, confidence, phase, observer, notes)
                               VALUES (%s, 'speaks-as', %s, 1.0, 'salt', %s, 'auto-registered on frame creation')
                               ON CONFLICT DO NOTHING""",
                            (who, sa, token),
                        )
                    print(f"  + ({who} --speaks-as--> {sa}) [1.0, salt]")
            for sf in for_line.split():
                if sf:
                    with conn.cursor() as cur:
                        cur.execute(
                            """INSERT INTO edges (subject, predicate, object, confidence, phase, observer, notes)
                               VALUES (%s, 'speaks-for', %s, 0.7, 'fluid', %s, 'auto-registered on frame creation')
                               ON CONFLICT DO NOTHING""",
                            (who, sf, token),
                        )
                    print(f"  + ({who} --speaks-for--> {sf}) [0.7, fluid]")
            conn.commit()
            composite_file.unlink(missing_ok=True)
    conn.close()


def cmd_add(args):
    confidence = 0.7
    phase = "fluid"
    note = ""
    positional = []
    i = 0
    while i < len(args):
        if args[i] == "--confidence" and i + 1 < len(args):
            confidence = float(args[i + 1]); i += 2
        elif args[i] == "--phase" and i + 1 < len(args):
            phase = args[i + 1]; i += 2
        elif args[i] == "--note" and i + 1 < len(args):
            note = args[i + 1]; i += 2
        else:
            positional.append(args[i]); i += 1

    if len(positional) < 3:
        print("usage: edge add <s> <p> <o> [--confidence N] [--phase P] [--note 'text']")
        sys.exit(1)

    subject, predicate, obj = positional[0], positional[1], positional[2]
    frame = _require_frame()
    g = Graph(frame)
    edge = g.add(subject, predicate, obj, confidence, phase, note)
    print(f"  + {_fmt_edge(edge)}")
    if note:
        print(f"    note: {note}")


def cmd_find(args):
    if not args:
        print("usage: edge find <term>")
        sys.exit(1)
    conn = connect()
    with conn.cursor() as cur:
        term = args[0]
        cur.execute("""
            SELECT e.subject, e.predicate, e.object, e.confidence, e.phase, f.who
            FROM live_edges e JOIN frames f ON e.observer = f.token
            WHERE e.subject ILIKE %s OR e.predicate ILIKE %s OR e.object ILIKE %s
            ORDER BY e.confidence DESC
        """, (f"%{term}%", f"%{term}%", f"%{term}%"))
        rows = cur.fetchall()
    conn.close()
    if not rows:
        print("  no edges found")
    else:
        for s, p, o, c, ph, w in rows:
            print(f"  ({s} --{p}--> {o}) [{c:.2f}, {ph}, @{w}]")


def cmd_about(args):
    if not args:
        print("usage: edge about <subject>")
        sys.exit(1)
    conn = connect()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT e.predicate, e.object, e.confidence, e.phase, f.who
            FROM live_edges e JOIN frames f ON e.observer = f.token
            WHERE e.subject = %s ORDER BY e.confidence DESC
        """, (args[0],))
        rows = cur.fetchall()
    conn.close()
    if not rows:
        print("  no edges found")
    else:
        for p, o, c, ph, w in rows:
            print(f"  --{p}--> {o} [{c:.2f}, {ph}, @{w}]")


def cmd_from(args):
    if not args:
        print("usage: edge from <who>")
        sys.exit(1)
    conn = connect()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT e.subject, e.predicate, e.object, e.confidence, e.phase
            FROM live_edges e JOIN frames f ON e.observer = f.token
            WHERE f.who = %s ORDER BY e.updated_at DESC
        """, (args[0],))
        rows = cur.fetchall()
    conn.close()
    if not rows:
        print("  no edges found")
    else:
        for s, p, o, c, ph in rows:
            print(f"  ({s} --{p}--> {o}) [{c:.2f}, {ph}]")


def cmd_parallax(args):
    exclude = ""
    no_game = False
    i = 0
    while i < len(args):
        if args[i] == "--exclude" and i + 1 < len(args):
            exclude = args[i + 1]; i += 2
        elif args[i] == "--no-game":
            no_game = True; i += 1
        else:
            i += 1

    conn = connect()
    where = "1=1"
    if exclude:
        where += f" AND subject NOT LIKE '{exclude}%' AND object NOT LIKE '{exclude}%'"
    if no_game:
        where += " AND subject !~ '^[a-z0-9_-]+:[0-9a-f]{8,}$' AND object !~ '^[a-z0-9_-]+:[0-9a-f]{8,}$'"

    with conn.cursor() as cur:
        cur.execute(f"SELECT * FROM parallax WHERE {where} ORDER BY spread DESC;")
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    conn.close()

    if not rows:
        print("  no parallax — all observers agree (or only one observer)")
    else:
        for row in rows:
            r = dict(zip(cols, row))
            print(
                f"  ({r['subject']} --{r['predicate']}--> {r['object']}) "
                f"spread={r['spread']:.3f} observers={r['observers']} "
                f"[{r['min_confidence']:.2f}–{r['max_confidence']:.2f}] "
                f"who={r['who']}"
            )


def cmd_parallax_token(args):
    conn = connect()
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM parallax_token ORDER BY spread DESC;")
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    conn.close()
    if not rows:
        print("  no token-level parallax")
    else:
        for row in rows:
            r = dict(zip(cols, row))
            print(
                f"  ({r['subject']} --{r['predicate']}--> {r['object']}) "
                f"spread={r['spread']:.3f} tokens={r['observers']} "
                f"who={r['who']}"
            )


def cmd_frames(args):
    conn = connect()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT f.token, f.who, f.cwd, f.created_at,
                   (SELECT count(*) FROM live_edges e WHERE e.observer = f.token) as edges
            FROM frames f ORDER BY f.created_at DESC;
        """)
        rows = cur.fetchall()
    conn.close()
    for token, who, cwd, created_at, n_edges in rows:
        print(f"  {who:<30} {n_edges:>4} edges  {str(created_at)[:16]}  {token}")


def cmd_whoami(args):
    token = read_token()
    if not token:
        print("  no frame. run: edge iam <who>")
        return
    conn = connect()
    with conn.cursor() as cur:
        cur.execute("SELECT token, who, cwd, truths, created_at FROM frames WHERE token = %s", (token,))
        row = cur.fetchone()
    conn.close()
    if not row:
        print(f"  frame {token} not found in database")
        return
    t, who, cwd, truths, created_at = row
    n = len(truths) if truths else 0
    status = "ready" if n >= 3 else f"{n}/3 truths"
    print(f"  {who} ({status})")
    print(f"  token: {t}")
    if truths:
        for tr in truths:
            print(f"  truth: ({tr['s']} --{tr['p']}--> {tr['o']})")


def cmd_ls(args):
    phase = args[0] if args else None
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
    for row in rows:
        if phase:
            s, p, o, c, w = row
            print(f"  ({s} --{p}--> {o}) [{c:.2f}, {phase}, @{w}]")
        else:
            s, p, o, c, ph, w = row
            print(f"  ({s} --{p}--> {o}) [{c:.2f}, {ph}, @{w}]")


def cmd_dissolve(args):
    if len(args) < 3:
        print("usage: edge dissolve <subject> <predicate> <object>")
        sys.exit(1)
    frame = _require_frame()
    g = Graph(frame)
    n = g.dissolve(args[0], args[1], args[2])
    print(f"  dissolved {n} edge(s): ({args[0]} --{args[1]}--> {args[2]})")


def cmd_count(args):
    conn = connect()
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM phase_summary;")
        print("  Phase summary:")
        for phase, n, avg_c in cur.fetchall():
            print(f"    {phase}: {n} edges, avg confidence {avg_c:.2f}")
        cur.execute("""
            SELECT f.who, count(*) as n FROM live_edges e
            JOIN frames f ON e.observer = f.token
            GROUP BY f.who ORDER BY n DESC;
        """)
        print("  By observer:")
        for who, n in cur.fetchall():
            print(f"    {who}: {n}")
        cur.execute("SELECT count(*) FROM live_edges;")
        print(f"  Total: {cur.fetchone()[0]}")
    conn.close()


def cmd_orient(args):
    days = int(args[0]) if args else 7
    width = 60
    repo = os.path.basename(os.getcwd())

    # Extract truth terms from current frame, if any, for subjective weighting
    truth_terms = []
    token = read_token()
    if token:
        c = connect()
        with c.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT term FROM (
                    SELECT jsonb_array_elements(truths)->>'s' AS term FROM frames WHERE token = %s
                    UNION
                    SELECT jsonb_array_elements(truths)->>'o' AS term FROM frames WHERE token = %s
                ) t WHERE term IS NOT NULL
            """, (token, token))
            truth_terms = [r[0] for r in cur.fetchall()]
        c.close()

    print()
    header = f"  ORIENTATION MAP  —  {repo}  —  {date.today().isoformat()}"
    if truth_terms:
        header += f"  [seeded by frame]"
    print(header)
    print(f"  {'─' * width}")
    print()

    conn = connect()
    sections = [
        ("ENTERING", "enters", "    {subject} → {object}", 6),
        ("GLOWING", "glows-because", "    {subject}\n      {object}", 8),
        ("SAILING TOWARD", "sails-toward", "    {subject} → {object}", 6),
        ("SAILING AWAY FROM", "sails-away-from", "    {subject} ← {object}", 6),
        ("NOW ORIENTED TOWARD", "now-oriented-toward", "    {object}", 5),
        ("SIGNAL TRAVELS BACK THROUGH", "travels-back-through", "    {object}", 8),
    ]

    for title, predicate, fmt, limit in sections:
        print(f"  {title}")
        extra_where = ""
        if predicate == "travels-back-through":
            extra_where = ""  # no time filter for truths
        else:
            extra_where = f"AND e.created_at > now() - interval '{days} days'"

        if truth_terms and predicate != "travels-back-through":
            # Subjective ordering: edges touching truth terms surface first
            placeholders = ",".join(["%s"] * len(truth_terms))
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT e.subject, e.object FROM live_edges e
                    WHERE e.predicate = %s {extra_where}
                    ORDER BY
                        CASE WHEN e.subject = ANY(ARRAY[{placeholders}]::text[])
                                  OR e.object = ANY(ARRAY[{placeholders}]::text[]) THEN 0 ELSE 1 END,
                        e.created_at DESC
                    LIMIT %s
                """, (predicate, *truth_terms, *truth_terms, limit))
                rows = cur.fetchall()
        else:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT e.subject, e.object FROM live_edges e
                    WHERE e.predicate = %s {extra_where}
                    ORDER BY e.created_at DESC LIMIT %s
                """, (predicate, limit))
                rows = cur.fetchall()

        for subject, obj in rows:
            print(fmt.format(subject=subject, object=obj))
        print()

    print(f"  {'─' * width}")
    print()
    conn.close()

    # Refresh starmap if frame is established
    if token:
        c = connect()
        with c.cursor() as cur:
            cur.execute("SELECT jsonb_array_length(truths) FROM frames WHERE token = %s", (token,))
            row = cur.fetchone()
        c.close()
        if row and row[0] >= 3:
            _starmap_inner(quiet=True)


def cmd_ran(args):
    if not args:
        print("Usage: edge ran <movement>")
        sys.exit(1)
    movement = args[0]

    # Register the run (uses cmd_add internally)
    cmd_add(["this-session", "ran", movement])

    # Show prior deposits
    print()
    print(f"  PRIOR DEPOSITS  —  {movement}")
    print("  ────────────────────────────────────────")

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

    for notes, edge_str, who, dt in rows:
        parts = [p for p in [notes, edge_str, who, dt] if p]
        print(" | ".join(parts))


def _starmap_inner(quiet=False):
    """Build the starmap document. Used by both cmd_starmap and orient refresh."""
    token = read_token()
    if not token:
        if not quiet:
            print("  no frame. run: edge iam <who>")
        return

    conn = connect()
    with conn.cursor() as cur:
        cur.execute("SELECT who FROM frames WHERE token = %s", (token,))
        row = cur.fetchone()
    if not row:
        conn.close()
        return
    who = row[0]

    cwd = os.path.basename(os.getcwd())
    starmap_path = frame_dir() / "starmap"

    # Extract truth terms
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT term FROM (
                SELECT jsonb_array_elements(truths)->>'s' AS term FROM frames WHERE token = %s
                UNION
                SELECT jsonb_array_elements(truths)->>'o' AS term FROM frames WHERE token = %s
            ) t WHERE term IS NOT NULL
        """, (token, token))
        terms = [r[0] for r in cur.fetchall()]

    if not terms:
        conn.close()
        if not quiet:
            print("  frame has no truths yet. say three true things first.")
        return

    lines = []
    lines.append(f"# Starmap — {who} @ {cwd}")
    lines.append(f"*{date.today().isoformat()}* — from frame `{token}`")
    lines.append("")
    lines.append("## Truths")

    with conn.cursor() as cur:
        cur.execute("""
            SELECT (t->>'s'), (t->>'p'), (t->>'o')
            FROM frames, jsonb_array_elements(truths) AS t
            WHERE token = %s
        """, (token,))
        for s, p, o in cur.fetchall():
            lines.append(f"- {s} --{p}--> {o}")

    lines.append("")
    lines.append("## Nearby edges")
    lines.append("")

    for term in terms:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT e.subject || ' --' || e.predicate || '--> ' || e.object,
                       e.phase, f.who
                FROM live_edges e
                JOIN frames f ON e.observer = f.token
                WHERE (e.subject = %s OR e.object = %s)
                  AND e.subject != 'this-session'
                  AND e.predicate NOT IN ('ran', 'enters')
                ORDER BY e.created_at DESC LIMIT 8
            """, (term, term))
            edges = cur.fetchall()

        if edges:
            lines.append(f"### {term}")
            for edge_str, phase, edge_who in edges:
                lines.append(f"- `{phase}` {edge_str} [{edge_who}]")
            lines.append("")

    lines.append("## Recent deposits")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT e.subject || ' --' || e.predicate || '--> ' || SUBSTRING(e.object, 1, 80),
                   f.who
            FROM live_edges e
            JOIN frames f ON e.observer = f.token
            WHERE e.predicate = 'deposited'
            ORDER BY e.created_at DESC LIMIT 5
        """)
        for dep, dep_who in cur.fetchall():
            lines.append(f"- {dep} [{dep_who}]")

    lines.append("")
    lines.append("---")
    lines.append("*Refreshed by `edge starmap`. Also updates on `edge orient` and during dwelling.*")

    conn.close()

    content = "\n".join(lines) + "\n"
    starmap_path.write_text(content)

    if not quiet:
        print(content)
        print(f"  written to {starmap_path}")


def cmd_starmap(args):
    _starmap_inner(quiet=False)


def cmd_raw(args):
    if not args:
        print("usage: edge raw <sql>")
        sys.exit(1)
    sql = " ".join(args)
    conn = connect()
    with conn.cursor() as cur:
        cur.execute(sql)
        if cur.description:
            cols = [d[0] for d in cur.description]
            print("  " + " | ".join(cols))
            for row in cur.fetchall():
                print("  " + " | ".join(str(v) for v in row))
        else:
            print(f"  {cur.rowcount} rows affected")
    conn.commit()
    conn.close()


def cmd_digest(args):
    from .digest import ParallaxDigest, default_who
    limit = 5
    min_spread = 0.05
    dry_run = False
    verbose = True
    who = ""
    i = 0
    while i < len(args):
        if args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1]); i += 2
        elif args[i] == "--min-spread" and i + 1 < len(args):
            min_spread = float(args[i + 1]); i += 2
        elif args[i] == "--who" and i + 1 < len(args):
            who = args[i + 1]; i += 2
        elif args[i] == "--dry-run":
            dry_run = True; i += 1
        elif args[i] == "--quiet":
            verbose = False; i += 1
        else:
            i += 1
    who = who or default_who()
    ParallaxDigest(who=who).run(limit=limit, min_spread=min_spread, dry_run=dry_run, verbose=verbose)


def cmd_isomorph(args):
    from .digest import IsomorphFinder, default_who
    limit = 5
    min_jaccard = 0.3
    dry_run = False
    verbose = True
    who = ""
    i = 0
    while i < len(args):
        if args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1]); i += 2
        elif args[i] == "--min-jaccard" and i + 1 < len(args):
            min_jaccard = float(args[i + 1]); i += 2
        elif args[i] == "--who" and i + 1 < len(args):
            who = args[i + 1]; i += 2
        elif args[i] == "--dry-run":
            dry_run = True; i += 1
        elif args[i] == "--quiet":
            verbose = False; i += 1
        else:
            i += 1
    who = who or default_who()
    IsomorphFinder(who=who).run(limit=limit, min_jaccard=min_jaccard, dry_run=dry_run, verbose=verbose)


def cmd_help(args):
    print("Establish a reference frame:")
    print("  edge iam <who>                         start a frame")
    print("  edge iam <s1> [<s2>...] --for <o1> [<o2>...]   composite frame")
    print("  edge true <s> <p> <o>                  say a true thing (need 3)")
    print("  edge whoami                            current frame")
    print()
    print("Record:")
    print("  edge add <s> <p> <o> [--confidence N] [--phase P] [--note 'text']")
    print()
    print("Query:")
    print("  edge find <term>                       search everywhere")
    print("  edge about <subject>                   edges from subject")
    print("  edge from <who>                        the graph from a perspective")
    print("  edge parallax [--no-game] [--exclude <prefix>]  where observers disagree")
    print("  edge parallax-token                    parallax by frame token")
    print("  edge frames                            list all reference frames")
    print("  edge ls [phase]                        list edges")
    print("  edge dissolve <s> <p> <o>              soft-delete")
    print("  edge count                             summary")
    print("  edge raw <sql>                         escape hatch")
    print()
    print("Discover:")
    print("  edge ran <movement>                    register run + show prior deposits")
    print("  edge digest [--limit N] [--min-spread F] [--who 'name'] [--dry-run]")
    print("  edge isomorph [--limit N] [--min-jaccard F] [--who 'name'] [--dry-run]")
    print("  edge orient [days]                     orientation map (default 7d)")
    print("  edge starmap                           nearby graph from truths → .edge/starmap")


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

COMMANDS = {
    "iam": cmd_iam,
    "true": cmd_true,
    "add": cmd_add,
    "find": cmd_find,
    "about": cmd_about,
    "from": cmd_from,
    "parallax": cmd_parallax,
    "parallax-token": cmd_parallax_token,
    "frames": cmd_frames,
    "whoami": cmd_whoami,
    "ls": cmd_ls,
    "dissolve": cmd_dissolve,
    "count": cmd_count,
    "orient": cmd_orient,
    "ran": cmd_ran,
    "starmap": cmd_starmap,
    "raw": cmd_raw,
    "digest": cmd_digest,
    "isomorph": cmd_isomorph,
    "help": cmd_help,
    "-h": cmd_help,
    "--help": cmd_help,
}


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "ls"
    args = sys.argv[2:]

    handler = COMMANDS.get(cmd)
    if handler:
        handler(args)
    else:
        print(f"unknown command: {cmd}")
        print("try: edge help")
        sys.exit(1)


if __name__ == "__main__":
    main()
