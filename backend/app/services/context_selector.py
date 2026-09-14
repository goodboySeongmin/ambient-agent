from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from app.services.activity_normalizer import (
    get_normalized_activities,
)


# =========================================================
# Temporal Configuration
# =========================================================

# 현재 작업으로 강하게 간주
ACTIVE_WINDOW_SECONDS = 5 * 60

# 현재 작업과 연결될 수 있는 최근 문맥
RECENT_WINDOW_SECONDS = 15 * 60

# 이 시간 이상 이벤트가 없으면 사용자를 idle로 판단
IDLE_THRESHOLD_SECONDS = 15 * 60

MAX_ACTIVE_ACTIVITIES = 20
MAX_RECENT_ACTIVITIES = 20

MAX_SEARCH_ITEMS = 10
MAX_TITLE_ITEMS = 10
MAX_DOMAIN_ITEMS = 8


# =========================================================
# Time Helpers
# =========================================================

def _utc_now() -> datetime:
    return datetime.now(
        timezone.utc
    )


def _ensure_aware(
    dt: datetime,
) -> datetime:
    """
    DB timestamp가 timezone-aware면 그대로 사용하고,
    혹시 naive datetime이면 UTC로 간주한다.
    """

    if dt.tzinfo is None:
        return dt.replace(
            tzinfo=timezone.utc
        )

    return dt


def _seconds_ago(
    timestamp: datetime,
    reference_time: datetime,
) -> float:
    timestamp = _ensure_aware(
        timestamp
    )

    reference_time = _ensure_aware(
        reference_time
    )

    return max(
        0.0,
        (
            reference_time
            - timestamp
        ).total_seconds(),
    )


# =========================================================
# Text Helpers
# =========================================================

def _clean_text(
    value: str | None,
) -> str | None:
    if value is None:
        return None

    cleaned = " ".join(
        str(value).split()
    ).strip()

    if not cleaned:
        return None

    return cleaned


def _normalize_text(
    value: str | None,
) -> str | None:
    cleaned = _clean_text(
        value
    )

    if cleaned is None:
        return None

    return cleaned.lower()


# =========================================================
# Activity Serialization
# =========================================================

def _activity_to_dict(
    activity,
    reference_time: datetime,
) -> dict[str, Any]:
    age_seconds = None

    if activity.timestamp is not None:
        age_seconds = _seconds_ago(
            activity.timestamp,
            reference_time,
        )

    return {
        "timestamp": (
            activity.timestamp.isoformat()
            if activity.timestamp
            else None
        ),

        "age_seconds": (
            round(
                age_seconds,
                2,
            )
            if age_seconds is not None
            else None
        ),

        "activity_type": activity.activity_type,

        "domain": _clean_text(
            activity.domain
        ),

        "url": _clean_text(
            activity.url
        ),

        "title": _clean_text(
            activity.title
        ),

        "search_query": _clean_text(
            activity.search_query
        ),
    }


# =========================================================
# Temporal Split
# =========================================================

def _split_activities_by_time(
    activities,
    reference_time: datetime,
):
    """
    실제 현재 시간(reference_time)을 기준으로 분리한다.

    active:
        최근 5분

    recent:
        5분 초과 ~ 15분

    historical:
        15분 초과
    """

    valid_activities = [
        activity
        for activity in activities
        if activity.timestamp is not None
    ]

    valid_activities.sort(
        key=lambda activity: activity.timestamp
    )

    active = []
    recent = []
    historical = []

    for activity in valid_activities:
        age_seconds = _seconds_ago(
            activity.timestamp,
            reference_time,
        )

        if age_seconds <= ACTIVE_WINDOW_SECONDS:
            active.append(
                activity
            )

        elif age_seconds <= RECENT_WINDOW_SECONDS:
            recent.append(
                activity
            )

        else:
            historical.append(
                activity
            )

    return (
        active,
        recent,
        historical,
    )


# =========================================================
# Search Evidence
# =========================================================

def _build_search_evidence(
    activities,
    reference_time: datetime,
    limit: int = MAX_SEARCH_ITEMS,
) -> dict[str, Any]:
    search_items = []

    normalized_queries = []

    original_query_map = {}

    for activity in activities:
        query = _clean_text(
            activity.search_query
        )

        if not query:
            continue

        normalized = _normalize_text(
            query
        )

        if not normalized:
            continue

        original_query_map.setdefault(
            normalized,
            query,
        )

        normalized_queries.append(
            normalized
        )

        age_seconds = _seconds_ago(
            activity.timestamp,
            reference_time,
        )

        search_items.append(
            {
                "timestamp": (
                    activity.timestamp.isoformat()
                ),

                "age_seconds": round(
                    age_seconds,
                    2,
                ),

                "query": query,

                "domain": _clean_text(
                    activity.domain
                ),
            }
        )

    counter = Counter(
        normalized_queries
    )

    repeated_queries = []

    for normalized, count in counter.most_common(
        limit
    ):
        if count < 2:
            continue

        matching_items = [
            item
            for item in search_items
            if _normalize_text(
                item["query"]
            ) == normalized
        ]

        last_seen_seconds_ago = None

        if matching_items:
            last_seen_seconds_ago = min(
                item["age_seconds"]
                for item in matching_items
            )

        repeated_queries.append(
            {
                "query": original_query_map[
                    normalized
                ],

                "count": count,

                "last_seen_seconds_ago": (
                    round(
                        last_seen_seconds_ago,
                        2,
                    )
                    if last_seen_seconds_ago is not None
                    else None
                ),
            }
        )

    unique_queries = []

    seen = set()

    for item in reversed(
        search_items
    ):
        normalized = _normalize_text(
            item["query"]
        )

        if not normalized:
            continue

        if normalized in seen:
            continue

        seen.add(
            normalized
        )

        unique_queries.append(
            {
                "query": item["query"],

                "last_seen_seconds_ago": item[
                    "age_seconds"
                ],
            }
        )

        if len(
            unique_queries
        ) >= limit:
            break

    unique_queries.reverse()

    return {
        "search_count": len(
            search_items
        ),

        "searches": search_items[
            -limit:
        ],

        "repeated_queries": (
            repeated_queries
        ),

        "unique_queries": (
            unique_queries
        ),
    }


# =========================================================
# Title Evidence
# =========================================================

def _build_title_evidence(
    activities,
    reference_time: datetime,
) -> dict[str, Any]:
    counter = Counter()

    original_map = {}

    latest_seen = {}

    for activity in activities:
        title = _clean_text(
            activity.title
        )

        if not title:
            continue

        normalized = _normalize_text(
            title
        )

        if not normalized:
            continue

        counter[
            normalized
        ] += 1

        original_map.setdefault(
            normalized,
            title,
        )

        age_seconds = _seconds_ago(
            activity.timestamp,
            reference_time,
        )

        previous = latest_seen.get(
            normalized
        )

        if (
            previous is None
            or age_seconds < previous
        ):
            latest_seen[
                normalized
            ] = age_seconds

    frequent_titles = []

    for normalized, count in counter.most_common(
        MAX_TITLE_ITEMS
    ):
        frequent_titles.append(
            {
                "title": original_map[
                    normalized
                ],

                "count": count,

                "last_seen_seconds_ago": round(
                    latest_seen[
                        normalized
                    ],
                    2,
                ),
            }
        )

    return {
        "frequent_titles": frequent_titles,
    }


# =========================================================
# Domain Evidence
# =========================================================

def _build_domain_evidence(
    activities,
    reference_time: datetime,
) -> dict[str, Any]:
    counter = Counter()

    latest_seen = {}

    for activity in activities:
        domain = _clean_text(
            activity.domain
        )

        if not domain:
            continue

        counter[
            domain
        ] += 1

        age_seconds = _seconds_ago(
            activity.timestamp,
            reference_time,
        )

        previous = latest_seen.get(
            domain
        )

        if (
            previous is None
            or age_seconds < previous
        ):
            latest_seen[
                domain
            ] = age_seconds

    top_domains = []

    for domain, count in counter.most_common(
        MAX_DOMAIN_ITEMS
    ):
        top_domains.append(
            {
                "domain": domain,

                "count": count,

                "last_seen_seconds_ago": round(
                    latest_seen[
                        domain
                    ],
                    2,
                ),
            }
        )

    return {
        "top_domains": top_domains,
    }


# =========================================================
# Active Context
# =========================================================

def _build_active_context(
    activities,
    reference_time: datetime,
) -> dict[str, Any]:
    if not activities:
        return {
            "current_activity": None,
            "recent_activities": [],
            "recent_searches": [],
            "recent_titles": [],
            "recent_domains": [],
        }

    ordered = sorted(
        activities,
        key=lambda activity: activity.timestamp
    )

    current_activity = ordered[
        -1
    ]

    recent_searches = []
    recent_titles = []
    recent_domains = []

    seen_searches = set()
    seen_titles = set()
    seen_domains = set()

    for activity in reversed(
        ordered
    ):
        query = _clean_text(
            activity.search_query
        )

        if query:
            normalized = _normalize_text(
                query
            )

            if normalized not in seen_searches:
                seen_searches.add(
                    normalized
                )

                recent_searches.append(
                    query
                )

        title = _clean_text(
            activity.title
        )

        if title:
            normalized = _normalize_text(
                title
            )

            if normalized not in seen_titles:
                seen_titles.add(
                    normalized
                )

                recent_titles.append(
                    title
                )

        domain = _clean_text(
            activity.domain
        )

        if (
            domain
            and domain not in seen_domains
        ):
            seen_domains.add(
                domain
            )

            recent_domains.append(
                domain
            )

    recent_searches = list(
        reversed(
            recent_searches[
                :MAX_SEARCH_ITEMS
            ]
        )
    )

    recent_titles = list(
        reversed(
            recent_titles[
                :MAX_TITLE_ITEMS
            ]
        )
    )

    recent_domains = list(
        reversed(
            recent_domains[
                :MAX_DOMAIN_ITEMS
            ]
        )
    )

    return {
        "current_activity": _activity_to_dict(
            current_activity,
            reference_time,
        ),

        "recent_activities": [
            _activity_to_dict(
                activity,
                reference_time,
            )
            for activity in ordered[
                -MAX_ACTIVE_ACTIVITIES:
            ]
        ],

        "recent_searches": (
            recent_searches
        ),

        "recent_titles": (
            recent_titles
        ),

        "recent_domains": (
            recent_domains
        ),
    }


# =========================================================
# Historical Context
# =========================================================

def _build_historical_context(
    activities,
    reference_time: datetime,
) -> dict[str, Any]:
    return {
        "activity_count": len(
            activities
        ),

        "search_evidence": (
            _build_search_evidence(
                activities,
                reference_time,
            )
        ),

        "title_evidence": (
            _build_title_evidence(
                activities,
                reference_time,
            )
        ),

        "domain_evidence": (
            _build_domain_evidence(
                activities,
                reference_time,
            )
        ),
    }


# =========================================================
# Public API
# =========================================================

def build_context_selection(
    db,
    session_id: int,
) -> dict[str, Any]:
    activities = get_normalized_activities(
        db,
        session_id,
    )

    if not activities:
        raise ValueError(
            f"session_id={session_id}에 활동 데이터가 없습니다."
        )

    valid_activities = [
        activity
        for activity in activities
        if activity.timestamp is not None
    ]

    if not valid_activities:
        raise ValueError(
            f"session_id={session_id}에 timestamp가 있는 활동이 없습니다."
        )

    valid_activities.sort(
        key=lambda activity: activity.timestamp
    )

    # 핵심:
    # latest activity가 아니라 실제 현재 시각 사용
    reference_time = _utc_now()

    last_activity = valid_activities[
        -1
    ]

    last_activity_age_seconds = (
        _seconds_ago(
            last_activity.timestamp,
            reference_time,
        )
    )

    is_idle = (
        last_activity_age_seconds
        >= IDLE_THRESHOLD_SECONDS
    )

    (
        active_activities,
        recent_activities,
        historical_activities,
    ) = _split_activities_by_time(
        valid_activities,
        reference_time,
    )

    active_context = (
        _build_active_context(
            active_activities,
            reference_time,
        )
    )

    recent_context = {
        "activity_count": len(
            recent_activities
        ),

        "activities": [
            _activity_to_dict(
                activity,
                reference_time,
            )
            for activity in recent_activities[
                -MAX_RECENT_ACTIVITIES:
            ]
        ],

        "search_evidence": (
            _build_search_evidence(
                recent_activities,
                reference_time,
            )
        ),

        "title_evidence": (
            _build_title_evidence(
                recent_activities,
                reference_time,
            )
        ),

        "domain_evidence": (
            _build_domain_evidence(
                recent_activities,
                reference_time,
            )
        ),
    }

    historical_context = (
        _build_historical_context(
            historical_activities,
            reference_time,
        )
    )

    return {
        "reference_timestamp": (
            reference_time.isoformat()
        ),

        "last_activity_timestamp": (
            last_activity.timestamp.isoformat()
        ),

        "last_activity_age_seconds": round(
            last_activity_age_seconds,
            2,
        ),

        "is_idle": is_idle,

        "windows": {
            "active_seconds": (
                ACTIVE_WINDOW_SECONDS
            ),

            "recent_seconds": (
                RECENT_WINDOW_SECONDS
            ),

            "idle_threshold_seconds": (
                IDLE_THRESHOLD_SECONDS
            ),
        },

        "active_context": (
            active_context
        ),

        "recent_context": (
            recent_context
        ),

        "historical_context": (
            historical_context
        ),

        "selection_stats": {
            "total_activity_count": len(
                valid_activities
            ),

            "active_activity_count": len(
                active_activities
            ),

            "recent_activity_count": len(
                recent_activities
            ),

            "historical_activity_count": len(
                historical_activities
            ),
        },
    }