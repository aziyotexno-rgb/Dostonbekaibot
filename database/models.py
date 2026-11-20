"""SQLAlchemy 2.0 ORM models for Dostonbek AI Bot."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class SchemaMigration(Base):
    __tablename__ = "schema_migrations"

    version: Mapped[str] = mapped_column(String(64), primary_key=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str] = mapped_column(String(128), default="Dostonbek")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Tashkent")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    settings: Mapped[Optional["BotSettings"]] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    reminders: Mapped[list["Reminder"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class BotSettings(Base):
    __tablename__ = "bot_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user_profiles.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    morning_call_time: Mapped[str] = mapped_column(String(5), default="08:00")
    evening_report_time: Mapped[str] = mapped_column(String(5), default="21:00")
    morning_call_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    evening_report_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    voice_name: Mapped[str] = mapped_column(String(64), default="uz-UZ-SardorNeural")
    voice_rate: Mapped[str] = mapped_column(String(16), default="+0%")
    default_reminder_mode: Mapped[str] = mapped_column(String(16), default="voice")

    # Retry & interactive call behavior
    retry_call_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    retry_call_delay_minutes: Mapped[int] = mapped_column(Integer, default=5)
    retry_call_max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    response_wait_seconds: Mapped[int] = mapped_column(Integer, default=15)

    # Quiet hours window (default 23:00 - 07:00 Asia/Tashkent)
    quiet_hours_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    quiet_hours_start: Mapped[str] = mapped_column(String(5), default="23:00")
    quiet_hours_end: Mapped[str] = mapped_column(String(5), default="07:00")

    # Admin-only PRO trial mode (simulation only, zero real billing)
    pro_trial_active: Mapped[bool] = mapped_column(Boolean, default=False)
    pro_trial_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    ai_style: Mapped[str] = mapped_column(String(24), default="friendly")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["UserProfile"] = relationship(back_populates="settings")


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    # once | daily | weekly | monthly | custom_days
    recurrence_type: Mapped[str] = mapped_column(String(24), default="once")
    recurrence_days: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    # text | voice | call
    delivery_method: Mapped[str] = mapped_column(String(16), default="voice")
    is_voice: Mapped[bool] = mapped_column(Boolean, default=True)

    # once | wait_response | retry_no_answer | until_completed
    reminder_policy: Mapped[str] = mapped_column(String(32), default="until_completed")
    attempts_count: Mapped[int] = mapped_column(Integer, default=0)
    last_response_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    awaiting_response: Mapped[bool] = mapped_column(Boolean, default=False)

    # pending | completed | cancelled
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    last_triggered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["UserProfile"] = relationship(back_populates="reminders")


class CallLog(Base):
    __tablename__ = "call_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reminder_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    caller_username: Mapped[str] = mapped_column(String(64), default="@Yordamchiaidosa")
    callee_username: Mapped[str] = mapped_column(String(64), default="@D_admin_aka")
    purpose: Mapped[str] = mapped_column(String(128), default="morning_briefing")
    # initiated | ringing | answered | completed | hung_up_unconfirmed | missed | declined | failed | unavailable
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    transcript_text: Mapped[str] = mapped_column(Text, default="")
    user_voice_reply: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    detected_intent: Mapped[Optional[str]] = mapped_column(String(48), nullable=True)
    error_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DailyReport(Base):
    __tablename__ = "daily_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    report_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    total_tasks: Mapped[int] = mapped_column(Integer, default=0)
    completed_tasks: Mapped[int] = mapped_column(Integer, default=0)
    calls_made: Mapped[int] = mapped_column(Integer, default=0)
    calls_answered: Mapped[int] = mapped_column(Integer, default=0)
    summary_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PendingConfirmation(Base):
    __tablename__ = "pending_confirmations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_reminder_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NotificationDispatch(Base):
    """Idempotency ledger guaranteeing Cron Job and Web Service never send duplicates."""

    __tablename__ = "notification_dispatches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True, nullable=False, index=True)
    dispatch_type: Mapped[str] = mapped_column(String(48), nullable=False)
    reminder_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(24), default="scheduler")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
