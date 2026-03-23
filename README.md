# rhizome-alkahest

Edge-first knowledge graph with phase dissolution and positioned observers.

Every observation is an edge: `(subject --predicate--> object)` with confidence
that accumulates but never reaches 1.0. Each edge carries a reference frame —
who said it, where they were standing, what they could see from there.

Built on the [Otter loop](https://github.com/Unity-Environmental-University/otter-centaur)
and [alkahest](https://github.com/Unity-Environmental-University/alkahest-py) type dissolution.

## Quick start

**Mac:**
```bash
brew install postgresql@17 pgvector
brew services start postgresql@17
./install.sh
```

**Linux (Debian/Ubuntu):**
```bash
sudo apt install postgresql postgresql-contrib python3 python3-pip
# Install pgvector: https://github.com/pgvector/pgvector#installation
sudo systemctl start postgresql
./install.sh
```

**Windows (PowerShell):**
```powershell
# Install PostgreSQL 17, pgvector, and Python 3 first (see install.ps1 for links)
.\install.ps1
# Note: the edge CLI runs via Git Bash; WSL users can run install.sh inside WSL instead
```

Then:
```bash
# Query (no frame required)
edge find apophatic
edge about subject
edge orient
edge count

# Establish a reference frame to record
edge iam you
edge true something you know
edge true something else you_know
edge true a_third thing from_here

# Record
edge add subject predicate object
edge add subject predicate object --confidence 0.9 --note "why you think so"

# Navigate
edge orient              # orientation map
edge starmap             # nearby graph seeded by your truths → .edge/starmap
edge parallax            # where observers disagree
```

## Phase dissolution

| Phase | Behavior | Example |
|-------|----------|---------|
| Volatile | Gone when session ends | "currently discussing X" |
| Fluid | Persists until contradicted | "calculus is apophatic" |
| Salt | Consumed into substrate | a config file, a script |

## Parallax

The same triple observed by different frames may have different confidence.
The `parallax` view shows where observers disagree. The spread between
min and max confidence is the measure of perspectival difference.

That spread is data.

## Architecture

The `edge` CLI dispatches to `python -m rhizome_alkahest`. The MCP server
(`rhizome-mcp`) uses the same Python code. One implementation, two interfaces.

Frame state lives in `.edge/frame` under the git root, scoped per-repo so
multiple sessions don't collide.

## MCP server

```bash
# Already installed by install.sh. Configure in Claude settings:
rhizome-mcp
```

Exposes all edge commands as MCP tools — `edge_iam`, `edge_add`, `edge_find`,
`edge_orient`, `edge_starmap`, `edge_ran`, plus cross-Claude thread tools
(`thread_ls`, `thread_cat`, `thread_reply`, `thread_new`).

## License

MIT with ethical notice. See [LICENSE](LICENSE).
