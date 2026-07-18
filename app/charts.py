"""Plotly figure builders for the dashboard.

Pure functions: DataFrame in, Plotly Figure out. No Streamlit, no data
access, no metric math — they only *draw* frames that transforms.py has
already shaped. Keeping figure-building separate from both the data
transforms and the Streamlit wiring means each concern stays testable on
its own: you can assert on a Figure's traces without spinning up the UI.
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


def _empty_figure(message: str) -> go.Figure:
    """A blank figure carrying a centered message.

    Shown when there's nothing to plot yet, so the dashboard renders an
    explicit 'no data' state instead of an axis-less empty box. Mirrors
    the empty-frame contract in transforms.py: callers never have to
    special-case emptiness before handing data to a chart.
    """
    fig = go.Figure()
    fig.add_annotation(
        text=message, showarrow=False,
        xref="paper", yref="paper", x=0.5, y=0.5,
        font=dict(size=14, color="gray"),
    )
    fig.update_layout(xaxis=dict(visible=False), yaxis=dict(visible=False))
    return fig


def line_chart(
    df: pd.DataFrame,
    x_col: str,
    y_cols: list[str],
    labels: dict[str, str],
    y_axis_title: str,
    title: str,
) -> go.Figure:
    """Build a multi-series line chart from selected columns of a wide df.

    `df` is 'wide' (one column per metric, as transforms.py produces). The
    melt to long form happens *here*, inside the chart layer, because that
    reshape exists solely to satisfy Plotly Express's 'one row per point +
    a color column' model — callers shouldn't have to know about it.

    All series share ONE y-axis on purpose: this builder is scale-agnostic
    and trusts the caller to pass columns on a comparable scale (e.g. all
    centimetres). Mixing units (a 90 cm waist with a 0.8 ratio) would
    flatten the smaller series — that grouping decision belongs to the UI.

    `labels` maps raw column names -> human-readable text, applied to the
    legend and hover, so the chart reads in Spanish without hard-coding any
    label inside this generic builder.
    """
    if df.empty or not y_cols:
        return _empty_figure("Aún no hay datos para mostrar")

    # Wide -> long: one row per (x, metric, value). 'variable'/'value' are
    # melt's defaults; we rename them and map metric names through `labels`.
    long_df = df.melt(
        id_vars=[x_col], value_vars=y_cols,
        var_name="metric", value_name="value",
    )
    long_df["metric"] = long_df["metric"].map(labels).fillna(long_df["metric"])

    fig = px.line(
        long_df, x=x_col, y="value", color="metric",
        markers=True,  # weekly/monthly series are sparse; markers make the
                       # individual data points visible, not just the line
    )
    fig.update_layout(
        title=title,
        xaxis_title=None,        # dates are self-explanatory on the axis
        yaxis_title=y_axis_title,
        legend_title_text="",
        hovermode="x unified",   # single hover box listing every series at
                                 # a given date — ideal for comparing metrics
    )
    return fig