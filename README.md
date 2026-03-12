# rhizome-alkahest

Edge-first knowledge graph with phase dissolution and positioned observers.

Every observation is an edge: `(subject --predicate--> object)` with confidence
that accumulates but never reaches 1.0. Each edge carries a reference frame —
who said it, where they were standing, what they could see from there.

Built on the [Otter loop](https://github.com/Unity-Environmental-University/otter-centaur)
and [alkahest](https://github.com/Unity-Environmental-University/alkahest-py) type dissolution.

## Quick start

```bash
# Requires PostgreSQL 17 + pgvector
brew install postgresql@17 pgvector
brew services start postgresql@17

# Install: sets up the database, links the edge CLI, and installs the Claude skill
./install.sh

# Establish a reference frame
edge iam you
edge true something you know
edge true something else you_know
edge true a_third thing from_here

# Record
edge add subject predicate object
edge add subject predicate object --confidence 0.9 --note "why you think so"

# Query
edge about subject
edge from you
edge parallax
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

## License

MIT with ethical notice. See [LICENSE](LICENSE).
