"""Evening report generation and statistics summaries."""

from __future__ import annotations

from database.repository import BotRepository
from utils.time_utils import now_in_tz


async def build_and_save_evening_report(
    repo: BotRepository,
    user_id: int,
    user_name: str,
    tz_name: str = "Asia/Tashkent",
) -> str:
    stats = await repo.get_daily_stats(user_id, tz_name)
    today = now_in_tz(tz_name).date()
    total = stats["today_total"]
    completed = stats["today_completed"]
    pending = stats["today_pending"]
    pct = round((completed / total) * 100) if total > 0 else 100

    summary = (
        f"📊 <b>Kechki hisobot ({today.strftime('%d.%m.%Y')})</b>\n\n"
        f"Assalomu alaykum, {user_name}! Bugungi kun yakunlari:\n"
        f"• Jami vazifalar: <b>{total}</b>\n"
        f"• Bajarilgan: <b>{completed}</b> ({pct}%)\n"
        f"• Bajarilmagan: <b>{pending}</b>\n"
        f"• Amalga oshirilgan qo'ng'iroqlar: <b>{stats['today_calls_total']}</b> "
        f"(javob berilgan: {stats['today_calls_answered']})\n"
        f"• Faol takroriy eslatmalar: <b>{stats['recurring_active']}</b>"
    )

    await repo.save_daily_report(
        user_id=user_id,
        report_date=today,
        total_tasks=total,
        completed_tasks=completed,
        calls_made=stats["today_calls_total"],
        calls_answered=stats["today_calls_answered"],
        summary_text=summary,
    )
    return summary
