{{ config(
    materialized='incremental',
    unique_key='event_id',
    on_schema_change='sync_all_columns',
    cluster_by=['date_trunc(\'day\', created_at)']
)}}
with source as (
    select * from {{ source('gh_archive', 'raw_events')}}

    {% if is_incremental() %}
    -- lookback window: GH Archive events can land a few hours late,
    -- so re-scan a 3-hour overlap rather than trusting the exact max timestamp.
    -- unique_key handles any overlap safely as a merge, not a duplicate.
    where created_at > (
        select dateadd('hour', -3, max(created_at))
        from {{this}}
    )
    {% endif %}
),

renamed as (

    select
        id as event_id,
        type as event_type,
        created_at,

    -- VARIANT JSON parsing: colon navigates into the object, :: casts the result
       actor:id::number as actor_id,
       actor:login::string as actor_login,
       repo:id::number as repo_id,
       repo:name::string as repo_name,
       payload
    from source
),

deduplicated as (

    -- GH Archive occasionally repeats the same event_id across adjacent
    -- hourly files. Keep only the first-seen row per event_id.
    SELECT *, ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY created_at) AS rn
    FROM renamed

)

select event_id,
    event_type,
    actor_id,
    actor_login,
    repo_id,
    repo_name,
    payload,
    created_at
from deduplicated 
where rn = 1