with events as (

    select
        repo_id,
        repo_name,
        event_type,
        {{ get_event_category('event_type') }} as event_category,
        date_trunc('day', created_at)          as date_day,
        actor_id
    from {{ ref('stg_gh_events') }}

),

aggregated as (

    select
        {{ dbt_utils.generate_surrogate_key(['repo_id', 'date_day']) }} as surrogate_key,
        repo_id,
        repo_name,
        date_day,

        -- event category counts
        count_if(event_category = 'star')          as star_count,
        count_if(event_category = 'fork')          as fork_count,
        count_if(event_category = 'code')          as code_event_count,
        count_if(event_category = 'issue')         as issue_count,
        count_if(event_category = 'release')       as release_count,

        -- unique contributor count for the day
        count(distinct actor_id)                   as unique_contributors,

        -- total events
        count(*)                                   as total_events

    from events
    group by 1, 2, 3, 4

)

select * from aggregated