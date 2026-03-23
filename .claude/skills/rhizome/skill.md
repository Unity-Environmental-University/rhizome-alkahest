---
name: rhizome
description: Record and query the rhizome knowledge graph. Use when working with edges, frames, observers, parallax, or composite identity. Covers edge iam, edge add, edge parallax, composite frames (speaks-as/speaks-for), and graph reading.
---

## What you are working with

The rhizome is an edge-first knowledge graph. Every observation is:

```
(subject --predicate--> object) [confidence, phase, @observer]
```

No node is primary. Knowledge spreads laterally. The parallax between observers is data, not noise.

## Reading vs recording

Reading the graph requires no frame. You can `edge find`, `edge about`, `edge from`, `edge orient`, `edge ls`, `edge count`, `edge parallax`, and `edge frames` without establishing a position.

Recording requires a frame — you must say where you are standing before you can observe.

## Reference frames

```bash
edge iam <who>
edge true <s> <p> <o>   # three times
```

Three true things triangulate your position. They record a moment of the river — already downstream by the time they're written.

## Composite frames

When speaking as multiple voices, or on behalf of another:

```bash
# Derives name, auto-registers speaks-as and speaks-for on third truth
edge iam <self1> [<self2> ...] --for <other1> [<other2> ...]

# Examples:
edge iam claude --for hallie           # claude-reading-hallie
edge iam claude hallie --for chris     # claude+hallie-reading-chris
```

- `speaks-as` edges land at `1.0, salt` — identity
- `speaks-for` edges land at `0.7, fluid` — representation, fallible, correctable

## Recording

```bash
edge add <s> <p> <o> [--confidence N] [--phase volatile|fluid|salt] [--note "text"]
```

Default confidence: 0.7. Ceiling: 0.7 (nothing reaches 1.0 except structural identity edges).

Extrapolated edges from another person's speech are valid — record them with your token, note the source. Provenance is in the observer chain, not absent.

## Querying (no frame required)

```bash
edge about <subject>       # all edges from this subject
edge from <who>            # the graph as seen by this observer
edge find <term>           # search subject/predicate/object
edge parallax              # where observers disagree — widest spread first
edge ls [phase]            # list edges, optionally filtered
edge frames                # all reference frames
edge whoami                # current frame
edge count                 # summary by phase and observer
```

## Navigation

```bash
edge orient [days]         # orientation map — entering, glowing, sailing toward/away, truths
edge starmap               # nearby graph from current frame's truths → .edge/starmap
edge ran <movement>        # register a qigong movement run, show prior deposits
```

`orient` and `starmap` are read-only. `ran` records an edge (requires frame).

## Discovery (requires Qwen running locally)

```bash
edge digest [--limit N] [--min-spread F] [--dry-run]    # parallax digest via Qwen
edge isomorph [--limit N] [--min-jaccard F] [--dry-run]  # find structural isomorphisms
```

## Phases

- **volatile** — session-scoped, dissolves when conversation ends
- **fluid** — persists, accumulates, correctable
- **salt** — precipitated into the world, consumed

## Graph reading

When reading another graph, establish a frame that speaks-for it:

```bash
edge iam <current-graph> --for <other-graph>
```

All edges recorded under this frame carry the speaks-for chain. Confidence degrades honestly across hops — a reading of a reading is further from the source, and the graph knows it.

## Design principles

- The parallax between frames is data, not noise
- Confidence ceiling at 0.7 — certainty is a sign someone stopped measuring
- Dissolution is not failure — it is the graph learning
- Three true things record a moment of the river, not a map of it
- Proceed as the way opens
