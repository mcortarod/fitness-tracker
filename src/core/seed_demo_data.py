"""
Generate a synthetic SQLite database for demo/development purposes.

Design goals:
    * Deterministic (fixed seed 2026) — tests can rely on it.
    * Realistic-looking evolution modeled as three phases with different
      slopes: aggressive loss (Jan–Mar), moderate loss (Apr–May), plateau
      (Jun onward). Meant to look believable, not to be a physiological
      model.
    * Idempotent: running it twice produces the same database from scratch.

Usage:
    python -m src.core.seed_demo_data

Output:
    database/fitness_demo.db  (overwritten on each run)
"""

from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

# -------------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH  = PROJECT_ROOT / "database" / "schema.sql"
DB_PATH      = PROJECT_ROOT / "database" / "fitness_demo.db"

# Calendar dimension: pre-loaded, wide range that comfortably covers the
# whole project. Facts will only reference dates within this range.
CALENDAR_START = date(2025, 12, 29)
CALENDAR_END   = date(2027, 12, 31)

# Facts window: start of the year up to today.
FACTS_START = date(2026, 1, 1)

# Synthetic profile — neutral, fictional values.
PROFILE = {
    "height_cm":   175.0,
    "sex":         "M",
    "birth_date":  "1995-06-15",
}

# -------------------------------------------------------------------------
# Simulation: three-phase weight-loss trajectory.
# -------------------------------------------------------------------------
# Phase boundaries are inclusive on the start, exclusive on the end.
# Daily deltas are the AVERAGE change per day within the phase; noise is
# applied on top. Phases beyond July fall back to the "plateau" defaults.
PHASES = [
    # (start_date,       end_date,          mass_delta_per_day)
    (date(2026, 1, 1),   date(2026, 4, 1),  -0.09),  # aggressive: ~2.7 kg/mo
    (date(2026, 4, 1),   date(2026, 6, 1),  -0.05),  # moderate:   ~1.5 kg/mo
    (date(2026, 6, 1),   date(2028, 1, 1),  -0.01),  # plateau:    ~0.3 kg/mo
]

INITIAL_MASS_KG = 88.0
MASS_NOISE_KG   = 0.35   # daily gaussian noise

# Perimeters: scale roughly with mass change. Instead of modeling each
# perimeter's own phased trajectory (over-engineering), we derive them
# from the cumulative mass change relative to the initial mass, applying
# a per-perimeter sensitivity coefficient. Waist reacts strongly, neck
# barely at all — realistic pattern for body-composition changes.
INITIAL_PERIMETERS_CM = {
    "neck_cm":        41.0,
    "shoulder_cm":   122.0,
    "right_arm_cm":   35.0,
    "left_arm_cm":    35.0,
    "waist_cm":       98.0,
    "hip_cm":        104.0,
    "right_thigh_cm": 60.0,
    "left_thigh_cm":  60.0,
}
# cm change per kg of mass change. Empirical ballpark, not medical.
PERIMETER_SENSITIVITY = {
    "neck_cm":        0.05,
    "shoulder_cm":    0.10,
    "right_arm_cm":   0.15,
    "left_arm_cm":    0.15,
    "waist_cm":       0.90,
    "hip_cm":         0.50,
    "right_thigh_cm": 0.35,
    "left_thigh_cm":  0.35,
}
PERIMETER_NOISE_CM = 0.4

RANDOM_SEED = 2026


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------
def iso(d: date) -> str:
    """Format a date as ISO 8601 string ('YYYY-MM-DD')."""
    return d.isoformat()


def monday_of(d: date) -> date:
    """Return the Monday of the ISO week containing d."""
    return d - timedelta(days=d.weekday())


def daily_delta(d: date) -> float:
    """Return the phase-appropriate mass delta for a given date."""
    for start, end, delta in PHASES:
        if start <= d < end:
            return delta
    return 0.0   # dates outside any defined phase: no trend


# -------------------------------------------------------------------------
# Data generators
# -------------------------------------------------------------------------
def generate_calendar(start: date, end: date) -> list[tuple]:
    """One row per day for dim_date, inclusive of both endpoints."""
    rows = []
    current = start
    while current <= end:
        rows.append((
            iso(current),
            current.year,
            current.month,
            current.day,
            current.weekday(),                    # 0=Mon .. 6=Sun
            iso(monday_of(current)),
            current.isocalendar().week,
        ))
        current += timedelta(days=1)
    return rows


def generate_mass(start: date, end: date) -> tuple[list[tuple], dict[str, float]]:
    """
    Simulate daily mass. Returns:
        * rows for fact_mass insertion
        * dict {iso_date: cumulative_mass_change_kg} — used later to
          derive perimeters from mass change consistently.
    """
    rows = []
    cumulative_change: dict[str, float] = {}
    current_mass = INITIAL_MASS_KG
    d = start
    while d <= end:
        current_mass += daily_delta(d) + random.gauss(0, MASS_NOISE_KG)
        rows.append((iso(d), round(current_mass, 1)))
        cumulative_change[iso(d)] = current_mass - INITIAL_MASS_KG
        d += timedelta(days=1)
    return rows, cumulative_change


def generate_perimeters(
    start: date,
    end: date,
    mass_change_by_date: dict[str, float],
) -> list[tuple]:
    """
    One row per ISO week. Measurements are 'taken' on Sunday but stored
    keyed by that ISO week's Monday. `measured_on` records the Sunday.

    Perimeter values are derived from cumulative mass change with a
    per-perimeter sensitivity coefficient plus gaussian noise.
    """
    rows = []
    # First Sunday >= start. weekday()==6 is Sunday.
    first_sunday = start + timedelta(days=(6 - start.weekday()) % 7)

    sunday = first_sunday
    while sunday <= end:
        week_start = monday_of(sunday)
        mass_change = mass_change_by_date.get(iso(sunday), 0.0)

        row = [iso(week_start), iso(sunday)]
        for col, initial in INITIAL_PERIMETERS_CM.items():
            sensitivity = PERIMETER_SENSITIVITY[col]
            value = (
                initial
                + sensitivity * mass_change
                + random.gauss(0, PERIMETER_NOISE_CM)
            )
            row.append(round(value, 1))
        rows.append(tuple(row))
        sunday += timedelta(days=7)
    return rows


# -------------------------------------------------------------------------
# Main
# -------------------------------------------------------------------------
def main() -> None:
    random.seed(RANDOM_SEED)

    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    try:
        # Enforce foreign keys for this connection.
        conn.execute("PRAGMA foreign_keys = ON")

        # 1. Apply schema.
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

        # 2. Populate dim_date (wide pre-load).
        conn.executemany(
            """INSERT INTO dim_date
               (date, year, month, day, day_of_week, week_start_date, iso_week)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            generate_calendar(CALENDAR_START, CALENDAR_END),
        )

        # 3. Populate profile.
        conn.execute(
            """INSERT INTO profile (id, height_cm, sex, birth_date)
               VALUES (1, ?, ?, ?)""",
            (PROFILE["height_cm"], PROFILE["sex"], PROFILE["birth_date"]),
        )

        # 4. Facts.
        facts_end = date.today()
        mass_rows, mass_change_by_date = generate_mass(FACTS_START, facts_end)
        conn.executemany(
            "INSERT INTO fact_mass (date, mass_kg) VALUES (?, ?)",
            mass_rows,
        )
        conn.executemany(
            """INSERT INTO fact_perimeters
               (week_start_date, measured_on,
                neck_cm, shoulder_cm,
                right_arm_cm, left_arm_cm,
                waist_cm, hip_cm,
                right_thigh_cm, left_thigh_cm)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            generate_perimeters(FACTS_START, facts_end, mass_change_by_date),
        )

        conn.commit()
        print(f"Demo database created at: {DB_PATH}")
        print(f"  Calendar: {CALENDAR_START} → {CALENDAR_END}")
        print(f"  Facts:    {FACTS_START} → {facts_end}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()