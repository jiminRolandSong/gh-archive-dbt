with labels as (
    select * from {{ ref('int_pr_labels')}}
),

daily_counts as (

    select
        date_trunc('day', created_at) as date_day,
        label_name,
        count(*) as label_applied_count,
        count(distinct repo_id) as unique_repos,
        count(distinct event_id) as unique_prs
    from labels
    group by 1, 2
),

ranked as (

    select
        date_day,
        label_name,
        label_applied_count,
        unique_repos,
        unique_prs,
        rank() over (
            partition by date_day
            order by label_applied_count desc
        ) as daily_rank

    from daily_counts

)

select
    date_day,
    label_name,
    label_applied_count,
    unique_repos,
    unique_prs,
    daily_rank
from ranked
qualify daily_rank <= 20
order by date_day desc, daily_rank