"""All Telegram inline keyboards in pure, natural Uzbek."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database.models import BotSettings, Reminder


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📅 Bugungi rejalar", callback_data="menu:today"),
                InlineKeyboardButton(text="➕ Yangi eslatma", callback_data="menu:new_reminder"),
            ],
            [
                InlineKeyboardButton(text="📝 Barcha eslatmalar", callback_data="menu:all_reminders"),
                InlineKeyboardButton(text="🔔 Takroriy eslatmalar", callback_data="menu:recurring"),
            ],
            [
                InlineKeyboardButton(text="📞 Qo‘ng‘iroq sozlamalari", callback_data="menu:call_settings"),
                InlineKeyboardButton(text="⚙️ Bot sozlamalari", callback_data="menu:bot_settings"),
            ],
            [
                InlineKeyboardButton(text="📊 Kunlik statistika", callback_data="menu:stats"),
                InlineKeyboardButton(text="🤖 AI yordamchi", callback_data="menu:ai"),
            ],
        ]
    )


def back_home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="menu:home")]
        ]
    )


def recurrence_kb(prefix: str = "rec") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="1️⃣ Bir martalik", callback_data=f"{prefix}:once"),
                InlineKeyboardButton(text="🔁 Har kuni", callback_data=f"{prefix}:daily"),
            ],
            [
                InlineKeyboardButton(text="📆 Har hafta", callback_data=f"{prefix}:weekly"),
                InlineKeyboardButton(text="🗓 Har oy", callback_data=f"{prefix}:monthly"),
            ],
            [
                InlineKeyboardButton(text="🎯 Belgilangan kunlarda", callback_data=f"{prefix}:custom_days"),
            ],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="menu:home")],
        ]
    )


def custom_days_kb(selected: set[int]) -> InlineKeyboardMarkup:
    days = [
        (0, "Du"),
        (1, "Se"),
        (2, "Ch"),
        (3, "Pa"),
        (4, "Ju"),
        (5, "Sh"),
        (6, "Ya"),
    ]
    row = [
        InlineKeyboardButton(
            text=f"{'✅ ' if idx in selected else ''}{label}",
            callback_data=f"day_toggle:{idx}",
        )
        for idx, label in days
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            row[:4],
            row[4:],
            [InlineKeyboardButton(text="✔️ Tasdiqlash", callback_data="day_confirm")],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="menu:home")],
        ]
    )


def delivery_method_kb(prefix: str = "method") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💬 Matnli", callback_data=f"{prefix}:text"),
                InlineKeyboardButton(text="🎙 Ovozli", callback_data=f"{prefix}:voice"),
                InlineKeyboardButton(text="📞 Qo‘ng‘iroq", callback_data=f"{prefix}:call"),
            ],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="menu:home")],
        ]
    )


def reminder_policy_kb(prefix: str = "policy") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="1️⃣ Bir marta eslatish",
                    callback_data=f"{prefix}:once",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🎙 Javobni kutish",
                    callback_data=f"{prefix}:wait_response",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📞 Javob bo‘lmasa qayta qo‘ng‘iroq",
                    callback_data=f"{prefix}:retry_no_answer",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔁 Bajarilmaguncha eslatib turish",
                    callback_data=f"{prefix}:until_completed",
                ),
            ],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="menu:home")],
        ]
    )


def reminder_list_kb(reminders: list[Reminder], back_target: str = "menu:home") -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for rem in reminders[:15]:
        icon = "✅" if rem.status == "completed" else ("🚫" if rem.status == "cancelled" else "⏳")
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{icon} #{rem.id} {rem.title[:28]}",
                    callback_data=f"rem_view:{rem.id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="🏠 Bosh menyu", callback_data=back_target)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reminder_detail_kb(rem: Reminder) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if rem.status == "pending":
        rows.append(
            [
                InlineKeyboardButton(
                    text="✅ Bajarildi deb belgilash",
                    callback_data=f"rem_done:{rem.id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="✏️ Nomini o‘zgartirish", callback_data=f"rem_edit_title:{rem.id}"),
            InlineKeyboardButton(text="🕒 Vaqtini o‘zgartirish", callback_data=f"rem_edit_time:{rem.id}"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(text="🗑 O‘chirish", callback_data=f"rem_del_ask:{rem.id}"),
            InlineKeyboardButton(text="⬅️ Ro‘yxatga qaytish", callback_data="menu:all_reminders"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_delete_kb(confirmation_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Ha, o‘chirish",
                    callback_data=f"confirm_del_yes:{confirmation_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Bekor qilish",
                    callback_data=f"confirm_del_no:{confirmation_id}",
                ),
            ]
        ]
    )


def call_settings_kb(cfg: BotSettings) -> InlineKeyboardMarkup:
    morning_state = "Yoqilgan ✅" if cfg.morning_call_enabled else "O‘chirilgan ❌"
    retry_state = "Yoqilgan ✅" if cfg.retry_call_enabled else "O‘chirilgan ❌"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"☀️ Qo‘ng‘iroq vaqti: {cfg.morning_call_time}",
                    callback_data="cfg:set_morning_time",
                ),
                InlineKeyboardButton(
                    text=f"🔔 Holati: {morning_state}",
                    callback_data="cfg:toggle_morning",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=f"🔁 Qayta qo‘ng‘iroq: {retry_state}",
                    callback_data="cfg:toggle_retry",
                ),
                InlineKeyboardButton(
                    text=f"⏱ Oralig‘i: {cfg.retry_call_delay_minutes} daqiqa",
                    callback_data="cfg:cycle_retry_delay",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=f"🔢 Maksimal urinish: {cfg.retry_call_max_attempts} marta",
                    callback_data="cfg:cycle_max_attempts",
                ),
                InlineKeyboardButton(
                    text=f"🎙 Javob kutish: {cfg.response_wait_seconds} soniya",
                    callback_data="cfg:cycle_wait_seconds",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📞 Hozir sinov qo‘ng‘irog‘i qilish",
                    callback_data="call:test_now",
                ),
                InlineKeyboardButton(
                    text="📜 Qo‘ng‘iroqlar tarixi",
                    callback_data="call:history",
                ),
            ],
            [InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="menu:home")],
        ]
    )


def bot_settings_kb(cfg: BotSettings, tz_name: str, is_pro: bool) -> InlineKeyboardMarkup:
    voice_label = "Sardor (Erkak)" if "Sardor" in cfg.voice_name else "Madina (Ayol)"
    style_labels = {"formal": "Rasmiy", "friendly": "Samimiy", "concise": "Qisqa"}
    mode_labels = {"voice": "Ovozli", "text": "Matnli", "call": "Qo‘ng‘iroq"}
    quiet_text = (
        f"{cfg.quiet_hours_start}–{cfg.quiet_hours_end}"
        if cfg.quiet_hours_enabled
        else "O‘chirilgan"
    )
    pro_badge = "Faol (Sinov)" if is_pro else "Oddiy rejim"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"☀️ Qo‘ng‘iroq vaqti: {cfg.morning_call_time}",
                    callback_data="cfg:set_morning_time",
                ),
                InlineKeyboardButton(
                    text=f"🌙 Kunlik hisobot: {cfg.evening_report_time}",
                    callback_data="cfg:set_evening_time",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=f"⏱ Qayta oraliq: {cfg.retry_call_delay_minutes} daq",
                    callback_data="cfg:cycle_retry_delay",
                ),
                InlineKeyboardButton(
                    text=f"🔢 Maksimal qo‘ng‘iroq: {cfg.retry_call_max_attempts}x",
                    callback_data="cfg:cycle_max_attempts",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=f"🎙 Javob kutish: {cfg.response_wait_seconds} soniya",
                    callback_data="cfg:cycle_wait_seconds",
                ),
                InlineKeyboardButton(
                    text=f"⏩ Ovoz tezligi: {cfg.voice_rate}",
                    callback_data="cfg:cycle_rate",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=f"🔕 Tinch vaqt: {quiet_text}",
                    callback_data="cfg:set_quiet_hours",
                ),
                InlineKeyboardButton(
                    text=f"🗣 Ovoz: {voice_label}",
                    callback_data="cfg:cycle_voice",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=f"🔔 Standart usul: {mode_labels.get(cfg.default_reminder_mode, cfg.default_reminder_mode)}",
                    callback_data="cfg:cycle_mode",
                ),
                InlineKeyboardButton(
                    text=f"🤖 Uslub: {style_labels.get(cfg.ai_style, cfg.ai_style)}",
                    callback_data="cfg:cycle_ai_style",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=f"🧪 PRO sinov rejimi: {pro_badge}",
                    callback_data="menu:pro_trial",
                ),
                InlineKeyboardButton(
                    text=f"🌍 Vaqt zonasi: {tz_name}",
                    callback_data="cfg:set_timezone",
                ),
            ],
            [InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="menu:home")],
        ]
    )


def pro_trial_kb(is_pro: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text="🧪 3 kunlik sinovni yoqish", callback_data="pro:activate:3"),
            InlineKeyboardButton(text="🧪 7 kunlik sinovni yoqish", callback_data="pro:activate:7"),
        ],
        [
            InlineKeyboardButton(text="📅 Muddatni kiritish (kun)", callback_data="pro:custom_days"),
            InlineKeyboardButton(text="🔍 Imkoniyatlarni tekshirish", callback_data="pro:check_features"),
        ],
    ]
    if is_pro:
        rows.append(
            [InlineKeyboardButton(text="🚫 PRO sinovni bekor qilish", callback_data="pro:cancel")]
        )
    rows.append(
        [
            InlineKeyboardButton(text="⬅️ Sozlamalarga qaytish", callback_data="menu:bot_settings"),
            InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="menu:home"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
