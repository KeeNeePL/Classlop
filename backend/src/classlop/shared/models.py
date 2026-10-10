import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from classlop.shared.db import Base
from classlop.shared.queue import MAX_RECEIVES

STATUSES = ("queued", "running", "succeeded", "failed", "waiting_for_sign_in")


class Job(Base):
    __tablename__ = "job"
    __table_args__ = (
        CheckConstraint(f"status IN {STATUSES}", name="job_status"),
        {"schema": "shared"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    key: Mapped[str | None] = mapped_column(Text, unique=True)
    status: Mapped[str] = mapped_column(Text, default="queued")
    progress: Mapped[dict | None] = mapped_column(JSONB)
    result: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    @property
    def final_attempt(self) -> bool:
        """The last try before SQS moves the message to the dead-letter queue."""
        return self.attempts >= MAX_RECEIVES


class TokenCache(Base):
    """The MSAL token cache: one row, since one Teacher signs in."""

    __tablename__ = "token_cache"
    __table_args__ = {"schema": "shared"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    data: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Schedule(Base):
    """Dev stand-in for EventBridge Scheduler: the `scheduler` service fires what is due."""

    __tablename__ = "schedule"
    __table_args__ = {"schema": "shared"}

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    next_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    every_seconds: Mapped[int | None] = mapped_column(Integer)
