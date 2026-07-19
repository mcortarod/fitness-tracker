"""Streamlit presentation layer for the Fitness Tracker.

Thin UI on top of src/core: it collects input and renders data, but
contains no business logic or SQL. All data access goes through
src.core.database; all range calculations through src.core.metrics.
"""

import streamlit as st
from datetime import date, timedelta
from src.core.database import (
    get_profile, 
    upsert_profile, 
    upsert_mass, 
    upsert_perimeters,
    get_mass_records,
    get_perimeter_records
)
from src.core.models import Profile, PerimeterInput
from app.transforms import (
    mass_records_to_df,
    perimeter_records_to_df,
    aggregate_perimeters_monthly,
    series_in_range,
    RAW_PERIMETER_COLS,
    DERIVED_METRIC_COLS
)
from app.charts import line_chart
from src.core.metrics import compute_kpi

from typing import NamedTuple

class KpiSpec(NamedTuple):
    """Declarative config for one KPI card.

    A NamedTuple (not a plain tuple) so fields are read by name instead of
    by position — the list had grown past the point where positional access
    stays readable. Immutable on purpose: these are static config rows, not
    data that flows.

    `source` names WHICH frame to read ("mass" or "weekly") rather than
    holding the DataFrame itself: the frames are loaded per rerun, so they
    don't belong inside what is otherwise a compile-time constant. The loop
    resolves the label to the actual frame.
    """
    label: str             # KPI card title
    source: str            # "mass" | "weekly": which DataFrame to read
    value_col: str         # column holding the metric
    date_col: str          # column to filter the range on
    unit: str              # suffix shown after the value ("kg", "%", "")
    lower_is_better: bool  # True -> down is green ("inverse"); False -> "normal"
    decimals: int          # precision for value and absolute delta

# Page-level config must be the first Streamlit call in the script.
st.set_page_config(page_title="Fitness Tracker", page_icon="📊", layout="wide")

st.title("Fitness Tracker")

# The whole app assumes a profile exists (height + sex are required by the
# BMI and body-fat formulas). We fetch it once per rerun and let each tab
# decide what to do when it's missing.
profile = get_profile()

# Sidebar navigation: a single radio picks which zone renders. Unlike
# st.tabs (which builds every panel on each rerun), this only executes the
# selected branch below — so the Dashboard's DB reads don't run while
# you're on Registro. Dashboard is listed first: viewing data is the more
# frequent action than entering it.
section = st.sidebar.radio(
    "Navegación",
    options=["📊 Dashboard", "📝 Registro"],
    label_visibility="collapsed",  # the sidebar's presence is self-explanatory
)

if section == "📊 Dashboard":
    st.header("Dashboard")

    # Every view CROSS JOINs profile, so without a profile there's simply
    # no data to plot. Guard here for a clear message instead of empty charts.
    if profile is None:
        st.info("Configura tu perfil en la pestaña Registro para ver el dashboard.")
    else:
        # ---- Global date range (drives EVERYTHING below) -------------
        # This selector comes BEFORE loading data because the range is now an
        # input to the DB reads, not a post-filter. Default: Jan 1st of the
        # current year -> today. `max_value=today` forbids picking future
        # dates. Changing it re-reads both frames, already clamped in SQL.
        today = date.today()
        col_from, col_to = st.columns(2)
        with col_from:
            range_start = st.date_input(
                "Desde", value=date(today.year, 1, 1),
                max_value=today, key="range_start",
            )
        with col_to:
            range_end = st.date_input(
                "Hasta", value=today, max_value=today, key="range_end",
            )

        # Load both frames ONCE, already clamped to the range in the query
        # (Option A: filter in the DB, using the start/end params that
        # database.py has exposed since 2026-07-18). Passing ISO strings, the
        # format the SQL layer compares against. One read per frame per rerun.
        mass_df = mass_records_to_df(
            get_mass_records(range_start.isoformat(), range_end.isoformat())
        )
        weekly_df = perimeter_records_to_df(
            get_perimeter_records(range_start.isoformat(), range_end.isoformat())
        )

        # ---- KPIs (top of the dashboard) -----------------------------
        st.subheader("KPIs")

        # KPIs compare RAW weekly values (weekly_df), never the monthly
        # aggregate — the range's true first-vs-last points, independent of the
        # chart granularity toggle further down. series_in_range still applies,
        # but since the frame is already range-clamped in SQL its date filter
        # is now a no-op — it just extracts the column as list[float] for
        # compute_kpi. (Simplifying its signature is Phase 4 work: it has
        # pending tests.)
        kpi_specs = [
            KpiSpec("Masa",              "mass",   "mass_kg",              "date",   "kg", True,  1),
            KpiSpec("IMC",               "mass",   "bmi",                  "date",   "",   True,  1),
            KpiSpec("% graso",           "weekly", "body_fat_pct",         "period", "%",  True,  1),
            KpiSpec("Cintura",           "weekly", "waist_cm",             "period", "cm", True,  1),
            KpiSpec("Ratio cint-cad",    "weekly", "waist_hip_ratio",      "period", "",   True,  2),
            KpiSpec("Ratio hombro-cint", "weekly", "shoulder_waist_ratio", "period", "",   False, 2),
        ]

        # Resolve each spec's `source` label to the frame loaded up top. This
        # is why the frame isn't stored inside the spec: it's a per-rerun value.
        frames = {"mass": mass_df, "weekly": weekly_df}

        cols = st.columns(len(kpi_specs))
        for col, spec in zip(cols, kpi_specs):
            df = frames[spec.source]
            values = series_in_range(df, spec.value_col, spec.date_col, range_start, range_end)
            kpi = compute_kpi(values)
            with col:
                if kpi is None:
                    st.metric(spec.label, "—")   # no data in range
                else:
                    st.metric(
                        spec.label,
                        f"{kpi.end_value:.{spec.decimals}f}{spec.unit}",
                        delta=(
                            f"{kpi.delta_absolute:+.{spec.decimals}f}{spec.unit} "
                            f"({kpi.delta_percent:+.1f}%)"
                        ),
                        # Green = desired direction. Shrinking metrics use
                        # "inverse" (down = green); shoulder/waist grows toward
                        # its ideal, so "normal".
                        delta_color="inverse" if spec.lower_is_better else "normal",
                    )

        # ---- Mass (daily) --------------------------------------------
        st.subheader("Masa corporal")
        fig_mass = line_chart(
            mass_df, x_col="date", y_cols=["mass_kg"],
            labels={"mass_kg": "Masa (kg)"},
            y_axis_title="kg", title="Evolución de la masa (diaria)",
        )
        st.plotly_chart(fig_mass, use_container_width=True)

        # ---- Perimeters (weekly / monthly) ---------------------------
        st.subheader("Perímetros y métricas")

        # This toggle drives ONLY this section; mass stays daily by design.
        granularity = st.radio(
            "Granularidad", options=["Semanal", "Mensual"], horizontal=True,
        )

        # Single switch point: everything downstream is granularity-agnostic
        # because both frames share the 'period' column (see transforms.py).
        perim_df = (
            aggregate_perimeters_monthly(weekly_df)
            if granularity == "Mensual" else weekly_df
        )

        # Perimeters (cm): user picks which to overlay — they share a scale.
        selected = st.multiselect(
            "Perímetros (cm)",
            options=list(RAW_PERIMETER_COLS),
            default=["waist_cm", "hip_cm"],           # headline measurements
            format_func=lambda c: RAW_PERIMETER_COLS[c],
        )
        st.plotly_chart(
            line_chart(
                perim_df, x_col="period", y_cols=selected,
                labels=RAW_PERIMETER_COLS, y_axis_title="cm",
                title=f"Perímetros ({granularity.lower()})",
            ),
            use_container_width=True,
        )

        # Ratios: own chart — a ~0.8 scale would be crushed beside cm.
        st.plotly_chart(
            line_chart(
                perim_df, x_col="period",
                y_cols=["waist_hip_ratio", "shoulder_waist_ratio"],
                labels=DERIVED_METRIC_COLS, y_axis_title="ratio",
                title=f"Ratios ({granularity.lower()})",
            ),
            use_container_width=True,
        )

        # Body fat: own chart again — ~20% differs from the ratios' scale.
        st.plotly_chart(
            line_chart(
                perim_df, x_col="period", y_cols=["body_fat_pct"],
                labels=DERIVED_METRIC_COLS, y_axis_title="%",
                title=f"% graso ({granularity.lower()})",
            ),
            use_container_width=True,
        )

elif section == "📝 Registro":
    st.header("Registro de datos")

    # Internal tabs, ordered by how often each is used: Masa (daily) first
    # so it's the panel you land on, then Perímetros (weekly), then Perfil
    # (set once). Note: st.tabs always opens the FIRST tab — ordering is the
    # only way to control the default landing tab (see decision log).
    tab_mass, tab_perimeters, tab_profile = st.tabs(
        ["⚖️ Masa", "📏 Perímetros", "👤 Perfil"]
    )
    # --- Profile form -------------------------------------------------
    # Shown first because height + sex are prerequisites for BMI and
    # body-fat calculations. Pre-fills with current values if a profile
    # already exists, so this doubles as "edit profile".
    # --- Mass tab: daily body mass ------------------------------------
    with tab_mass:
        st.subheader("Masa corporal (diaria)")
        with st.form("mass_form"):
            mass_date = st.date_input("Fecha", value="today")
            mass_kg = st.number_input(
                "Masa (kg)", min_value=20.0, max_value=300.0, value=70.0, step=0.1,
            )
            submitted_mass = st.form_submit_button("Guardar masa")

        if submitted_mass:
            upsert_mass(mass_date.isoformat(), mass_kg)
            st.success(f"Masa registrada para {mass_date.isoformat()}.")

    # --- Perimeters tab: weekly measurements --------------------------
    with tab_perimeters:
        st.subheader("Perímetros (semanal)")
        with st.form("perimeters_form"):
            measured_on = st.date_input("Fecha de medición", value="today")
            col1, col2 = st.columns(2)
            with col1:
                neck_cm = st.number_input("Cuello (cm)", min_value=0.0, step=0.1)
                shoulder_cm = st.number_input("Hombro (cm)", min_value=0.0, step=0.1)
                right_arm_cm = st.number_input("Brazo derecho (cm)", min_value=0.0, step=0.1)
                left_arm_cm = st.number_input("Brazo izquierdo (cm)", min_value=0.0, step=0.1)
            with col2:
                waist_cm = st.number_input("Cintura (cm)", min_value=0.0, step=0.1)
                hip_cm = st.number_input("Cadera (cm)", min_value=0.0, step=0.1)
                right_thigh_cm = st.number_input("Muslo derecho (cm)", min_value=0.0, step=0.1)
                left_thigh_cm = st.number_input("Muslo izquierdo (cm)", min_value=0.0, step=0.1)
            submitted_perimeters = st.form_submit_button("Guardar perímetros")

        if submitted_perimeters:
            # Derive the ISO week's Monday from the measurement date.
            # weekday() returns 0=Monday..6=Sunday, so subtracting it lands on
            # that week's Monday regardless of which day the measurement was taken.
            week_start = measured_on - timedelta(days=measured_on.weekday())

            upsert_perimeters(PerimeterInput(
                week_start_date=week_start,
                measured_on=measured_on,
                neck_cm=neck_cm, shoulder_cm=shoulder_cm,
                right_arm_cm=right_arm_cm, left_arm_cm=left_arm_cm,
                waist_cm=waist_cm, hip_cm=hip_cm,
                right_thigh_cm=right_thigh_cm, left_thigh_cm=left_thigh_cm,
            ))
            st.success(f"Perímetros registrados (semana del {week_start.isoformat()}).")

    # --- Profile tab: height + sex (BMI/body-fat prerequisites) --------
    with tab_profile:
        st.subheader("Perfil")
        with st.form("profile_form"):
            height_cm = st.number_input(
                "Altura (cm)", min_value=100.0, max_value=250.0,
                value=profile.height_cm if profile else 170.0, step=0.5,
            )
            sex = st.selectbox(
                "Sexo", options=["M", "F"],
                index=0 if (profile is None or profile.sex == "M") else 1,
            )
            submitted_profile = st.form_submit_button("Guardar perfil")

        if submitted_profile:
            upsert_profile(Profile(height_cm=height_cm, sex=sex))
            st.success("Perfil guardado.")
            st.rerun()  # re-read the profile so the rest of the app sees it