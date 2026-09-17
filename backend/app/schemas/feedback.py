from typing import Literal

from pydantic import BaseModel


FeedbackType = Literal[
    "accepted",
    "dismissed",
    "helpful",
    "not_helpful",
]


class FeedbackContextSnapshot(BaseModel):
    goal: str | None = None
    task: str | None = None
    state: str = "unknown"
    blocker: str | None = None
    confidence: float = 0.0


class FeedbackStuckSnapshot(BaseModel):
    stuck_score: float = 0.0


class FeedbackInterventionSnapshot(BaseModel):
    session_id: int
    intervention_score: float = 0.0
    context: FeedbackContextSnapshot
    stuck_signal: FeedbackStuckSnapshot


class FeedbackCreate(BaseModel):
    feedback_type: FeedbackType
    intervention: FeedbackInterventionSnapshot


class FeedbackResponse(BaseModel):
    id: int
    session_id: int
    feedback_type: FeedbackType
    context_fingerprint: str | None
    goal: str | None
    task: str | None
    blocker: str | None
    context_state: str | None
    context_confidence: float | None
    stuck_score: float | None
    intervention_score: float | None
    created_at: str
