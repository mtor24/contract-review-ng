"""Dashboard: KPIs, upcoming deadlines, risk mix and recent activity."""

from datetime import date, datetime, timezone

import altair as alt
import pandas as pd
import streamlit as st

from core.missing import contract_types

from storage import models
from ui.components import empty_state, fmt_date, institution_band, md_escape, page_header
from ui.state import get_conn, load_samples

institution_band()

if page_header(
    "Dashboard",
    "Your contracts, open risks and upcoming deadlines at a glance.",
    "Review a contract",
    ":material/add:",
):
    st.switch_page("ui/pages/review.py")

conn = get_conn()
today = date.today()

if models.dashboard_counts(conn, today)["contracts"] == 0:
    empty_state("No contracts yet. Upload your first contract to begin.")
    if st.button("Load the 7 sample contracts", icon=":material/download:"):
        n = load_samples(conn)
        st.toast(f"Loaded {n} sample contracts", icon=":material/check:")
        st.rerun()
    st.stop()

counts = models.dashboard_counts(conn, today)
cols = st.columns(4)
with cols[0]:
    st.metric("Contracts stored", counts["contracts"], border=True)
with cols[1]:
    st.metric("Under review", counts["under_review"], border=True)
with cols[2]:
    st.metric("High-risk flags open", counts["open_high"], border=True)
with cols[3]:
    st.metric("Deadlines in next 30 days", counts["deadlines_30"], border=True)

left, right = st.columns(2)

with left:
    st.subheader("Upcoming deadlines")
    upcoming = models.upcoming_obligations(conn, today, 30)
    if not upcoming:
        empty_state("No deadlines in the next 30 days.")
    for ob in upcoming:
        due = date.fromisoformat(ob["due_date"])
        days = (due - today).days
        when = "today" if days == 0 else ("tomorrow" if days == 1 else f"in {days} days")
        with st.container(border=True):
            st.markdown(
                f"**{fmt_date(due)}** - {md_escape(ob['contract_title'])}"
                + (f" ({md_escape(ob['period_text'])})" if ob.get("period_text") else "")
            )
            st.caption(f"{md_escape(ob['party'])} - due {when}")

with right:
    st.subheader("Risks by contract type")
    rows = models.risk_by_type(conn)
    if not rows:
        empty_state("No open risk findings.")
    else:
        frame = pd.DataFrame(rows)
        # Show "Lease / Tenancy Agreement" rather than the internal id "lease".
        frame["type"] = frame["type"].map(contract_types()).fillna(frame["type"])
        chart = (
            alt.Chart(frame)
            .mark_bar()
            .encode(
                x=alt.X("count:Q", title=None, axis=alt.Axis(grid=False, tickMinStep=1)),
                y=alt.Y("type:N", title=None, sort="-x", axis=alt.Axis(grid=False)),
                # Colour and legend labels always travel together.
                color=alt.Color(
                    "severity:N",
                    title="Severity",
                    scale=alt.Scale(
                        domain=["High", "Medium", "Low"],
                        range=["#C0392B", "#D68910", "#2E86C1"],
                    ),
                ),
            )
            .properties(height=260)
        )
        st.altair_chart(chart, width="stretch", theme=None)

st.subheader("Recent activity")
activity = models.recent_activity(conn, limit=8)
if not activity:
    empty_state("Nothing has happened yet.")
for entry in activity:
    ts = datetime.fromisoformat(entry["ts"])
    delta = datetime.now(timezone.utc) - ts
    minutes = int(delta.total_seconds() // 60)
    if minutes < 1:
        ago = "just now"
    elif minutes < 60:
        ago = f"{minutes} min ago"
    elif minutes < 60 * 24:
        ago = f"{minutes // 60} h ago"
    else:
        ago = f"{minutes // (60 * 24)} d ago"
    title = entry["contract_title"] or "a deleted contract"
    st.caption(f"{ago} - {md_escape(entry['action'])} - {md_escape(title)}")
