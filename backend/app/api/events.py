from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.db.database import SessionLocal
from app.models.event import Event
from app.models.session import Session
from app.schemas.event import EventCreate, EventResponse


router = APIRouter(
    prefix="/events",
    tags=["events"],
)


SESSION_TIMEOUT = timedelta(minutes=10)


def get_db():
    db = SessionLocal()

    try:
        yield db

    finally:
        db.close()


def get_or_create_session(
    db: DBSession,
) -> Session:
    now = datetime.now(timezone.utc)

    statement = (
        select(Session)
        .order_by(Session.last_event_at.desc())
        .limit(1)
    )

    latest_session = db.scalar(statement)

    if latest_session is None:
        new_session = Session(
            started_at=now,
            last_event_at=now,
            event_count=0,
        )

        db.add(new_session)
        db.flush()

        return new_session

    if (
        now - latest_session.last_event_at
        > SESSION_TIMEOUT
    ):
        new_session = Session(
            started_at=now,
            last_event_at=now,
            event_count=0,
        )

        db.add(new_session)
        db.flush()

        return new_session

    return latest_session


@router.post(
    "",
    response_model=EventResponse,
    status_code=201,
)
def create_event(
    event_data: EventCreate,
    db: DBSession = Depends(get_db),
):
    current_session = get_or_create_session(db)

    event = Event(
        session_id=current_session.id,
        source=event_data.source,
        event_type=event_data.event_type,
        url=event_data.url,
        title=event_data.title,
        domain=event_data.domain,
        search_query=event_data.search_query,
        is_sensitive=event_data.is_sensitive,
    )

    db.add(event)

    current_session.last_event_at = (
        datetime.now(timezone.utc)
    )

    current_session.event_count += 1

    db.commit()
    db.refresh(event)

    return event


@router.get(
    "",
    response_model=list[EventResponse],
)
def get_events(
    limit: int = 50,
    db: DBSession = Depends(get_db),
):
    statement = (
        select(Event)
        .order_by(Event.timestamp.desc())
        .limit(limit)
    )

    events = db.scalars(
        statement
    ).all()

    return events