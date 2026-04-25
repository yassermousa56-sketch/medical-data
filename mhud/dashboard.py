from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict

import plotly.graph_objects as go
import streamlit as st


def _parse_date(value: object) -> dt.date | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    # Expecting ISO yyyy-mm-dd from our writes
    try:
        return dt.date.fromisoformat(s[:10])
    except Exception:
        return None


def render_dashboard(records: list[dict]) -> None:
    st.subheader("Analytics Dashboard")

    if not records:
        st.info("No data yet. Submit some records first.")
        return

    normalized = []
    for r in records:
        d = _parse_date(r.get("visit_date"))
        if not d:
            continue
        normalized.append(
            {
                "visit_date": d,
                "medical_unit": str(r.get("medical_unit", "")).strip(),
                "fp_status": str(r.get("fp_status", "")).strip(),
            }
        )
    if not normalized:
        st.info("No valid-dated rows found yet.")
        return

    c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
    today = dt.date.today()
    total_all = len(normalized)
    total_today = sum(1 for r in normalized if r["visit_date"] == today)
    fp_non_use = sum(1 for r in normalized if r.get("fp_status") == "لا تستخدم")
    unit_count = len({r.get("medical_unit") for r in normalized if r.get("medical_unit")})
    c1.metric("Total Visits (All)", f"{total_all:,}")
    c2.metric("Total Visits (Today)", f"{total_today:,}")
    c3.metric("Non-use (لا تستخدم)", f"{fp_non_use:,}")
    c4.metric("Units (Distinct)", f"{unit_count:,}")

    with st.expander("Filters", expanded=True):
        min_d = min(r["visit_date"] for r in normalized)
        max_d = max(r["visit_date"] for r in normalized)
        dr = st.date_input("Date range", value=(min_d, max_d))
        unit_options = ["All"] + sorted({r["medical_unit"] for r in normalized if r["medical_unit"]})
        unit = st.selectbox("Medical Unit", unit_options, index=0)

    if isinstance(dr, tuple) and len(dr) == 2:
        start, end = dr
        filtered = [r for r in normalized if start <= r["visit_date"] <= end]
    else:
        filtered = list(normalized)
    if unit != "All":
        filtered = [r for r in filtered if r.get("medical_unit") == unit]

    st.divider()

    left, right = st.columns([1.2, 1])

    with left:
        by_day = defaultdict(int)
        for r in filtered:
            by_day[r["visit_date"]] += 1
        xs = sorted(by_day.keys())
        ys = [by_day[x] for x in xs]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines+markers", name="Visits"))
        fig.update_layout(title="Daily Visits Trend", height=360, margin=dict(l=10, r=10, t=60, b=10))
        st.plotly_chart(fig, use_container_width=True)

    with right:
        counts = Counter([r.get("fp_status") or "—" for r in filtered])
        labels = list(counts.keys())
        values = list(counts.values())
        fig2 = go.Figure(data=[go.Pie(labels=labels, values=values, hole=0.35)])
        fig2.update_layout(title="Family Planning Status", height=360, margin=dict(l=10, r=10, t=60, b=10))
        st.plotly_chart(fig2, use_container_width=True)

    unit_counts = Counter([r.get("medical_unit") or "—" for r in filtered])
    bx = list(unit_counts.keys())
    by = list(unit_counts.values())
    fig3 = go.Figure(data=[go.Bar(x=bx, y=by)])
    fig3.update_layout(title="Visits per Medical Unit", height=380, margin=dict(l=10, r=10, t=60, b=10))
    st.plotly_chart(fig3, use_container_width=True)

