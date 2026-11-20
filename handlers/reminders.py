"""Reminder CRUD, FSM creation wizard, editing, completion, and safe delete confirmations."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from database.engine import DatabaseManager
from database.repository import BotRepository
from keyboards.inline import (
    back_home_kb,
    confirm_delete_kb,
    custom_days_kb,
    delivery_method_kb,
    recurrence_kb,
    reminder_detail_kb,
    reminder_list_kb,
    reminder_policy_kb,
)
from scheduler.jobs import BotScheduler
from services.reminder_service import format_reminder_card
from utils.time_utils import (
    combine_local,
    format_recurrence_uz,
    format_uz_datetime,
    now_in_tz,
    parse_user_date,
    parse_user_time,
    to_tz,
)

router = Router(name="reminders")


class NewReminderStates(StatesGroup):
    title = State()
    description = State()
    date = State()
    time = State()
    recurrence = State()
    custom_days = State()
    method = State()
    policy = State()


class EditReminderStates(StatesGroup):
    title = State()
    time = State()


@router.callback_query(F.data == "menu:today")
async def cb_today(callback: CallbackQuery, db: DatabaseManager) -> None:
    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(callback.from_user.id)
        today = now_in_tz(user.timezone).date()
        items = await repo.list_reminders_for_date(user.id, today, user.timezone)

    if not items:
        text = "📅 <b>Bugungi rejalar</b>\n\nBugun uchun rejalashtirilgan eslatmalar yo‘q."
        kb = back_home_kb()
    else:
        cards = [format_reminder_card(r, user.timezone) for r in items]
        text = f"📅 <b>Bugungi rejalar ({today.strftime('%d.%m.%Y')})</b>\n\n" + "\n\n".join(cards)
        kb = reminder_list_kb(items)

    if callback.message:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "menu:all_reminders")
async def cb_all_reminders(callback: CallbackQuery, db: DatabaseManager) -> None:
    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(callback.from_user.id)
        items = await repo.list_reminders(user.id, limit=20)

    if not items:
        text = "📝 <b>Barcha eslatmalar</b>\n\nHozircha eslatmalar mavjud emas."
        kb = back_home_kb()
    else:
        cards = [format_reminder_card(r, user.timezone) for r in items[:10]]
        text = "📝 <b>Barcha eslatmalar</b>\n\n" + "\n\n".join(cards)
        kb = reminder_list_kb(items)

    if callback.message:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "menu:recurring")
async def cb_recurring(callback: CallbackQuery, db: DatabaseManager) -> None:
    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(callback.from_user.id)
        items = await repo.list_reminders(user.id, status="pending", recurring_only=True, limit=20)

    if not items:
        text = "🔔 <b>Takroriy eslatmalar</b>\n\nHozircha faol takroriy eslatmalar yo‘q."
        kb = back_home_kb()
    else:
        lines = []
        for rem in items:
            rec_label = format_recurrence_uz(rem.recurrence_type, rem.recurrence_days)
            lines.append(f"{format_reminder_card(rem, user.timezone)}\n   🔁 {rec_label}")
        text = "🔔 <b>Takroriy eslatmalar</b>\n\n" + "\n\n".join(lines)
        kb = reminder_list_kb(items)

    if callback.message:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "menu:new_reminder")
async def cb_new_reminder(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(NewReminderStates.title)
    if callback.message:
        await callback.message.edit_text(
            "➕ <b>Yangi eslatma yaratish</b>\n\n1/6 — Vazifa nomini kiriting:",
            reply_markup=back_home_kb(),
            parse_mode="HTML",
        )
    await callback.answer()


@router.message(NewReminderStates.title)
async def fsm_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if not title:
        await message.answer("Iltimos, vazifa nomini matn ko‘rinishida kiriting.")
        return
    await state.update_data(title=title)
    await state.set_state(NewReminderStates.description)
    await message.answer(
        "2/6 — Vazifa tavsifini kiriting (yoki bo‘sh qoldirish uchun <code>-</code> yozing):",
        parse_mode="HTML",
    )


@router.message(NewReminderStates.description)
async def fsm_description(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    desc = "" if raw == "-" else raw
    await state.update_data(description=desc)
    await state.set_state(NewReminderStates.date)
    await message.answer(
        "3/6 — Sanani kiriting (masalan: <code>bugun</code>, <code>ertaga</code> yoki <code>2026-11-25</code>):",
        parse_mode="HTML",
    )


@router.message(NewReminderStates.date)
async def fsm_date(message: Message, state: FSMContext, db: DatabaseManager) -> None:
    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(message.from_user.id)
        tz_name = user.timezone
    parsed = parse_user_date(message.text or "", tz_name)
    if parsed is None:
        await message.answer(
            "Sana formati noto‘g‘ri. Masalan: <code>bugun</code>, <code>ertaga</code> yoki <code>25.11.2026</code>.",
            parse_mode="HTML",
        )
        return
    await state.update_data(date_iso=parsed.isoformat())
    await state.set_state(NewReminderStates.time)
    await message.answer(
        "4/6 — Vaqtni kiriting (<code>HH:MM</code> formatida, masalan <code>09:30</code>):",
        parse_mode="HTML",
    )


@router.message(NewReminderStates.time)
async def fsm_time(message: Message, state: FSMContext) -> None:
    parsed_time = parse_user_time(message.text or "")
    if parsed_time is None:
        await message.answer(
            "Vaqt formati noto‘g‘ri. Iltimos <code>09:30</code> ko‘rinishida yuboring.",
            parse_mode="HTML",
        )
        return
    await state.update_data(time_str=parsed_time.strftime("%H:%M"))
    await state.set_state(NewReminderStates.recurrence)
    await message.answer(
        "5/6 — Takrorlanish turini tanlang:",
        reply_markup=recurrence_kb(),
    )


@router.callback_query(NewReminderStates.recurrence, F.data.startswith("rec:"))
async def fsm_recurrence(callback: CallbackQuery, state: FSMContext) -> None:
    rec_type = callback.data.split(":", 1)[1]
    await state.update_data(recurrence_type=rec_type, custom_days=[])

    if rec_type == "custom_days":
        await state.set_state(NewReminderStates.custom_days)
        if callback.message:
            await callback.message.edit_text(
                "Haftaning qaysi kunlarida takrorlansin? Tanlang va <b>Tasdiqlash</b> tugmasini bosing:",
                reply_markup=custom_days_kb(set()),
                parse_mode="HTML",
            )
    else:
        await state.set_state(NewReminderStates.method)
        if callback.message:
            await callback.message.edit_text(
                "6/6 — Eslatma usulini tanlang:",
                reply_markup=delivery_method_kb(),
            )
    await callback.answer()


@router.callback_query(NewReminderStates.custom_days, F.data.startswith("day_toggle:"))
async def fsm_day_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    day_idx = int(callback.data.split(":", 1)[1])
    data = await state.get_data()
    selected = set(data.get("custom_days", []))
    if day_idx in selected:
        selected.remove(day_idx)
    else:
        selected.add(day_idx)
    await state.update_data(custom_days=sorted(selected))
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=custom_days_kb(selected))
    await callback.answer()


@router.callback_query(NewReminderStates.custom_days, F.data == "day_confirm")
async def fsm_day_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    selected = data.get("custom_days", [])
    if not selected:
        await callback.answer("Kamida bitta kunni tanlang!", show_alert=True)
        return
    await state.set_state(NewReminderStates.method)
    if callback.message:
        await callback.message.edit_text(
            "6/6 — Eslatma usulini tanlang:",
            reply_markup=delivery_method_kb(),
        )
    await callback.answer()


@router.callback_query(NewReminderStates.method, F.data.startswith("method:"))
async def fsm_method_next(callback: CallbackQuery, state: FSMContext) -> None:
    method = callback.data.split(":", 1)[1]
    await state.update_data(delivery_method=method)
    await state.set_state(NewReminderStates.policy)
    if callback.message:
        await callback.message.edit_text(
            "7/7 — Eslatish tartibini tanlang:",
            reply_markup=reminder_policy_kb(),
        )
    await callback.answer()


@router.callback_query(NewReminderStates.policy, F.data.startswith("policy:"))
async def fsm_policy_save(
    callback: CallbackQuery,
    state: FSMContext,
    db: DatabaseManager,
    scheduler: BotScheduler,
) -> None:
    policy = callback.data.split(":", 1)[1]
    data = await state.get_data()
    method = data.get("delivery_method", "voice")

    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(callback.from_user.id)
        d = parse_user_date(data["date_iso"], user.timezone)
        t = parse_user_time(data["time_str"])
        assert d is not None and t is not None
        scheduled_at = combine_local(d, t, user.timezone)

        custom_days = data.get("custom_days", [])
        rec_days_str = ",".join(str(x) for x in custom_days) if custom_days else None

        rem = await repo.create_reminder(
            user_id=user.id,
            title=data["title"],
            description=data.get("description", ""),
            scheduled_at=scheduled_at,
            recurrence_type=data["recurrence_type"],
            recurrence_days=rec_days_str,
            delivery_method=method,
            is_voice=(method in {"voice", "call"}),
            reminder_policy=policy,
        )
        scheduler.schedule_reminder(rem.id, scheduled_at, user.timezone)

    await state.clear()
    if callback.message:
        await callback.message.edit_text(
            f"✅ <b>Eslatma saqlandi!</b>\n\n"
            f"{format_reminder_card(rem, user.timezone)}\n"
            f"🔁 {format_recurrence_uz(rem.recurrence_type, rem.recurrence_days)}",
            reply_markup=back_home_kb(),
            parse_mode="HTML",
        )
    await callback.answer("Saqlandi!")


@router.callback_query(F.data.startswith("rem_view:"))
async def cb_rem_view(callback: CallbackQuery, db: DatabaseManager) -> None:
    rem_id = int(callback.data.split(":", 1)[1])
    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(callback.from_user.id)
        rem = await repo.get_reminder(rem_id, user_id=user.id)

    if rem is None:
        await callback.answer("Eslatma topilmadi.", show_alert=True)
        return

    text = (
        f"{format_reminder_card(rem, user.timezone)}\n"
        f"🔁 Takrorlanish: {format_recurrence_uz(rem.recurrence_type, rem.recurrence_days)}"
    )
    if callback.message:
        await callback.message.edit_text(
            text,
            reply_markup=reminder_detail_kb(rem),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("rem_done:"))
async def cb_rem_done(
    callback: CallbackQuery, db: DatabaseManager, scheduler: BotScheduler
) -> None:
    rem_id = int(callback.data.split(":", 1)[1])
    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(callback.from_user.id)
        rem = await repo.mark_completed(rem_id, user.id)
        if rem:
            scheduler.cancel_reminder_job(rem.id)

    if rem is None:
        await callback.answer("Eslatma topilmadi.", show_alert=True)
        return

    if callback.message:
        await callback.message.edit_text(
            f"✅ <b>Vazifa bajarildi deb belgilandi!</b>\n\n{format_reminder_card(rem, user.timezone)}",
            reply_markup=reminder_detail_kb(rem),
            parse_mode="HTML",
        )
    await callback.answer("Bajarildi!")


@router.callback_query(F.data.startswith("rem_edit_title:"))
async def cb_edit_title(callback: CallbackQuery, state: FSMContext) -> None:
    rem_id = int(callback.data.split(":", 1)[1])
    await state.set_state(EditReminderStates.title)
    await state.update_data(edit_rem_id=rem_id)
    if callback.message:
        await callback.message.edit_text(
            f"✏️ <b>#{rem_id} eslatma nomini o‘zgartirish</b>\n\nYangi nomni yuboring:",
            reply_markup=back_home_kb(),
            parse_mode="HTML",
        )
    await callback.answer()


@router.message(EditReminderStates.title)
async def fsm_edit_title_save(
    message: Message, state: FSMContext, db: DatabaseManager
) -> None:
    data = await state.get_data()
    rem_id = int(data["edit_rem_id"])
    new_title = (message.text or "").strip()
    if not new_title:
        await message.answer("Nom bo‘sh bo‘lishi mumkin emas.")
        return

    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(message.from_user.id)
        rem = await repo.update_reminder(rem_id, user.id, title=new_title)

    await state.clear()
    if rem:
        await message.answer(
            f"✅ Nom yangilandi!\n\n{format_reminder_card(rem, user.timezone)}",
            reply_markup=reminder_detail_kb(rem),
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("rem_edit_time:"))
async def cb_edit_time(callback: CallbackQuery, state: FSMContext) -> None:
    rem_id = int(callback.data.split(":", 1)[1])
    await state.set_state(EditReminderStates.time)
    await state.update_data(edit_rem_id=rem_id)
    if callback.message:
        await callback.message.edit_text(
            f"🕒 <b>#{rem_id} eslatma vaqtini o‘zgartirish</b>\n\nYangi vaqtni <code>HH:MM</code> formatida yuboring:",
            reply_markup=back_home_kb(),
            parse_mode="HTML",
        )
    await callback.answer()


@router.message(EditReminderStates.time)
async def fsm_edit_time_save(
    message: Message,
    state: FSMContext,
    db: DatabaseManager,
    scheduler: BotScheduler,
) -> None:
    parsed_t = parse_user_time(message.text or "")
    if parsed_t is None:
        await message.answer("Vaqt formati noto‘g‘ri (masalan: <code>14:30</code>).", parse_mode="HTML")
        return

    data = await state.get_data()
    rem_id = int(data["edit_rem_id"])

    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(message.from_user.id)
        rem = await repo.get_reminder(rem_id, user.id)
        if rem is None:
            await state.clear()
            await message.answer("Eslatma topilmadi.")
            return
        local_dt = to_tz(rem.scheduled_at, user.timezone)
        updated_dt = combine_local(local_dt.date(), parsed_t, user.timezone)
        rem = await repo.update_reminder(rem_id, user.id, scheduled_at=updated_dt)
        if rem and rem.status == "pending":
            scheduler.schedule_reminder(rem.id, updated_dt, user.timezone)

    await state.clear()
    await message.answer(
        f"✅ Vaqt yangilandi!\n\n{format_reminder_card(rem, user.timezone)}",
        reply_markup=reminder_detail_kb(rem),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("rem_del_ask:"))
async def cb_del_ask(callback: CallbackQuery, db: DatabaseManager) -> None:
    rem_id = int(callback.data.split(":", 1)[1])
    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(callback.from_user.id)
        rem = await repo.get_reminder(rem_id, user.id)
        if rem is None:
            await callback.answer("Eslatma topilmadi.", show_alert=True)
            return
        pc = await repo.create_pending_confirmation(
            user_id=user.id,
            action_type="delete_reminder",
            target_reminder_id=rem.id,
            payload={"title": rem.title},
        )

    if callback.message:
        await callback.message.edit_text(
            f"⚠️ <b>O‘chirishni tasdiqlaysizmi?</b>\n\n"
            f"📌 {rem.title}\n🕒 {format_uz_datetime(rem.scheduled_at, user.timezone)}",
            reply_markup=confirm_delete_kb(pc.id),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_del_yes:"))
async def cb_confirm_del_yes(
    callback: CallbackQuery, db: DatabaseManager, scheduler: BotScheduler
) -> None:
    conf_id = int(callback.data.split(":", 1)[1])
    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(callback.from_user.id)
        pc = await repo.get_pending_confirmation(conf_id, user.id)
        if pc is None:
            await callback.answer("Tasdiqlash muddati tugagan yoki topilmadi.", show_alert=True)
            return
        rem_id = pc.target_reminder_id
        deleted = False
        if rem_id is not None:
            deleted = await repo.delete_reminder(rem_id, user.id)
            scheduler.cancel_reminder_job(rem_id)
        await repo.delete_pending_confirmation(conf_id)

    if callback.message:
        msg = "🗑 Eslatma muvaffaqiyatli o‘chirildi." if deleted else "Eslatma allaqachon o‘chirilgan."
        await callback.message.edit_text(msg, reply_markup=back_home_kb())
    await callback.answer("O‘chirildi")


@router.callback_query(F.data.startswith("confirm_del_no:"))
async def cb_confirm_del_no(callback: CallbackQuery, db: DatabaseManager) -> None:
    conf_id = int(callback.data.split(":", 1)[1])
    async with db.session() as sess:
        repo = BotRepository(sess)
        user = await repo.get_or_create_user(callback.from_user.id)
        pc = await repo.get_pending_confirmation(conf_id, user.id)
        if pc:
            await repo.delete_pending_confirmation(conf_id)
    if callback.message:
        await callback.message.edit_text(
            "❌ O‘chirish bekor qilindi. Eslatma saqlab qolindi.",
            reply_markup=back_home_kb(),
        )
    await callback.answer("Bekor qilindi")
