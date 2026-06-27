import os
import json
from datetime import date
import snowflake.connector
import anthropic
from dotenv import load_dotenv

load_dotenv()

# ── Snowflake connection ──────────────────────────────────────────
def get_snowflake_conn():
    return snowflake.connector.connect(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        password=os.getenv("SNOWFLAKE_PASSWORD"),
        database=os.getenv("SNOWFLAKE_DATABASE"),
        schema=os.getenv("SNOWFLAKE_SCHEMA"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
        role=os.getenv("SNOWFLAKE_ROLE"),
    )

# ── Fetch mart data ───────────────────────────────────────────────
def fetch_mart_data(conn):
    cursor = conn.cursor()

    # 1. Trending repos (top 10 latest day)
    cursor.execute("""
        SELECT repo_name, rolling_7d_stars, rolling_7d_forks,
               unique_contributors, trending_rank, date_day
        FROM dbt_jimin_dev.mart_trending_repos
        WHERE date_day = (SELECT MAX(date_day) FROM dbt_jimin_dev.mart_trending_repos)
          AND trending_rank <= 10
        ORDER BY trending_rank
    """)
    trending = cursor.fetchall()
    trending_cols = [d[0] for d in cursor.description]

    # 2. Language trends (last 7 days)
    cursor.execute("""
        SELECT date_day, event_category, event_count, wow_growth_rate
        FROM dbt_jimin_dev.mart_language_trends
        WHERE date_day >= DATEADD('day', -7, (SELECT MAX(date_day) FROM dbt_jimin_dev.mart_language_trends))
        ORDER BY date_day DESC, event_count DESC
    """)
    trends = cursor.fetchall()
    trends_cols = [d[0] for d in cursor.description]

    # 3. Label usage (top 10 latest day)
    cursor.execute("""
        SELECT label_name, label_applied_count, unique_repos, daily_rank
        FROM dbt_jimin_dev.mart_label_usage
        WHERE date_day = (SELECT MAX(date_day) FROM dbt_jimin_dev.mart_label_usage)
          AND daily_rank <= 10
        ORDER BY daily_rank
    """)
    labels = cursor.fetchall()
    labels_cols = [d[0] for d in cursor.description]

    cursor.close()

    return {
        "trending_repos": [dict(zip(trending_cols, row)) for row in trending],
        "language_trends": [dict(zip(trends_cols, row)) for row in trends],
        "label_usage":     [dict(zip(labels_cols, row)) for row in labels],
    }

# ── Build prompt ──────────────────────────────────────────────────
def build_prompt(data: dict) -> str:
    return f"""You are a developer trends analyst. Below is GitHub activity data 
from the last 24 hours, pulled from a real-time dbt pipeline on GH Archive data.

## Trending Repositories (Top 10 by 7-day rolling stars)
{json.dumps(data['trending_repos'], indent=2, default=str)}

## Activity Category Trends (Last 7 days)
{json.dumps(data['language_trends'], indent=2, default=str)}

## Most Applied PR Labels (Today's Top 10)
{json.dumps(data['label_usage'], indent=2, default=str)}

Write a concise developer trends briefing (max 300 words) covering:
1. Which repositories are gaining the most momentum and why they might be trending
2. Notable shifts in developer activity patterns (code vs issues vs stars)
3. What the PR label patterns reveal about developer workflows

Be specific — reference actual repo names and numbers from the data.
Write in a confident, analyst tone suitable for a daily engineering newsletter.
"""

# ── Save insight to Snowflake ─────────────────────────────────────
def save_insight(conn, insight_text: str, data: dict):
    cursor = conn.cursor()

    # Create table if not exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dbt_jimin_dev.mart_daily_insights (
            insight_date    DATE,
            generated_at    TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
            insight_text    VARCHAR,
            trending_repos  VARIANT,
            model_used      VARCHAR
        )
    """)

    cursor.execute("""
        INSERT INTO dbt_jimin_dev.mart_daily_insights 
            (insight_date, insight_text, trending_repos, model_used)
        SELECT
            CURRENT_DATE(),
            %s,
            PARSE_JSON(%s),
            %s
    """, (
        insight_text,
        json.dumps(data['trending_repos'], default=str),
        'claude-sonnet-4-6'
    ))

    conn.commit()
    cursor.close()
    print("✅ Insight saved to mart_daily_insights")

# ── Main ──────────────────────────────────────────────────────────
def main():
    print("🔌 Connecting to Snowflake...")
    conn = get_snowflake_conn()

    print("📊 Fetching mart data...")
    data = fetch_mart_data(conn)
    print(f"  → {len(data['trending_repos'])} trending repos")
    print(f"  → {len(data['language_trends'])} trend rows")
    print(f"  → {len(data['label_usage'])} label rows")

    print("🤖 Calling Claude API...")
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": build_prompt(data)}]
    )
    insight_text = message.content[0].text
    print("\n── Generated Insight ──────────────────────────────")
    print(insight_text)
    print("───────────────────────────────────────────────────\n")

    print("💾 Saving to Snowflake...")
    save_insight(conn, insight_text, data)

    conn.close()
    print("✅ Done")

if __name__ == "__main__":
    main()