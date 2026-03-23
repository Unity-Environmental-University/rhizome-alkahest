"""
Parallax Digest — surfaces discoveries using a local LLM.

For each high-spread parallax disagreement, fetches the semantic neighborhood
(edges near the subject/object in embedding space), then asks Qwen what a third
observer would see that neither existing frame can see. Writes discoveries back
as fluid edges with observer qwen-2.5-7b.

Usage:
    from rhizome_alkahest.digest import ParallaxDigest
    digest = ParallaxDigest()
    discoveries = digest.run(limit=5)

Or from the CLI:
    edge digest [--limit N] [--dry-run] [--min-spread F] [--exclude-prefix PREFIX]
"""

import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import psycopg
from openai import OpenAI

from .db import connect
from .edge import Edge
from .frame import Frame
from .graph import Graph

QWEN_BASE_URL = "http://localhost:5052/v1"
QWEN_MODEL = "Qwen/Qwen2.5-7B-Instruct"


def default_who() -> str:
    project = Path(os.getcwd()).name
    today = date.today().isoformat()
    return f"qwen-2.5-7b @ {project}, {today}"

DIGEST_PROMPT = """\
You are a third observer looking at a knowledge graph where two observers disagree.

## The disagreement (parallax)

Subject: {subject}
Predicate: {predicate}
Objects seen by different observers:
{observer_views}

Confidence spread: {spread:.3f}

## Semantic neighborhood

These are edges near this subject/object in the graph (related concepts):
{neighborhood}

## Task

From your position as a third observer, what edge would you record that neither \
of the existing observers can see from their frames? Look for:
- Something implied by the tension between the two views
- Something the neighborhood suggests but no one has named
- A relationship that becomes visible only when you hold both views simultaneously

Respond with exactly one JSON object:
{{
  "subject": "...",
  "predicate": "...",
  "object": "...",
  "confidence": 0.0-1.0,
  "note": "one sentence explaining what you see from this position"
}}

Only respond with the JSON. No explanation outside it.
"""


@dataclass
class Discovery:
    subject: str
    predicate: str
    object: str
    confidence: float
    note: str
    source_parallax: dict  # the parallax row that prompted this


class ParallaxDigest:
    def __init__(self, who: str = "", conn: Optional[psycopg.Connection] = None):
        self.who = who or default_who()
        self.conn = conn or connect()
        self.client = OpenAI(base_url=QWEN_BASE_URL, api_key="local")
        self._frame: Optional[Frame] = None

    def _get_frame(self) -> Frame:
        if self._frame:
            return self._frame
        truths = [
            (self.who, "role", "third-observer"),
            (self.who, "task", "triangulate-parallax"),
            (self.who, "output", "candidate-edges"),
        ]
        frame = Frame.establish(
            who=self.who,
            truths=truths,
            conn=self.conn,
        )
        self._frame = frame
        return frame

    def _fetch_parallax(
        self,
        min_spread: float = 0.05,
        exclude_prefixes: tuple[str, ...] = ("connect5:",),
        limit: int = 10,
    ) -> list[dict]:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT subject, predicate, object, observers, min_confidence,
                       max_confidence, spread, who
                FROM parallax
                WHERE spread >= %s
                ORDER BY spread DESC
                """,
            (min_spread,),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]

        filtered = [
            r for r in rows
            if not any(r["subject"].startswith(p) for p in exclude_prefixes)
        ]
        return filtered[:limit]

    def _fetch_neighborhood(self, subject: str, object: str, k: int = 8) -> list[str]:
        """
        Return k edges semantically close to the subject or object.
        Uses pgvector cosine similarity on existing edge embeddings.
        Falls back to text search if no embeddings found.
        """
        with self.conn.cursor() as cur:
            # Find a representative embedding for the subject or object term
            cur.execute(
                """
                SELECT embedding FROM live_edges
                WHERE (subject = %s OR object = %s) AND embedding IS NOT NULL
                LIMIT 1
                """,
                (subject, object),
            )
            row = cur.fetchone()

        if row and row[0] is not None:
            embedding = row[0]
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT subject, predicate, object, confidence
                    FROM live_edges
                    WHERE embedding IS NOT NULL
                      AND subject != %s AND object != %s
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (subject, object, embedding, k),
                )
                rows = cur.fetchall()
        else:
            # Fallback: text search
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT subject, predicate, object, confidence
                    FROM live_edges
                    WHERE subject ILIKE %s OR object ILIKE %s
                      OR subject ILIKE %s OR object ILIKE %s
                    LIMIT %s
                    """,
                    (f"%{subject}%", f"%{subject}%", f"%{object}%", f"%{object}%", k),
                )
                rows = cur.fetchall()

        return [f"({r[0]} --{r[1]}--> {r[2]}) [{r[3]:.2f}]" for r in rows]

    def _ask_qwen(self, parallax_row: dict, neighborhood: list[str]) -> Optional[Discovery]:
        who_list = parallax_row.get("who", [])
        observer_views = "\n".join(
            f"  - observer {i+1}: {w}" for i, w in enumerate(who_list)
        )
        neighborhood_text = "\n".join(f"  {e}" for e in neighborhood) or "  (none found)"

        prompt = DIGEST_PROMPT.format(
            subject=parallax_row["subject"],
            predicate=parallax_row["predicate"],
            observer_views=observer_views,
            spread=parallax_row["spread"],
            neighborhood=neighborhood_text,
        )

        try:
            response = self.client.chat.completions.create(
                model=QWEN_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=256,
            )
            text = response.choices[0].message.content.strip()
            # Strip markdown code fences if present
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            data = json.loads(text)
            return Discovery(
                subject=str(data["subject"]),
                predicate=str(data["predicate"]),
                object=str(data["object"]),
                confidence=float(data.get("confidence", 0.6)),
                note=str(data.get("note", "")),
                source_parallax=parallax_row,
            )
        except Exception as e:
            return None

    def _write_discovery(self, discovery: Discovery) -> Edge:
        frame = self._get_frame()
        graph = Graph(frame=frame, conn=self.conn)
        src = discovery.source_parallax
        full_note = (
            f"{discovery.note} "
            f"[parallax: {src['subject']} --{src['predicate']}--> {src['object']}, "
            f"spread={src['spread']:.3f}]"
        )
        return graph.add(
            subject=discovery.subject,
            predicate=discovery.predicate,
            object=discovery.object,
            confidence=discovery.confidence,
            phase="fluid",
            notes=full_note,
        )

    def run(
        self,
        limit: int = 5,
        min_spread: float = 0.05,
        exclude_prefixes: tuple[str, ...] = ("connect5:",),
        dry_run: bool = False,
        neighborhood_k: int = 8,
        verbose: bool = True,
    ) -> list[Discovery]:
        parallax_rows = self._fetch_parallax(
            min_spread=min_spread,
            exclude_prefixes=exclude_prefixes,
            limit=limit,
        )

        if verbose:
            print(f"  {len(parallax_rows)} parallax disagreements to digest")

        discoveries = []
        for row in parallax_rows:
            neighborhood = self._fetch_neighborhood(
                row["subject"], row["object"], k=neighborhood_k
            )

            if verbose:
                print(f"\n  parallax: ({row['subject']} --{row['predicate']}--> {row['object']}) spread={row['spread']:.3f}")
                print(f"  neighborhood: {len(neighborhood)} edges")

            discovery = self._ask_qwen(row, neighborhood)
            if discovery is None:
                if verbose:
                    print("  → no discovery (model returned nothing parseable)")
                continue

            if verbose:
                print(f"  → ({discovery.subject} --{discovery.predicate}--> {discovery.object}) [{discovery.confidence:.2f}]")
                print(f"     {discovery.note}")

            if not dry_run:
                self._write_discovery(discovery)

            discoveries.append(discovery)

        if verbose and not dry_run:
            print(f"\n  {len(discoveries)} discoveries written to graph (@{self.who})")

        return discoveries


# ---------------------------------------------------------------------------
# Isomorphism finder
# ---------------------------------------------------------------------------

ISOMORPH_PROMPT = """\
You are looking at two nodes in a knowledge graph that have structurally similar \
relationship patterns — they participate in the same kinds of predicates, but they \
live in different conceptual domains.

## Node A: {node_a}

Edges:
{edges_a}

## Node B: {node_b}

Edges:
{edges_b}

## Predicate overlap

These predicates appear for both nodes: {shared_predicates}
Jaccard similarity: {jaccard:.2f}

## Task

Is there a genuine structural isomorphism here — a mapping where the relationship \
pattern of A mirrors the relationship pattern of B? If yes, name it precisely: \
what does each node *correspond to* in the other's domain?

If the similarity is superficial (same predicate words, different structures), say so.

If genuine, respond with a JSON object:
{{
  "isomorphism": true,
  "node_a": "{node_a}",
  "node_b": "{node_b}",
  "mapping": "one sentence naming the correspondence",
  "bridge_edges": [
    {{"subject": "...", "predicate": "corresponds-to", "object": "...", "note": "..."}},
    {{"subject": "...", "predicate": "corresponds-to", "object": "...", "note": "..."}}
  ],
  "confidence": 0.0-1.0
}}

If superficial, respond with:
{{
  "isomorphism": false,
  "reason": "..."
}}

Only respond with the JSON.
"""


@dataclass
class Isomorphism:
    node_a: str
    node_b: str
    mapping: str
    bridge_edges: list[dict]
    confidence: float
    jaccard: float


class IsomorphFinder:
    """
    Finds structurally similar node pairs (same predicate shapes, different domains)
    and asks Qwen whether the similarity is a genuine isomorphism.

    Usage:
        finder = IsomorphFinder()
        results = finder.run(limit=5)

    CLI:
        edge isomorph [--limit N] [--min-jaccard F] [--dry-run]
    """

    NOISE_PREFIXES = ("connect5:", "go9:", "sf-schema:")

    def __init__(self, who: str = "", conn: Optional[psycopg.Connection] = None):
        self.who = who or default_who()
        self.conn = conn or connect()
        self.client = OpenAI(base_url=QWEN_BASE_URL, api_key="local")
        self._frame: Optional[Frame] = None

    def _get_frame(self) -> Frame:
        if self._frame:
            return self._frame
        truths = [
            (self.who, "role", "isomorphism-detector"),
            (self.who, "task", "find-structural-correspondence"),
            (self.who, "output", "bridge-edges"),
        ]
        self._frame = Frame.establish(who=self.who, truths=truths, conn=self.conn)
        return self._frame

    def _fetch_node_signatures(
        self, min_edges: int = 3
    ) -> dict[str, set[str]]:
        """Return {subject: {predicate, ...}} for nodes with enough edges, excluding noise."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT subject, predicate
                FROM live_edges
                WHERE dissolved_at IS NULL
                """,
            )
            rows = cur.fetchall()

        from collections import defaultdict
        sigs: dict[str, set[str]] = defaultdict(set)
        for subject, predicate in rows:
            if any(subject.startswith(p) for p in self.NOISE_PREFIXES):
                continue
            sigs[subject].add(predicate)

        return {s: preds for s, preds in sigs.items() if len(preds) >= min_edges}

    def _jaccard(self, a: set, b: set) -> float:
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    def _fetch_node_embeddings(self, nodes: list[str]) -> dict[str, list[float]]:
        """Return mean embedding per node (average over all its edges that have one)."""
        if not nodes:
            return {}
        # Fetch one representative embedding per node (first available)
        result = {}
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (subject) subject, embedding::text
                FROM live_edges
                WHERE subject = ANY(%s) AND embedding IS NOT NULL
                """,
                (nodes,),
            )
            for subject, emb_text in cur.fetchall():
                # pgvector returns '[0.1,0.2,...]' format
                vals = [float(x) for x in emb_text.strip("[]").split(",")]
                result[subject] = vals
        return result

    def _cosine_distance(self, a: list[float], b: list[float]) -> float:
        import math
        dot = sum(x * y for x, y in zip(a, b))
        mag_a = math.sqrt(sum(x * x for x in a))
        mag_b = math.sqrt(sum(x * x for x in b))
        if mag_a == 0 or mag_b == 0:
            return 1.0
        return 1.0 - dot / (mag_a * mag_b)

    def _find_candidate_pairs(
        self,
        signatures: dict[str, set[str]],
        min_jaccard: float = 0.3,
        min_embedding_distance: float = 0.15,
        limit: int = 10,
    ) -> list[tuple[str, str, float, set[str]]]:
        """
        Return (node_a, node_b, jaccard, shared_predicates) pairs sorted by jaccard desc.
        Requires high structural similarity (jaccard) AND semantic distance (embeddings)
        so we find cross-domain isomorphisms, not just same-type duplicates.
        """
        nodes = list(signatures.keys())
        embeddings = self._fetch_node_embeddings(nodes)

        candidates = []
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                a, b = nodes[i], nodes[j]
                if a in b or b in a:
                    continue
                # Same prefix = same type, skip — but allow impl: comparisons
                a_prefix = a.split(":")[0]
                b_prefix = b.split(":")[0]
                COMPARE_WITHIN = {"impl", "bug"}
                if a_prefix == b_prefix and len(a_prefix) > 3 and a_prefix not in COMPARE_WITHIN:
                    continue
                j_score = self._jaccard(signatures[a], signatures[b])
                if j_score < min_jaccard:
                    continue
                # Require semantic distance if embeddings available for both
                if a in embeddings and b in embeddings:
                    dist = self._cosine_distance(embeddings[a], embeddings[b])
                    if dist < min_embedding_distance:
                        continue
                shared = signatures[a] & signatures[b]
                candidates.append((a, b, j_score, shared))

        candidates.sort(key=lambda x: x[2], reverse=True)
        return candidates[:limit]

    def _fetch_edges_for(self, subject: str) -> list[str]:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT predicate, object, confidence
                FROM live_edges
                WHERE subject = %s
                ORDER BY confidence DESC
                LIMIT 12
                """,
                (subject,),
            )
            return [f"  --{p}--> {o} [{c:.2f}]" for p, o, c in cur.fetchall()]

    def _ask_qwen(
        self, node_a: str, node_b: str, jaccard: float, shared: set[str]
    ) -> Optional[Isomorphism]:
        edges_a = "\n".join(self._fetch_edges_for(node_a)) or "  (none)"
        edges_b = "\n".join(self._fetch_edges_for(node_b)) or "  (none)"

        prompt = ISOMORPH_PROMPT.format(
            node_a=node_a,
            node_b=node_b,
            edges_a=edges_a,
            edges_b=edges_b,
            shared_predicates=", ".join(sorted(shared)),
            jaccard=jaccard,
        )

        try:
            response = self.client.chat.completions.create(
                model=QWEN_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.6,
                max_tokens=512,
            )
            text = response.choices[0].message.content.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            data = json.loads(text)

            if not data.get("isomorphism"):
                return None

            return Isomorphism(
                node_a=node_a,
                node_b=node_b,
                mapping=data.get("mapping", ""),
                bridge_edges=data.get("bridge_edges", []),
                confidence=float(data.get("confidence", 0.6)),
                jaccard=jaccard,
            )
        except Exception:
            return None

    def _write_isomorphism(self, iso: Isomorphism):
        frame = self._get_frame()
        graph = Graph(frame=frame, conn=self.conn)
        note_prefix = f"isomorphism: {iso.mapping} [jaccard={iso.jaccard:.2f}]"
        for be in iso.bridge_edges:
            graph.add(
                subject=be["subject"],
                predicate=be.get("predicate", "corresponds-to"),
                object=be["object"],
                confidence=iso.confidence,
                phase="fluid",
                notes=f"{note_prefix} — {be.get('note', '')}",
            )

    def run(
        self,
        limit: int = 5,
        min_jaccard: float = 0.3,
        min_edges: int = 3,
        dry_run: bool = False,
        verbose: bool = True,
    ) -> list[Isomorphism]:
        signatures = self._fetch_node_signatures(min_edges=min_edges)
        candidates = self._find_candidate_pairs(
            signatures, min_jaccard=min_jaccard, limit=limit * 3
        )

        if verbose:
            print(f"  {len(candidates)} candidate pairs (jaccard ≥ {min_jaccard}), checking top {limit * 3}")

        results = []
        checked = 0
        for node_a, node_b, jaccard, shared in candidates:
            if checked >= limit * 3:
                break
            checked += 1

            if verbose:
                print(f"\n  pair: '{node_a}' / '{node_b}'")
                print(f"  shared predicates: {sorted(shared)}  jaccard={jaccard:.2f}")

            iso = self._ask_qwen(node_a, node_b, jaccard, shared)

            if iso is None:
                if verbose:
                    print("  → no isomorphism (superficial or unparseable)")
                continue

            if verbose:
                print(f"  → ISOMORPHISM [{iso.confidence:.2f}]: {iso.mapping}")
                for be in iso.bridge_edges:
                    print(f"     ({be['subject']} --{be.get('predicate','corresponds-to')}--> {be['object']})")

            if not dry_run:
                self._write_isomorphism(iso)

            results.append(iso)
            if len(results) >= limit:
                break

        if verbose and not dry_run:
            print(f"\n  {len(results)} isomorphisms written to graph (@{self.who})")

        return results
