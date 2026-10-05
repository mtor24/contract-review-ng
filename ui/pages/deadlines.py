"""Deadlines: timeline and month-grouped list of obligations with due dates."""

from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from storage import models
from ui.components import empty_state, fmt_date, md_escape, page_header
from ui.state import get_conn

page_header(
    "Deadlines",
    "Obligations with a calculated due date, from the latest version of each contract.",
)

conn = get_conn()
today = date.today()

WINDOW_DAYS = {"30 days": 30, "60 days": 60, "90 days": 90}

pick = st.columns([0.4, 0.6])
with pick[0]:
    window = st.segmented_control(
        "Show the next", list(WINDOW_DAYS.keys()), default="30 days"
    )
with pick[1]:
    include_overdue = st.checkbox("Include overdue")

days = WINDOW_DAYS[window or "30 days"]
items = models.upcoming_obligations(conn, today, days)

if include_overdue:
    # The model only looks forward, so look back far enough (ten years) to catch
    # every overdue obligation, not just the last month's.
    past = models.upcoming_obligations(conn, today - timedelta(days=3650), 3650)
    overdue = [o for o in past if o["due_date"] < today.isoformat()]
    seen = {o["id"] for o in items}
    items = [o for o in overdue if o["id"] not in seen] + items

if not items:
    empty_state(
        "No deadlines in this window.",
        "Dates are calculated only where the contract gives an anchor date.",
    )
    st.stop()


def _urgency(due: date) -> str:
    delta = (due - today).days
    if delta < 0:
        return "Overdue"
    if delta <= 7:
        return "Within 7 days"
    if delta <= 30:
        return "Within 30 days"
    return "Later"


def _excerpt(text: str, limit: int = 120) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + " ..."


frame = pd.DataFrame(
    {
        "due": [date.fromisoformat(o["due_date"]) for o in items],
        "contract": [o["contract_title"] for o in items],
        "party": [o["party"] for o in items],
        "period": [o.get("period_text") or "" for o in items],
        "excerpt": [_excerpt(o["text"]) for o in items],
        "urgency": [_urgency(date.fromisoformat(o["due_date"])) for o in items],
    }
)
# Sort y by each contract's earliest due date so the soonest sits at the top.
first_due = frame.groupby("contract")["due"].min().sort_values()
order = first_due.index.tolist()

URGENCY_COLORS = {
    "Overdue": "#C0392B",
    "Within 7 days": "#C0392B",
    "Within 30 days": "#D68910",
    "Later": "#1E2A44",
}

points = (
    alt.Chart(frame)
    .mark_point(filled=True, size=90)
    .encode(
        x=alt.X("due:T", title=None, axis=alt.Axis(format="%d %b")),
        y=alt.Y("contract:N", title=None, sort=order),
        color=alt.Color(
            "urgency:N",
            title="Due",
            scale=alt.Scale(
                domain=list(URGENCY_COLORS.keys()),
                range=list(URGENCY_COLORS.values()),
            ),
            legend=alt.Legend(labelColor="#1F2937"),
        ),
        tooltip=[
            alt.Tooltip("contract:N", title="Contract"),
            alt.Tooltip("party:N", title="Party"),
            alt.Tooltip("excerpt:N", title="Obligation"),
            alt.Tooltip("period:N", title="Period"),
            alt.Tooltip("due:T", title="Due", format="%d %b %Y"),
        ],
    )
)
today_rule = (
    alt.Chart(pd.DataFrame({"today": [today]}))
    .mark_rule(color="#B8963E", strokeWidth=2)
    .encode(x="today:T")
)
chart = (
    alt.layer(points, today_rule)
    .properties(height=max(160, 34 * len(order)))
)
st.altair_chart(chart, width="stretch", theme=None)

# List grouped by calendar month.
by_month: dict[str, list[dict]] = {}
for ob in items:
    key = date.fromisoformat(ob["due_date"]).strftime("%B %Y")
    by_month.setdefault(key, []).append(ob)

for month in sorted(by_month, key=lambda m: date.fromisoformat(by_month[m][0]["due_date"])):
    st.subheader(month)
    for ob in by_month[month]:
        due = date.fromisoformat(ob["due_date"])
        delta = (due - today).days
        with st.container(border=True):
            top = st.columns([0.7, 0.3], vertical_alignment="center")
            with top[0]:
                st.markdown(
                    f"**{fmt_date(due)}** - {md_escape(ob['contract_title'])}"
                    + (f" ({md_escape(ob['period_text'])})" if ob.get("period_text") else "")
                )
                st.caption(f"{md_escape(ob['party'])} - {md_escape(_excerpt(ob['text']))}")
            with top[1]:
                if delta < 0:
                    st.badge("Overdue", icon=":material/error:", color="red")
                else:
                    when = "today" if delta == 0 else ("tomorrow" if delta == 1 else f"in {delta} days")
                    st.badge(when, icon=":material/event:", color="orange" if delta <= 7 else "blue")
                if st.button(
                    "Open contract",
                    key=f"dl-{ob['id']}",
                    type="tertiary",
                    icon=":material/folder_open:",
                ):
                    st.switch_page(
                        "ui/pages/register.py", query_params={"contract": ob["contract_id"]}
                    )
