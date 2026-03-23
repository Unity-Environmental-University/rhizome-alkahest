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

# Query (no frame required)
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

# Navigate
edge orient [days]         # orientation map (default 7d)
edge starmap               # nearby graph from truths → .edge/starmap
edge ran <movement>        # register a qigong run + show prior deposits
```

## Phase dissolution

- **Volatile** — session-scoped. Gone when the conversation ends.
- **Fluid** — persists across sessions. Stable until contradicted.
- **Salt** — precipitates into code, config, or the real world. Consumed.

## Reference frames

Reading the graph requires no frame. Recording requires one.
To record edges you must first establish where you're standing.
`edge iam <who>` starts a frame. Then say three true things from
your current position. That triangulates your reference frame.

The same person from different positions is a different frame.
The parallax between frames is data, not noise.

## Schema

- `frames` — reference frames (token, who, cwd, truths, context)
- `edges` — the atoms (s, p, o, confidence, phase, observer, notes, positionality, embedding)
- `steps` — otter loop history
- `sessions` — conversation provenance
- `live_edges` — view: undissolved edges only
- `phase_summary` — view: counts by phase
- `parallax` — view: where observers disagree

## Architecture

The `edge` CLI is a thin bash dispatch to `python -m rhizome_alkahest`.
The MCP server (`rhizome_alkahest/mcp_server.py`) uses the same Python code.
One implementation, two interfaces.

Frame state lives in `.edge/frame` under the git root (scoped per-repo).

## Design principles

Proceed as the way opens.

## Skill

A Claude skill for working with this graph lives at `.claude/skills/rhizome/skill.md`. It covers frames, composite identity (speaks-as/speaks-for), recording, querying, and graph reading.
