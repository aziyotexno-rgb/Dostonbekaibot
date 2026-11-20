"""Secure local script to generate TELEGRAM_SESSION_STRING for @Yordamchiaidosa.

IMPORTANT SECURITY RULES:
- Run this script ONLY on your trusted local machine.
- NEVER request Telegram login codes or 2FA passwords through any web interface.
- Store the generated TELEGRAM_SESSION_STRING only in your .env or Render Environment Variables.
"""

from __future__ import annotations

import asyncio
import getpass


async def generate_session() -> None:
    try:
        from pyrogram import Client
    except ImportError:
        print("Xatolik: pyrogram o'rnatilmagan. Avval `pip install pyrogram tgcrypto` bajaring.")
        return

    print("=== DOSTONBEK AI BOT — MTProto Session Generator (@Yordamchiaidosa) ===")
    print("Diqqat: Ushbu ma'lumotlar faqat lokal kompyuteringizda ishlatiladi.\n")

    api_id_raw = input("TELEGRAM_API_ID (my.telegram.org dan): ").strip()
    if not api_id_raw.isdigit():
        print("Xatolik: TELEGRAM_API_ID faqat raqam bo'lishi kerak.")
        return

    api_hash = getpass.getpass("TELEGRAM_API_HASH (kiritish yashirilgan): ").strip()
    if not api_hash:
        print("Xatolik: TELEGRAM_API_HASH bo'sh bo'lishi mumkin emas.")
        return

    async with Client(
        name="local_session_gen",
        api_id=int(api_id_raw),
        api_hash=api_hash,
        in_memory=True,
    ) as app:
        me = await app.get_me()
        session_str = await app.export_session_string()
        print("\n✅ Muvaffaqiyatli ulandi!")
        print(f"Akkaunt: @{me.username or 'username_yoq'} (ID: {me.id})")
        print("\nQuyidagi TELEGRAM_SESSION_STRING qiymatini .env yoki Render Secrets ga qo'shing:\n")
        print(session_str)
        print("\n⚠️ Ushbu satrni hech kimga bermang va GitHub ga yuklamang!")


if __name__ == "__main__":
    asyncio.run(generate_session())
