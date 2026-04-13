"""Tests for .edgeignore loading and SQL generation."""

import os
import tempfile

from rhizome_alkahest.cli_helpers import load_edgeignore, edgeignore_sql


def test_edgeignore_sql_empty():
    clause, params = edgeignore_sql([])
    assert clause == ""
    assert params == []


def test_edgeignore_sql_single_prefix():
    clause, params = edgeignore_sql(["go9:"])
    assert clause == "e.subject NOT LIKE %s"
    assert params == ["go9:%"]


def test_edgeignore_sql_multiple_prefixes():
    clause, params = edgeignore_sql(["go9:", "connect5:"])
    assert "AND" in clause
    assert len(params) == 2
    assert params[0] == "go9:%"
    assert params[1] == "connect5:%"


def test_edgeignore_sql_custom_column():
    clause, params = edgeignore_sql(["go9:"], column="subject")
    assert "subject NOT LIKE" in clause


def test_load_edgeignore_from_repo():
    """load_edgeignore finds the .edgeignore at repo root."""
    prefixes = load_edgeignore()
    assert "go9:" in prefixes
    assert "connect5:" in prefixes
