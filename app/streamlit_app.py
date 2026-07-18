"""Streamlit presentation layer for the Fitness Tracker.

Thin UI on top of src/core: it collects input and renders data, but
contains no business logic or SQL. All data access goes through
src.core.database; all range calculations through src.core.metrics.
"""

import streamlit as st
from datetime import timedelta
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
    RAW_PERIMETER_COLS,
    DERIVED_METRIC_COLS
)
from app.charts import line_chart

# Page-level config must be the first Streamlit call in the script.
st.set_page_config(page_title="Fitness Tracker", page_icon="📊", layout="wide")

st.title("Fitness Tracker")

# The whole app assumes a profile exists (height + sex are required by the
# BMI and body-fat formulas). We fetch it once per rerun and let each tab
# decide what to do when it's missing.
profile = get_profile()

# Two clear zones for a two-purpose app: record data vs. view it.
tab_record, tab_dashboard = st.tabs(["📝 Registro", "📊 Dashboard"])

with tab_record:
    st.header("Registro de datos")
    # --- Profile form -------------------------------------------------
    # Shown first because height + sex are prerequisites for BMI and
    # body-fat calculations. Pre-fills with current values if a profile
    # already exists, so this doubles as "edit profile".
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

    # --- Daily mass form ----------------------------------------------
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

    # --- Weekly perimeters form ---------------------------------------
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

with tab_dashboard:
    st.header("Dashboard")

    # Every view CROSS JOINs profile, so without a profile there's simply
    # no data to plot. Guard here for a clear message instead of empty charts.
    if profile is None:
        st.info("Configura tu perfil en la pestaña Registro para ver el dashboard.")
    else:
        # ---- Mass (daily) --------------------------------------------
        st.subheader("Masa corporal")
        mass_df = mass_records_to_df(get_mass_records())  # no range = full history

        col_chart, col_kpi = st.columns([3, 1])
        with col_chart:
            fig_mass = line_chart(
                mass_df, x_col="date", y_cols=["mass_kg"],
                labels={"mass_kg": "Masa (kg)"},
                y_axis_title="kg", title="Evolución de la masa (diaria)",
            )
            st.plotly_chart(fig_mass, use_container_width=True)
        with col_kpi:
            # BMI as a value, not a line: with constant height its curve is
            # identical in shape to mass. The latest number is the signal.
            if not mass_df.empty:
                st.metric("IMC actual", f"{mass_df.iloc[-1]['bmi']:.1f}")

        # ---- Perimeters (weekly / monthly) ---------------------------
        st.subheader("Perímetros y métricas")

        # This toggle drives ONLY this section; mass stays daily by design.
        granularity = st.radio(
            "Granularidad", options=["Semanal", "Mensual"], horizontal=True,
        )

        weekly_df = perimeter_records_to_df(get_perimeter_records())
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
                y_cols=["waist_hip_ratio", "waist_shoulder_ratio"],
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