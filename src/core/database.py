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

def upsert_profile(profile: Profile) -> None:
    """Insert or update the single user profile (id = 1).

    Takes a Profile model (height, sex, optional birth_date). Uses the
    same UPSERT pattern as the fact tables: the profile row always
    reflects the latest values entered, and the id = 1 CHECK constraint
    guarantees there's never more than one profile. Named parameters keep
    the mapping explicit.
    """
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO profile (id, height_cm, sex, birth_date)
            VALUES (1, :height_cm, :sex, :birth_date)
            ON CONFLICT(id) DO UPDATE SET
                height_cm  = excluded.height_cm,
                sex        = excluded.sex,
                birth_date = excluded.birth_date
            """,
            profile.model_dump(mode="json"),
        )

def get_profile() -> Profile | None:
    """Return the single user profile, or None if not set up yet.

    The profile table is constrained to exactly one row (id = 1), so we
    fetch that row directly. Returns None instead of raising when the
    profile hasn't been created, so the UI can show a "set up your
    profile" prompt on first run rather than crashing.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT height_cm, sex, birth_date FROM profile WHERE id = 1"
        ).fetchone()
    return Profile(**row) if row else None

def get_mass_records(start_date: str, end_date: str) -> list[MassRecord]:
    """Return daily mass + BMI records within [start_date, end_date].

    Reads from v_daily_metrics (not fact_mass) so BMI comes precomputed
    by the view — the app never needs raw mass without its derived
    metric. Ordered by date so the caller can treat the list as a time
    series directly (first = range start, last = latest) for both the
    chart and the KPI comparison.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT date, mass_kg, bmi
            FROM v_daily_metrics
            WHERE date BETWEEN ? AND ?
            ORDER BY date
            """,
            (start_date, end_date),
        ).fetchall()
    return [MassRecord(**row) for row in rows]

def get_perimeter_records(start_date: str, end_date: str) -> list[PerimeterRecord]:
    """Return weekly perimeter metrics within [start_date, end_date].

    Reads from v_weekly_metrics so ratios and body-fat % come precomputed.
    Filtered by week_start_date and ordered chronologically, same time-
    series contract as get_mass_records.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT week_start_date, waist_cm, hip_cm, neck_cm, shoulder_cm,
                   waist_hip_ratio, waist_shoulder_ratio, body_fat_pct
            FROM v_weekly_metrics
            WHERE week_start_date BETWEEN ? AND ?
            ORDER BY week_start_date
            """,
            (start_date, end_date),
        ).fetchall()
    return [PerimeterRecord(**row) for row in rows]