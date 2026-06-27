from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
import sys
import os

sys.path.insert(0, "/opt/airflow/dbt")

default_args = {
    "owner": "jimin",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

def run_insights():
    os.environ.setdefault("SNOWFLAKE_DATABASE", "GH_ARCHIVE")
    os.environ.setdefault("SNOWFLAKE_SCHEMA", "dbt_jimin_dev")
    os.environ.setdefault("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH")
    os.environ.setdefault("SNOWFLAKE_ROLE", "TRANSFORMER")

    from insights.insights_generator import main
    main()

with DAG(
    dag_id="gh_archive_daily_insights",
    default_args=default_args,
    description="Daily GitHub trend insights via Claude API",
    schedule_interval="0 0 * * *",
    start_date=datetime(2024, 1, 15),
    catchup=False,
    tags=["gh-archive", "insights", "claude"],
) as dag:

    run_insights_task = PythonOperator(
        task_id="generate_daily_insights",
        python_callable=run_insights,
    )