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
edge add tolkien learned finnish --slug tolkien-finnish   # name it

# Edge-as-subject — reference by slug, hash, or triple
edge add e[tolkien-finnish] illustrates dedication         # by slug
edge add e[a3f2c9b1] illustrates dedication                # by hash
edge add e[tolkien learned finnish] illustrates dedication  # by triple

# Agglutinative grammar — edge say
edge say shear is zpd-boundary:glows-because:apophasis     # : chains nodes
edge say hallie builds rooms~obs                            # ~ marks evidentiality
edge say hallie builds rooms~because:care:drives:design     # ~ links edges

# Aliases for common predicates
edge alias gb glows-because       # create
edge alias                        # list all
edge say shear is boundary:gb:apophasis   # use in say

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

# Stewardship
edge garden                # surface edges needing tending
edge name <hash> <slug>    # retroactively name an edge
edge decompose <hash> s p o [s p o ...]   # break long edge into parts
edge words                 # vocabulary frequency
edge words predicates      # just predicates

# Navigate
edge orient [days]         # orientation map (default 7d)
edge starmap               # nearby graph from truths → .edge/starmap
edge ran <movement>        # register a qigong run + show prior deposits
```

## Slugs, hashes, and edge-as-subject

Every edge gets an auto-generated 8-char content hash (`#a3f2c9b1`).
Edges can also be given a human-friendly slug (`--slug my-name`).
Both are printed on creation and can be used to reference the edge
as the subject of another edge via `e[slug-or-hash]` notation.

`e[s p o]` resolves by triple content (no slug/hash needed).

The canonical form for an edge-as-subject is `e:subject/predicate/object`.

## Agglutinative grammar

`edge say` parses sentences where `:` and `~` suffixes generate edges.
Grammar predicates (which words trigger splits) come from the graph
itself — any predicate with >= 5 uses becomes a structural word.

- `:pred:value` — node chain. Object becomes next subject.
- `~marker` — bare evidentiality tag on the edge.
- `~pred:value` — edge annotation (edge → value).
- `~pred:s:p:o` — edge-to-edge link (clause → clause).

Aliases (`edge alias bc because`) map short forms to full predicates.
Aliases are edges themselves: `(bc --is-alias-for--> because)`.

## Stewardship

- `edge garden` — surfaces long edges and unnamed salt.
  Filters out edges already decomposed.
- `edge name` — retroactively slug an edge by hash.
- `edge decompose` — break a long edge into parts, linked by
  `decomposed-into` edges back to the original.
- `edge words` — vocabulary frequency across positions.

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
- `edges` — the atoms (s, p, o, confidence, phase, observer, notes, positionality, embedding, slug, hash)
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
