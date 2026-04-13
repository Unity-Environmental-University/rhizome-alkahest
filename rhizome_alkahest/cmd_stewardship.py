"""Stewardship commands: garden, gc, name, decompose, words.

Tending the graph — surfacing what needs attention, cleaning what's stale,
naming what's unnamed, breaking what's too large.
"""

import sys

from .db import connect
from .edge import Edge
from .graph import Graph
from .cli_helpers import require_frame, fmt_edge


def cmd_garden(args):
    """Surface edges that need tending: long terms, missing slugs on salt, near-duplicates.

    --pace: show deposit rate per observer in last hour (learning governor dose signal)
    --fluid-ratio: show fluid/salt ratio per observer (integration signal)
    --limit N: max results per section (default 20)
    """
    limit = 20
    do_pace = "--pace" in args
    do_fluid_ratio = "--fluid-ratio" in args
    i = 0
    while i < len(args):
        if args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1]); i += 2
        elif args[i] in ("--pace", "--fluid-ratio"):
            i += 1
        else:
            i += 1

    conn = connect()
    with conn.cursor() as cur:
        # --- Learning governor: pace signal ---
        if do_pace:
            cur.execute("""
                SELECT f.who,
                       count(*) AS deposits,
                       min(e.created_at) AS first_deposit,
                       max(e.created_at) AS last_deposit,
                       EXTRACT(EPOCH FROM max(e.created_at) - min(e.created_at)) / NULLIF(count(*) - 1, 0) AS avg_interval_sec
                FROM live_edges e JOIN frames f ON e.observer = f.token
                WHERE e.created_at > now() - interval '1 hour'
                AND e.predicate NOT IN ('speaks-as', 'speaks-for', 'scoped-to', 'reply-to',
                                        'needs-attention-from', 'records', 'completed-on')
                GROUP BY f.who
                ORDER BY count(*) DESC
            """)
            pace_rows = cur.fetchall()
            if pace_rows:
                print("  === deposit pace (last hour) — learning governor dose signal ===")
                for who, count, first, last, avg_sec in pace_rows:
                    interval_str = f"{avg_sec:.0f}s between deposits" if avg_sec else "single deposit"
                    warning = ""
                    if count > 15:
                        warning = " ⚠ hyper-mode (>15 deposits/hour)"
                    elif avg_sec and avg_sec < 30:
                        warning = " ⚠ rapid-fire (<30s intervals)"
                    print(f"  @{who}: {count} deposits, {interval_str}{warning}")
            else:
                print("  === deposit pace — no deposits in last hour ===")
            print()

        # --- Learning governor: fluid/salt ratio ---
        if do_fluid_ratio:
            cur.execute("""
                SELECT f.who,
                       count(*) FILTER (WHERE e.phase = 'fluid') AS fluid,
                       count(*) FILTER (WHERE e.phase = 'salt') AS salt,
                       count(*) FILTER (WHERE e.phase = 'volatile') AS volatile,
                       count(*) AS total
                FROM live_edges e JOIN frames f ON e.observer = f.token
                AND e.predicate NOT IN ('speaks-as', 'speaks-for', 'scoped-to', 'reply-to',
                                        'needs-attention-from', 'records', 'completed-on')
                GROUP BY f.who
                ORDER BY count(*) FILTER (WHERE e.phase = 'fluid') DESC
                LIMIT %s
            """, (limit,))
            ratio_rows = cur.fetchall()
            if ratio_rows:
                print("  === fluid/salt ratio — learning governor integration signal ===")
                for who, fluid, salt, volatile, total in ratio_rows:
                    ratio = fluid / salt if salt > 0 else float('inf')
                    warning = ""
                    if ratio > 5.0:
                        warning = " ⚠ window too open (fluid/salt > 5:1)"
                    elif salt > 0 and ratio < 0.5:
                        warning = " ⚠ mostly hardened (fluid/salt < 1:2)"
                    ratio_str = f"{ratio:.1f}:1" if salt > 0 else "∞ (no salt)"
                    print(f"  @{who}: {fluid} fluid, {salt} salt, {volatile} volatile ({total} total) — ratio {ratio_str}{warning}")
            else:
                print("  === fluid/salt ratio — no edges ===")
            print()

        # If only governor flags were requested, skip standard garden
        if do_pace or do_fluid_ratio:
            if not (set(args) - {"--pace", "--fluid-ratio", "--limit"} - {str(limit)}):
                conn.close()
                return

        # Long edges — subject or object over 50 chars, excluding already-decomposed
        cur.execute("""
            SELECT e.id, e.subject, e.predicate, e.object, e.confidence, e.phase, f.who, e.hash, e.slug
            FROM live_edges e JOIN frames f ON e.observer = f.token
            WHERE (length(e.subject) > 50 OR length(e.object) > 50)
            AND NOT EXISTS (
                SELECT 1 FROM live_edges d
                WHERE d.predicate = 'decomposed-into'
                AND d.subject = 'e:' || e.subject || '/' || e.predicate || '/' || e.object
            )
            ORDER BY greatest(length(e.subject), length(e.object)) DESC
            LIMIT %s
        """, (limit,))
        long_edges = cur.fetchall()

        # Salt edges without slugs (high-value, unnamed)
        cur.execute("""
            SELECT e.id, e.subject, e.predicate, e.object, e.confidence, e.phase, f.who, e.hash, e.slug
            FROM live_edges e JOIN frames f ON e.observer = f.token
            WHERE e.phase = 'salt' AND e.slug IS NULL
            AND e.predicate NOT IN ('speaks-as', 'speaks-for')
            ORDER BY e.confidence DESC
            LIMIT %s
        """, (limit,))
        unnamed_salt = cur.fetchall()

    conn.close()

    if long_edges:
        print(f"  === long edges ({len(long_edges)}) — may want decomposing ===")
        for row in long_edges:
            _id, s, p, o, c, ph, w, h, sl = row
            longest = max(len(s), len(o))
            tag = f" slug:{sl}" if sl else ""
            print(f"  [{longest}ch] ({s} --{p}--> {o}) [{c:.2f}, {ph}, @{w}] #{h}{tag}")

    if unnamed_salt:
        print(f"\n  === salt without slugs ({len(unnamed_salt)}) — worth naming? ===")
        for row in unnamed_salt:
            _id, s, p, o, c, ph, w, h, sl = row
            print(f"  ({s} --{p}--> {o}) [{c:.2f}, @{w}] #{h}")

    if not long_edges and not unnamed_salt and not do_pace and not do_fluid_ratio:
        print("  garden is tidy")


def cmd_name(args):
    """Retroactively slug an existing edge: edge name <hash-or-slug> <new-slug>"""
    if len(args) < 2:
        print("usage: edge name <hash> <slug>")
        sys.exit(1)

    ref, new_slug = args[0], args[1]
    conn = connect()
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE edges SET slug = %s
            WHERE (hash = %s OR slug = %s) AND dissolved_at IS NULL
            RETURNING subject, predicate, object, hash
        """, (new_slug, ref, ref))
        row = cur.fetchone()
    conn.commit()
    conn.close()

    if row:
        s, p, o, h = row
        print(f"  named: ({s} --{p}--> {o}) #{h} → slug:{new_slug}")
    else:
        print(f"  error: no live edge with hash/slug '{ref}'")
        sys.exit(1)


def cmd_decompose(args):
    """Decompose a long edge into parts. Parts are new edges; the original gets a decomposed-into link.

    usage: edge decompose <hash-or-slug> <s1> <p1> <o1> [<s2> <p2> <o2> ...]
    Each group of 3 args is a new edge (subject, predicate, object).
    """
    if len(args) < 4:
        print("usage: edge decompose <hash> <s> <p> <o> [<s> <p> <o> ...]")
        print("  each triple is a new edge decomposed from the original")
        sys.exit(1)

    ref = args[0]
    triples_raw = args[1:]
    if len(triples_raw) % 3 != 0:
        print("  error: parts must be groups of 3 (subject predicate object)")
        sys.exit(1)

    frame = require_frame()
    g = Graph(frame)

    # Resolve the original
    original = g.resolve_slug(ref)
    if original is None:
        # Try as e: prefix too
        conn = connect()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, subject, predicate, object, confidence, phase, observer, notes, created_at, slug, hash
                FROM live_edges WHERE hash = %s OR slug = %s LIMIT 1
            """, (ref, ref))
            row = cur.fetchone()
        conn.close()
        if row:
            original = Edge(
                id=str(row[0]), subject=row[1], predicate=row[2], object=row[3],
                confidence=row[4], phase=row[5], observer=row[6], notes=row[7],
                created_at=row[8], slug=row[9], hash=row[10],
            )
        else:
            print(f"  error: no live edge with hash/slug '{ref}'")
            sys.exit(1)

    original_ref = f"e:{original.subject}/{original.predicate}/{original.object}"

    # Create the decomposed parts
    parts = []
    for i in range(0, len(triples_raw), 3):
        s, p, o = triples_raw[i], triples_raw[i + 1], triples_raw[i + 2]
        edge = g.add(s, p, o, phase=original.phase)
        parts.append(edge)
        print(f"  + {fmt_edge(edge)}  #{edge.hash}")

    # Link original → decomposed-into each part
    for part in parts:
        part_ref = f"{part.subject}/{part.predicate}/{part.object}"
        link = g.add(original_ref, "decomposed-into", part_ref)
        print(f"  ~ {fmt_edge(link)}")

    print(f"\n  decomposed #{original.hash or ref} into {len(parts)} part(s)")


def cmd_words(args):
    """Vocabulary frequency: what terms does the graph actually use?"""
    limit = 30
    kind = "all"  # all, subjects, predicates, objects
    i = 0
    while i < len(args):
        if args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1]); i += 2
        elif args[i] in ("subjects", "predicates", "objects"):
            kind = args[i]; i += 1
        else:
            i += 1

    conn = connect()
    with conn.cursor() as cur:
        if kind == "predicates":
            cur.execute("""
                SELECT predicate AS term, count(*) AS n
                FROM live_edges GROUP BY predicate ORDER BY n DESC LIMIT %s
            """, (limit,))
        elif kind == "subjects":
            cur.execute("""
                SELECT subject AS term, count(*) AS n
                FROM live_edges GROUP BY subject ORDER BY n DESC LIMIT %s
            """, (limit,))
        elif kind == "objects":
            cur.execute("""
                SELECT object AS term, count(*) AS n
                FROM live_edges GROUP BY object ORDER BY n DESC LIMIT %s
            """, (limit,))
        else:
            # All positions — unnest into one column
            cur.execute("""
                SELECT term, count(*) AS n FROM (
                    SELECT subject AS term FROM live_edges
                    UNION ALL SELECT predicate FROM live_edges
                    UNION ALL SELECT object FROM live_edges
                ) t GROUP BY term ORDER BY n DESC LIMIT %s
            """, (limit,))

        rows = cur.fetchall()
    conn.close()

    print(f"  === {kind} vocabulary (top {limit}) ===")
    for term, n in rows:
        print(f"  {n:4d}  {term}")


def cmd_gc(args):
    """Dissolve stale volatile edges.

    --days N: older than N days (default 14)
    --predicate P: only dissolve edges with this predicate (e.g. dreamt-on)
    --dry: show what would be dissolved without doing it
    --all-volatile: dissolve all volatile regardless of age (still respects --predicate)
    """
    days = 14
    predicate = None
    dry = "--dry" in args
    all_volatile = "--all-volatile" in args
    i = 0
    while i < len(args):
        if args[i] == "--days" and i + 1 < len(args):
            days = int(args[i + 1]); i += 2
        elif args[i] == "--predicate" and i + 1 < len(args):
            predicate = args[i + 1]; i += 2
        elif args[i] in ("--dry", "--all-volatile"):
            i += 1
        else:
            i += 1

    conn = connect()
    with conn.cursor() as cur:
        # Count first
        where = "phase = 'volatile' AND dissolved_at IS NULL"
        params = []
        if not all_volatile:
            where += " AND created_at < now() - interval '%s days'"
            params.append(days)
        if predicate:
            where += " AND predicate = %s"
            params.append(predicate)

        cur.execute(f"SELECT count(*) FROM edges WHERE {where}", params)
        count = cur.fetchone()[0]

        if count == 0:
            print("  nothing to collect")
            return

        if dry:
            # Show a sample
            cur.execute(
                f"""SELECT subject, predicate, object, created_at::date
                    FROM edges WHERE {where}
                    ORDER BY created_at ASC LIMIT 20""",
                params,
            )
            print(f"  would dissolve {count} volatile edge(s):")
            for s, p, o, d in cur.fetchall():
                print(f"    ({s} --{p}--> {o}) [{d}]")
            if count > 20:
                print(f"    ... and {count - 20} more")
            return

        cur.execute(f"UPDATE edges SET dissolved_at = now() WHERE {where}", params)
        conn.commit()
        print(f"  dissolved {count} volatile edge(s)")
