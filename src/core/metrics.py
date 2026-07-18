"""Business calculations that operate on series of records.

Per-row formulas (BMI, body-fat %, ratios) live in SQL views, so this
module deliberately does NOT recompute them. It only holds logic a view
can't express naturally: operations over a user-selected range of rows,
like KPI deltas.
"""
from src.core.models import KpiResult

def compute_kpi(values: list[float]) -> KpiResult | None:
    """Compare the first and last value of an ordered series.

    Expects `values` already sorted chronologically (as returned by the
    database layer). Returns None if the series is empty, so the UI can
    show a 'no data' state instead of crashing. With a single data point,
    start and end coincide and deltas are zero — a valid, meaningful state
    (you have a reading but no change yet).
    """
    if not values:
        return None

    start_value = values[0]
    end_value = values[-1]
    delta_absolute = end_value - start_value

    # Guard against division by zero: if the starting value is 0 (not
    # expected for body metrics, but defensive), report percent as 0
    # rather than raising.
    delta_percent = (delta_absolute / start_value * 100) if start_value else 0.0

    return KpiResult(
        start_value=start_value,
        end_value=end_value,
        delta_absolute=delta_absolute,
        delta_percent=delta_percent,
    )