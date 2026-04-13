"""Integration test: edge creation and cleanup lifecycle.

Verifies that test edges are properly created and dissolved,
so tests don't leave debris in the live database.
"""

import subprocess
import sys
import uuid


def run_edge(*args) -> tuple[str, int]:
    result = subprocess.run(
        [sys.executable, "-m", "rhizome_alkahest.cli", *args],
        capture_output=True, text=True,
        cwd="/Users/hlarsson/repos/unity/rhizome-alkahest",
    )
    return result.stdout + result.stderr, result.returncode


class TestEdgeLifecycle:
    """Create a test edge, verify it, dissolve it, verify it's gone."""

    def test_add_find_dissolve(self):
        # Use a unique marker so we don't collide with real data
        marker = f"test-{uuid.uuid4().hex[:8]}"
        subject = f"test-subject-{marker}"
        predicate = "test-predicate"
        obj = f"test-object-{marker}"

        try:
            # Create — requires a frame, so use edge raw to insert directly
            # Actually, let's just use the find/dissolve path with raw SQL
            # to avoid needing a frame for a test edge
            from rhizome_alkahest.db import connect
            conn = connect()
            with conn.cursor() as cur:
                # Insert a test edge directly
                cur.execute("""
                    INSERT INTO edges (subject, predicate, object, confidence, phase, observer)
                    SELECT %s, %s, %s, 0.5, 'volatile',
                           (SELECT token FROM frames LIMIT 1)
                    RETURNING id
                """, (subject, predicate, obj))
                edge_id = cur.fetchone()[0]
            conn.commit()

            # Verify it shows up in find
            out, rc = run_edge("find", marker)
            assert rc == 0
            assert subject in out, f"Created edge not found in output: {out}"

            # Dissolve it
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE edges SET dissolved_at = now() WHERE id = %s",
                    (edge_id,)
                )
            conn.commit()

            # Verify it's gone from find
            out, rc = run_edge("find", marker)
            assert subject not in out, f"Dissolved edge still showing: {out}"

        finally:
            # Belt and suspenders: make sure it's dissolved even if test fails
            try:
                conn = connect()
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE edges SET dissolved_at = now() WHERE subject = %s AND dissolved_at IS NULL",
                        (subject,)
                    )
                conn.commit()
                conn.close()
            except Exception:
                pass
