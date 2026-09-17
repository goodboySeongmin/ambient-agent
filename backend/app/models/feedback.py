from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class Feedback(Base):
    __tablename__ = "feedback_events"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id"),
        nullable=False,
        index=True,
    )

    feedback_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    context_fingerprint: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )

    goal: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    task: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    blocker: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    context_state: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        index=True,
    )

    context_confidence: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    stuck_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    intervention_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
