with events as (

    select
        repo_name,
        -- extract language hint from repo name is not reliable,
        -- so we use event_category as a proxy for activity type
        -- (real language data would come from GitHub API enrichment later)
        {{ get_event_category('event_type') }}      as event_category,
        event_type,
        date_trunc('day', created_at)               as date_day,
        actor_id
    from {{ ref('stg_gh_events') }}

),

daily as (

    select
        date_day,
        event_category,
        count(*)                    as event_count,
        count(distinct actor_id)    as unique_contributors,
        count(distinct repo_name)   as unique_repos

    from events
    group by 1, 2

),

with_growth as (

    select
        date_day,
        event_category,
        event_count,
        unique_contributors,
        unique_repos,

        -- week-over-week growth rate per category
        lag(event_count, 7) over (
            partition by event_category
            order by date_day
        ) as event_count_7d_ago,

        {{ safe_divide(
            'event_count - lag(event_count, 7) over (partition by event_category order by date_day)',
            'lag(event_count, 7) over (partition by event_category order by date_day)'
        ) }} as wow_growth_rate

    from daily

)

select * from with_growth
order by date_day desc, event_count desc