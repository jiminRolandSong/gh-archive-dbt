with events as (

    select
        actor_id,
        actor_login,
        repo_id,
        repo_name,
        event_type,
        {{ get_event_category('event_type') }} as event_category,
        date_trunc('day', created_at)          as date_day,
        created_at
    from {{ ref('stg_gh_events') }}

),

aggregated as (

    select
        {{ dbt_utils.generate_surrogate_key(['actor_id', 'date_day']) }} as surrogate_key,
        actor_id,
        date_day,

        -- actor_login도 username 변경 시 같은 날 여러 값 가능 → 대표값 채택
        max_by(actor_login, created_at)                    as actor_login,

        count(*)                                            as total_events,
        count_if(event_category = 'code')                  as code_contributions,
        count_if(event_category = 'issue')                 as issue_interactions,
        count_if(event_category = 'star')                  as stars_given,
        count(distinct repo_id)                            as unique_repos_touched,
        {{ safe_divide('count_if(event_category = \'code\')', 'count(*)') }} as code_contribution_ratio

    from events
    group by actor_id, date_day  -- actor_login 제거

)

select * from aggregated