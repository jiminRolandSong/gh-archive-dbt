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

with tab_pipeline:
    st.header("Pipeline Architecture")
    st.caption("End-to-end data flow from GH Archive to this live dashboard.")

    st.graphviz_chart("""
        digraph pipeline {
            graph [rankdir=TB splines=ortho bgcolor="transparent" pad="0.4"]
            node  [fontname="Helvetica" fontsize=13 style=filled shape=box
                   fillcolor="#1e2530" fontcolor="#e8eaf0" color="#4a5568"
                   margin="0.25,0.15" penwidth=1.5]
            edge  [color="#4a9eff" penwidth=1.8 arrowsize=0.8]

            GHA  [label="GH Archive\ngharchive.org\n~40k events / hr"
                  fillcolor="#0d3b6e" fontcolor="#90caf9"]
            LAMB [label="AWS Lambda\n+ EventBridge\nhourly trigger"
                  fillcolor="#1a3a2a" fontcolor="#80cbc4"]
            S3   [label="S3\nraw JSON"
                  fillcolor="#1a3a2a" fontcolor="#80cbc4"]
            SF   [label="Snowflake\nRAW.raw_events"
                  fillcolor="#1a2040" fontcolor="#9fa8da"]
            DBT  [label="dbt (this project)\nstg → int → mart"
                  fillcolor="#2d1b4e" fontcolor="#ce93d8"]

            subgraph cluster_marts {
                label="dbt Mart Tables" fontcolor="#ce93d8" fontsize=11
                color="#4a4060" style=dashed
                M1 [label="mart_trending_repos"]
                M2 [label="mart_contributor_retention"]
                M3 [label="mart_language_trends"]
                M4 [label="mart_label_usage"]
            }

            CLAUDE [label="Claude API\ndaily insights (midnight)"
                    fillcolor="#3b1a1a" fontcolor="#ef9a9a"]
            ST     [label="Streamlit Live Demo ✅\ngh-archive-dbt-jimin.streamlit.app"
                    fillcolor="#0d3b2a" fontcolor="#a5d6a7" penwidth=2.5 color="#66bb6a"]

            GHA  -> LAMB [label=" hourly" fontcolor="#aaaaaa" fontsize=10]
            LAMB -> S3
            S3   -> SF
            SF   -> DBT
            DBT  -> M1
            DBT  -> M2
            DBT  -> M3
            DBT  -> M4
            M1   -> CLAUDE
            M3   -> CLAUDE
            M4   -> CLAUDE
            M1   -> ST
            M3   -> ST
            M4   -> ST
            CLAUDE -> ST [label=" daily insight" fontcolor="#aaaaaa" fontsize=10]
        }
    """, use_container_width=True)

    st.divider()

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("**Ingestion**")
        st.markdown("""
- GH Archive publishes hourly `.json.gz` dumps
- AWS EventBridge triggers Lambda on the hour
- Lambda downloads & stages raw JSON into S3
- Snowflake `COPY INTO` loads S3 → `RAW.raw_events`
""")
    with col2:
        st.markdown("**Transformation (dbt)**")
        st.markdown("""
- `stg_gh_events` — incremental dedup (3hr lookback)
- `int_*` — ephemeral CTEs, no intermediate objects
- `mart_trending_repos` — top-100 by 7d rolling stars
- `mart_language_trends` — daily category breakdown + WoW
- `mart_label_usage` — top-20 PR labels per day
""")
    with col3:
        st.markdown("**Serving**")
        st.markdown("""
- Airflow runs `dbt run + dbt test` every hour
- Claude API generates a daily briefing at midnight
- Insight saved to `mart_daily_insights`
- This Streamlit app queries marts directly (TTL 5 min)
- Live at [gh-archive-dbt-jimin.streamlit.app](https://gh-archive-dbt-jimin.streamlit.app/)
""")
