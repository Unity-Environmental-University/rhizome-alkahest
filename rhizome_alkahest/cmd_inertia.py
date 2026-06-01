"""Inertia — resistance to change, as a computed read.

The paradigm (Hallie, 2026-06-01): the more live things prehend a fact, the
more *fixed* it is — but fixity-by-density is instantaneous. Inertia is the
temporal correction: how much *mass* a fact has accumulated by holding still
while being prehended over time. A fact can be load-bearing-but-green (high
density, low inertia — cheap to revise now) or quiet-but-immovable (low
density, high inertia — an old axiom the whole graph grew up assuming; pull
it and things crack in ways current density can't see).

This is a READ, not a stored field — no schema change, fully reversible.
Phase is treated as a coarse reading of where a fact sits on the single
continuous inertia scale:

    volatile  →  fluid  →  salt  →  locked
       0      →  low    →  high  →    ∞
    massless          earned       declared

Formula (normalized 0..1, no new columns — uses what the schema already has):

    inertia = W_AGE  * min(days_since_updated / AGE_SCALE, 1)
            + W_CONF * confidence            # accumulates, never reaches 1.0 —
                                             # already a mass proxy in the schema
            + W_DENS * min(node_degree / DEG_SCALE, 1)

The weights lean on confidence and age over raw density on purpose: density
alone mis-reads the load-bearing-but-quiet fact (e.g. `speaks-as` identity
edges — confidence 1.0, almost un-prehended, but the observer model rests on
them). Inertia is what protects those from a naive gc.

Validated against the live graph 2026-06-01: ranks salt > fluid > volatile
without being told phase, and surfaces low-degree high-confidence identity
edges at the top — exactly the facts pure density would wrongly mark cheap.
"""

import sys

from .db import connect

# Tunables. Kept as module constants so the formula is one obvious place.
W_AGE, W_CONF, W_DENS = 0.4, 0.4, 0.2
AGE_SCALE = 90.0   # days held still to count as "fully aged"
DEG_SCALE = 50.0   # node degree to count as "fully dense"

# Game telemetry dominates raw degree without carrying meaning — exclude it
# so inertia reflects the semantic graph, not Connect-5 / Go move volume.
_NOISE = (
    "e.subject NOT LIKE 'go9:%%' AND e.subject NOT LIKE 'connect5:%%' "
    "AND e.object NOT IN ('draw','win','loss')"
)

_INERTIA_SQL = f"""
    {W_AGE} * LEAST(EXTRACT(EPOCH FROM (now()-e.updated_at))/86400.0/{AGE_SCALE}, 1.0)
  + {W_CONF} * e.confidence
  + {W_DENS} * LEAST((
        SELECT count(*) FROM live_edges r
        WHERE r.subject=e.subject OR r.object=e.subject
           OR r.subject=e.object  OR r.object=e.object
    )::float/{DEG_SCALE}, 1.0)
"""


def _phase_band(inertia: float) -> str:
    """Coarse band label — where this inertia sits on the volatile→locked scale."""
    if inertia < 0.45:
        return "volatile-band"
    if inertia < 0.62:
        return "fluid-band"
    return "salt-band"


def cmd_inertia(args):
    """Show the inertia (resistance to change) of edges matching a term.

    edge inertia <term> [--limit N]

    Reports each matching edge's computed inertia, its components (age /
    confidence / density), and which band the inertia falls in — so you can
    see when a fact's declared phase and its actual mass disagree (a quiet
    axiom reading salt-band while labelled fluid, or stale telemetry reading
    volatile-band while labelled salt).
    """
    limit = 15
    terms = []
    i = 0
    while i < len(args):
        if args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1]); i += 2
        else:
            terms.append(args[i]); i += 1
    if not terms:
        print("usage: edge inertia <term> [--limit N]")
        sys.exit(1)
    term = " ".join(terms)

    conn = connect()
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT e.phase, e.confidence,
                   EXTRACT(EPOCH FROM (now()-e.updated_at))/86400.0 AS age_days,
                   (SELECT count(*) FROM live_edges r
                      WHERE r.subject=e.subject OR r.object=e.subject
                         OR r.subject=e.object  OR r.object=e.object) AS degree,
                   ({_INERTIA_SQL}) AS inertia,
                   e.subject, e.predicate, e.object
            FROM live_edges e
            WHERE (e.subject ILIKE %s OR e.predicate ILIKE %s OR e.object ILIKE %s)
              AND {_NOISE}
            ORDER BY inertia DESC
            LIMIT %s
            """,
            (f"%{term}%", f"%{term}%", f"%{term}%", limit),
        )
        rows = cur.fetchall()

    if not rows:
        print(f"  no edges matching '{term}'")
        return

    print(f"\n  INERTIA  —  \"{term}\"   (resistance to change)")
    print(f"  {'─' * 66}\n")
    for phase, conf, age, deg, inertia, s, p, o in rows:
        band = _phase_band(inertia)
        mismatch = "" if band.startswith(phase) else f"  ⚠ labelled {phase}"
        print(f"  {inertia:.3f}  [{band}{mismatch}]")
        print(f"         age {age:.0f}d · conf {conf:.2f} · degree {deg}")
        print(f"         ({s} --{p}--> {o[:50]})\n")


def cmd_mass(args):
    """The heaviest facts in the graph — highest inertia, the ones it takes
    real force to move. The de-facto axioms, whether or not anyone declared
    them so.

    edge mass [--limit N] [--quiet-only]

    --quiet-only: restrict to LOW-density facts (degree <= 3). These are the
    load-bearing-but-quiet edges — high inertia, almost un-prehended — that
    pure density-fixity would dangerously mark as cheap to remove. The most
    important thing inertia catches that density can't.
    """
    limit = 20
    quiet_only = "--quiet-only" in args
    i = 0
    while i < len(args):
        if args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1]); i += 2
        else:
            i += 1

    degree_clause = ""
    if quiet_only:
        degree_clause = (
            " AND (SELECT count(*) FROM live_edges r"
            "      WHERE r.subject=e.subject OR r.object=e.subject"
            "         OR r.subject=e.object  OR r.object=e.object) <= 3"
        )

    conn = connect()
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT e.phase, e.confidence,
                   EXTRACT(EPOCH FROM (now()-e.updated_at))/86400.0 AS age_days,
                   (SELECT count(*) FROM live_edges r
                      WHERE r.subject=e.subject OR r.object=e.subject
                         OR r.subject=e.object  OR r.object=e.object) AS degree,
                   ({_INERTIA_SQL}) AS inertia,
                   e.subject, e.predicate, e.object
            FROM live_edges e
            WHERE {_NOISE}{degree_clause}
            ORDER BY inertia DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()

    label = "heaviest QUIET facts (load-bearing but un-prehended)" if quiet_only else "heaviest facts"
    print(f"\n  MASS  —  {label}")
    print(f"  {'─' * 66}\n")
    for phase, conf, age, deg, inertia, s, p, o in rows:
        print(f"  {inertia:.3f}  [{phase}]  age {age:.0f}d · conf {conf:.2f} · deg {deg}")
        print(f"         ({s} --{p}--> {o[:50]})\n")
