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