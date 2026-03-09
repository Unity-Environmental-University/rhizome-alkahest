"""Database connection. One function. That's it."""

import psycopg

DB_NAME = "rhizome-alkahest"


def connect(dbname: str = DB_NAME) -> psycopg.Connection:
    """Return a connection to the rhizome-alkahest database."""
    return psycopg.connect(f"dbname={dbname}")
