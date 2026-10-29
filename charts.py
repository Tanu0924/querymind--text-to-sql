"""Chart rendering helpers (Plotly)."""
from typing import Any, Dict, Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from .nl2sql import format_inr, is_money_col

PALETTE = ["#2563eb", "#0ea5e9", "#14b8a6", "#f59e0b", "#ef4444", "#8b5cf6", "#64748b"]


def build_figure(df: pd.DataFrame, chart: Dict[str, Any]) -> Optional[go.Figure]:
    """Return a Plotly figure for line/bar/pie charts, or None for table/metric."""
    ctype, x, y = chart.get("type"), chart.get("x"), chart.get("y")
    title = chart.get("title") or ""
    if ctype not in ("line", "bar", "pie") or x not in df.columns or y not in df.columns or df.empty:
        return None
    if ctype == "line":
        fig = px.line(df, x=x, y=y, markers=True, title=title, color_discrete_sequence=PALETTE)
    elif ctype == "bar":
        fig = px.bar(df, x=x, y=y, title=title, color_discrete_sequence=PALETTE)
    else:
        fig = px.pie(df, names=x, values=y, title=title, hole=0.4, color_discrete_sequence=PALETTE)
    if is_money_col(y) and ctype != "pie":
        fig.update_yaxes(tickprefix="₹")
    fig.update_layout(margin=dict(l=10, r=10, t=50, b=10), height=380,
                      font=dict(family="Inter, sans-serif"), legend_title_text="")
    return fig


def metric_display(df: pd.DataFrame, chart: Dict[str, Any]):
    """(label, formatted value) for a single-value result."""
    col = chart.get("y") or df.columns[0]
    val = df.iloc[0][col] if col in df.columns else df.iloc[0, 0]
    if isinstance(val, (int, float)) and is_money_col(col):
        return col.replace("_", " ").title(), format_inr(val)
    if isinstance(val, float):
        return col.replace("_", " ").title(), f"{val:,.2f}"
    return col.replace("_", " ").title(), str(val)
