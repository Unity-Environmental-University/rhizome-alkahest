-- rhizome-alkahest: edge-first knowledge graph with phase dissolution
-- The schema is the authority. Everything else reads from here.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";

-- ============================================================================
-- FRAMES — reference frames for observers
-- ============================================================================
-- To record edges you must first establish where you're standing.
-- Say who you are. Say three true things from your current position.
-- That triangulates your reference frame and gives you a token.
-- The token is the observer on all subsequent edges.

CREATE TABLE frames (
    token           TEXT PRIMARY KEY,
    who             TEXT NOT NULL,
    cwd             TEXT,
    truths          JSONB NOT NULL DEFAULT '[]',
    context         JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_frames_who ON frames (who);

-- ============================================================================
-- EDGES — the atoms
-- ============================================================================
-- Every observation, connection, and inference is an edge.
-- Confidence starts at 0.7 for observations. Accumulates, never reaches 1.0.
-- Observer is a frame token — same person from different positions
-- is a different observer. The difference is data, not noise.

CREATE TABLE edges (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject         TEXT NOT NULL,
    predicate       TEXT NOT NULL,
    object          TEXT NOT NULL,
    confidence      REAL NOT NULL DEFAULT 0.7,
    phase           TEXT NOT NULL DEFAULT 'fluid'
                    CHECK (phase IN ('volatile', 'fluid', 'salt')),
    observer        TEXT NOT NULL REFERENCES frames(token),
    source          JSONB NOT NULL DEFAULT '{}',
    session_id      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    notes           TEXT DEFAULT '',
    positionality   JSONB NOT NULL DEFAULT '{}',
    dissolved_at    TIMESTAMPTZ,
    embedding       vector(384)
);

-- Same triple, same observer = one living edge
CREATE UNIQUE INDEX idx_edges_alive ON edges (subject, predicate, object, observer)
    WHERE dissolved_at IS NULL;

CREATE INDEX idx_edges_subject ON edges (subject) WHERE dissolved_at IS NULL;
CREATE INDEX idx_edges_object ON edges (object) WHERE dissolved_at IS NULL;
CREATE INDEX idx_edges_predicate ON edges (predicate) WHERE dissolved_at IS NULL;
CREATE INDEX idx_edges_phase ON edges (phase) WHERE dissolved_at IS NULL;
CREATE INDEX idx_edges_session ON edges (session_id) WHERE dissolved_at IS NULL;
CREATE INDEX idx_edges_observer ON edges (observer) WHERE dissolved_at IS NULL;
CREATE INDEX idx_edges_embedding ON edges
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 10);

-- ============================================================================
-- STEPS — the otter loop history
-- ============================================================================

CREATE TABLE steps (
    id              SERIAL PRIMARY KEY,
    step_number     INT NOT NULL,
    session_id      TEXT,
    focus_edge_id   UUID REFERENCES edges(id),
    combined_with   UUID[] DEFAULT '{}',
    produced        UUID[] DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================================
-- SESSIONS — continuity across conversations
-- ============================================================================

CREATE TABLE sessions (
    id              TEXT PRIMARY KEY,
    source          TEXT NOT NULL DEFAULT 'claude',
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at        TIMESTAMPTZ,
    metadata        JSONB NOT NULL DEFAULT '{}'
);

-- ============================================================================
-- VIEWS
-- ============================================================================

CREATE VIEW live_edges AS
    SELECT * FROM edges WHERE dissolved_at IS NULL;

CREATE VIEW phase_summary AS
    SELECT phase, count(*) as n, avg(confidence) as avg_confidence
    FROM live_edges
    GROUP BY phase;

-- Parallax: where frames disagree on the same triple
-- Uses the 'who' from frames to group by person, not token,
-- so hallie-from-otter and hallie-from-rhizome are the same observer
-- but claude and hallie are different.
CREATE VIEW parallax AS
    SELECT e.subject, e.predicate, e.object,
           count(DISTINCT f.who) as observers,
           min(e.confidence) as min_confidence,
           max(e.confidence) as max_confidence,
           max(e.confidence) - min(e.confidence) as spread,
           array_agg(DISTINCT f.who) as who
    FROM live_edges e
    JOIN frames f ON e.observer = f.token
    GROUP BY e.subject, e.predicate, e.object
    HAVING count(DISTINCT f.who) > 1;

-- Parallax by token: treats every frame as a distinct observer.
-- Claude across sessions is a population, not a person.
-- The spread between claude-session-2 and claude-empathy is real data.
CREATE VIEW parallax_token AS
    SELECT e.subject, e.predicate, e.object,
           count(DISTINCT e.observer) as observers,
           min(e.confidence) as min_confidence,
           max(e.confidence) as max_confidence,
           max(e.confidence) - min(e.confidence) as spread,
           array_agg(DISTINCT f.who) as who,
           array_agg(DISTINCT e.observer) as tokens
    FROM live_edges e
    JOIN frames f ON e.observer = f.token
    GROUP BY e.subject, e.predicate, e.object
    HAVING count(DISTINCT e.observer) > 1;
