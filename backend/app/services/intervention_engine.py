from __future__ import annotations

from typing import Any

from app.services.context_engine import (
    infer_session_context,
)

from app.services.stuck_signal_engine import (
    calculate_stuck_signal,
)


# =========================================================
# Thresholds
# =========================================================

INTERVENTION_THRESHOLD = 0.60
STRONG_INTERVENTION_THRESHOLD = 0.80

MIN_CONTEXT_CONFIDENCE = 0.40
MIN_STUCK_SCORE = 0.40


# =========================================================
# Helpers
# =========================================================

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


def _has_text(
    value: str | None,
) -> bool:
    if value is None:
        return False

    return bool(
        str(value).strip()
    )


# =========================================================
# Component Scores
# =========================================================

def _calculate_need_score(
    stuck_signal: dict[str, Any],
) -> float:
    return _clamp(
        float(
            stuck_signal.get(
                "stuck_score",
                0.0,
            )
        )
    )


def _calculate_confidence_score(
    context: dict[str, Any],
) -> float:
    return _clamp(
        float(
            context.get(
                "confidence",
                0.0,
            )
        )
    )


def _calculate_task_clarity_score(
    context: dict[str, Any],
) -> float:
    score = 0.0

    if _has_text(
        context.get(
            "goal"
        )
    ):
        score += 0.4

    if _has_text(
        context.get(
            "task"
        )
    ):
        score += 0.6

    return _clamp(
        score
    )


def _calculate_blocker_score(
    context: dict[str, Any],
) -> float:
    if _has_text(
        context.get(
            "blocker"
        )
    ):
        return 1.0

    return 0.0


def _calculate_interruption_cost(
    context: dict[str, Any],
    stuck_signal: dict[str, Any],
) -> float:
    state = context.get(
        "state",
        "unknown",
    )

    confidence = float(
        context.get(
            "confidence",
            0.0,
        )
    )

    stuck_score = float(
        stuck_signal.get(
            "stuck_score",
            0.0,
        )
    )

    cost = 0.0

    if state == "idle":
        return 1.0

    if state == "unknown":
        cost += 0.40

    if state == "reading":
        cost += 0.15

    if confidence < 0.30:
        cost += 0.25

    if stuck_score < 0.20:
        cost += 0.25

    elif stuck_score < 0.40:
        cost += 0.10

    return _clamp(
        cost
    )


# =========================================================
# Hard Gates
# =========================================================

def _apply_hard_gate(
    context: dict[str, Any],
    stuck_signal: dict[str, Any],
) -> tuple[bool, str | None]:
    state = context.get(
        "state",
        "unknown",
    )

    confidence = float(
        context.get(
            "confidence",
            0.0,
        )
    )

    stuck_score = float(
        stuck_signal.get(
            "stuck_score",
            0.0,
        )
    )

    if state == "idle":
        return (
            False,
            "사용자가 현재 비활성 상태입니다.",
        )

    if stuck_score < MIN_STUCK_SCORE:
        return (
            False,
            "현재 막힘 신호가 충분하지 않습니다.",
        )

    if (
        state == "unknown"
        and confidence < MIN_CONTEXT_CONFIDENCE
    ):
        return (
            False,
            "현재 작업 맥락을 충분히 이해하지 못했습니다.",
        )

    return (
        True,
        None,
    )


# =========================================================
# Recommended Action
# =========================================================

def _build_recommended_action(
    context: dict[str, Any],
) -> str | None:
    blocker = context.get(
        "blocker"
    )

    task = context.get(
        "task"
    )

    state = context.get(
        "state"
    )

    if _has_text(
        blocker
    ):
        return (
            f"현재 문제인 '{blocker}' 해결을 도울 수 있다고 제안합니다."
        )

    if (
        state == "debugging"
        and _has_text(
            task
        )
    ):
        return (
            f"'{task}' 문제 해결을 도울 수 있다고 제안합니다."
        )

    if _has_text(
        task
    ):
        return (
            f"현재 작업인 '{task}'을 도울 수 있다고 제안합니다."
        )

    return None


# =========================================================
# Public API
# =========================================================

def calculate_intervention(
    db,
    session_id: int,
) -> dict[str, Any]:
    context = infer_session_context(
        db,
        session_id,
    )

    stuck_signal = calculate_stuck_signal(
        db,
        session_id,
    )

    gate_passed, gate_reason = (
        _apply_hard_gate(
            context,
            stuck_signal,
        )
    )

    if not gate_passed:
        return {
            "session_id": session_id,

            "should_intervene": False,

            "intervention_score": 0.0,

            "level": "none",

            "reason": gate_reason,

            "recommended_action": None,

            "components": {
                "need": round(
                    _calculate_need_score(
                        stuck_signal
                    ),
                    4,
                ),

                "confidence": round(
                    _calculate_confidence_score(
                        context
                    ),
                    4,
                ),

                "task_clarity": round(
                    _calculate_task_clarity_score(
                        context
                    ),
                    4,
                ),

                "blocker": round(
                    _calculate_blocker_score(
                        context
                    ),
                    4,
                ),

                "interruption_cost": round(
                    _calculate_interruption_cost(
                        context,
                        stuck_signal,
                    ),
                    4,
                ),
            },

            "context": context,

            "stuck_signal": {
                "stuck_score": stuck_signal.get(
                    "stuck_score",
                    0.0,
                ),

                "stuck_level": stuck_signal.get(
                    "stuck_level",
                    "low",
                ),

                "is_stuck_candidate": stuck_signal.get(
                    "is_stuck_candidate",
                    False,
                ),
            },
        }

    need = _calculate_need_score(
        stuck_signal
    )

    confidence = _calculate_confidence_score(
        context
    )

    task_clarity = _calculate_task_clarity_score(
        context
    )

    blocker = _calculate_blocker_score(
        context
    )

    interruption_cost = _calculate_interruption_cost(
        context,
        stuck_signal,
    )

    score = (
        need * 0.50
        + confidence * 0.20
        + task_clarity * 0.15
        + blocker * 0.15
        - interruption_cost
    )

    score = round(
        _clamp(
            score
        ),
        4,
    )

    should_intervene = (
        score
        >= INTERVENTION_THRESHOLD
    )

    if (
        score
        >= STRONG_INTERVENTION_THRESHOLD
    ):
        level = "strong"

    elif (
        score
        >= INTERVENTION_THRESHOLD
    ):
        level = "suggest"

    else:
        level = "none"

    if should_intervene:
        reason = (
            "현재 막힘 신호와 작업 맥락이 충분히 명확해 "
            "선제적 도움을 제안할 가치가 있습니다."
        )

    else:
        reason = (
            "막힘 신호는 있으나 현재 개입하기에는 "
            "확신이나 기대 가치가 충분하지 않습니다."
        )

    return {
        "session_id": session_id,

        "should_intervene": (
            should_intervene
        ),

        "intervention_score": score,

        "level": level,

        "reason": reason,

        "recommended_action": (
            _build_recommended_action(
                context
            )
            if should_intervene
            else None
        ),

        "components": {
            "need": round(
                need,
                4,
            ),

            "confidence": round(
                confidence,
                4,
            ),

            "task_clarity": round(
                task_clarity,
                4,
            ),

            "blocker": round(
                blocker,
                4,
            ),

            "interruption_cost": round(
                interruption_cost,
                4,
            ),
        },

        "context": context,

        "stuck_signal": {
            "stuck_score": (
                stuck_signal.get(
                    "stuck_score",
                    0.0,
                )
            ),

            "stuck_level": (
                stuck_signal.get(
                    "stuck_level",
                    "low",
                )
            ),

            "is_stuck_candidate": (
                stuck_signal.get(
                    "is_stuck_candidate",
                    False,
                )
            ),
        },
    }