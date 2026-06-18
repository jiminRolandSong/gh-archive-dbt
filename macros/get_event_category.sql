{% macro get_event_category(event_type_column) %}
    case {{ event_type_column }}
        when 'WatchEvent'                      then 'star'
        when 'ForkEvent'                       then 'fork'
        when 'PushEvent'                       then 'code'
        when 'PullRequestEvent'                then 'code'
        when 'PullRequestReviewEvent'          then 'code'
        when 'PullRequestReviewCommentEvent'   then 'code'
        when 'CommitCommentEvent'              then 'code'
        when 'IssuesEvent'                     then 'issue'
        when 'IssueCommentEvent'               then 'issue'
        when 'CreateEvent'                     then 'repo_activity'
        when 'DeleteEvent'                     then 'repo_activity'
        when 'ReleaseEvent'                    then 'release'
        when 'MemberEvent'                     then 'community'
        when 'SponsorshipEvent'                then 'community'
        when 'GollumEvent'                     then 'wiki'
        when 'PublicEvent'                     then 'repo_activity'
        else                                        'other'
    end
{% endmacro %}