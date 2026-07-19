"""Presentation-layer data transforms for the dashboard.

Pure functions with no Streamlit and no database access: they turn the
Pydantic read-models returned by src.core into pandas DataFrames ready
to plot, and handle the weekly -> monthly aggregation.

Why this lives here and not in src.core:
- src.core is business logic that must stay pandas-free, so it remains
  reusable by a future FastAPI service (which speaks Pydantic, not
  DataFrames).
- Keeping it out of streamlit_app.py (importing that module runs the
  whole UI as a side effect) is what makes these functions unit-testable
  in isolation later (Phase 4).

The metric formulas (BMI, body-fat %, ratios) are NOT here: they live in
the SQL views. This module only reshapes and time-aggregates values that
were already computed upstream.
"""
from __future__ import annotations
import pandas as pd
from src.core.models import MassRecord, PerimeterRecord
from datetime import date as date_type

# --- Column groupings & human-readable labels -------------------------
# Split by scale so the UI never mixes centimetres with dimensionless
# ratios / percentages on the same axis. Extending the dashboard to arms
# and thighs later means adding entries here (once the view exposes them).
RAW_PERIMETER_COLS: dict[str, str] = {
    "neck_cm": "Cuello (cm)",
    "shoulder_cm": "Hombro (cm)",
    "waist_cm": "Cintura (cm)",
    "hip_cm": "Cadera (cm)",
}
DERIVED_METRIC_COLS: dict[str, str] = {
    "waist_hip_ratio": "Ratio cintura-cadera",
    "shoulder_waist_ratio": "Ratio hombro-cintura",
    "body_fat_pct": "% graso",
}
# Every numeric perimeter-side column, used when averaging monthly.
_PERIMETER_VALUE_COLS = list(RAW_PERIMETER_COLS) + list(DERIVED_METRIC_COLS)


def mass_records_to_df(records: list[MassRecord]) -> pd.DataFrame:
    """Daily mass records -> DataFrame with a datetime 'date' column.

    Columns: date (datetime64), mass_kg, bmi. Returns an empty frame with
    those columns when there are no records, so callers can rely on the
    schema and just check .empty instead of guarding against KeyErrors.
    """
    if not records:
        return pd.DataFrame(columns=["date", "mass_kg", "bmi"])

    df = pd.DataFrame([r.model_dump() for r in records])
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def perimeter_records_to_df(records: list[PerimeterRecord]) -> pd.DataFrame:
    """Weekly perimeter records -> DataFrame with a datetime week column.

    The temporal column is renamed from 'week_start_date' to a generic
    'period', so the exact same plotting code can consume either this
    weekly frame or the monthly one from aggregate_perimeters_monthly().
    """
    cols = ["period"] + _PERIMETER_VALUE_COLS
    if not records:
        return pd.DataFrame(columns=cols)

    df = pd.DataFrame([r.model_dump() for r in records])
    df = df.rename(columns={"week_start_date": "period"})
    df["period"] = pd.to_datetime(df["period"])
    return df.sort_values("period").reset_index(drop=True)


def aggregate_perimeters_monthly(weekly_df: pd.DataFrame) -> pd.DataFrame:
    """Collapse the weekly perimeter frame into one point per month.

    Each week lands in the month of its Monday ('period'), then every
    metric column is averaged. We average the already-computed weekly
    values (ratios and body-fat included) rather than recomputing them
    from averaged perimeters — see the decision log for why the numeric
    difference is negligible and not worth duplicating domain formulas.

    Expects the output of perimeter_records_to_df (a 'period' column).
    """
    if weekly_df.empty:
        return weekly_df.copy()

    monthly = (
        weekly_df
        .set_index("period")
        .resample("MS")            # MS = Month Start: buckets by calendar month
        .mean(numeric_only=True)   # skipna=True: a partial month averages what it has
        .dropna(how="all")         # drop months with zero weeks recorded
        .reset_index()
    )
    return monthly

def series_in_range(
    df: pd.DataFrame,
    value_col: str,
    date_col: str,
    start: date_type,
    end: date_type,
) -> list[float]:
    """Extract one metric's values within [start, end] as a plain list.

    The bridge between the DataFrames the dashboard already holds and
    compute_kpi, which wants a bare list[float]. Filtering here (not in the
    UI) keeps streamlit_app.py declarative and makes this slice-and-extract
    unit-testable in Phase 4 — including the empty-range case, which returns
    [] so compute_kpi can answer None without the UI branching on dates.

    Bounds are inclusive and compared as datetimes, matching the datetime64
    columns that transforms.py produces.
    """
    if df.empty or value_col not in df.columns:
        return []

    mask = (df[date_col] >= pd.Timestamp(start)) & (df[date_col] <= pd.Timestamp(end))
    return df.loc[mask, value_col].tolist()