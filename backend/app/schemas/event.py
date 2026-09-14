from datetime import datetime

from pydantic import BaseModel, ConfigDict


class EventCreate(BaseModel):
    source: str
    event_type: str

    url: str | None = None
    title: str | None = None
    domain: str | None = None

    search_query: str | None = None

    is_sensitive: bool = False


class EventResponse(BaseModel):
    id: int
    session_id: int | None

    timestamp: datetime

    source: str
    event_type: str

    url: str | None = None
    title: str | None = None
    domain: str | None = None

    search_query: str | None = None

    is_sensitive: bool

    model_config = ConfigDict(
        from_attributes=True
    )