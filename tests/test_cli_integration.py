"""Integration tests: commands produce expected output against the live database.

These run real commands and check that output is non-empty and well-formed.
They catch silent breakage that the dispatch smoke test misses.
"""

import subprocess
import sys


def run_edge(*args) -> tuple[str, int]:
    """Run an edge command, return (stdout, returncode)."""
    result = subprocess.run(
        [sys.executable, "-m", "rhizome_alkahest.cli", *args],
        capture_output=True, text=True,
        cwd="/Users/hlarsson/repos/unity/rhizome-alkahest",
    )
    return result.stdout + result.stderr, result.returncode


class TestQueryCommands:
    def test_count_shows_phases(self):
        out, rc = run_edge("count")
        assert rc == 0
        assert "Phase summary:" in out
        assert "volatile:" in out or "fluid:" in out or "salt:" in out

    def test_find_returns_edges(self):
        out, rc = run_edge("find", "hallie")
        assert rc == 0
        # Should find at least one edge mentioning hallie
        assert "--" in out  # edge format contains --predicate-->

    def test_ls_runs(self):
        out, rc = run_edge("ls", "fluid")
        assert rc == 0

    def test_about_runs(self):
        out, rc = run_edge("about", "hallie")
        assert rc == 0

    def test_frames_runs(self):
        out, rc = run_edge("frames")
        assert rc == 0
        assert "edges" in out  # header shows edge counts

    def test_words_runs(self):
        out, rc = run_edge("words", "predicates", "--limit", "5")
        assert rc == 0
        assert "vocabulary" in out


class TestStewardshipCommands:
    def test_garden_runs(self):
        out, rc = run_edge("garden", "--limit", "3")
        assert rc == 0

    def test_gc_dry_runs(self):
        out, rc = run_edge("gc", "--dry")
        assert rc == 0
        assert "dissolve" in out or "nothing to collect" in out


class TestGrammarCommands:
    def test_say_dry_runs(self):
        out, rc = run_edge("say", "--dry", "test", "is", "working")
        assert rc == 0
        assert "grammar" in out

    def test_alias_list_runs(self):
        out, rc = run_edge("alias")
        assert rc == 0


class TestHelp:
    def test_help_runs(self):
        out, rc = run_edge("help")
        assert rc == 0
        assert "edge iam" in out
        assert "edge add" in out
        assert "edge gc" in out
