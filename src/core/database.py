"""Data access layer for the Fitness Tracker app.

Encapsulates all SQLite access behind small, typed functions.
Nothing outside this module should import sqlite3 directly.
"""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from src.core.models import Profile, MassRecord, PerimeterRecord, PerimeterInput

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

def upsert_mass(record_date: str, mass_kg: float) -> None:
    """Insert or overwrite the mass record for a given day.

    Uses UPSERT (INSERT ... ON CONFLICT) so re-recording the same day
    updates the value instead of failing on the primary key. This matches
    real usage of a personal tracker: the record for a day should always
    reflect the last value you entered (bitacora decision, this session).
    """
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO fact_mass (date, mass_kg)
            VALUES (?, ?)
            ON CONFLICT(date) DO UPDATE SET mass_kg = excluded.mass_kg
            """,
            (record_date, mass_kg),
        )

def upsert_perimeters(record: PerimeterInput) -> None:
    """Insert or overwrite the perimeters record for a given ISO week.

    Same UPSERT rationale as upsert_mass: re-recording a week updates the
    row instead of failing on the primary key (week_start_date). Takes a
    PerimeterInput so callers pass values by name, not by a fragile
    positional list of eight same-typed floats.
    """
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO fact_perimeters (
                week_start_date, measured_on,
                neck_cm, shoulder_cm, right_arm_cm, left_arm_cm,
                waist_cm, hip_cm, right_thigh_cm, left_thigh_cm
            )
            VALUES (:week_start_date, :measured_on,
                    :neck_cm, :shoulder_cm, :right_arm_cm, :left_arm_cm,
                    :waist_cm, :hip_cm, :right_thigh_cm, :left_thigh_cm)
            ON CONFLICT(week_start_date) DO UPDATE SET
                measured_on    = excluded.measured_on,
                neck_cm        = excluded.neck_cm,
                shoulder_cm    = excluded.shoulder_cm,
                right_arm_cm   = excluded.right_arm_cm,
                left_arm_cm    = excluded.left_arm_cm,
                waist_cm       = excluded.waist_cm,
                hip_cm         = excluded.hip_cm,
                right_thigh_cm = excluded.right_thigh_cm,
                left_thigh_cm  = excluded.left_thigh_cm
            """,
            record.model_dump(mode="json"),
        )