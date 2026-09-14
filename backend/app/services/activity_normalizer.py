from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse, parse_qs

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.models.event import Event


# 일반 동일 페이지 이벤트 병합
PAGE_MERGE_WINDOW_SECONDS = 5

# 동일 검색어에서 발생하는 브라우저 기술 이벤트 병합
SEARCH_MERGE_WINDOW_SECONDS = 10


@dataclass
class NormalizedActivity:
    timestamp: datetime
    activity_type: str

    domain: Optional[str]
    url: Optional[str]
    title: Optional[str]

    search_query: Optional[str]

    source_event_ids: list[int]


def normalize_search_query(
    query: Optional[str],
) -> Optional[str]:

    if not query:
        return None

    normalized = " ".join(
        query
        .strip()
        .lower()
        .split()
    )

    return normalized or None


def canonicalize_url(
    url: Optional[str],
) -> Optional[str]:
    """
    분석에 필요한 핵심 URL만 남긴다.

    Google 검색의 경우:
    수많은 tracking parameter를 제거하고
    검색어 q만 사용한다.
    """

    if not url:
        return None

    try:
        parsed = urlparse(url)

        hostname = (
            parsed.hostname or ""
        ).lower()

        # ------------------------------------------
        # Google
        # ------------------------------------------

        if "google." in hostname:

            query_params = parse_qs(
                parsed.query
            )

            search_query = (
                query_params.get(
                    "q",
                    [None],
                )[0]
            )

            if search_query:
                normalized_query = (
                    normalize_search_query(
                        search_query
                    )
                )

                return (
                    f"{parsed.scheme}://"
                    f"{hostname}/search"
                    f"?q={normalized_query}"
                )

        # ------------------------------------------
        # Naver Search
        # ------------------------------------------

        if hostname in {
            "search.naver.com",
            "m.search.naver.com",
        }:

            query_params = parse_qs(
                parsed.query
            )

            search_query = (
                query_params.get(
                    "query",
                    [None],
                )[0]
            )

            if search_query:
                normalized_query = (
                    normalize_search_query(
                        search_query
                    )
                )

                return (
                    f"{parsed.scheme}://"
                    f"{hostname}/search"
                    f"?query={normalized_query}"
                )

        # ------------------------------------------
        # 일반 URL
        # ------------------------------------------

        return (
            f"{parsed.scheme}://"
            f"{parsed.netloc}"
            f"{parsed.path}"
        )

    except Exception:
        return url


def classify_activity(
    event: Event,
) -> str:

    if event.search_query:
        return "search"

    if event.event_type == "page_visit":
        return "page_visit"

    if event.event_type == "tab_activated":
        return "tab_switch"

    return "other"


def is_same_search(
    previous: NormalizedActivity,
    event: Event,
) -> bool:

    if (
        previous.activity_type
        != "search"
    ):
        return False

    previous_query = (
        normalize_search_query(
            previous.search_query
        )
    )

    current_query = (
        normalize_search_query(
            event.search_query
        )
    )

    if (
        not previous_query
        or
        not current_query
    ):
        return False

    if (
        previous_query
        != current_query
    ):
        return False

    delta_seconds = (
        event.timestamp
        - previous.timestamp
    ).total_seconds()

    return (
        0
        <= delta_seconds
        <= SEARCH_MERGE_WINDOW_SECONDS
    )


def is_same_page(
    previous: NormalizedActivity,
    event: Event,
) -> bool:

    previous_url = canonicalize_url(
        previous.url
    )

    current_url = canonicalize_url(
        event.url
    )

    if (
        not previous_url
        or
        not current_url
    ):
        return False

    if previous_url != current_url:
        return False

    delta_seconds = (
        event.timestamp
        - previous.timestamp
    ).total_seconds()

    return (
        0
        <= delta_seconds
        <= PAGE_MERGE_WINDOW_SECONDS
    )


def same_logical_activity(
    previous: NormalizedActivity,
    event: Event,
) -> bool:

    # 검색 행동은 URL보다 query를 우선한다.
    if (
        previous.activity_type == "search"
        and event.search_query
    ):
        return is_same_search(
            previous,
            event,
        )

    # 일반 브라우저 이벤트
    if event.event_type in {
        "tab_activated",
        "page_visit",
    }:
        return is_same_page(
            previous,
            event,
        )

    return False


def merge_event_into_activity(
    activity: NormalizedActivity,
    event: Event,
) -> None:

    activity.source_event_ids.append(
        event.id
    )

    if event.title:
        activity.title = event.title

    if event.url:
        activity.url = event.url

    if event.domain:
        activity.domain = event.domain

    if event.search_query:
        activity.search_query = (
            normalize_search_query(
                event.search_query
            )
        )

        activity.activity_type = (
            "search"
        )


def create_activity(
    event: Event,
) -> NormalizedActivity:

    return NormalizedActivity(
        timestamp=event.timestamp,

        activity_type=(
            classify_activity(event)
        ),

        domain=event.domain,

        url=event.url,

        title=event.title,

        search_query=(
            normalize_search_query(
                event.search_query
            )
        ),

        source_event_ids=[
            event.id
        ],
    )


def normalize_events(
    events: list[Event],
) -> list[NormalizedActivity]:

    normalized: list[
        NormalizedActivity
    ] = []

    for event in events:

        if not normalized:
            normalized.append(
                create_activity(event)
            )
            continue

        previous_activity = (
            normalized[-1]
        )

        if same_logical_activity(
            previous_activity,
            event,
        ):
            merge_event_into_activity(
                previous_activity,
                event,
            )

            continue

        normalized.append(
            create_activity(event)
        )

    return normalized


def get_normalized_activities(
    db: DBSession,
    session_id: int,
) -> list[NormalizedActivity]:

    statement = (
        select(Event)
        .where(
            Event.session_id
            == session_id
        )
        .order_by(
            Event.timestamp.asc()
        )
    )

    events = list(
        db.scalars(
            statement
        ).all()
    )

    return normalize_events(
        events
    )