from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from app.services.activity_normalizer import (
    get_normalized_activities,
)

from app.services.semantic_similarity import (
    calculate_search_similarity_pairs,
)


# =========================================================
# Window Configuration
# =========================================================

STUCK_WINDOW_SECONDS = 15 * 60

RAPID_SWITCH_SECONDS = 10


# =========================================================
# Signal Weights
# =========================================================

SEARCH_REPEAT_WEIGHT = 0.30
SEARCH_REVISIT_WEIGHT = 0.25
SEMANTIC_LOOP_WEIGHT = 0.20
RAPID_SWITCH_WEIGHT = 0.15
DURATION_WEIGHT = 0.10


# =========================================================
# Score Thresholds
# =========================================================

MEDIUM_STUCK_THRESHOLD = 0.40
HIGH_STUCK_THRESHOLD = 0.65

SEMANTIC_SIMILARITY_THRESHOLD = 0.80


# =========================================================
# Duration Thresholds
# =========================================================

DURATION_START_SECONDS = 3 * 60
DURATION_SATURATION_SECONDS = 12 * 60


# =========================================================
# Helpers
# =========================================================

def _utc_now() -> datetime:
    return datetime.now(
        timezone.utc
    )


def _ensure_aware(
    dt: datetime,
) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(
            tzinfo=timezone.utc
        )

    return dt


def _seconds_ago(
    timestamp: datetime,
    reference_time: datetime,
) -> float:
    return max(
        0.0,
        (
            _ensure_aware(
                reference_time
            )
            - _ensure_aware(
                timestamp
            )
        ).total_seconds(),
    )


def _clamp(
    value: float,
    minimum: float = 0.0,
    maximum: float = 1.0,
) -> float:
    return max(
        minimum,
        min(
            maximum,
            value,
        ),
    )


def _normalize_query(
    query: str | None,
) -> str | None:
    if query is None:
        return None

    normalized = " ".join(
        str(query)
        .strip()
        .lower()
        .split()
    )

    if not normalized:
        return None

    return normalized


# =========================================================
# Window
# =========================================================

def _get_window_activities(
    activities,
    reference_time: datetime,
):
    valid = [
        activity
        for activity in activities
        if activity.timestamp is not None
    ]

    valid.sort(
        key=lambda activity: activity.timestamp
    )

    window = []

    for activity in valid:
        age_seconds = _seconds_ago(
            activity.timestamp,
            reference_time,
        )

        if age_seconds <= STUCK_WINDOW_SECONDS:
            window.append(
                activity
            )

    return window


# =========================================================
# Current Features
# =========================================================

def calculate_current_stuck_features(
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

    window_activities = (
        _get_window_activities(
            valid_activities,
            reference_time,
        )
    )

    # 최근 15분 안에 activity 자체가 없다면
    # 현재 stuck 상태가 아님
    if not window_activities:
        return {
            "activity_count": 0,

            "duration_seconds": 0.0,

            "search_count": 0,

            "unique_search_query_count": 0,

            "repeated_search_count": 0,

            "search_revisit_count": 0,

            "semantic_search_pair_count": 0,

            "semantic_search_loop_count": 0,

            "semantic_search_similarity_avg": 0.0,

            "semantic_search_similarity_max": 0.0,

            "domain_switch_count": 0,

            "rapid_switch_count": 0,

            "window_seconds": (
                STUCK_WINDOW_SECONDS
            ),

            "window_start": None,

            "window_end": (
                reference_time.isoformat()
            ),

            "last_activity_timestamp": (
                last_activity.timestamp.isoformat()
            ),

            "last_activity_age_seconds": round(
                last_activity_age_seconds,
                2,
            ),

            "has_recent_activity": False,
        }

    activity_count = len(
        window_activities
    )

    # -------------------------
    # Duration
    # -------------------------

    if activity_count >= 2:
        duration_seconds = max(
            0.0,
            (
                window_activities[-1].timestamp
                - window_activities[0].timestamp
            ).total_seconds(),
        )

    else:
        duration_seconds = 0.0

    # -------------------------
    # Searches
    # -------------------------

    search_queries = []

    normalized_search_queries = []

    for activity in window_activities:
        query = _normalize_query(
            activity.search_query
        )

        if not query:
            continue

        search_queries.append(
            activity.search_query
        )

        normalized_search_queries.append(
            query
        )

    search_count = len(
        normalized_search_queries
    )

    query_counter = Counter(
        normalized_search_queries
    )

    unique_search_query_count = len(
        query_counter
    )

    repeated_search_count = sum(
        max(
            0,
            count - 1,
        )
        for count in query_counter.values()
    )

    # -------------------------
    # Search Revisit
    # -------------------------

    search_revisit_count = 0

    last_seen_activity_index = {}

    for index, activity in enumerate(
        window_activities
    ):
        query = _normalize_query(
            activity.search_query
        )

        if not query:
            continue

        if query in last_seen_activity_index:
            previous_index = (
                last_seen_activity_index[
                    query
                ]
            )

            if index - previous_index > 1:
                search_revisit_count += 1

        last_seen_activity_index[
            query
        ] = index

    # -------------------------
    # Semantic Loops
    # -------------------------

    semantic_search_pair_count = 0
    semantic_search_loop_count = 0

    similarities = []

    if len(
        search_queries
    ) >= 2:
        pairs = (
            calculate_search_similarity_pairs(
                search_queries
            )
        )

        semantic_search_pair_count = len(
            pairs
        )

        for pair in pairs:
            similarity = float(
                pair.get(
                    "similarity",
                    0.0,
                )
            )

            similarities.append(
                similarity
            )

            is_loop = pair.get(
                "is_semantic_loop"
            )

            if is_loop is None:
                is_loop = (
                    similarity
                    >= SEMANTIC_SIMILARITY_THRESHOLD
                )

            if is_loop:
                semantic_search_loop_count += 1

    if similarities:
        similarity_avg = (
            sum(
                similarities
            )
            / len(
                similarities
            )
        )

        similarity_max = max(
            similarities
        )

    else:
        similarity_avg = 0.0
        similarity_max = 0.0

    # -------------------------
    # Domain Switching
    # -------------------------

    domain_switch_count = 0
    rapid_switch_count = 0

    previous_activity = None

    for activity in window_activities:
        if previous_activity is None:
            previous_activity = activity
            continue

        previous_domain = (
            previous_activity.domain
        )

        current_domain = (
            activity.domain
        )

        if (
            previous_domain
            and current_domain
            and previous_domain != current_domain
        ):
            domain_switch_count += 1

            delta_seconds = (
                activity.timestamp
                - previous_activity.timestamp
            ).total_seconds()

            if (
                0.0
                <= delta_seconds
                <= RAPID_SWITCH_SECONDS
            ):
                rapid_switch_count += 1

        previous_activity = activity

    return {
        "activity_count": (
            activity_count
        ),

        "duration_seconds": round(
            duration_seconds,
            2,
        ),

        "search_count": (
            search_count
        ),

        "unique_search_query_count": (
            unique_search_query_count
        ),

        "repeated_search_count": (
            repeated_search_count
        ),

        "search_revisit_count": (
            search_revisit_count
        ),

        "semantic_search_pair_count": (
            semantic_search_pair_count
        ),

        "semantic_search_loop_count": (
            semantic_search_loop_count
        ),

        "semantic_search_similarity_avg": round(
            similarity_avg,
            4,
        ),

        "semantic_search_similarity_max": round(
            similarity_max,
            4,
        ),

        "domain_switch_count": (
            domain_switch_count
        ),

        "rapid_switch_count": (
            rapid_switch_count
        ),

        "window_seconds": (
            STUCK_WINDOW_SECONDS
        ),

        "window_start": (
            window_activities[0]
            .timestamp
            .isoformat()
        ),

        "window_end": (
            reference_time.isoformat()
        ),

        "last_activity_timestamp": (
            last_activity.timestamp.isoformat()
        ),

        "last_activity_age_seconds": round(
            last_activity_age_seconds,
            2,
        ),

        "has_recent_activity": True,
    }


# =========================================================
# Signal Functions
# =========================================================

def _calculate_search_repeat_signal(
    features: dict[str, Any],
) -> float:
    search_count = features[
        "search_count"
    ]

    if search_count <= 1:
        return 0.0

    return _clamp(
        features[
            "repeated_search_count"
        ]
        / max(
            1,
            search_count - 1,
        )
    )


def _calculate_search_revisit_signal(
    features: dict[str, Any],
) -> float:
    search_count = features[
        "search_count"
    ]

    if search_count <= 1:
        return 0.0

    return _clamp(
        features[
            "search_revisit_count"
        ]
        / max(
            1,
            search_count - 1,
        )
    )


def _calculate_semantic_loop_signal(
    features: dict[str, Any],
) -> float:
    pair_count = features[
        "semantic_search_pair_count"
    ]

    if pair_count <= 0:
        return 0.0

    loop_ratio = (
        features[
            "semantic_search_loop_count"
        ]
        / pair_count
    )

    similarity_avg = features[
        "semantic_search_similarity_avg"
    ]

    return _clamp(
        (
            loop_ratio
            + similarity_avg
        )
        / 2.0
    )


def _calculate_rapid_switch_signal(
    features: dict[str, Any],
) -> float:
    activity_count = features[
        "activity_count"
    ]

    if activity_count <= 1:
        return 0.0

    ratio = (
        features[
            "rapid_switch_count"
        ]
        / max(
            1,
            activity_count - 1,
        )
    )

    return _clamp(
        ratio
        / 0.30
    )


def _calculate_duration_signal(
    features: dict[str, Any],
) -> float:
    duration_seconds = features[
        "duration_seconds"
    ]

    if duration_seconds <= DURATION_START_SECONDS:
        return 0.0

    if duration_seconds >= DURATION_SATURATION_SECONDS:
        return 1.0

    return _clamp(
        (
            duration_seconds
            - DURATION_START_SECONDS
        )
        /
        (
            DURATION_SATURATION_SECONDS
            - DURATION_START_SECONDS
        )
    )


# =========================================================
# Reasons
# =========================================================

def _build_reasons(
    signals: dict[str, float],
) -> list[str]:
    reasons = []

    if signals[
        "search_repeat"
    ] >= 0.4:
        reasons.append(
            "최근 작업 구간에서 동일한 검색을 반복하고 있습니다."
        )

    if signals[
        "search_revisit"
    ] >= 0.3:
        reasons.append(
            "다른 활동을 확인한 뒤 이전 검색으로 반복해서 돌아오고 있습니다."
        )

    if signals[
        "semantic_loop"
    ] >= 0.6:
        reasons.append(
            "최근 검색들이 의미적으로 유사한 문제를 반복해서 다루고 있습니다."
        )

    if signals[
        "rapid_switch"
    ] >= 0.5:
        reasons.append(
            "최근 짧은 시간 안에 여러 페이지나 도메인을 빠르게 전환하고 있습니다."
        )

    if signals[
        "duration"
    ] >= 0.6:
        reasons.append(
            "현재 작업 흐름이 일정 시간 이상 지속되고 있습니다."
        )

    return reasons


# =========================================================
# Public API
# =========================================================

def calculate_stuck_signal(
    db,
    session_id: int,
) -> dict[str, Any]:
    features = (
        calculate_current_stuck_features(
            db,
            session_id,
        )
    )

    # 최근 activity가 없으면
    # 무조건 현재 stuck 아님
    if not features[
        "has_recent_activity"
    ]:
        return {
            "session_id": (
                session_id
            ),

            "stuck_score": 0.0,

            "stuck_level": "low",

            "is_stuck_candidate": False,

            "signals": {
                "search_repeat": 0.0,
                "search_revisit": 0.0,
                "semantic_loop": 0.0,
                "rapid_switch": 0.0,
                "duration": 0.0,
            },

            "reasons": [],

            "diagnostics": {
                **features,
            },
        }

    signals = {
        "search_repeat": round(
            _calculate_search_repeat_signal(
                features
            ),
            4,
        ),

        "search_revisit": round(
            _calculate_search_revisit_signal(
                features
            ),
            4,
        ),

        "semantic_loop": round(
            _calculate_semantic_loop_signal(
                features
            ),
            4,
        ),

        "rapid_switch": round(
            _calculate_rapid_switch_signal(
                features
            ),
            4,
        ),

        "duration": round(
            _calculate_duration_signal(
                features
            ),
            4,
        ),
    }

    stuck_score = (
        signals[
            "search_repeat"
        ]
        * SEARCH_REPEAT_WEIGHT

        + signals[
            "search_revisit"
        ]
        * SEARCH_REVISIT_WEIGHT

        + signals[
            "semantic_loop"
        ]
        * SEMANTIC_LOOP_WEIGHT

        + signals[
            "rapid_switch"
        ]
        * RAPID_SWITCH_WEIGHT

        + signals[
            "duration"
        ]
        * DURATION_WEIGHT
    )

    stuck_score = round(
        _clamp(
            stuck_score
        ),
        4,
    )

    if (
        stuck_score
        >= HIGH_STUCK_THRESHOLD
    ):
        stuck_level = "high"

    elif (
        stuck_score
        >= MEDIUM_STUCK_THRESHOLD
    ):
        stuck_level = "medium"

    else:
        stuck_level = "low"

    return {
        "session_id": session_id,

        "stuck_score": (
            stuck_score
        ),

        "stuck_level": (
            stuck_level
        ),

        "is_stuck_candidate": (
            stuck_score
            >= MEDIUM_STUCK_THRESHOLD
        ),

        "signals": signals,

        "reasons": (
            _build_reasons(
                signals
            )
        ),

        "diagnostics": {
            **features,
        },
    }