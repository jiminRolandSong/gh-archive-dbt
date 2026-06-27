from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.providers.amazon.aws.operators.lambda_function import LambdaInvokeFunctionOperator
import json

default_args = {
    "owner": "jimin",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="gh_archive_pipeline",
    default_args=default_args,
    description="GH Archive hourly ingestion + dbt transform",
    schedule_interval="5 * * * *",  # 매시 5분 (Lambda 완료 여유시간)
    start_date=datetime(2024, 1, 15),
    catchup=False,
    tags=["gh-archive", "ingestion", "dbt"],
) as dag:

    # Task 1: Lambda invoke → S3 → Snowflake raw_events
    ingest = LambdaInvokeFunctionOperator(
        task_id="ingest_gh_archive",
        function_name="gh-archive-ingestion",
        payload=json.dumps({}),  # 빈 payload → Lambda가 자동으로 전 시간 계산
        aws_conn_id="aws_default",
        region_name="us-east-1",
        log_type="Tail",
    )

    # Task 2: dbt run → stg_gh_events부터 downstream 전체
    dbt_run = BashOperator(
    task_id="dbt_run",
    bash_command="""
        mkdir -p /home/airflow/.dbt
        cat > /home/airflow/.dbt/profiles.yml << EOF
        gh_archive:
        target: dev
        outputs:
            dev:
            type: snowflake
            account: $SNOWFLAKE_ACCOUNT
            user: $SNOWFLAKE_USER
            password: $SNOWFLAKE_PASSWORD
            role: TRANSFORMER
            database: GH_ARCHIVE
            warehouse: COMPUTE_WH
            schema: dbt_jimin_dev
            threads: 4
        EOF
        cd /opt/airflow/dbt && /home/airflow/.local/bin/dbt run --select stg_gh_events+ --profiles-dir /home/airflow/.dbt --project-dir /opt/airflow/dbt
        """,
        )


    dbt_test = BashOperator(
    task_id="dbt_test",
    bash_command="""
        mkdir -p /home/airflow/.dbt
        cat > /home/airflow/.dbt/profiles.yml << EOF
        gh_archive:
        target: dev
        outputs:
            dev:
            type: snowflake
            account: $SNOWFLAKE_ACCOUNT
            user: $SNOWFLAKE_USER
            password: $SNOWFLAKE_PASSWORD
            role: TRANSFORMER
            database: GH_ARCHIVE
            warehouse: COMPUTE_WH
            schema: dbt_jimin_dev
            threads: 4
        EOF
        cd /opt/airflow/dbt && /home/airflow/.local/bin/dbt test --select stg_gh_events+ --profiles-dir /home/airflow/.dbt --project-dir /opt/airflow/dbt
        """,
        )

    ingest >> dbt_run >> dbt_test