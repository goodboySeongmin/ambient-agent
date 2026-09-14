from datetime import datetime

from pydantic import BaseModel


class NormalizedActivityResponse(
    BaseModel
):
    timestamp: datetime

    activity_type: str

    domain: str | None
    url: str | None
    title: str | None

    search_query: str | None

    source_event_ids: list[int]


class SearchSimilarityResponse(
    BaseModel
):
    pair_index: int

    previous_query: str
    current_query: str

    similarity: float

    threshold: float

    is_semantic_loop: bool


class StuckSignalsResponse(
    BaseModel
):
    search_repeat: float
    search_revisit: float
    semantic_loop: float
    rapid_switch: float
    duration: float


class StuckDiagnosticsResponse(
    BaseModel
):
    activity_count: int
    search_count: int

    domain_switch_count: int
    rapid_switch_count: int

    semantic_similarity_avg: float


class StuckSignalResponse(
    BaseModel
):
    session_id: int

    stuck_score: float

    stuck_level: str

    is_stuck_candidate: bool

    signals: StuckSignalsResponse

    reasons: list[str]

    diagnostics: (
        StuckDiagnosticsResponse
    )


class SessionFeaturesResponse(
    BaseModel
):
    session_id: int

    activity_count: int

    duration_seconds: float

    tab_switch_count: int
    page_visit_count: int

    unique_domain_count: int

    domain_switch_count: int

    domain_revisit_count: int

    revisit_rate: float

    most_visited_domain: (
        str | None
    )

    same_domain_streak_max: int

    rapid_switch_count: int

    search_count: int

    unique_search_query_count: int

    repeated_search_count: int

    search_revisit_count: int

    semantic_search_pair_count: int

    semantic_search_loop_count: int

    semantic_search_similarity_avg: float

    semantic_search_similarity_max: float

    avg_seconds_between_activities: float

class SessionContextResponse(BaseModel):
    goal: str | None
    task: str | None
    state: str
    blocker: str | None
    summary: str
    confidence: float