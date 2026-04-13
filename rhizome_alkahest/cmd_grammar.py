"""Agglutinative grammar commands: say, alias.

Morphology:
  :  — node chain (suffix). Object becomes next subject.
     rooms:from:inhabitation → (rooms --from--> inhabitation)

  ~  — edge annotation (stance/evidentiality). Binds to the edge, not node.
     rooms~because:inhabitation drives design
     → edge-to-edge link: (e:s/p/rooms --because--> e:inhabitation/drives/design)

The grammar (which predicates act as suffixes) comes from the graph itself.
"""

import sys

from .db import connect
from .graph import Graph
from .cli_helpers import require_frame, fmt_edge, resolve_subject


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

    frame = require_frame()
    g = Graph(frame)

    for s_raw, p, o_raw in triples:
        s_root, s_chains, s_anns = _expand_agglutination(s_raw, grammar)
        o_root, o_chains, o_anns = _expand_agglutination(o_raw, grammar)

        s_root = resolve_subject(s_root, g)

        # Base triple
        base = g.add(s_root, p, o_root)
        print(f"  + {fmt_edge(base)}  #{base.hash}")

        # Object chains: rooms:from:inhabitation → (rooms --from--> inhabitation)
        chain_prev = o_root
        for cp, co in o_chains:
            chain_edge = g.add(chain_prev, cp, co)
            print(f"    : {fmt_edge(chain_edge)}  #{chain_edge.hash}")
            chain_prev = co

        # Edge annotations via ~
        base_ref = f"e:{base.subject}/{base.predicate}/{base.object}"
        for ap, awords in o_anns:
            if len(awords) >= 3:
                ann_s, ann_p, ann_o = awords[0], awords[1], awords[2]
                ann_edge = g.add(ann_s, ann_p, ann_o)
                ann_ref = f"e:{ann_edge.subject}/{ann_edge.predicate}/{ann_edge.object}"
                link = g.add(base_ref, ap, ann_ref)
                print(f"    ~ {fmt_edge(ann_edge)}  #{ann_edge.hash}")
                print(f"      {ap} → #{link.hash}")
            elif len(awords) == 1:
                link = g.add(base_ref, ap, awords[0])
                print(f"    ~ ({base_ref} --{ap}--> {awords[0]})  #{link.hash}")
            elif len(awords) == 0:
                link = g.add(base_ref, "evidentiality", ap)
                print(f"    ~ ({base_ref} --evidentiality--> {ap})  #{link.hash}")


def cmd_alias(args):
    """Create or list predicate aliases for edge say.

    edge alias bc because          — create alias
    edge alias                     — list all aliases
    edge alias --rm bc             — remove alias
    """
    if not args:
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
        frame = require_frame()
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
    frame = require_frame()
    g = Graph(frame)
    edge = g.add(abbrev, "is-alias-for", full, confidence=1.0, phase="salt")
    print(f"  + {abbrev} → {full}")
    print(f"    now usable in edge say: :{abbrev}:value")
