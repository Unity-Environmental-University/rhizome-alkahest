"""Graph — the interface to the knowledge graph."""

import hashlib
import json
from typing import Optional

import psycopg

from .db import connect
from .edge import Edge
from .frame import Frame
from .frame_pointer import git_context


def edge_hash(subject: str, predicate: str, object: str, observer: str) -> str:
    """Deterministic 8-char hash for an edge triple + observer."""
    content = f"{subject}\0{predicate}\0{object}\0{observer}"
    return hashlib.sha256(content.encode()).hexdigest()[:8]


class Graph:
    """A positioned view into the knowledge graph."""

    def __init__(self, frame: Frame, conn: Optional[psycopg.Connection] = None):
        if not frame.ready:
            raise ValueError("Frame needs 3 truths before you can use the graph")
        self.frame = frame
        self.conn = conn or connect()

    def add(
        self,
        subject: str,
        predicate: str,
        object: str,
        confidence: float = 0.7,
        phase: str = "fluid",
        notes: str = "",
        slug: str | None = None,
    ) -> Edge:
        """Record an edge from this frame's position."""
        pos = json.dumps(git_context())
        ehash = edge_hash(subject, predicate, object, self.frame.token)
        with self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO edges (subject, predicate, object, confidence, phase, observer, notes, positionality, slug, hash)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT DO NOTHING
                   RETURNING id, created_at""",
                (subject, predicate, object, confidence, phase, self.frame.token, notes, pos, slug, ehash),
            )
            row = cur.fetchone()
        self.conn.commit()

        edge = Edge(
            subject=subject,
            predicate=predicate,
            object=object,
            confidence=confidence,
            phase=phase,
            observer=self.frame.token,
            notes=notes,
            slug=slug,
            hash=ehash,
        )
        if row:
            edge.id, edge.created_at = row
        return edge

    def resolve_slug(self, slug: str) -> Edge | None:
        """Look up a live edge by slug or hash."""
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT id, subject, predicate, object, confidence, phase, observer, notes, created_at, slug, hash
                   FROM live_edges WHERE slug = %s OR hash = %s LIMIT 1""",
                (slug, slug),
            )
            row = cur.fetchone()
            if row:
                e = self._row_to_edge(row[:9])
                e.slug = row[9]
                e.hash = row[10]
                return e
            return None

    def about(self, subject: str) -> list[Edge]:
        """All living edges with this subject."""
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT id, subject, predicate, object, confidence, phase, observer, notes, created_at
                   FROM live_edges WHERE subject = %s ORDER BY confidence DESC""",
                (subject,),
            )
            return [self._row_to_edge(r) for r in cur.fetchall()]

    def find(self, term: str) -> list[Edge]:
        """Search subject, predicate, or object."""
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT id, subject, predicate, object, confidence, phase, observer, notes, created_at
                   FROM live_edges
                   WHERE subject ILIKE %s OR predicate ILIKE %s OR object ILIKE %s
                   ORDER BY confidence DESC""",
                (f"%{term}%", f"%{term}%", f"%{term}%"),
            )
            return [self._row_to_edge(r) for r in cur.fetchall()]

    def from_observer(self, who: str) -> list[Edge]:
        """All living edges from this person (across all their frames)."""
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT e.id, e.subject, e.predicate, e.object, e.confidence,
                          e.phase, e.observer, e.notes, e.created_at
                   FROM live_edges e
                   JOIN frames f ON e.observer = f.token
                   WHERE f.who = %s
                   ORDER BY e.updated_at DESC""",
                (who,),
            )
            return [self._row_to_edge(r) for r in cur.fetchall()]

    def parallax(
        self, subject: str | None = None, predicate: str | None = None, object: str | None = None
    ) -> list[dict]:
        """Where observers disagree. Optionally filter to a specific triple."""
        with self.conn.cursor() as cur:
            query = "SELECT * FROM parallax"
            params: list = []
            conditions = []
            if subject:
                conditions.append("subject = %s")
                params.append(subject)
            if predicate:
                conditions.append("predicate = %s")
                params.append(predicate)
            if object:
                conditions.append("object = %s")
                params.append(object)
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY spread DESC"
            cur.execute(query, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def dissolve(self, subject: str, predicate: str, object: str) -> int:
        """Soft-delete all living edges matching this triple."""
        with self.conn.cursor() as cur:
            cur.execute(
                """UPDATE edges SET dissolved_at = now()
                   WHERE subject = %s AND predicate = %s AND object = %s
                   AND dissolved_at IS NULL""",
                (subject, predicate, object),
            )
            count = cur.rowcount
        self.conn.commit()
        return count

    def count(self) -> dict:
        """Summary stats."""
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM phase_summary")
            phases = {row[0]: {"n": row[1], "avg_confidence": row[2]} for row in cur.fetchall()}
            cur.execute("SELECT count(*) FROM live_edges")
            total = cur.fetchone()[0]
        return {"phases": phases, "total": total}

    def _row_to_edge(self, row) -> Edge:
        return Edge(
            id=str(row[0]),
            subject=row[1],
            predicate=row[2],
            object=row[3],
            confidence=row[4],
            phase=row[5],
            observer=row[6],
            notes=row[7],
            created_at=row[8],
        )
