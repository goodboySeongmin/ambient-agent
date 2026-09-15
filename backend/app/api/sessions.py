from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
)

from sqlalchemy import (
    text,
)

from sqlalchemy.orm import (
    Session as DBSession,
)

from app.db.database import (
    SessionLocal,
)

from app.services.activity_normalizer import (
    get_normalized_activities,
)

from app.services.context_engine import (
    infer_session_context,
)

from app.services.context_selector import (
    build_context_selection,
)

from app.services.semantic_similarity import (
    calculate_search_similarity_pairs,
)

from app.services.session_features import (
    calculate_session_features,
)

from app.services.stuck_signal_engine import (
    calculate_stuck_signal,
)

from app.services.intervention_engine import (
    calculate_intervention,
)

from app.services.solution_engine import (
    generate_solution,
)

router = APIRouter()


# =========================================================
# Database Dependency
# =========================================================

def get_db():
    db = SessionLocal()

    try:
        yield db

    finally:
        db.close()


# =========================================================
# Current Session Resolver
# =========================================================

def get_current_session_record(
    db: DBSession,
):
    """
    가장 최근 last_event_at을 가진 session을 반환한다.
    """

    result = db.execute(
        text(
            """
            SELECT
                id,
                started_at,
                last_event_at,
                event_count
            FROM sessions
            ORDER BY last_event_at DESC
            LIMIT 1
            """
        )
    ).mappings().first()

    if result is None:
        raise ValueError(
            "생성된 session이 없습니다."
        )

    return result


def get_current_session_id(
    db: DBSession,
) -> int:
    record = (
        get_current_session_record(
            db
        )
    )

    return int(
        record[
            "id"
        ]
    )


# =========================================================
# Serialization
# =========================================================

def serialize_activity(
    activity,
):
    return {
        "timestamp": (
            activity.timestamp.isoformat()
            if activity.timestamp
            else None
        ),

        "activity_type": (
            activity.activity_type
        ),

        "domain": (
            activity.domain
        ),

        "url": (
            activity.url
        ),

        "title": (
            activity.title
        ),

        "search_query": (
            activity.search_query
        ),

        "source_event_ids": (
            activity.source_event_ids
        ),
    }


# =========================================================
# CURRENT SESSION APIs
# =========================================================

@router.get(
    "/sessions/current"
)
def get_current_session(
    db: DBSession = Depends(
        get_db
    ),
):
    try:
        record = (
            get_current_session_record(
                db
            )
        )

        return {
            "id": record[
                "id"
            ],

            "started_at": (
                record[
                    "started_at"
                ].isoformat()
                if record[
                    "started_at"
                ]
                else None
            ),

            "last_event_at": (
                record[
                    "last_event_at"
                ].isoformat()
                if record[
                    "last_event_at"
                ]
                else None
            ),

            "event_count": (
                record[
                    "event_count"
                ]
            ),
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(
                exc
            ),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                f"{type(exc).__name__}: {exc}"
            ),
        )


@router.get(
    "/sessions/current/context-selection"
)
def get_current_context_selection(
    db: DBSession = Depends(
        get_db
    ),
):
    try:
        session_id = (
            get_current_session_id(
                db
            )
        )

        return (
            build_context_selection(
                db,
                session_id,
            )
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(
                exc
            ),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                f"{type(exc).__name__}: {exc}"
            ),
        )


@router.get(
    "/sessions/current/stuck-signal"
)
def get_current_stuck_signal(
    db: DBSession = Depends(
        get_db
    ),
):
    try:
        session_id = (
            get_current_session_id(
                db
            )
        )

        return (
            calculate_stuck_signal(
                db,
                session_id,
            )
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(
                exc
            ),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                f"{type(exc).__name__}: {exc}"
            ),
        )


@router.get(
    "/sessions/current/context"
)
def get_current_context(
    db: DBSession = Depends(
        get_db
    ),
):
    try:
        session_id = (
            get_current_session_id(
                db
            )
        )

        return (
            infer_session_context(
                db,
                session_id,
            )
        )

    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(
                exc
            ),
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(
                exc
            ),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                f"{type(exc).__name__}: {exc}"
            ),
        )

@router.get(
    "/sessions/current/intervention"
)
def get_current_intervention(
    db: DBSession = Depends(
        get_db
    ),
):
    try:
        session_id = (
            get_current_session_id(
                db
            )
        )

        return (
            calculate_intervention(
                db,
                session_id,
            )
        )

    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(
                exc
            ),
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(
                exc
            ),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                f"{type(exc).__name__}: {exc}"
            ),
        )
    
# =========================================================
# Session Features
# =========================================================

@router.get(
    "/sessions/{session_id}/features"
)
def get_session_features(
    session_id: int,
    db: DBSession = Depends(
        get_db
    ),
):
    try:
        return (
            calculate_session_features(
                db,
                session_id,
            )
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(
                exc
            ),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                f"{type(exc).__name__}: {exc}"
            ),
        )


# =========================================================
# Activities
# =========================================================

@router.get(
    "/sessions/{session_id}/activities"
)
def get_session_activities(
    session_id: int,
    db: DBSession = Depends(
        get_db
    ),
):
    try:
        activities = (
            get_normalized_activities(
                db,
                session_id,
            )
        )

        if not activities:
            raise ValueError(
                f"session_id={session_id}에 활동 데이터가 없습니다."
            )

        return [
            serialize_activity(
                activity
            )
            for activity in activities
        ]

    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(
                exc
            ),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                f"{type(exc).__name__}: {exc}"
            ),
        )


# =========================================================
# Search Similarity
# =========================================================

@router.get(
    "/sessions/{session_id}/search-similarities"
)
def get_session_search_similarities(
    session_id: int,
    db: DBSession = Depends(
        get_db
    ),
):
    try:
        activities = (
            get_normalized_activities(
                db,
                session_id,
            )
        )

        if not activities:
            raise ValueError(
                f"session_id={session_id}에 활동 데이터가 없습니다."
            )

        search_queries = []

        for activity in activities:
            if (
                activity.activity_type
                == "search"
                and activity.search_query
            ):
                search_queries.append(
                    activity.search_query
                )

        return (
            calculate_search_similarity_pairs(
                search_queries
            )
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(
                exc
            ),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                f"{type(exc).__name__}: {exc}"
            ),
        )


# =========================================================
# Stuck Signal
# =========================================================

@router.get(
    "/sessions/{session_id}/stuck-signal"
)
def get_session_stuck_signal(
    session_id: int,
    db: DBSession = Depends(
        get_db
    ),
):
    try:
        return (
            calculate_stuck_signal(
                db,
                session_id,
            )
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(
                exc
            ),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                f"{type(exc).__name__}: {exc}"
            ),
        )


# =========================================================
# Context Selection
# =========================================================

@router.get(
    "/sessions/{session_id}/context-selection"
)
def get_session_context_selection(
    session_id: int,
    db: DBSession = Depends(
        get_db
    ),
):
    try:
        return (
            build_context_selection(
                db,
                session_id,
            )
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(
                exc
            ),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                f"{type(exc).__name__}: {exc}"
            ),
        )


# =========================================================
# Context
# =========================================================

@router.get(
    "/sessions/{session_id}/context"
)
def get_session_context(
    session_id: int,
    db: DBSession = Depends(
        get_db
    ),
):
    try:
        return (
            infer_session_context(
                db,
                session_id,
            )
        )

    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(
                exc
            ),
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(
                exc
            ),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                f"{type(exc).__name__}: {exc}"
            ),
        )

# =========================================================
# Solution Agent
# =========================================================

@router.post(
    "/sessions/current/solution"
)
def get_current_solution(
    db: DBSession = Depends(
        get_db
    ),
):
    try:
        session_id = (
            get_current_session_id(
                db
            )
        )

        return (
            generate_solution(
                db,
                session_id,
            )
        )

    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(
                exc
            ),
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(
                exc
            ),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                f"{type(exc).__name__}: {exc}"
            ),
        )
