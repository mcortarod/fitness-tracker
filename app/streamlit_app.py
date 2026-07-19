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
        # Load both frames ONCE, up front: the KPI block (now first) and the
        # charts below all read from them — one DB read per rerun, reused.
        # Both hold full history; the KPI block filters a range in memory.
        mass_df = mass_records_to_df(get_mass_records())
        weekly_df = perimeter_records_to_df(get_perimeter_records())

        # ---- KPIs by date range (top of the dashboard) ---------------
        st.subheader("KPIs por rango")

        # KPIs always compare RAW weekly values (weekly_df), never the monthly
        # aggregate — the range's true first-vs-last points, independent of the
        # chart granularity toggle further down.

        # Default range: full span of recorded mass, so KPIs are populated on
        # first load instead of forcing the user to pick dates.
        if not mass_df.empty:
            default_start = mass_df.iloc[0]["date"].date()
            default_end = mass_df.iloc[-1]["date"].date()
        else:
            default_start = default_end = date.today()

        col_from, col_to = st.columns(2)
        with col_from:
            kpi_start = st.date_input("Desde", value=default_start, key="kpi_start")
        with col_to:
            kpi_end = st.date_input("Hasta", value=default_end, key="kpi_end")

        # Declarative spec: (label, df, value_col, date_col, unit,
        # lower_is_better). Adding a KPI later is one line here — no new widget
        # code. `lower_is_better` drives the delta color: metrics we want to
        # shrink are True; shoulder/waist grows toward ~1.618, so it's False.
        kpi_specs = [
            ("Masa",              mass_df,   "mass_kg",              "date",   "kg", True),
            ("IMC",               mass_df,   "bmi",                  "date",   "",   True),
            ("% graso",           weekly_df, "body_fat_pct",         "period", "%",  True),
            ("Cintura",           weekly_df, "waist_cm",             "period", "cm", True),
            ("Ratio cint-cad",    weekly_df, "waist_hip_ratio",      "period", "",   True),
            ("Ratio hombro-cint", weekly_df, "shoulder_waist_ratio", "period", "",   False),
        ]

        cols = st.columns(len(kpi_specs))
        for col, (label, df, value_col, date_col, unit, lower_is_better) in zip(cols, kpi_specs):
            values = series_in_range(df, value_col, date_col, kpi_start, kpi_end)
            kpi = compute_kpi(values)
            with col:
                if kpi is None:
                    st.metric(label, "—")   # no data in range
                else:
                    st.metric(
                        label,
                        f"{kpi.end_value:.1f}{unit}",
                        delta=f"{kpi.delta_absolute:+.1f}{unit} ({kpi.delta_percent:+.1f}%)",
                        # Green = movement in the desired direction. Shrinking
                        # metrics use "inverse" (down = green); shoulder/waist
                        # grows toward its ideal, so it uses "normal".
                        delta_color="inverse" if lower_is_better else "normal",
                    )

        # ---- Mass (daily) --------------------------------------------
        # Full width now: the standalone "IMC actual" metric that used to sit
        # beside this chart is gone — IMC lives in the KPI block above.
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