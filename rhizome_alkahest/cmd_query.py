"""Query commands: find, about, from, parallax, parallax_token, frames, whoami, ls, dissolve, count.

Reading the graph — searching, browsing, measuring. No frame required
for most of these (dissolve is the exception).
"""

import sys

from .db import connect
from .frame_pointer import read_token
from .graph import Graph
from .cli_helpers import require_frame, load_edgeignore, edgeignore_sql


def cmd_find(args):
    show_all = "--all" in args
    args = [a for a in args if a != "--all"]
    if not args:
        print("usage: edge find <term>")
        sys.exit(1)
    conn = connect()
    with conn.cursor() as cur:
        term = args[0]
        query = """
            SELECT e.subject, e.predicate, e.object, e.confidence, e.phase, f.who
            FROM live_edges e JOIN frames f ON e.observer = f.token
            WHERE (e.subject ILIKE %s OR e.predicate ILIKE %s OR e.object ILIKE %s)
        """
        params = [f"%{term}%", f"%{term}%", f"%{term}%"]
        if not show_all:
            ignore_clause, ignore_params = edgeignore_sql(load_edgeignore())
            if ignore_clause:
                query += " AND " + ignore_clause
                params.extend(ignore_params)
        query += " ORDER BY e.confidence DESC"
        cur.execute(query, params)
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
    show_all = "--all" in args
    args = [a for a in args if a != "--all"]
    phase = args[0] if args else None
    conn = connect()
    with conn.cursor() as cur:
        if phase:
            query = """
                SELECT e.subject, e.predicate, e.object, e.confidence, f.who
                FROM live_edges e JOIN frames f ON e.observer = f.token
                WHERE e.phase = %s
            """
            params = [phase]
        else:
            query = """
                SELECT e.subject, e.predicate, e.object, e.confidence, e.phase, f.who
                FROM live_edges e JOIN frames f ON e.observer = f.token
                WHERE 1=1
            """
            params = []
        if not show_all:
            ignore_clause, ignore_params = edgeignore_sql(load_edgeignore())
            if ignore_clause:
                query += " AND " + ignore_clause
                params.extend(ignore_params)
        query += " ORDER BY e.updated_at DESC"
        cur.execute(query, params)
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
    frame = require_frame()
    g = Graph(frame)
    n = g.dissolve(args[0], args[1], args[2])
    print(f"  dissolved {n} edge(s): ({args[0]} --{args[1]}--> {args[2]})")


def cmd_count(args):
    show_all = "--all" in args
    conn = connect()
    with conn.cursor() as cur:
        ignore_clause, ignore_params = "", []
        if not show_all:
            ignore_clause, ignore_params = edgeignore_sql(load_edgeignore())

        if ignore_clause:
            cur.execute("""
                SELECT e.phase, count(*), avg(e.confidence)
                FROM live_edges e
                WHERE """ + ignore_clause + """
                GROUP BY e.phase ORDER BY count(*) DESC
            """, ignore_params)
        else:
            cur.execute("SELECT * FROM phase_summary;")
        print("  Phase summary:")
        for phase, n, avg_c in cur.fetchall():
            print(f"    {phase}: {n} edges, avg confidence {avg_c:.2f}")

        if ignore_clause:
            cur.execute("""
                SELECT f.who, count(*) as n
                FROM live_edges e JOIN frames f ON e.observer = f.token
                WHERE """ + ignore_clause + """
                GROUP BY f.who ORDER BY n DESC
            """, ignore_params)
        else:
            cur.execute("""
                SELECT f.who, count(*) as n
                FROM live_edges e JOIN frames f ON e.observer = f.token
                GROUP BY f.who ORDER BY n DESC
            """)
        print("  By observer:")
        for who, n in cur.fetchall():
            print(f"    {who}: {n}")

        if ignore_clause:
            cur.execute("SELECT count(*) FROM live_edges e WHERE " + ignore_clause, ignore_params)
        else:
            cur.execute("SELECT count(*) FROM live_edges")
        total = cur.fetchone()[0]
        label = "Total" if show_all else "Total (filtered)"
        print(f"  {label}: {total}")
    conn.close()
