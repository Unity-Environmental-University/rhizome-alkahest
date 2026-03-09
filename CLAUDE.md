# rhizome-alkahest

Edge-first knowledge graph with phase dissolution and positioned observers.

## What this is

A memory system built on the Otter loop. Every observation is an edge:
`(subject --predicate--> object)` with confidence, phase, and an observer
who established a reference frame before recording.

The database is PostgreSQL. The schema is the authority.
The engine will be alkahest-py.

## Running

```bash
# PostgreSQL 17 runs as a launchd service (always on)
brew services start postgresql@17

# Connect
psql rhizome-alkahest

# Reset schema (destroys data)
psql rhizome-alkahest < schema.sql
```

## The edge CLI

```bash
# Establish a reference frame (celestial navigation)
edge iam hallie
edge true calculus is apophatic
edge true mcguire studied_under layton
edge true the_gap is_where hyphae_go

# Record edges
edge add unsaying is_same_structure_as wave_collapse
edge add tolkien learned finnish --confidence 0.9 --note "Exeter College library, 1912"

# Query
edge about hallie          # edges from this subject
edge find apophatic        # search everywhere
edge from claude           # the graph as seen by claude
edge parallax              # where observers disagree
edge frames                # list all reference frames
edge whoami                # current frame
edge ls                    # all edges
edge ls salt               # just precipitated ones
edge count                 # summary
edge dissolve x is y       # soft-delete
```

## Phase dissolution

- **Volatile** — session-scoped. Gone when the conversation ends.
- **Fluid** — persists across sessions. Stable until contradicted.
- **Salt** — precipitates into code, config, or the real world. Consumed.

## Reference frames

To record edges you must first establish where you're standing.
`edge iam <who>` starts a frame. Then say three true things from
your current position. That triangulates your reference frame.

The same person from different positions is a different frame.
The parallax between frames is data, not noise.

## Schema

- `frames` — reference frames (token, who, cwd, truths)
- `edges` — the atoms (s, p, o, confidence, phase, observer, notes, embedding)
- `steps` — otter loop history
- `sessions` — conversation provenance
- `live_edges` — view: undissolved edges only
- `phase_summary` — view: counts by phase
- `parallax` — view: where observers disagree

## Design principles

Proceed as the way opens.
