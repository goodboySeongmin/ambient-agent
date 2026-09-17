import hashlib
import re
from typing import Any

from sqlalchemy.orm import Session as DBSession

from app.models.feedback import Feedback


ALLOWED_FEEDBACK_TYPES = {
    "accepted",
    "dismissed",
    "helpful",
    "not_helpful",
}


def _normalize_context_text(
    value: Any,
) -> str:
    if value is None:
        return ""

    text = str(value).strip().lower()

    return re.sub(
        r"\s+",
        " ",
        text,
    )


def build_context_fingerprint(
    context: dict[str, Any],
) -> str | None:
    parts = [
        _normalize_context_text(
            context.get("goal")
        ),
        _normalize_context_text(
            context.get("task")
        ),
        _normalize_context_text(
            context.get("blocker")
        ),
    ]

    if not any(parts):
        return None

    raw = "\n".join(parts)

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()


def create_feedback(
    db: DBSession,
    current_session_id: int,
    feedback_type: str,
    intervention_snapshot: dict[str, Any],
) -> Feedback:
    if (
        feedback_type
        not in ALLOWED_FEEDBACK_TYPES
    ):
        raise ValueError(
            f"지원하지 않는 feedback_type입니다: "
            f"{feedback_type}"
        )

    snapshot_session_id = int(
        intervention_snapshot.get(
            "session_id",
            0,
        )
    )

    if (
        snapshot_session_id
        != current_session_id
    ):
        raise ValueError(
            "현재 session과 intervention snapshot의 "
            "session_id가 일치하지 않습니다."
        )

    context = (
        intervention_snapshot.get(
            "context"
        )
        or {}
    )

    stuck_signal = (
        intervention_snapshot.get(
            "stuck_signal"
        )
        or {}
    )

    context_fingerprint = (
        build_context_fingerprint(
            context
        )
    )

    if context_fingerprint is None:
        raise ValueError(
            "feedback을 저장할 수 있는 "
            "유효한 context가 없습니다."
        )

    feedback = Feedback(
        session_id=current_session_id,
        feedback_type=feedback_type,
        context_fingerprint=(
            context_fingerprint
        ),
        goal=context.get("goal"),
        task=context.get("task"),
        blocker=context.get("blocker"),
        context_state=context.get(
            "state",
            "unknown",
        ),
        context_confidence=float(
            context.get(
                "confidence",
                0.0,
            )
        ),
        stuck_score=float(
            stuck_signal.get(
                "stuck_score",
                0.0,
            )
        ),
        intervention_score=float(
            intervention_snapshot.get(
                "intervention_score",
                0.0,
            )
        ),
    )

    db.add(feedback)
    db.commit()
    db.refresh(feedback)

    return feedback


def serialize_feedback(
    feedback: Feedback,
) -> dict[str, Any]:
    return {
        "id": feedback.id,
        "session_id": feedback.session_id,
        "feedback_type": (
            feedback.feedback_type
        ),
        "context_fingerprint": (
            feedback.context_fingerprint
        ),
        "goal": feedback.goal,
        "task": feedback.task,
        "blocker": feedback.blocker,
        "context_state": (
            feedback.context_state
        ),
        "context_confidence": (
            feedback.context_confidence
        ),
        "stuck_score": (
            feedback.stuck_score
        ),
        "intervention_score": (
            feedback.intervention_score
        ),
        "created_at": (
            feedback.created_at.isoformat()
        ),
    }


def apply_feedback_suppression(
    db: DBSession,
    intervention: dict[str, Any],
) -> dict[str, Any]:
    result = dict(intervention)

    result["suppressed"] = False
    result["suppression_reason"] = None

    session_id = intervention.get(
        "session_id"
    )

    context = (
        intervention.get("context")
        or {}
    )

    if session_id is None:
        return result

    context_fingerprint = (
        build_context_fingerprint(
            context
        )
    )

    if context_fingerprint is None:
        return result

    latest_feedback = (
        db.query(Feedback)
        .filter(
            Feedback.session_id
            == int(session_id),
            Feedback.context_fingerprint
            == context_fingerprint,
            Feedback.feedback_type.in_(
                [
                    "accepted",
                    "dismissed",
                ]
            ),
        )
        .order_by(
            Feedback.created_at.desc(),
            Feedback.id.desc(),
        )
        .first()
    )

    if latest_feedback is None:
        return result

    if (
        latest_feedback.feedback_type
        != "dismissed"
    ):
        return result

    result["should_intervene"] = False
    result["suppressed"] = True
    result["suppression_reason"] = (
        "user_dismissed_same_context"
    )

    return result
