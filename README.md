# DOSTONBEK AI BOT

Sof o‘zbek tilida gapiradigan, Telegram orqali **interaktiv 1:1 VoIP qo‘ng‘irog‘i** (`@Yordamchiaidosa` → `@D_admin_aka`) qiladigan, foydalanuvchi javobini tinglab tushunadigan va vazifa bajarilmaguncha qoidalar asosida eslatib turadigan shaxsiy AI kotib.

## Yangi va asosiy imkoniyatlar

- **Sof o‘zbek tili**: Barcha menyular, bildirishnomalar, qo‘ng‘iroqdagi suhbat va AI javoblari tabiiy o‘zbek tilida.
- **Interaktiv ovozli qo‘ng‘iroq**: Qo‘ng‘iroq ochilganda bot salomlashadi, vazifani aytadi, foydalanuvchi javobini kutadi, PCM -> WAV -> Gemini STT orqali nutqni aniqlaydi va quyidagi 6 ta buyruqni bajaradi:
  - *"Ha, bajardim"* / *"Ha, esladim"* → Vazifani bajarilgan deb belgilaydi.
  - *"Hali bajarmadim"* → Qayta eslatishni faol qoldiradi.
  - *"Keyinroq eslat"* → 15 daqiqaga suradi.
  - *"Bir soatdan keyin eslat"* → 1 soatga suradi.
  - *"Eslatmani bekor qil"* → Eslatmani bekor qiladi.
  - *"Bugungi rejalarimni ayt"* → Kunlik vazifalarni ovozli o‘qib beradi.
- **Qizil tugma va bajarilish farqi**: Qo‘ng‘iroqni qizil tugma bilan yakunlash vazifani bajardi deb hisoblamaydi (`hung_up_unconfirmed` / `declined` qayd etiladi va maksimal urinish + tinch vaqt chegarasida qayta qo‘ng‘iroq qilinadi).
- **Render Web Service + Cron Job + PostgreSQL Idempotency**:
  - `web/health.py`: `/health` diagnostika endpointi hamda ixtiyoriy Webhook (`USE_WEBHOOK=true`) yoki Polling rejimi.
  - `cron_runner.py`: Har 5 daqiqada ishlaydigan Render Cron Job. `notification_dispatches` jadvali orqali Web Service va Cron Job bir vaqtda ishlaganda ham bitta eslatma ikki marta yuborilmaydi.
- **PostgreSQL migratsiyalari**: `database/migrations.py` ishga tushganda avtomatik bajariladi hamda `migrations/001_initial_schema.sql` va `migrations/002_voice_cron_pro_upgrade.sql` fayllari mavjud.
- **PRO sinov rejimi (faqat administrator uchun)**: Haqiqiy to‘lovsiz sinov rejimi — muddat belgilash, imkoniyatlarni tekshirish va bekor qilish faqat `ALLOWED_TELEGRAM_ID` uchun ochiq.

## Render Bepul Tarifi Cheklovlari Haqida Ochiq Izoh

1. **Render Free Web Service uyqu rejimi**: Bepul tarifda Web Service 15 daqiqa HTTP so‘rov bo‘lmasa uxlab qoladi. Shu sabab:
   - `USE_WEBHOOK=true` rejimida Telegram xabar kelganda xizmatni uyg‘otadi;
   - Rejalashtirilgan eslatmalar va kunlik hisobotlar kechikmasligi uchun alohida **Render Cron Job** (`cron_runner.py`, `*/5 * * * *`) yoki `/health` ping xizmatidan foydalanish tavsiya etiladi.
   - Aniq soniyali 24/7 uyg‘onishsiz ishlash uchun Render Starter (`worker` yoki `web`) tarifi talab qilinadi.
2. **1:1 VoIP qo‘ng‘iroq talablari**: Haqiqiy qo‘ng‘iroq uchun `Dockerfile` ichidagi `ffmpeg`, `ntgcalls`, `pyrogram` hamda `@Yordamchiaidosa` uchun lokal yaratilgan `TELEGRAM_SESSION_STRING` zarur. Agar ulardan biri mavjud bo‘lmasa, tizim soxta qo‘ng‘iroq ko‘rsatmaydi — `unavailable` holatini yozib, ovozli xabar (`send_voice`) zaxira bildirishnomasini yuboradi.
