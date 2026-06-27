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
        st.error(f"Snowflake 연결 실패: {e}")
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

tab_insights, tab_trending, tab_activity, tab_labels = st.tabs([
    "Daily Insights",
    "Trending Repos",
    "Activity Trends",
    "PR Label Usage",
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
        st.info("아직 생성된 인사이트가 없습니다. 아래 버튼으로 첫 인사이트를 생성하세요.")

    st.divider()

    if st.button("Generate New Insight", type="primary"):
        with st.spinner("Claude API 호출 중..."):
            try:
                sys.path.insert(0, os.path.join(os.path.dirname(__file__), "insights"))
                from insights_generator import main as generate_insight
                generate_insight()
                st.cache_data.clear()
                st.success("인사이트가 생성되었습니다! 페이지를 새로고침하면 표시됩니다.")
                st.rerun()
            except Exception as e:
                st.error(f"인사이트 생성 실패: {e}")

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
        st.info("mart_trending_repos 데이터가 없습니다.")
    else:
        date_col = "DATE_DAY"
        date_options = dates_df[date_col].tolist()
        selected_date = st.selectbox(
            "날짜 선택",
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
            st.info("선택한 날짜에 데이터가 없습니다.")

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
        st.info("mart_language_trends 데이터가 없습니다.")
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
            st.info("WoW 성장률 데이터가 없습니다.")

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
        st.info("mart_label_usage 데이터가 없습니다.")
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
