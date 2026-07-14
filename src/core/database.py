"""Data access layer for the Fitness Tracker app.

Encapsulates all SQLite access behind small, typed functions.
Nothing outside this module should import sqlite3 directly.
"""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

# DATABASE_PATH is read from the environment so that switching between
# synthetic and real data is a matter of configuration, not code changes
# Falls back to the demo DB so the app works out of the box for anyone 
# cloning the repo.
DEFAULT_BD_PATH = Path(__file__).resolve().parents[2] / "database" / "fitness_demo.db"
DATABASE_PATH = os.environ.get("DATABASE_PATH", str(DEFAULT_BD_PATH))

@contextmanager
def get_connection():
    """Yield a configured SQLite connection, closing it afterwards.

    Centralizes two things every caller needs but shouldn't repeat:
    - PRAGMA foreign_keys, since SQLite ignores FKs by default and this
      is a per-connection setting 
    - row_factory = sqlite3.Row, so query results behave like dicts
      (row["mass_kg"]) instead of positional tuples, which is what lets
      us build Pydantic models from them cleanly in the next step.
    """
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()