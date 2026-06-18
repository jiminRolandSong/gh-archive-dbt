with daily_stats as (

    select * from {{ ref('int_repo_daily_stats') }}

),

rolling as (

    select
        repo_id,
        repo_name,
        date_day,
        star_count,
        fork_count,
        code_event_count,
        unique_contributors,
        total_events,

        -- compute rolling totals first (no nesting)
        sum(star_count) over (
            partition by repo_id
            order by date_day
            rows between 6 preceding and current row
        ) as rolling_7d_stars,

        sum(fork_count) over (
            partition by repo_id
            order by date_day
            rows between 6 preceding and current row
        ) as rolling_7d_forks,

        sum(code_event_count) over (
            partition by repo_id
            order by date_day
            rows between 6 preceding and current row
        ) as rolling_7d_code_events

    from daily_stats

),

ranked as (

    -- rank on the already-computed rolling_7d_stars, not a nested window
    select
        *,
        rank() over (
            partition by date_day
            order by rolling_7d_stars desc
        ) as trending_rank
    from rolling

)

select
    repo_id,
    repo_name,
    date_day,
    star_count,
    rolling_7d_stars,
    rolling_7d_forks,
    rolling_7d_code_events,
    unique_contributors,
    trending_rank
from ranked
where trending_rank <= 100