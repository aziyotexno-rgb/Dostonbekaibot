"""Daily statistics handler."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from database.engine import DatabaseManager
from database.repository import BotRepository
from keyboards.inline import back_home_kb

router = Router(name="stats")


@router.callback_query(F.data == "menu:stats")
async def cb_stats(callback: CallbackQuery, db: DatabaseManager) -> None:
    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(callback.from_user.id)
        stats = await repo.get_daily_stats(user.id, user.timezone)

    total = stats["today_total"]
    done = stats["today_completed"]
    pct = round((done / total) * 100) if total > 0 else 0

    text = (
        f"📊 <b>Kunlik statistika ({stats['date']})</b>\n\n"
        f"• Bugungi jami vazifalar: <b>{total}</b>\n"
        f"• Bajarilgan: <b>{done}</b> ({pct}%)\n"
        f"• Kutilayotgan: <b>{stats['today_pending']}</b>\n"
        f"• Faol takroriy eslatmalar: <b>{stats['recurring_active']}</b>\n"
        f"• Bugungi qo‘ng‘iroqlar: <b>{stats['today_calls_total']}</b> "
        f"(javob berilgan: <b>{stats['today_calls_answered']}</b>)"
    )

    if callback.message:
        await callback.message.edit_text(
            text, reply_markup=back_home_kb(), parse_mode="HTML"
        )
    await callback.answer()
