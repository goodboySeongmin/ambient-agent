from collections import Counter
from datetime import datetime

from sqlalchemy.orm import Session as DBSession

from app.services.activity_normalizer import (
    get_normalized_activities,
)

from app.services.semantic_similarity import (
    calculate_semantic_search_features,
)


RAPID_SWITCH_THRESHOLD_SECONDS = 10


def calculate_session_features(
    db: DBSession,
    session_id: int,
) -> dict:

    activities = get_normalized_activities(
        db=db,
        session_id=session_id,
    )

    # --------------------------------------------------
    # Activity가 없는 경우
    # --------------------------------------------------

    if not activities:
        return {
            "session_id": session_id,

            "activity_count": 0,

            "duration_seconds": 0.0,

            "tab_switch_count": 0,

            "page_visit_count": 0,

            "unique_domain_count": 0,

            "domain_switch_count": 0,

            "domain_revisit_count": 0,

            "revisit_rate": 0.0,

            "most_visited_domain": None,

            "same_domain_streak_max": 0,

            "rapid_switch_count": 0,

            "search_count": 0,

            "unique_search_query_count": 0,

            "repeated_search_count": 0,

            "search_revisit_count": 0,

            "semantic_search_pair_count": 0,

            "semantic_search_loop_count": 0,

            "semantic_search_similarity_avg": 0.0,

            "semantic_search_similarity_max": 0.0,

            "avg_seconds_between_activities": 0.0,
        }

    # --------------------------------------------------
    # 기본 정보
    # --------------------------------------------------

    activity_count = len(
        activities
    )

    first_timestamp: datetime = (
        activities[0].timestamp
    )

    last_timestamp: datetime = (
        activities[-1].timestamp
    )

    duration_seconds = (
        last_timestamp
        - first_timestamp
    ).total_seconds()

    # --------------------------------------------------
    # Activity Type
    # --------------------------------------------------

    tab_switch_count = sum(
        1
        for activity in activities
        if activity.activity_type
        == "tab_switch"
    )

    page_visit_count = sum(
        1
        for activity in activities
        if activity.activity_type
        == "page_visit"
    )

    # --------------------------------------------------
    # Domain
    # --------------------------------------------------

    domains = [
        activity.domain

        for activity in activities

        if activity.domain
    ]

    unique_domains = set(
        domains
    )

    domain_counter = Counter(
        domains
    )

    most_visited_domain = None

    if domain_counter:

        most_visited_domain = (
            domain_counter
            .most_common(1)[0][0]
        )

    # --------------------------------------------------
    # Domain Switch
    # --------------------------------------------------

    domain_switch_count = 0

    previous_domain = None

    for activity in activities:

        current_domain = (
            activity.domain
        )

        if not current_domain:
            continue

        if (
            previous_domain is not None
            and
            current_domain
            != previous_domain
        ):
            domain_switch_count += 1

        previous_domain = (
            current_domain
        )

    # --------------------------------------------------
    # Domain Revisit
    # --------------------------------------------------

    seen_domains = set()

    domain_revisit_count = 0

    for domain in domains:

        if domain in seen_domains:

            domain_revisit_count += 1

        else:

            seen_domains.add(
                domain
            )

    if domains:

        revisit_rate = (
            domain_revisit_count
            / len(domains)
        )

    else:

        revisit_rate = 0.0

    # --------------------------------------------------
    # 동일 Domain 연속 활동 최대 길이
    # --------------------------------------------------

    same_domain_streak_max = 0

    current_streak = 0

    previous_domain = None

    for activity in activities:

        current_domain = (
            activity.domain
        )

        if not current_domain:
            continue

        if (
            current_domain
            == previous_domain
        ):

            current_streak += 1

        else:

            current_streak = 1

        same_domain_streak_max = max(
            same_domain_streak_max,
            current_streak,
        )

        previous_domain = (
            current_domain
        )

    # --------------------------------------------------
    # Activity 간 시간 간격
    # --------------------------------------------------

    time_differences = []

    for index in range(
        1,
        len(activities),
    ):

        previous_activity = (
            activities[index - 1]
        )

        current_activity = (
            activities[index]
        )

        delta_seconds = (
            current_activity.timestamp
            - previous_activity.timestamp
        ).total_seconds()

        if delta_seconds >= 0:

            time_differences.append(
                delta_seconds
            )

    if time_differences:

        avg_seconds_between_activities = (
            sum(time_differences)
            / len(time_differences)
        )

    else:

        avg_seconds_between_activities = 0.0

    # --------------------------------------------------
    # Rapid Domain Switch
    # --------------------------------------------------

    rapid_switch_count = 0

    for index in range(
        1,
        len(activities),
    ):

        previous_activity = (
            activities[index - 1]
        )

        current_activity = (
            activities[index]
        )

        if (
            not previous_activity.domain
            or
            not current_activity.domain
        ):
            continue

        if (
            previous_activity.domain
            == current_activity.domain
        ):
            continue

        delta_seconds = (
            current_activity.timestamp
            - previous_activity.timestamp
        ).total_seconds()

        if (
            0
            <= delta_seconds
            <= RAPID_SWITCH_THRESHOLD_SECONDS
        ):
            rapid_switch_count += 1

    # --------------------------------------------------
    # Search Activities
    # --------------------------------------------------

    search_activities = [
        activity

        for activity in activities

        if (
            activity.activity_type
            == "search"
            and
            activity.search_query
        )
    ]

    search_count = len(
        search_activities
    )

    search_queries = [
        activity.search_query
        .strip()
        .lower()

        for activity
        in search_activities
    ]

    # --------------------------------------------------
    # Unique Search Query
    # --------------------------------------------------

    unique_search_queries = set(
        search_queries
    )

    unique_search_query_count = len(
        unique_search_queries
    )

    # --------------------------------------------------
    # Exact Search Repeat
    # --------------------------------------------------

    search_query_counter = Counter(
        search_queries
    )

    repeated_search_count = sum(
        count - 1

        for count
        in search_query_counter.values()

        if count > 1
    )

    # --------------------------------------------------
    # Search Revisit
    #
    # 동일 검색어가 이전에 등장했고,
    # 그 사이에 다른 activity가 하나 이상 있었다면
    # revisit으로 판단
    #
    # Search A
    # → ChatGPT
    # → Search A
    #
    # = revisit 1
    #
    # Search A
    # → Search A
    #
    # = revisit 아님
    # --------------------------------------------------

    search_revisit_count = 0

    last_search_activity_index = {}

    for index, activity in enumerate(
        activities
    ):

        if (
            activity.activity_type
            != "search"
            or
            not activity.search_query
        ):
            continue

        current_query = (
            activity.search_query
            .strip()
            .lower()
        )

        previous_index = (
            last_search_activity_index
            .get(current_query)
        )

        if previous_index is not None:

            if (
                index
                - previous_index
                > 1
            ):
                search_revisit_count += 1

        last_search_activity_index[
            current_query
        ] = index

    # --------------------------------------------------
    # Semantic Search Features
    #
    # 검색어가 정확히 같지 않아도
    # 의미적으로 같은 문제인지 계산
    #
    # ex)
    #
    # postgresql connection refused
    #
    # postgres localhost connection refused
    #
    # --------------------------------------------------

    semantic_features = (
        calculate_semantic_search_features(
            search_queries
        )
    )

    # --------------------------------------------------
    # Response
    # --------------------------------------------------

    return {
        "session_id": session_id,

        "activity_count":
            activity_count,

        "duration_seconds": round(
            duration_seconds,
            2,
        ),

        "tab_switch_count":
            tab_switch_count,

        "page_visit_count":
            page_visit_count,

        "unique_domain_count": len(
            unique_domains
        ),

        "domain_switch_count":
            domain_switch_count,

        "domain_revisit_count":
            domain_revisit_count,

        "revisit_rate": round(
            revisit_rate,
            4,
        ),

        "most_visited_domain":
            most_visited_domain,

        "same_domain_streak_max":
            same_domain_streak_max,

        "rapid_switch_count":
            rapid_switch_count,

        "search_count":
            search_count,

        "unique_search_query_count":
            unique_search_query_count,

        "repeated_search_count":
            repeated_search_count,

        "search_revisit_count":
            search_revisit_count,

        "semantic_search_pair_count": (
            semantic_features[
                "semantic_search_pair_count"
            ]
        ),

        "semantic_search_loop_count": (
            semantic_features[
                "semantic_search_loop_count"
            ]
        ),

        "semantic_search_similarity_avg": (
            semantic_features[
                "semantic_search_similarity_avg"
            ]
        ),

        "semantic_search_similarity_max": (
            semantic_features[
                "semantic_search_similarity_max"
            ]
        ),

        "avg_seconds_between_activities": round(
            avg_seconds_between_activities,
            2,
        ),
    }