{{ config(materialized='ephemeral') }}

with labeled_events as (

    select
        event_id,
        repo_id,
        repo_name,
        actor_id,
        created_at,
        payload
    from {{ ref('stg_gh_events') }}
    where event_type = 'PullRequestEvent'
      and payload:action::string = 'labeled'

),

labels_flattened as (

    select
        e.event_id,
        e.repo_id,
        e.repo_name,
        e.actor_id,
        e.created_at,
        e.payload:pull_request:number::number as pr_number,
        f.value:name::string  as label_name,
        f.value:color::string as label_color,
        f.index                as label_position

    from labeled_events e,
        lateral flatten(input => e.payload:labels) f

)

select * from labels_flattened