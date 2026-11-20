"""Repository layer encapsulating all database queries and idempotent dispatch."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    BotSettings,
    CallLog,
    DailyReport,
    NotificationDispatch,
    PendingConfirmation,
    Reminder,
    UserProfile,
)
from utils.time_utils import get_zone, now_in_tz, to_tz


class BotRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_or_create_user(
        self,
        telegram_id: int,
        username: Optional[str] = None,
        full_name: str = "Dostonbek",
        default_timezone: str = "Asia/Tashkent",
        default_voice_name: str = "uz-UZ-SardorNeural",
        default_voice_rate: str = "+0%",
    ) -> UserProfile:
        stmt = select(UserProfile).where(UserProfile.telegram_id == telegram_id)
        result = await self.session.execute(stmt)
        user = result.scalar_one_or_none()
        if user is None:
            user = UserProfile(
                telegram_id=telegram_id,
                username=username,
                full_name=full_name or "Dostonbek",
                timezone=default_timezone,
            )
            self.session.add(user)
            await self.session.flush()

            settings = BotSettings(
                user_id=user.id,
                voice_name=default_voice_name,
                voice_rate=default_voice_rate,
            )
            self.session.add(settings)
            await self.session.flush()
        else:
            if username and user.username != username:
                user.username = username
            if full_name and user.full_name != full_name:
                user.full_name = full_name
            await self.get_settings(user.id)
        return user

    async def get_settings(self, user_id: int) -> BotSettings:
        stmt = select(BotSettings).where(BotSettings.user_id == user_id)
        result = await self.session.execute(stmt)
        settings = result.scalar_one_or_none()
        if settings is None:
            settings = BotSettings(user_id=user_id)
            self.session.add(settings)
            await self.session.flush()
        return settings

    async def update_settings(self, user_id: int, **kwargs) -> BotSettings:
        settings = await self.get_settings(user_id)
        for key, value in kwargs.items():
            if hasattr(settings, key):
                setattr(settings, key, value)
        await self.session.flush()
        return settings

    async def is_pro_effective(self, user_id: int) -> bool:
        """Check whether admin-only PRO trial is active and unexpired."""
        cfg = await self.get_settings(user_id)
        if not cfg.pro_trial_active:
            return False
        if cfg.pro_trial_expires_at is not None:
            now_utc = datetime.now(timezone.utc)
            exp = (
                cfg.pro_trial_expires_at
                if cfg.pro_trial_expires_at.tzinfo
                else cfg.pro_trial_expires_at.replace(tzinfo=timezone.utc)
            )
            if exp <= now_utc:
                cfg.pro_trial_active = False
                await self.session.flush()
                return False
        return True

    async def activate_pro_trial(self, user_id: int, days: int = 7) -> BotSettings:
        expires = datetime.now(timezone.utc) + timedelta(days=days)
        return await self.update_settings(
            user_id, pro_trial_active=True, pro_trial_expires_at=expires
        )

    async def cancel_pro_trial(self, user_id: int) -> BotSettings:
        return await self.update_settings(
            user_id, pro_trial_active=False, pro_trial_expires_at=None
        )

    async def update_user_timezone(self, user_id: int, tz_name: str) -> UserProfile:
        stmt = select(UserProfile).where(UserProfile.id == user_id)
        user = (await self.session.execute(stmt)).scalar_one()
        user.timezone = tz_name
        await self.session.flush()
        return user

    async def create_reminder(
        self,
        user_id: int,
        title: str,
        scheduled_at: datetime,
        description: str = "",
        recurrence_type: str = "once",
        recurrence_days: Optional[str] = None,
        delivery_method: str = "voice",
        is_voice: bool = True,
        reminder_policy: str = "until_completed",
    ) -> Reminder:
        reminder = Reminder(
            user_id=user_id,
            title=title.strip()[:255],
            description=description.strip(),
            scheduled_at=scheduled_at,
            recurrence_type=recurrence_type,
            recurrence_days=recurrence_days,
            delivery_method=delivery_method,
            is_voice=is_voice,
            reminder_policy=reminder_policy,
            status="pending",
        )
        self.session.add(reminder)
        await self.session.flush()
        return reminder

    async def get_reminder(self, reminder_id: int, user_id: Optional[int] = None) -> Optional[Reminder]:
        stmt = select(Reminder).where(Reminder.id == reminder_id)
        if user_id is not None:
            stmt = stmt.where(Reminder.user_id == user_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_reminders(
        self,
        user_id: int,
        status: Optional[str] = None,
        recurring_only: bool = False,
        limit: int = 50,
    ) -> list[Reminder]:
        stmt = select(Reminder).where(Reminder.user_id == user_id)
        if status:
            stmt = stmt.where(Reminder.status == status)
        if recurring_only:
            stmt = stmt.where(Reminder.recurrence_type != "once")
        stmt = stmt.order_by(Reminder.scheduled_at.asc()).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_all_pending_reminders(self) -> list[Reminder]:
        stmt = (
            select(Reminder)
            .where(Reminder.status == "pending")
            .order_by(Reminder.scheduled_at.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_due_pending_reminders(self, reference_now: datetime) -> list[Reminder]:
        """Return pending reminders whose scheduled_at <= reference_now."""
        pending = await self.list_all_pending_reminders()
        due: list[Reminder] = []
        ref_utc = reference_now.astimezone(timezone.utc) if reference_now.tzinfo else reference_now.replace(tzinfo=timezone.utc)
        for rem in pending:
            sched = rem.scheduled_at
            sched_utc = sched.astimezone(timezone.utc) if sched.tzinfo else sched.replace(tzinfo=timezone.utc)
            if sched_utc <= ref_utc:
                due.append(rem)
        return due

    async def list_reminders_for_date(
        self, user_id: int, target_date: date, tz_name: str = "Asia/Tashkent"
    ) -> list[Reminder]:
        zone = get_zone(tz_name)
        start_local = datetime.combine(target_date, time.min).replace(tzinfo=zone)
        end_local = datetime.combine(target_date, time.max).replace(tzinfo=zone)
        stmt = (
            select(Reminder)
            .where(
                and_(
                    Reminder.user_id == user_id,
                    Reminder.status != "cancelled",
                )
            )
            .order_by(Reminder.scheduled_at.asc())
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        matched: list[Reminder] = []
        for rem in rows:
            local_dt = to_tz(rem.scheduled_at, tz_name)
            if start_local <= local_dt <= end_local:
                matched.append(rem)
        return matched

    async def update_reminder(self, reminder_id: int, user_id: int, **kwargs) -> Optional[Reminder]:
        rem = await self.get_reminder(reminder_id, user_id=user_id)
        if rem is None:
            return None
        for key, value in kwargs.items():
            if hasattr(rem, key):
                setattr(rem, key, value)
        await self.session.flush()
        return rem

    async def mark_completed(
        self, reminder_id: int, user_id: int, response_text: Optional[str] = None
    ) -> Optional[Reminder]:
        rem = await self.get_reminder(reminder_id, user_id=user_id)
        if rem is None:
            return None
        rem.status = "completed"
        rem.awaiting_response = False
        rem.completed_at = datetime.now(timezone.utc)
        if response_text:
            rem.last_response_text = response_text
        await self.session.flush()
        return rem

    async def mark_cancelled(
        self, reminder_id: int, user_id: int, response_text: Optional[str] = None
    ) -> Optional[Reminder]:
        rem = await self.get_reminder(reminder_id, user_id=user_id)
        if rem is None:
            return None
        rem.status = "cancelled"
        rem.awaiting_response = False
        if response_text:
            rem.last_response_text = response_text
        await self.session.flush()
        return rem

    async def delete_reminder(self, reminder_id: int, user_id: int) -> bool:
        rem = await self.get_reminder(reminder_id, user_id=user_id)
        if rem is None:
            return False
        await self.session.delete(rem)
        await self.session.flush()
        return True

    async def find_matching_reminders(
        self,
        user_id: int,
        query_text: Optional[str] = None,
        target_date: Optional[date] = None,
        target_hour: Optional[int] = None,
        tz_name: str = "Asia/Tashkent",
    ) -> list[Reminder]:
        pending = await self.list_reminders(user_id=user_id, status="pending", limit=100)
        results: list[Reminder] = []
        q_lower = (query_text or "").strip().lower()
        for rem in pending:
            local_dt = to_tz(rem.scheduled_at, tz_name)
            if target_date and local_dt.date() != target_date:
                continue
            if target_hour is not None and local_dt.hour != target_hour:
                continue
            if q_lower and q_lower not in rem.title.lower() and q_lower not in rem.description.lower():
                continue
            results.append(rem)
        return results

    async def claim_dispatch_key(
        self,
        idempotency_key: str,
        dispatch_type: str,
        reminder_id: Optional[int] = None,
        source: str = "scheduler",
    ) -> bool:
        """Atomically claim a notification key so Web Service & Cron Job never duplicate."""
        existing = (
            await self.session.execute(
                select(NotificationDispatch).where(
                    NotificationDispatch.idempotency_key == idempotency_key
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return False

        try:
            async with self.session.begin_nested():
                entry = NotificationDispatch(
                    idempotency_key=idempotency_key[:160],
                    dispatch_type=dispatch_type,
                    reminder_id=reminder_id,
                    source=source,
                )
                self.session.add(entry)
                await self.session.flush()
            return True
        except IntegrityError:
            return False

    async def create_pending_confirmation(
        self,
        user_id: int,
        action_type: str,
        target_reminder_id: Optional[int],
        payload: dict,
        ttl_minutes: int = 10,
    ) -> PendingConfirmation:
        expires = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
        pc = PendingConfirmation(
            user_id=user_id,
            action_type=action_type,
            target_reminder_id=target_reminder_id,
            payload_json=json.dumps(payload, ensure_ascii=False),
            expires_at=expires,
        )
        self.session.add(pc)
        await self.session.flush()
        return pc

    async def get_pending_confirmation(
        self, confirmation_id: int, user_id: int
    ) -> Optional[PendingConfirmation]:
        stmt = select(PendingConfirmation).where(
            and_(
                PendingConfirmation.id == confirmation_id,
                PendingConfirmation.user_id == user_id,
            )
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def delete_pending_confirmation(self, confirmation_id: int) -> None:
        stmt = select(PendingConfirmation).where(PendingConfirmation.id == confirmation_id)
        pc = (await self.session.execute(stmt)).scalar_one_or_none()
        if pc is not None:
            await self.session.delete(pc)
            await self.session.flush()

    async def log_call(
        self,
        user_id: int,
        caller_username: str,
        callee_username: str,
        purpose: str,
        status: str,
        duration_seconds: int = 0,
        transcript_text: str = "",
        error_detail: Optional[str] = None,
        attempt_number: int = 1,
        reminder_id: Optional[int] = None,
        user_voice_reply: Optional[str] = None,
        detected_intent: Optional[str] = None,
    ) -> CallLog:
        entry = CallLog(
            user_id=user_id,
            reminder_id=reminder_id,
            caller_username=caller_username,
            callee_username=callee_username,
            purpose=purpose,
            status=status,
            duration_seconds=duration_seconds,
            transcript_text=transcript_text,
            user_voice_reply=user_voice_reply,
            detected_intent=detected_intent,
            error_detail=error_detail,
            attempt_number=attempt_number,
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def list_recent_calls(self, user_id: int, limit: int = 10) -> list[CallLog]:
        stmt = (
            select(CallLog)
            .where(CallLog.user_id == user_id)
            .order_by(CallLog.created_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def save_daily_report(
        self,
        user_id: int,
        report_date: date,
        total_tasks: int,
        completed_tasks: int,
        calls_made: int,
        calls_answered: int,
        summary_text: str,
    ) -> DailyReport:
        stmt = select(DailyReport).where(
            and_(DailyReport.user_id == user_id, DailyReport.report_date == report_date)
        )
        existing = (await self.session.execute(stmt)).scalar_one_or_none()
        if existing:
            existing.total_tasks = total_tasks
            existing.completed_tasks = completed_tasks
            existing.calls_made = calls_made
            existing.calls_answered = calls_answered
            existing.summary_text = summary_text
            await self.session.flush()
            return existing

        report = DailyReport(
            user_id=user_id,
            report_date=report_date,
            total_tasks=total_tasks,
            completed_tasks=completed_tasks,
            calls_made=calls_made,
            calls_answered=calls_answered,
            summary_text=summary_text,
        )
        self.session.add(report)
        await self.session.flush()
        return report

    async def get_daily_stats(self, user_id: int, tz_name: str = "Asia/Tashkent") -> dict:
        today = now_in_tz(tz_name).date()
        todays_reminders = await self.list_reminders_for_date(user_id, today, tz_name)
        total = len(todays_reminders)
        completed = sum(1 for r in todays_reminders if r.status == "completed")
        pending = sum(1 for r in todays_reminders if r.status == "pending")

        recent_calls = await self.list_recent_calls(user_id, limit=25)
        today_calls = [
            c for c in recent_calls if c.created_at and to_tz(c.created_at, tz_name).date() == today
        ]
        answered_calls = sum(
            1 for c in today_calls if c.status in {"answered", "completed"}
        )

        all_pending = await self.list_reminders(user_id=user_id, status="pending", limit=200)
        recurring_count = sum(1 for r in all_pending if r.recurrence_type != "once")

        return {
            "date": today.isoformat(),
            "today_total": total,
            "today_completed": completed,
            "today_pending": pending,
            "recurring_active": recurring_count,
            "today_calls_total": len(today_calls),
            "today_calls_answered": answered_calls,
        }
