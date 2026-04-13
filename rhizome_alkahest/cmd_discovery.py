"""Discovery commands: orient, ran, starmap, raw, digest, overlap, attend, polarity, help."""

import os
import sys
from collections import Counter, defaultdict
from datetime import date

from .db import connect
from .frame_pointer import frame_dir, read_token
from .cli_helpers import require_frame
from .cmd_recording import cmd_add


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

    frame = require_frame()

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
