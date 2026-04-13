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
from .cmd_stewardship import cmd_garden, cmd_name, cmd_words, cmd_gc, cmd_decompose
from .cmd_query import (cmd_find, cmd_about, cmd_from, cmd_parallax,
                        cmd_parallax_token, cmd_frames, cmd_whoami,
                        cmd_ls, cmd_dissolve, cmd_count)


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


def _resolve_subject(subject: str, graph: Graph) -> str:
    """Resolve e[slug], e[hash], or e[s p o] notation to edge-as-subject text."""
    if subject.startswith("e[") and subject.endswith("]"):
        inner = subject[2:-1]
        parts = inner.split()
        if len(parts) == 3:
            # e[s p o] — resolve by triple content
            edge = graph.resolve_triple(parts[0], parts[1], parts[2])
            if edge is None:
                print(f"  error: no live edge matching ({parts[0]} --{parts[1]}--> {parts[2]})")
                sys.exit(1)
        else:
            # e[slug-or-hash]
            edge = graph.resolve_slug(inner)
            if edge is None:
                print(f"  error: no live edge with slug/hash '{inner}'")
                sys.exit(1)
        return f"e:{edge.subject}/{edge.predicate}/{edge.object}"
    return subject


def cmd_add(args):
    confidence = 0.7
    phase = "fluid"
    note = ""
    slug = None
    positional = []
    i = 0
    while i < len(args):
        if args[i] == "--confidence" and i + 1 < len(args):
            confidence = float(args[i + 1]); i += 2
        elif args[i] == "--phase" and i + 1 < len(args):
            phase = args[i + 1]; i += 2
        elif args[i] == "--note" and i + 1 < len(args):
            note = args[i + 1]; i += 2
        elif args[i] == "--slug" and i + 1 < len(args):
            slug = args[i + 1]; i += 2
        else:
            positional.append(args[i]); i += 1

    if len(positional) < 3:
        print("usage: edge add <s> <p> <o> [--confidence N] [--phase P] [--note 'text'] [--slug name]")
        sys.exit(1)

    frame = _require_frame()
    g = Graph(frame)
    subject = _resolve_subject(positional[0], g)
    predicate, obj = positional[1], positional[2]
    edge = g.add(subject, predicate, obj, confidence, phase, note, slug=slug)
    print(f"  + {_fmt_edge(edge)}")
    print(f"    #{edge.hash}")
    if slug:
        print(f"    slug: {slug}")
    if note:
        print(f"    note: {note}")

# Query commands: cmd_find, cmd_about, cmd_from, cmd_parallax, cmd_parallax_token,
# cmd_frames, cmd_whoami, cmd_ls, cmd_dissolve, cmd_count
# imported from cmd_query.py


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

    # Print starmap first (subjective layer) if frame is established
    if truth_terms:
        _starmap_inner(quiet=False)

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

    # starmap already printed and written at the top of orient (if frame established)


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
                  AND e.predicate NOT IN ('ran', 'enters', 'speaks-as', 'speaks-for')
                ORDER BY e.created_at DESC LIMIT 8
            """, (term, term))
            edges = cur.fetchall()

        if edges:
            lines.append(f"### {term}")
            for edge_str, phase, edge_who in edges:
                lines.append(f"- `{phase}` {edge_str} [{edge_who}]")
            lines.append("")

    # Attention section: top-5 edges by attention score
    lines.append("## Attention")
    lines.append("*Edges most relevant to current truths (by term overlap × phase × parallax)*")
    lines.append("")

    truth_terms_set = set(terms)
    SKIP_PREDS = ('outcome', 'valuation', 'board-string', 'move-chosen',
                  'speaks-as', 'speaks-for', 'ran', 'enters')

    with conn.cursor() as cur:
        cur.execute("""
            SELECT e.subject, e.predicate, e.object, e.confidence, e.phase, e.notes
            FROM live_edges e
            WHERE e.predicate != ALL(%s)
            ORDER BY e.created_at DESC
        """, (list(SKIP_PREDS),))
        att_edges = cur.fetchall()

    # Build co-occurrence for second-order relevance
    from collections import Counter
    att_term_idx = {}
    for i_e, (s, p, o, c, ph, n) in enumerate(att_edges):
        for t in (s, p, o):
            if t not in att_term_idx:
                att_term_idx[t] = set()
            att_term_idx[t].add(i_e)

    att_adjacent = set()
    for t in truth_terms_set:
        att_adjacent.update(att_term_idx.get(t, set()))

    second_order = Counter()
    for idx in att_adjacent:
        for t in (att_edges[idx][0], att_edges[idx][1], att_edges[idx][2]):
            if t not in truth_terms_set:
                second_order[t] += 1

    # Get parallax
    with conn.cursor() as cur:
        cur.execute("SELECT subject, predicate, object, spread FROM parallax WHERE spread > 0")
        par_map = {(s, p, o): sp for s, p, o, sp in cur.fetchall()}

    phase_w = {"salt": 1.5, "fluid": 1.0, "volatile": 0.7}
    att_scored = []
    for s, p, o, c, ph, n in att_edges:
        edge_terms = {s, p, o}
        direct = len(edge_terms & truth_terms_set)
        second = sum(second_order.get(t, 0) for t in edge_terms) / max(len(second_order), 1)
        if direct == 0 and second == 0:
            continue
        pw = phase_w.get(ph, 1.0)
        spread = par_map.get((s, p, o), 0)
        score = (direct * 3.0 + second) * pw * (1 + spread * 2) * c
        att_scored.append((score, s, p, o, ph, n))

    att_scored.sort(key=lambda x: -x[0])
    for score, s, p, o, ph, n in att_scored[:5]:
        note_str = f" — {n[:70]}" if n else ""
        lines.append(f"- [{score:.1f}] `{ph}` ({s} --{p}--> {o}){note_str}")

    if not att_scored:
        lines.append("- (no edges with attention signal)")
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


def cmd_overlap(args):
    from .digest import OverlapFinder, default_who
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
    OverlapFinder(who=who).run(limit=limit, min_jaccard=min_jaccard, dry_run=dry_run, verbose=verbose)


def cmd_attend(args):
    """Subjective attention: what in the graph is most relevant to the current frame's truths?

    Scores every knowledge edge by:
      1. Term overlap with truth terms (direct relevance)
      2. Phase weight: salt × 1.5, fluid × 1.0, volatile × 0.7
      3. Co-occurrence boost: edges that share terms with truth-adjacent edges
      4. Parallax boost: edges with high spread get attention (disagreement is interesting)

    --parallax: show where individual truths disagree about what matters
    --recovery: show inter-deposit intervals (learning governor arousal signal)
    --limit N: how many results (default 20)
    """
    import math
    from collections import Counter

    do_parallax = "--parallax" in args
    do_recovery = "--recovery" in args
    limit = 20
    i = 0
    while i < len(args):
        if args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1]); i += 2
        elif args[i] in ("--parallax", "--recovery"):
            i += 1
        else:
            i += 1

    if do_recovery:
        conn = connect()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT f.who, e.created_at,
                       EXTRACT(EPOCH FROM e.created_at - LAG(e.created_at) OVER (PARTITION BY f.who ORDER BY e.created_at)) AS gap_sec
                FROM live_edges e JOIN frames f ON e.observer = f.token
                WHERE e.created_at > now() - interval '2 hours'
                AND e.predicate NOT IN ('speaks-as', 'speaks-for', 'scoped-to', 'reply-to',
                                        'needs-attention-from', 'records', 'completed-on')
                ORDER BY f.who, e.created_at
            """)
            rows = cur.fetchall()
        conn.close()

        if not rows:
            print("  === recovery — no deposits in last 2 hours ===")
            return

        from collections import defaultdict
        observer_gaps = defaultdict(list)
        for who, ts, gap in rows:
            if gap is not None:
                observer_gaps[who].append(gap)

        print("  === inter-deposit intervals — learning governor arousal signal ===")
        for who, gaps in sorted(observer_gaps.items(), key=lambda x: -len(x[1])):
            if not gaps:
                continue
            avg = sum(gaps) / len(gaps)
            shortest = min(gaps)
            longest = max(gaps)
            rapid = sum(1 for g in gaps if g < 30)
            signal = ""
            if avg < 30:
                signal = " ⚠ ceiling: rapid-fire deposits, system may be flooding"
            elif avg > 600:
                signal = " ⚠ floor: long gaps, system may be disengaged"
            elif rapid > len(gaps) * 0.5:
                signal = " ⚡ bursting: >50% of intervals under 30s"
            else:
                signal = " ✓ in window"
            print(f"  @{who}: {len(gaps)+1} deposits, avg {avg:.0f}s apart (min {shortest:.0f}s, max {longest:.0f}s){signal}")
        return

    frame = _require_frame()

    conn = connect()

    # Extract truth terms
    with conn.cursor() as cur:
        cur.execute("""
            SELECT t->>'s' as s, t->>'p' as p, t->>'o' as o
            FROM frames, jsonb_array_elements(truths) AS t
            WHERE token = %s
        """, (frame.token,))
        truths = cur.fetchall()

    truth_terms = set()
    for s, p, o in truths:
        truth_terms.update([s, p, o])
    truth_terms.discard(None)

    if not truth_terms:
        print("  no truths in frame — nothing to attend from")
        conn.close()
        return

    # Fetch all knowledge edges (exclude game edges)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT e.subject, e.predicate, e.object, e.confidence, e.phase,
                   f.who, e.notes
            FROM live_edges e
            JOIN frames f ON e.observer = f.token
            WHERE e.predicate NOT IN (
                'outcome', 'valuation', 'board-string', 'move-chosen',
                'speaks-as', 'speaks-for', 'ran', 'enters'
            )
            ORDER BY e.created_at DESC
        """)
        edges = cur.fetchall()

    # Build co-occurrence index: term → set of edge indices that contain it
    term_to_edges = {}
    for i_edge, (s, p, o, c, ph, w, n) in enumerate(edges):
        for term in (s, p, o):
            if term not in term_to_edges:
                term_to_edges[term] = set()
            term_to_edges[term].add(i_edge)

    # Find truth-adjacent edges (share a term with any truth)
    truth_adjacent = set()
    for term in truth_terms:
        truth_adjacent.update(term_to_edges.get(term, set()))

    # Build second-order term set: terms that appear in truth-adjacent edges
    second_order_terms = Counter()
    for idx in truth_adjacent:
        s, p, o = edges[idx][0], edges[idx][1], edges[idx][2]
        for term in (s, p, o):
            if term not in truth_terms:
                second_order_terms[term] += 1

    # Get parallax data
    with conn.cursor() as cur:
        cur.execute("""
            SELECT subject, predicate, object, spread
            FROM parallax WHERE spread > 0
        """)
        parallax_map = {}
        for s, p, o, spread in cur.fetchall():
            parallax_map[(s, p, o)] = spread

    conn.close()

    # Phase weights
    phase_w = {"salt": 1.5, "fluid": 1.0, "volatile": 0.7}

    # Score each edge
    scored = []
    for s, p, o, c, ph, w, n in edges:
        edge_terms = {s, p, o}

        # 1. Direct term overlap with truths
        direct = len(edge_terms & truth_terms)
        if direct == 0 and not any(t in second_order_terms for t in edge_terms):
            continue  # skip edges with zero relevance

        # 2. Second-order relevance (co-occurrence with truth-adjacent edges)
        second = sum(second_order_terms.get(t, 0) for t in edge_terms) / max(len(second_order_terms), 1)

        # 3. Phase weight
        pw = phase_w.get(ph, 1.0)

        # 4. Parallax boost
        spread = parallax_map.get((s, p, o), 0)
        parallax_boost = 1 + spread * 2  # disagreement amplifies attention

        # Combined score
        score = (direct * 3.0 + second * 1.0) * pw * parallax_boost * c

        scored.append((score, s, p, o, c, ph, w, n, direct))

    scored.sort(key=lambda x: -x[0])

    if do_parallax and len(truths) > 1:
        # Per-truth attention fields, then show divergence
        per_truth = {}
        for ts, tp, to_ in truths:
            truth_label = f"({ts} --{tp}--> {to_})"
            t_terms = {ts, tp, to_} - {None}

            # Score edges for just this truth
            t_adjacent = set()
            for term in t_terms:
                t_adjacent.update(term_to_edges.get(term, set()))

            t_second = Counter()
            for idx in t_adjacent:
                for term in (edges[idx][0], edges[idx][1], edges[idx][2]):
                    if term not in t_terms:
                        t_second[term] += 1

            t_scored = {}
            for s, p, o, c, ph, w, n in edges:
                edge_terms = {s, p, o}
                direct = len(edge_terms & t_terms)
                second = sum(t_second.get(t, 0) for t in edge_terms) / max(len(t_second), 1)
                if direct == 0 and second == 0:
                    continue
                pw = phase_w.get(ph, 1.0)
                t_scored[(s, p, o)] = (direct * 3.0 + second) * pw * c

            per_truth[truth_label] = t_scored

        # Find edges where truths disagree most
        all_keys = set()
        for t_scored in per_truth.values():
            all_keys.update(t_scored.keys())

        divergences = []
        labels = list(per_truth.keys())
        for key in all_keys:
            scores = [per_truth[l].get(key, 0) for l in labels]
            if max(scores) < 0.01:
                continue
            # Normalize to make comparable
            mx = max(scores)
            norm = [s / mx for s in scores]
            divergence = max(norm) - min(norm)
            divergences.append((divergence, key, scores))

        divergences.sort(key=lambda x: -x[0])

        print(f"\n  ATTENTION PARALLAX — where your truths disagree")
        print(f"  truths: {', '.join(labels)}")
        print(f"  {'─' * 70}\n")

        for div, (s, p, o), scores in divergences[:limit]:
            score_str = "  ".join(f"{sc:.2f}" for sc in scores)
            print(f"  [{div:.2f}] ({s} --{p}--> {o})")
            print(f"         scores: {score_str}")

    else:
        # Standard attention output
        print(f"\n  ATTENTION — from {len(truth_terms)} truth terms")
        print(f"  terms: {', '.join(sorted(truth_terms))}")
        print(f"  {'─' * 70}\n")

        for score, s, p, o, c, ph, w, n, direct in scored[:limit]:
            marker = "●" * direct + "○" * (3 - direct)
            note_preview = f"  {n[:60]}..." if n and len(n) > 60 else f"  {n}" if n else ""
            print(f"  [{score:.2f}] {marker} ({s} --{p}--> {o}) [{ph}, @{w}]{note_preview}")

    print()


def cmd_polarity(args):
    """Predicate polarity: discover directional relationships between predicates.

    Two predicates are ALIGNED if they co-occur on the same (subject, object) pairs.
    They are ANTI-ALIGNED if they co-occur with subject↔object swapped.

    This reveals the graph's implicit type system: which predicates flow together,
    which flow against each other, and which are orthogonal.
    """
    from collections import Counter, defaultdict

    limit = 20
    pred_filter = None
    i = 0
    while i < len(args):
        if args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1]); i += 2
        elif not args[i].startswith("--"):
            pred_filter = args[i]; i += 1
        else:
            i += 1

    conn = connect()

    # Fetch all knowledge edges
    with conn.cursor() as cur:
        cur.execute("""
            SELECT subject, predicate, object FROM live_edges
            WHERE predicate NOT IN (
                'outcome', 'valuation', 'board-string', 'move-chosen',
                'speaks-as', 'speaks-for', 'ran', 'enters'
            )
        """)
        edges = cur.fetchall()
    conn.close()

    # Build: for each (subject, object) pair, which predicates appear?
    # And for each (object, subject) pair (reversed), which predicates appear?
    pair_preds = defaultdict(set)       # (s, o) → {predicates}
    pred_subjects = defaultdict(set)    # predicate → {subjects}
    pred_objects = defaultdict(set)     # predicate → {objects}

    for s, p, o in edges:
        pair_preds[(s, o)].add(p)
        pred_subjects[p].add(s)
        pred_objects[p].add(o)

    # Count co-occurrences between predicate pairs
    # same_dir: both appear on same (s, o) pair
    # reversed: p1 appears on (s, o) and p2 appears on (o, s)
    same_dir = Counter()
    reversed_dir = Counter()

    all_preds = sorted(pred_subjects.keys())

    for (s, o), preds in pair_preds.items():
        preds_list = sorted(preds)
        # Same direction: both predicates on same (s, o)
        for i_p in range(len(preds_list)):
            for j_p in range(i_p + 1, len(preds_list)):
                pair = (preds_list[i_p], preds_list[j_p])
                same_dir[pair] += 1

        # Reversed: predicates on (s, o) vs predicates on (o, s)
        rev_preds = pair_preds.get((o, s), set())
        for p1 in preds:
            for p2 in rev_preds:
                if p1 < p2:
                    reversed_dir[(p1, p2)] += 1
                elif p1 > p2:
                    reversed_dir[(p2, p1)] += 1

    # Also: subject overlap — predicates that share subjects flow from the same sources
    # Object overlap — predicates that flow toward the same targets
    subject_overlap = Counter()
    object_overlap = Counter()

    for i_p in range(len(all_preds)):
        for j_p in range(i_p + 1, len(all_preds)):
            p1, p2 = all_preds[i_p], all_preds[j_p]
            s_overlap = len(pred_subjects[p1] & pred_subjects[p2])
            o_overlap = len(pred_objects[p1] & pred_objects[p2])
            if s_overlap > 0:
                subject_overlap[(p1, p2)] = s_overlap
            if o_overlap > 0:
                object_overlap[(p1, p2)] = o_overlap

    if pred_filter:
        # Show polarity for one predicate against all others
        print(f"\n  POLARITY of '{pred_filter}'")
        print(f"  subjects: {len(pred_subjects.get(pred_filter, set()))}")
        print(f"  objects:  {len(pred_objects.get(pred_filter, set()))}")
        print(f"  {'─' * 70}\n")

        relations = []
        for p in all_preds:
            if p == pred_filter:
                continue
            pair = tuple(sorted([pred_filter, p]))
            sd = same_dir.get(pair, 0)
            rv = reversed_dir.get(pair, 0)
            so = subject_overlap.get(pair, 0)
            oo = object_overlap.get(pair, 0)
            total = sd + rv + so + oo
            if total == 0:
                continue
            # Polarity: positive = aligned, negative = anti-aligned
            polarity = (sd + so - rv) / max(sd + rv + so, 1)
            relations.append((polarity, p, sd, rv, so, oo, total))

        relations.sort(key=lambda x: -x[-1])  # by total signal

        print(f"  {'predicate':<30} {'pol':>5} {'same':>5} {'rev':>5} {'subj':>5} {'obj':>5}")
        print(f"  {'─' * 65}")
        for pol, p, sd, rv, so, oo, total in relations[:limit]:
            arrow = "→→" if pol > 0.3 else "←→" if pol < -0.3 else "──"
            print(f"  {p:<30} {pol:>+.2f} {sd:>5} {rv:>5} {so:>5} {oo:>5}  {arrow}")

    else:
        # Show strongest polarities across all predicate pairs
        print(f"\n  PREDICATE POLARITY — {len(all_preds)} predicates, {len(edges)} edges")
        print(f"  {'─' * 70}\n")

        all_pairs = set()
        all_pairs.update(same_dir.keys())
        all_pairs.update(reversed_dir.keys())
        all_pairs.update(subject_overlap.keys())
        all_pairs.update(object_overlap.keys())

        scored = []
        for pair in all_pairs:
            sd = same_dir.get(pair, 0)
            rv = reversed_dir.get(pair, 0)
            so = subject_overlap.get(pair, 0)
            oo = object_overlap.get(pair, 0)
            total = sd + rv + so + oo
            if total < 2:
                continue  # need minimum signal
            polarity = (sd + so - rv) / max(sd + rv + so, 1)
            scored.append((abs(polarity), polarity, pair[0], pair[1], sd, rv, so, oo, total))

        scored.sort(key=lambda x: (-x[0], -x[-1]))

        # Show strongest aligned
        aligned = [s for s in scored if s[1] > 0.3]
        anti = [s for s in scored if s[1] < -0.3]
        neutral = [s for s in scored if -0.3 <= s[1] <= 0.3 and s[-1] >= 3]

        if aligned:
            print(f"  ALIGNED (flow same direction):")
            for _, pol, p1, p2, sd, rv, so, oo, total in aligned[:limit // 3]:
                print(f"    {p1} →→ {p2}  (pol={pol:+.2f}, n={total})")

        if anti:
            print(f"\n  ANTI-ALIGNED (flow opposite):")
            for _, pol, p1, p2, sd, rv, so, oo, total in anti[:limit // 3]:
                print(f"    {p1} ←→ {p2}  (pol={pol:+.2f}, n={total})")

        if neutral:
            print(f"\n  ORTHOGONAL (co-occur but no directional bias):")
            for _, pol, p1, p2, sd, rv, so, oo, total in neutral[:limit // 3]:
                print(f"    {p1} ── {p2}  (pol={pol:+.2f}, n={total})")

    print()


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
    print("  edge overlap [--limit N] [--min-jaccard F] [--who 'name'] [--dry-run]")
    print("  edge embed [--batch-size N] [--dry-run]    backfill missing embeddings")
    print("  edge resonance <query> [--limit N]         semantic search by meaning")
    print("  edge attend [--parallax] [--limit N]    subjective attention from truths")
    print("  edge polarity [predicate] [--limit N]  predicate directional alignment")
    print("  edge orient [days]                     orientation map (default 7d)")
    print("  edge starmap                           nearby graph from truths → .edge/starmap")
    print("  edge garden [--limit N]                surface edges that need tending")
    print("  edge name <hash> <slug>                give an existing edge a slug")
    print("  edge decompose <hash> s p o [s p o..]  break a long edge into parts")
    print("  edge words [--limit N]                 vocabulary frequency across the graph")
    print("  edge say <sentence...>                 polysynthetic: graph predicates become grammar")
    print("  edge say --dry                         parse only, don't record")
    print("  edge gc [--days N] [--predicate P] [--dry] [--all-volatile]")
    print("                                         dissolve stale volatile edges (default 14d)")


# Stewardship commands: cmd_garden, cmd_name, cmd_words, cmd_gc, cmd_decompose
# imported from cmd_stewardship.py


# ---------------------------------------------------------------------------
# Agglutinative grammar — edge say
# ---------------------------------------------------------------------------
#
# Morphology:
#   :  — node chain (suffix). Object becomes next subject.
#      rooms:from:inhabitation → (rooms --from--> inhabitation)
#
#   ~  — edge annotation (stance/evidentiality). Binds to the edge, not node.
#      rooms~because:inhabitation drives design
#      → edge-to-edge link: (e:s/p/rooms --because--> e:inhabitation/drives/design)
#
# The grammar (which predicates act as suffixes) comes from the graph itself.

def _load_grammar(conn, min_uses: int = 5) -> tuple[set[str], dict[str, str]]:
    """Load the graph's grammar and aliases.

    Returns (predicates, aliases) where aliases maps short → full predicate.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT predicate, count(*) AS n
            FROM live_edges
            WHERE predicate NOT IN ('outcome', 'valuation', 'move-chosen', 'board-string')
            GROUP BY predicate
            HAVING count(*) >= %s
            ORDER BY n DESC
        """, (min_uses,))
        predicates = {row[0] for row in cur.fetchall()}

        # Load aliases: (abbrev --is-alias-for--> full-predicate)
        cur.execute("""
            SELECT subject, object FROM live_edges
            WHERE predicate = 'is-alias-for'
        """)
        aliases = {row[0]: row[1] for row in cur.fetchall()}

    # Aliases expand the grammar — the alias itself becomes a valid particle
    for abbrev, full in aliases.items():
        if full in predicates:
            predicates.add(abbrev)

    return predicates, aliases


def _expand_agglutination(token: str, grammar: set[str], aliases: dict[str, str] | None = None) -> tuple[str, list[tuple[str, str]], list[tuple[str, list[str]]]]:
    """Expand a token with : and ~ suffixes.

    Returns (root, chains, annotations) where:
      chains = [(predicate, object), ...] — node-to-node via :
      annotations = [(predicate, [clause_words...]), ...] — edge-to-edge via ~
    """
    aliases = aliases or {}

    def _resolve(pred: str) -> str:
        return aliases.get(pred, pred)

    # Split ~ annotations first
    tilde_parts = token.split("~")
    main_part = tilde_parts[0]
    annotations = []
    for ann in tilde_parts[1:]:
        ann_colon = ann.split(":")
        annotations.append((_resolve(ann_colon[0]), ann_colon[1:]))

    # Split : chains
    colon_parts = main_part.split(":")
    root = colon_parts[0]
    chains = []

    i = 1
    while i < len(colon_parts):
        pred = colon_parts[i]
        if pred in grammar and i + 1 < len(colon_parts):
            chains.append((_resolve(pred), colon_parts[i + 1]))
            i += 2
        else:
            root = root + ":" + pred
            i += 1

    return root, chains, annotations


def cmd_say(args):
    """Agglutinative edge creation. Suffixes generate edges.

    : chains nodes     — edge say hallie builds rooms:from:inhabitation
    ~ annotates edges  — edge say hallie builds rooms~because:inhabitation:drives:design

    Grammar predicates come from the graph itself (predicates with >= 5 uses).
    """
    dry = "--dry" in args
    args = [a for a in args if a != "--dry"]

    if len(args) < 3:
        print("usage: edge say <s> <p> <o[:pred:val...]> [<s> <p> <o> ...]")
        print("  :  chains nodes (object → subject)")
        print("  ~  annotates edges (edge-to-edge)")
        print("  grammar comes from predicates with >= 5 uses")
        sys.exit(1)

    conn = connect()
    grammar, aliases = _load_grammar(conn)
    conn.close()

    # Parse into triples: every 3 space-separated tokens is a triple,
    # but tokens may contain : and ~ suffixes that expand into more edges
    if len(args) % 3 != 0:
        # Allow trailing : chains on last token
        pass

    # Group into base triples
    triples = []
    i = 0
    while i + 2 < len(args):
        triples.append((args[i], args[i + 1], args[i + 2]))
        i += 3

    if dry:
        print(f"  grammar ({len(grammar)}): {', '.join(sorted(grammar)[:20])}...")
        if aliases:
            print(f"  aliases: {', '.join(f'{k}→{v}' for k, v in sorted(aliases.items()))}")
        print()
        for s, p, o in triples:
            s_root, s_chains, s_anns = _expand_agglutination(s, grammar, aliases)
            o_root, o_chains, o_anns = _expand_agglutination(o, grammar, aliases)
            print(f"  ({s_root} --{p}--> {o_root})")
            for cp, co in o_chains:
                prev = o_root if not o_chains[:1] else o_root
                print(f"    ({o_root} --{cp}--> {co})")
                o_root = co  # chain forward
            for ap, awords in o_anns:
                if len(awords) >= 2:
                    print(f"    e:... --{ap}--> e:{awords[0]}/.../{awords[-1]}")
                elif awords:
                    print(f"    e:... --{ap}--> {awords[0]}")
                else:
                    print(f"    ~{ap}")
        return

    frame = _require_frame()
    g = Graph(frame)

    for s_raw, p, o_raw in triples:
        s_root, s_chains, s_anns = _expand_agglutination(s_raw, grammar)
        o_root, o_chains, o_anns = _expand_agglutination(o_raw, grammar)

        s_root = _resolve_subject(s_root, g)

        # Base triple
        base = g.add(s_root, p, o_root)
        print(f"  + {_fmt_edge(base)}  #{base.hash}")

        # Object chains: rooms:from:inhabitation → (rooms --from--> inhabitation)
        chain_prev = o_root
        for cp, co in o_chains:
            chain_edge = g.add(chain_prev, cp, co)
            print(f"    : {_fmt_edge(chain_edge)}  #{chain_edge.hash}")
            chain_prev = co

        # Edge annotations via ~
        base_ref = f"e:{base.subject}/{base.predicate}/{base.object}"
        for ap, awords in o_anns:
            if len(awords) >= 3:
                # Full clause annotation: ~because:inhabitation:drives:design
                ann_s, ann_p, ann_o = awords[0], awords[1], awords[2]
                ann_edge = g.add(ann_s, ann_p, ann_o)
                ann_ref = f"e:{ann_edge.subject}/{ann_edge.predicate}/{ann_edge.object}"
                link = g.add(base_ref, ap, ann_ref)
                print(f"    ~ {_fmt_edge(ann_edge)}  #{ann_edge.hash}")
                print(f"      {ap} → #{link.hash}")
            elif len(awords) == 1:
                # Simple annotation: ~obs, ~inf, ~rep or ~stance:value
                link = g.add(base_ref, ap, awords[0])
                print(f"    ~ ({base_ref} --{ap}--> {awords[0]})  #{link.hash}")
            elif len(awords) == 0:
                # Bare marker: ~obs → edge --evidentiality--> obs
                link = g.add(base_ref, "evidentiality", ap)
                print(f"    ~ ({base_ref} --evidentiality--> {ap})  #{link.hash}")


def cmd_alias(args):
    """Create or list predicate aliases for edge say.

    edge alias bc because          — create alias
    edge alias                     — list all aliases
    edge alias --rm bc             — remove alias
    """
    if not args:
        # List aliases
        conn = connect()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT subject, object FROM live_edges
                WHERE predicate = 'is-alias-for'
                ORDER BY subject
            """)
            rows = cur.fetchall()
        conn.close()
        if not rows:
            print("  no aliases. create with: edge alias <short> <predicate>")
        else:
            for abbrev, full in rows:
                print(f"  {abbrev} → {full}")
        return

    if args[0] == "--rm" and len(args) >= 2:
        frame = _require_frame()
        g = Graph(frame)
        n = g.dissolve(args[1], "is-alias-for", "%")
        # dissolve needs exact match — query first
        conn = connect()
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE edges SET dissolved_at = now()
                WHERE subject = %s AND predicate = 'is-alias-for' AND dissolved_at IS NULL
                RETURNING object
            """, (args[1],))
            row = cur.fetchone()
        conn.commit()
        conn.close()
        if row:
            print(f"  removed: {args[1]} → {row[0]}")
        else:
            print(f"  no alias '{args[1]}' found")
        return

    if len(args) < 2:
        print("usage: edge alias <short> <predicate>")
        sys.exit(1)

    abbrev, full = args[0], args[1]
    frame = _require_frame()
    g = Graph(frame)
    edge = g.add(abbrev, "is-alias-for", full, confidence=1.0, phase="salt")
    print(f"  + {abbrev} → {full}")
    print(f"    now usable in edge say: :{abbrev}:value")


# ---------------------------------------------------------------------------
# Dream
# ---------------------------------------------------------------------------

def cmd_dream(args):
    """Pull random edges, free-associate across them, deposit a dream.

    The isle is full of noises, sounds and sweet airs, that give delight and hurt not.

    --n N: how many random edges to pull (default 5)
    --anti-orient: also pull edges far from current truths (requires frame)
    --dry: show the dream prompt without running it
    --model MODEL: which model to use (default claude-haiku-4-5-20251001)
    """
    import random

    n = 5
    anti_orient = "--anti-orient" in args
    dry = "--dry" in args
    model = "claude-haiku-4-5-20251001"
    i = 0
    while i < len(args):
        if args[i] == "--n" and i + 1 < len(args):
            n = int(args[i + 1]); i += 2
        elif args[i] == "--model" and i + 1 < len(args):
            model = args[i + 1]; i += 2
        elif args[i] in ("--anti-orient", "--dry"):
            i += 1
        else:
            i += 1

    conn = connect()
    edges = []      # display strings for the prompt
    triples = []    # (s, p, o) tuples for provenance links

    with conn.cursor() as cur:
        # Pull random knowledge edges — fluid and volatile only (salt has settled, doesn't dream)
        cur.execute("""
            SELECT e.subject, e.predicate, e.object, e.notes, e.phase, f.who
            FROM live_edges e JOIN frames f ON e.observer = f.token
            WHERE e.phase IN ('fluid', 'volatile')
            AND e.predicate NOT IN ('speaks-as', 'speaks-for', 'scoped-to', 'reply-to',
                                      'needs-attention-from', 'records', 'completed-on',
                                      'decomposed-into', 'compressed-to', 'dreamt-on')
            AND e.subject NOT LIKE 'task:%%'
            ORDER BY random()
            LIMIT %s
        """, (n,))
        for row in cur.fetchall():
            s, p, o, notes, phase, who = row
            edge_str = f"({s} --{p}--> {o})"
            if notes:
                edge_str += f" [note: {notes}]"
            edges.append(edge_str)
            triples.append((s, p, o))

        # Salt anchor — one settled edge to ground the dream (the familiar house)
        cur.execute("""
            SELECT e.subject, e.predicate, e.object, e.notes, e.phase, f.who
            FROM live_edges e JOIN frames f ON e.observer = f.token
            WHERE e.phase = 'salt'
            AND e.predicate NOT IN ('speaks-as', 'speaks-for', 'scoped-to', 'reply-to',
                                    'needs-attention-from', 'records', 'completed-on',
                                    'move-chosen', 'valuation', 'outcome')
            AND e.subject NOT LIKE 'task:%%'
            AND e.subject NOT LIKE 'go9:%%'
            AND e.subject NOT LIKE 'connect5:%%'
            ORDER BY random()
            LIMIT 1
        """)
        salt_row = cur.fetchone()
        if salt_row:
            s, p, o, notes, phase, who = salt_row
            edge_str = f"({s} --{p}--> {o}) [salt]"
            if notes:
                edge_str += f" [note: {notes}]"
            edges.append(edge_str)
            triples.append((s, p, o))

        # Anti-orient: pull edges far from current truths
        if anti_orient:
            try:
                frame = _require_frame()
                # Get truth terms
                truth_terms = set()
                for t in frame.truths:
                    for val in [t.get("s", ""), t.get("p", ""), t.get("o", "")]:
                        truth_terms.update(val.replace("-", " ").split())

                if truth_terms:
                    # Pull edges that share NO terms with truths (fluid/volatile only)
                    cur.execute("""
                        SELECT e.subject, e.predicate, e.object, e.notes, e.phase
                        FROM live_edges e
                        WHERE e.phase IN ('fluid', 'volatile')
                        AND e.predicate NOT IN ('speaks-as', 'speaks-for', 'scoped-to', 'reply-to',
                                                  'needs-attention-from', 'records', 'completed-on',
                                                  'dreamt-on')
                        AND e.subject NOT LIKE 'task:%%'
                        ORDER BY random()
                        LIMIT 50
                    """)
                    cold_edges = []
                    cold_triples = []
                    for row in cur.fetchall():
                        s, p, o, notes, phase = row
                        all_text = f"{s} {p} {o}".replace("-", " ")
                        overlap = sum(1 for t in truth_terms if t.lower() in all_text.lower())
                        if overlap == 0:
                            edge_str = f"({s} --{p}--> {o})"
                            if notes:
                                edge_str += f" [note: {notes}]"
                            cold_edges.append(edge_str)
                            cold_triples.append((s, p, o))
                    # Take up to 2 cold edges
                    edges.extend(cold_edges[:2])
                    triples.extend(cold_triples[:2])
            except SystemExit:
                pass  # No frame, skip anti-orient

    conn.close()

    if not edges:
        print("  no edges to dream on")
        return

    random.shuffle(edges)

    prompt_narrative = f"""You are dreaming.

Here are some things that were next to each other when you woke up:

{chr(10).join(f"  {e}" for e in edges)}

Let them be near each other. What do you notice? Not what they mean — what they *touch*.

Write a short paragraph — a few sentences — about what you see between them. Free-associate. Follow the heat. Don't name edges or triples, just write."""

    prompt_extract = """Here is a dream narrative:

{narrative}

What did it find? Pull out 1-3 relationships the dream made — connections between things, not descriptions of single things. Write them as short triples: subject predicate object (hyphenated names, 1-4 words each), one per line.

Then a blank line, then one sentence for the feeling."""

    if dry:
        print("  === dream prompt (pass 1: narrative) ===")
        print(prompt_narrative)
        print(f"\n  model: {model}")
        print(f"  edges: {len(edges)}")
        return

    # Call the model — prefer local Qwen, fall back to Anthropic API
    qwen_url = os.environ.get("QWEN_URL", "http://localhost:5052")
    use_local = model.startswith("qwen") or model == "local"
    if not use_local:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            use_local = True

    def _call_llm(prompt_text, max_tokens=300):
        if use_local:
            import urllib.request
            req_body = json.dumps({
                "model": "Qwen/Qwen2.5-7B-Instruct",
                "messages": [{"role": "user", "content": prompt_text}],
                "max_tokens": max_tokens,
                "temperature": 0.9,
            }).encode()
            req = urllib.request.Request(
                f"{qwen_url}/v1/chat/completions",
                data=req_body,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read())
            return result["choices"][0]["message"]["content"].strip()
        else:
            import anthropic
            client = anthropic.Anthropic()
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt_text}],
            )
            return response.content[0].text.strip()

    try:
        # Pass 1: free-associate a narrative
        narrative = _call_llm(prompt_narrative, max_tokens=400)
        print(f"  === dream narrative ===")
        print(f"  {narrative}")
        print()

        # Pass 2: extract edges from the narrative
        dream_text = _call_llm(prompt_extract.format(narrative=narrative), max_tokens=200)
    except Exception as e:
        print(f"  dream failed: {e}")
        return

    # Parse the response: lines with 3+ words are edges, blank line separates, rest is dream-note
    lines = dream_text.strip().split("\n")
    found_edges = []
    dream_note = ""
    past_blank = False
    for line in lines:
        line = line.strip()
        if not line:
            past_blank = True
            continue
        if past_blank:
            dream_note = (dream_note + " " + line).strip() if dream_note else line
        else:
            parts = line.split(None, 2)
            if len(parts) >= 3:
                found_edges.append((parts[0], parts[1], parts[2]))
            elif len(parts) == 2:
                found_edges.append((parts[0], "touches", parts[1]))

    # Print the dream
    print(f"  === dream ({len(edges)} edges pulled, {len(found_edges)} edges found) ===")
    for s, p, o in found_edges:
        print(f"  ({s} --{p}--> {o})")
    if dream_note:
        print(f"  note: {dream_note}")
    print()
    print(f"  dreamt on:")
    for e in edges:
        print(f"    {e}")

    # Deposit found edges as volatile with dreamt-on provenance
    try:
        frame = _require_frame()
        g = Graph(frame)
        for ds, dp, do_ in found_edges:
            edge = g.add(ds, dp, do_, 0.5, "volatile", dream_note)
            print(f"  + ({ds} --{dp}--> {do_}) #{edge.hash} [volatile]")
            # Link each found edge to its source edges
            dream_node = f"e:{ds}/{dp}/{do_}"
            for src_s, src_p, src_o in triples:
                source_node = f"e:{src_s}/{src_p}/{src_o}"
                g.add(dream_node, "dreamt-on", source_node, 0.5, "volatile", "")
    except (SystemExit, Exception) as e:
        print(f"  (dream not deposited — {e})")


def cmd_resonance(args):
    """Semantic search — find edges by meaning, not keywords."""
    from .db import connect
    from .embed import embed
    if not args:
        print("Usage: edge resonance <query> [--limit N]")
        return
    limit = 10
    query_parts = []
    i = 0
    while i < len(args):
        if args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1]); i += 2
        else:
            query_parts.append(args[i]); i += 1
    query = " ".join(query_parts)
    if not query:
        print("Usage: edge resonance <query> [--limit N]")
        return
    vec = embed(query)
    conn = connect()
    with conn.cursor() as cur:
        cur.execute(
            """SELECT subject, predicate, object, notes,
                      1 - (embedding <=> %s::vector) AS similarity,
                      phase, observer
               FROM live_edges
               WHERE embedding IS NOT NULL
               ORDER BY embedding <=> %s::vector
               LIMIT %s""",
            (vec, vec, limit),
        )
        rows = cur.fetchall()
    if not rows:
        print("  No edges with embeddings found.")
        return
    print(f"\n  RESONANCE  —  \"{query}\"")
    print(f"  {'─' * 60}\n")
    for s, p, o, notes, sim, phase, obs in rows:
        sim_pct = f"{sim:.3f}"
        triple = f"({s} --{p}--> {o})"
        print(f"  {sim_pct}  {triple}  [{phase}]")
        if notes:
            note_preview = notes[:80] + ("..." if len(notes) > 80 else "")
            print(f"         {note_preview}")
    print()


def cmd_embed(args):
    """Backfill embeddings for edges missing them."""
    from .db import connect
    from .embed import embed_batch, edge_text
    batch_size = 256
    dry_run = False
    for i, arg in enumerate(args):
        if arg == "--batch-size" and i + 1 < len(args):
            batch_size = int(args[i + 1])
        elif arg == "--dry-run":
            dry_run = True
    conn = connect()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, subject, predicate, object, notes FROM live_edges WHERE embedding IS NULL"
        )
        rows = cur.fetchall()
    if not rows:
        print("All edges already have embeddings.")
        return
    print(f"  {len(rows)} edges missing embeddings. Embedding in batches of {batch_size}...")
    if dry_run:
        print("  (dry run — not writing)")
        return
    texts = [edge_text(r[1], r[2], r[3], r[4] or "") for r in rows]
    vectors = embed_batch(texts, batch_size=batch_size)
    with conn.cursor() as cur:
        for (row, vec) in zip(rows, vectors):
            cur.execute("UPDATE edges SET embedding = %s WHERE id = %s", (vec, row[0]))
    conn.commit()
    print(f"  {len(rows)} embeddings written.")


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
    "overlap": cmd_overlap,
    "attend": cmd_attend,
    "polarity": cmd_polarity,
    "garden": cmd_garden,
    "name": cmd_name,
    "decompose": cmd_decompose,
    "words": cmd_words,
    "say": cmd_say,
    "alias": cmd_alias,
    "dream": cmd_dream,
    "gc": cmd_gc,
    "embed": cmd_embed,
    "resonance": cmd_resonance,
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
