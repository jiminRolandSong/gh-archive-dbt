import os
import sys
import streamlit as st
import snowflake.connector
import pandas as pd
import plotly.express as px
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="GH Archive Analytics",
    page_icon="📊",
    layout="wide",
)

# ── Snowflake connection ──────────────────────────────────────────

def get_connection():
    return snowflake.connector.connect(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        password=os.getenv("SNOWFLAKE_PASSWORD"),
        database=os.getenv("SNOWFLAKE_DATABASE", "GH_ARCHIVE"),
        schema=os.getenv("SNOWFLAKE_SCHEMA", "dbt_jimin_dev"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
        role=os.getenv("SNOWFLAKE_ROLE", "TRANSFORMER"),
    )

@st.cache_data(ttl=300)
def run_query(sql: str) -> pd.DataFrame:
    try:
        conn = get_connection()
        df = pd.read_sql(sql, conn)
        conn.close()
        return df
    except Exception as e:
        st.error(f"Snowflake connection failed: {e}")
        return pd.DataFrame()

# ── Sidebar ───────────────────────────────────────────────────────

with st.sidebar:
    st.title("GH Archive Analytics")
    st.divider()

    last_updated_df = run_query(
        "SELECT MAX(created_at) AS last_updated FROM dbt_jimin_dev.stg_gh_events"
    )
    if not last_updated_df.empty and last_updated_df["LAST_UPDATED"].iloc[0]:
        st.caption("Last updated")
        st.write(str(last_updated_df["LAST_UPDATED"].iloc[0])[:19] + " UTC")
    else:
        st.caption("Last updated: —")

    st.divider()
    st.caption("Snowflake · dbt · Streamlit")

# ── Tabs ──────────────────────────────────────────────────────────

tab_insights, tab_trending, tab_activity, tab_labels, tab_pipeline = st.tabs([
    "Daily Insights",
    "Trending Repos",
    "Activity Trends",
    "PR Label Usage",
    "Pipeline",
])

# ── Tab 1: Daily Insights ─────────────────────────────────────────

with tab_insights:
    st.header("Daily Insights")

    insight_df = run_query("""
        SELECT insight_text, generated_at, model_used
        FROM dbt_jimin_dev.mart_daily_insights
        ORDER BY generated_at DESC
        LIMIT 1
    """)

    if not insight_df.empty:
        row = insight_df.iloc[0]
        col1, col2 = st.columns([3, 1])
        with col2:
            st.metric("Model", row.get("MODEL_USED", "—"))
            generated = str(row.get("GENERATED_AT", "—"))[:19]
            st.metric("Generated at", generated)
        with col1:
            st.markdown(row.get("INSIGHT_TEXT", ""))
    else:
        st.info("No insights generated yet. Click the button below to create the first one.")

    st.divider()

    if st.button("Generate New Insight", type="primary"):
        progress = st.progress(0, text="Initializing...")
        status = st.empty()

        try:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "insights"))
            import insights_generator as ig

            progress.progress(10, text="Connecting to Snowflake...")
            status.caption("Step 1 / 4 — Opening Snowflake connection")
            conn = ig.get_snowflake_conn()

            progress.progress(30, text="Fetching mart data...")
            status.caption("Step 2 / 4 — Querying trending repos, language trends, label usage")
            data = ig.fetch_mart_data(conn)

            progress.progress(55, text="Calling Claude API...")
            status.caption(
                f"Step 3 / 4 — Sending prompt ({len(data['trending_repos'])} repos · "
                f"{len(data['language_trends'])} trend rows · "
                f"{len(data['label_usage'])} label rows)"
            )
            import anthropic
            client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
            message = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                messages=[{"role": "user", "content": ig.build_prompt(data)}],
            )
            insight_text = message.content[0].text

            progress.progress(80, text="Saving to Snowflake...")
            status.caption("Step 4 / 4 — Writing insight to mart_daily_insights")
            ig.save_insight(conn, insight_text, data)
            conn.close()

            progress.progress(100, text="Done!")
            status.empty()
            st.cache_data.clear()
            st.success("Insight generated and saved. Refreshing...")
            st.rerun()

        except Exception as e:
            progress.empty()
            status.empty()
            st.error(f"Insight generation failed: {e}")

# ── Tab 2: Trending Repos ─────────────────────────────────────────

with tab_trending:
    st.header("Trending Repos")

    dates_df = run_query("""
        SELECT DISTINCT date_day
        FROM dbt_jimin_dev.mart_trending_repos
        ORDER BY date_day DESC
        LIMIT 90
    """)

    if dates_df.empty:
        st.info("No data available in mart_trending_repos.")
    else:
        date_col = "DATE_DAY"
        date_options = dates_df[date_col].tolist()
        selected_date = st.selectbox(
            "Select date",
            options=date_options,
            format_func=lambda d: str(d)[:10],
        )

        repos_df = run_query(f"""
            SELECT repo_name, rolling_7d_stars, rolling_7d_forks,
                   unique_contributors, trending_rank
            FROM dbt_jimin_dev.mart_trending_repos
            WHERE date_day = '{str(selected_date)[:10]}'
              AND trending_rank <= 20
            ORDER BY trending_rank
        """)

        if not repos_df.empty:
            col_map = {c: c.lower() for c in repos_df.columns}
            repos_df = repos_df.rename(columns=col_map)

            st.dataframe(
                repos_df[["trending_rank", "repo_name", "rolling_7d_stars",
                           "rolling_7d_forks", "unique_contributors"]],
                use_container_width=True,
                hide_index=True,
            )

            fig = px.bar(
                repos_df,
                x="repo_name",
                y="rolling_7d_stars",
                color="rolling_7d_stars",
                color_continuous_scale="Blues",
                labels={"repo_name": "Repository", "rolling_7d_stars": "7-Day Rolling Stars"},
                title=f"Top 20 Trending Repos — {str(selected_date)[:10]}",
            )
            fig.update_layout(
                coloraxis_showscale=False,
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
            )
            fig.update_xaxes(showticklabels=False)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No data available for the selected date.")

# ── Tab 3: Activity Trends ────────────────────────────────────────

with tab_activity:
    st.header("Activity Trends")

    trends_df = run_query("""
        SELECT date_day, event_category, event_count, wow_growth_rate
        FROM dbt_jimin_dev.mart_language_trends
        WHERE date_day >= DATEADD('day', -30,
              (SELECT MAX(date_day) FROM dbt_jimin_dev.mart_language_trends))
        ORDER BY date_day, event_count DESC
    """)

    if trends_df.empty:
        st.info("No data available in mart_language_trends.")
    else:
        col_map = {c: c.lower() for c in trends_df.columns}
        trends_df = trends_df.rename(columns=col_map)
        trends_df["date_day"] = pd.to_datetime(trends_df["date_day"]).dt.date

        fig_count = px.line(
            trends_df,
            x="date_day",
            y="event_count",
            color="event_category",
            markers=True,
            labels={"date_day": "Date", "event_count": "Event Count",
                    "event_category": "Category"},
            title="Daily Event Count by Category (Last 30 Days)",
            color_discrete_sequence=px.colors.qualitative.Set2,
        )
        fig_count.update_layout(
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig_count, use_container_width=True)

        st.subheader("Week-over-Week Growth Rate")
        wow_df = trends_df.dropna(subset=["wow_growth_rate"])
        if not wow_df.empty:
            fig_wow = px.line(
                wow_df,
                x="date_day",
                y="wow_growth_rate",
                color="event_category",
                markers=True,
                labels={"date_day": "Date", "wow_growth_rate": "WoW Growth Rate (%)",
                        "event_category": "Category"},
                title="Week-over-Week Growth Rate by Category",
                color_discrete_sequence=px.colors.qualitative.Set2,
            )
            fig_wow.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
            fig_wow.update_layout(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
            )
            st.plotly_chart(fig_wow, use_container_width=True)
        else:
            st.info("No WoW growth rate data available.")

# ── Tab 4: PR Label Usage ─────────────────────────────────────────

with tab_labels:
    st.header("PR Label Usage")

    labels_df = run_query("""
        SELECT label_name, label_applied_count, unique_repos, daily_rank
        FROM dbt_jimin_dev.mart_label_usage
        WHERE date_day = (SELECT MAX(date_day) FROM dbt_jimin_dev.mart_label_usage)
          AND daily_rank <= 20
        ORDER BY daily_rank
    """)

    if labels_df.empty:
        st.info("No data available in mart_label_usage.")
    else:
        col_map = {c: c.lower() for c in labels_df.columns}
        labels_df = labels_df.rename(columns=col_map)
        labels_df = labels_df.sort_values("label_applied_count", ascending=True)

        fig = px.bar(
            labels_df,
            x="label_applied_count",
            y="label_name",
            orientation="h",
            color="label_applied_count",
            color_continuous_scale="Teal",
            text="label_applied_count",
            labels={"label_applied_count": "Applications", "label_name": "Label"},
            title="Top 20 PR Labels (Most Recent Day)",
        )
        fig.update_traces(textposition="outside")
        fig.update_layout(
            coloraxis_showscale=False,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            yaxis=dict(automargin=True),
        )
        st.plotly_chart(fig, use_container_width=True)

        st.dataframe(
            labels_df[["daily_rank", "label_name", "label_applied_count", "unique_repos"]],
            use_container_width=True,
            hide_index=True,
        )

# ── Tab 5: Pipeline ───────────────────────────────────────────────

def _node(label: str, sublabel: str, color: str):
    """Render a single pipeline node using st.container + column styling."""
    st.markdown(
        f"""<div style="border:2px solid {color};border-radius:8px;padding:8px 14px;
            text-align:center;background:transparent;margin:2px 0;">
            <div style="color:{color};font-weight:700;font-size:0.85rem;">{label}</div>
            <div style="color:#888;font-size:0.76rem;margin-top:2px;">{sublabel}</div>
            </div>""",
        unsafe_allow_html=True,
    )

def _arrow(text: str = ""):
    st.markdown(
        f'<div style="text-align:center;color:#555;line-height:1;">'
        f'{"<span style=\\'font-size:0.72rem;color:#777;\\'>" + text + "</span><br>" if text else ""}'
        f"↓</div>",
        unsafe_allow_html=True,
    )


C_ORCH    = "#2ca02c"
C_INGEST  = "#1f77b4"
C_STORAGE = "#17becf"
C_DBT     = "#ff7f0e"
C_AI      = "#9467bd"
C_SERVE   = "#d62728"

with tab_pipeline:
    st.header("Pipeline Architecture")
    st.caption("End-to-end data flow — GH Archive → Snowflake → dbt → Claude → Streamlit")

    # ── Two-column layout: hourly pipeline (left) | daily insights (right) ──
    left, gap, right = st.columns([10, 1, 5])

    with left:
        st.markdown(f"<p style='color:{C_ORCH};font-size:0.7rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;margin-bottom:4px;'>Orchestration — Hourly</p>", unsafe_allow_html=True)
        _node("Airflow · gh_archive_pipeline DAG", "schedule: '5 * * * *'  (every hour at :05)", C_ORCH)
        _arrow()
        _node("Task 1 · LambdaInvokeFunctionOperator", "invoke ingest_gh_archive (synchronous)", C_INGEST)
        _arrow()
        st.markdown(f"<p style='color:{C_INGEST};font-size:0.7rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;margin-bottom:4px;'>Ingestion</p>", unsafe_allow_html=True)
        _node("AWS Lambda", "ingestion/lambda_function.py", C_INGEST)
        _arrow()
        _node("GH Archive · gharchive.org", "fetch hourly .json.gz  (~50–500 MB)", C_INGEST)
        _arrow()
        _node("S3 · gh-archive-raw-140767157729/raw/", "multipart streaming upload — never fully in memory", C_INGEST)
        _arrow("COPY INTO via Storage Integration (IAM Role)")
        st.markdown(f"<p style='color:{C_STORAGE};font-size:0.7rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;margin-bottom:4px;'>Storage</p>", unsafe_allow_html=True)
        _node("Snowflake · RAW.raw_events", "append-only, ~40K events/hr", C_STORAGE)
        _arrow()
        st.markdown(f"<p style='color:{C_DBT};font-size:0.7rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;margin-bottom:4px;'>Transformation</p>", unsafe_allow_html=True)
        t2, t3 = st.columns(2)
        with t2:
            _node("Task 2 · dbt run", "stg_gh_events → int_* → mart_*", C_DBT)
        with t3:
            _node("Task 3 · dbt test", "schema tests on all mart tables", C_DBT)
        _arrow()
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            _node("mart_trending_repos", "7d rolling stars", C_DBT)
        with m2:
            _node("mart_contributor_retention", "cohort retention", C_DBT)
        with m3:
            _node("mart_language_trends", "category + WoW", C_DBT)
        with m4:
            _node("mart_label_usage", "PR labels", C_DBT)

    with right:
        st.markdown(f"<p style='color:{C_AI};font-size:0.7rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;margin-bottom:4px;'>Orchestration — Daily</p>", unsafe_allow_html=True)
        _node("Airflow · gh_archive_daily_insights DAG", "schedule: '0 0 * * *'  (daily midnight UTC)", C_AI)
        _arrow()
        _node("Claude API · claude-sonnet-4-6", "fetch mart data → generate briefing", C_AI)
        _arrow()
        _node("mart_daily_insights", "insight saved to Snowflake", C_STORAGE)

    # ── Streamlit at the bottom ──────────────────────────────────
    st.divider()
    st.markdown(f"<p style='color:{C_SERVE};font-size:0.7rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;margin-bottom:4px;'>Serving</p>", unsafe_allow_html=True)
    _node(
        "Streamlit Live Demo ✅",
        "reads from all mart tables + mart_daily_insights · TTL 5 min",
        C_SERVE,
    )
    st.markdown(
        "**Live demo:** [gh-archive-dbt-jimin.streamlit.app](https://gh-archive-dbt-jimin.streamlit.app/)",
    )

    st.divider()

    # ── Metrics row ───────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Events ingested", "~40K / hr", "GH Archive")
    c2.metric("Mart tables", "4", "dbt")
    c3.metric("Pipeline cadence", "Hourly", "Airflow")
    c4.metric("AI insights", "Daily", "Claude API")
