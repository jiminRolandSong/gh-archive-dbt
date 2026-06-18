with activity as (

    select * from {{ ref('int_developer_activity') }}

),

cohorts as (

    select
        actor_id,
        actor_login,
        date_day,
        total_events,
        code_contributions,

        -- cohort = the month the developer was first seen
        date_trunc('month',
            min(date_day) over (partition by actor_id)
        ) as cohort_month

    from activity

),

retention as (

    select
        cohort_month,
        date_trunc('month', date_day)                           as activity_month,
        datediff('month', cohort_month,
            date_trunc('month', date_day))                      as months_since_first,
        count(distinct actor_id)                                as retained_contributors,
        sum(code_contributions)                                 as total_code_contributions

    from cohorts
    group by 1, 2, 3

),

with_cohort_size as (

    select
        *,
        -- cohort size = how many contributors were first seen in cohort_month
        first_value(retained_contributors) over (
            partition by cohort_month
            order by months_since_first
        ) as cohort_size,

        -- retention rate for this month
        {{ safe_divide('retained_contributors',
            'first_value(retained_contributors) over (partition by cohort_month order by months_since_first)')
        }} as retention_rate

    from retention

)

select
    cohort_month,
    activity_month,
    months_since_first,
    cohort_size,
    retained_contributors,
    retention_rate,
    total_code_contributions
from with_cohort_size
order by cohort_month, months_since_first