"""Streamlit dashboard: course progress KPIs, completion chart, and a Q&A box for the Data Analyst Agent."""

import plotly.express as px
import streamlit as st

import db
from agent import DataAnalystAgent

st.set_page_config(page_title="Course Progress Analyst", layout="wide")
st.title("Course Progress & Completion")


# Cache dashboard queries for 10 minutes so the page doesn't hit the database on every rerun.
@st.cache_data(ttl=600)
def load_kpis():
    return db.get_kpis()


@st.cache_data(ttl=600)
def load_by_course():
    return db.completion_by_course(min_enrollments=100, top_n=15)


@st.cache_data(ttl=600)
def load_by_domain():
    return db.completion_by_domain(min_enrollments=100, top_n=15)


@st.cache_data(ttl=600)
def load_funnel():
    return db.funnel()


@st.cache_resource
def get_agent():
    return DataAnalystAgent()


# --- KPIs ---
kpis = load_kpis()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total enrollments", f"{int(kpis['total_enrollments']):,}")
c2.metric("Average progress", f"{kpis['avg_progress']:.1f}%")
c3.metric("Completed enrollments", f"{int(kpis['completed']):,}")
c4.metric("Completion rate", f"{kpis['completion_rate']:.1f}%")
st.caption("Completed = certified (is_certified = 1). Progress is capped at 100%.")

# --- Charts ---
left, right = st.columns([2, 1])

with left:
    st.subheader("Completion rate")
    tab_course, tab_domain = st.tabs(["By course", "By domain"])
    for tab, df, label in [
        (tab_course, load_by_course(), "course"),
        (tab_domain, load_by_domain(), "domain"),
    ]:
        with tab:
            fig = px.bar(
                df.sort_values("completion_rate"),
                x="completion_rate",
                y=label,
                orientation="h",
                hover_data=["enrollments", "completed"],
                labels={"completion_rate": "Completion rate, %", label: ""},
            )
            fig.update_layout(height=500, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig, width="stretch")
            st.caption(f"Top 15 by completion rate, only {label}s with at least 100 enrollments.")

with right:
    st.subheader("Learning funnel")
    f = load_funnel()
    # funnel_state is the furthest stage reached, so "reached stage X" = this stage + all later stages.
    f["reached"] = f["enrollments"][::-1].cumsum()[::-1]
    fig = px.funnel(f, x="reached", y="funnel_state", labels={"funnel_state": "", "reached": "Enrollments"})
    fig.update_layout(height=500, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, width="stretch")

# --- Agent ---
st.divider()
st.subheader("Ask the Data Analyst Agent")
with st.form("ask"):
    question = st.text_input(
        "Your question",
        placeholder="e.g. Which course level has the highest completion rate?",
    )
    submitted = st.form_submit_button("Ask")

if submitted and question.strip():
    try:
        agent = get_agent()
        with st.spinner("Analyzing..."):
            result = agent.ask(question.strip())
        st.markdown(result["answer"])
        if result["queries"]:
            with st.expander(f"SQL executed ({len(result['queries'])})"):
                for q in result["queries"]:
                    st.code(q, language="sql")
    except Exception as exc:
        st.error(f"Agent error: {exc}")
