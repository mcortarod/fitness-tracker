"""Pydantic models for entities read from the database.

These describe the *shape* of data as consumed by the business/
presentation layers (metrics.py, streamlit_app.py). They are decoupled
from database.py on purpose: metrics.py should be able to depend on
"what a MassRecord looks like" without depending on "how we talk to
SQLite" — that separation is also what keeps this file directly
reusable if the project ever migrates to a FastAPI backend, where
Pydantic models play the same role.
"""
from datetime import date as date_type
from pydantic import BaseModel

class Profile(BaseModel):
    """Mirrors the 'profile' table (single-row user profile)."""
    height_cm: float
    sex: str # 'M' or 'F', enforced by the schema's CHECK constraint
    birth_date: date_type | None = None

class MassRecord(BaseModel):
    """Mirrors 'v_daily_metrics': one row per day with mass + BMI."""
    date: date_type
    mass_kg: float
    bmi: float

class PerimeterRecord(BaseModel):
    """Mirrors 'v_weekly_metrics': one row per ISO week."""
    week_start_date: date_type
    waist_cm: float
    hip_cm: float
    neck_cm: float
    shoulder_cm: float
    waist_hip_ratio: float
    waist_shoulder_ratio: float
    body_fat_pct: float

class PerimeterInput(BaseModel):
    """Input schema for writing a weekly perimeters record.

    Distinct from PerimeterRecord (read model): this one carries the raw
    measurements we INSERT, while PerimeterRecord carries the computed
    ratios and body-fat % that the views return on read. Keeping write
    and read schemas separate is the standard FastAPI pattern (Create vs
    Read), and it's what makes upsert_perimeters callable by field name
    instead of by a fragile 8-argument positional list.
    """
    week_start_date: date_type
    measured_on: date_type | None = None
    neck_cm: float
    shoulder_cm: float
    right_arm_cm: float
    left_arm_cm: float
    waist_cm: float
    hip_cm: float
    right_thigh_cm: float
    left_thigh_cm: float

class KpiResult(BaseModel):
    """Result of comparing the first vs. last value of a selected range.

    Purely numeric and metric-agnostic: it reports what changed, not
    whether that change is 'good'. Interpreting direction (is a drop
    desirable?) is a presentation concern, kept out of the calculation
    so this stays reusable across every metric.
    """
    start_value: float      # first value in the range
    end_value: float        # latest value in the range
    delta_absolute: float   # end - start
    delta_percent: float    # (end - start) / start * 100