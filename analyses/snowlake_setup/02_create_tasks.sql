-- Run once manually in Snowflake to set up Task DAG
-- NOTE: Resume child task before root task (Snowflake DAG validation order)

-- Root task: merges new stream data into stg_gh_events every 60 min
CREATE OR REPLACE TASK GH_ARCHIVE.RAW.task_load_staging
  WAREHOUSE = COMPUTE_WH
  SCHEDULE = '60 MINUTE'
WHEN SYSTEM$STREAM_HAS_DATA('GH_ARCHIVE.RAW.raw_events_stream')
AS
MERGE INTO GH_ARCHIVE.dbt_jimin_dev.stg_gh_events t
USING (
    SELECT
        id                      as event_id,
        type                    as event_type,
        created_at,
        actor:id::number        as actor_id,
        actor:login::string     as actor_login,
        repo:id::number         as repo_id,
        repo:name::string       as repo_name,
        payload
    FROM GH_ARCHIVE.RAW.raw_events_stream
    WHERE repo:id::number IS NOT NULL
    QUALIFY ROW_NUMBER() OVER (PARTITION BY id ORDER BY created_at) = 1
) s
ON t.event_id = s.event_id
WHEN MATCHED THEN UPDATE SET
    t.event_type  = s.event_type,
    t.actor_id    = s.actor_id,
    t.actor_login = s.actor_login,
    t.repo_id     = s.repo_id,
    t.repo_name   = s.repo_name,
    t.payload     = s.payload,
    t.created_at  = s.created_at
WHEN NOT MATCHED THEN INSERT (
    event_id, event_type, created_at,
    actor_id, actor_login, repo_id, repo_name, payload
) VALUES (
    s.event_id, s.event_type, s.created_at,
    s.actor_id, s.actor_login, s.repo_id, s.repo_name, s.payload
);

-- Child task: triggered after root task completes
-- In production this would trigger a dbt run via external call
CREATE OR REPLACE TASK GH_ARCHIVE.RAW.task_refresh_marts
  WAREHOUSE = COMPUTE_WH
  AFTER GH_ARCHIVE.RAW.task_load_staging
AS
  SELECT 1;  -- placeholder: production would call dbt run externally

-- Resume order matters: child first, then root
ALTER TASK GH_ARCHIVE.RAW.task_refresh_marts RESUME;
ALTER TASK GH_ARCHIVE.RAW.task_load_staging RESUME;