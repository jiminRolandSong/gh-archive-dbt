with events as (

    select
        repo_id,
        repo_name,
        event_type,
        {{ get_event_category('event_type') }} as event_category,
        date_trunc('day', created_at)          as date_day,
        actor_id,
        created_at
    from {{ ref('stg_gh_events') }}

),

aggregated as (

    select
        {{ dbt_utils.generate_surrogate_key(['repo_id', 'date_day']) }} as surrogate_key,
        repo_id,
        date_day,

        -- repo_name이 같은 날 여러 개 나올 수 있으므로(rename/transfer),
        -- 가장 최근 이벤트의 이름을 대표값으로 채택
        max_by(repo_name, created_at)              as repo_name,

        count_if(event_category = 'star')          as star_count,
        count_if(event_category = 'fork')          as fork_count,
        count_if(event_category = 'code')          as code_event_count,
        count_if(event_category = 'issue')         as issue_count,
        count_if(event_category = 'release')       as release_count,
        count(distinct actor_id)                   as unique_contributors,
        count(*)                                   as total_events

    from events
    group by repo_id, date_day  -- repo_name 제거, repo_id + date_day만

)

select * from aggregated