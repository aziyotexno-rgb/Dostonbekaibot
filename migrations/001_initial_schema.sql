-- 001_initial_schema.sql — Dostonbek AI Bot boshlang'ich PostgreSQL sxemasi

CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(64) PRIMARY KEY,
    description VARCHAR(255) NOT NULL DEFAULT '',
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_profiles (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE NOT NULL,
    username VARCHAR(64),
    full_name VARCHAR(128) NOT NULL DEFAULT 'Dostonbek',
    timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Tashkent',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bot_settings (
    id SERIAL PRIMARY KEY,
    user_id INTEGER UNIQUE NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    morning_call_time VARCHAR(5) NOT NULL DEFAULT '08:00',
    evening_report_time VARCHAR(5) NOT NULL DEFAULT '21:00',
    morning_call_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    evening_report_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    voice_name VARCHAR(64) NOT NULL DEFAULT 'uz-UZ-SardorNeural',
    voice_rate VARCHAR(16) NOT NULL DEFAULT '+0%',
    default_reminder_mode VARCHAR(16) NOT NULL DEFAULT 'voice',
    retry_call_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    retry_call_delay_minutes INTEGER NOT NULL DEFAULT 5,
    retry_call_max_attempts INTEGER NOT NULL DEFAULT 3,
    ai_style VARCHAR(24) NOT NULL DEFAULT 'friendly',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS reminders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    scheduled_at TIMESTAMPTZ NOT NULL,
    recurrence_type VARCHAR(24) NOT NULL DEFAULT 'once',
    recurrence_days VARCHAR(32),
    delivery_method VARCHAR(16) NOT NULL DEFAULT 'voice',
    is_voice BOOLEAN NOT NULL DEFAULT TRUE,
    status VARCHAR(24) NOT NULL DEFAULT 'pending',
    last_triggered_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS call_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    caller_username VARCHAR(64) NOT NULL DEFAULT '@Yordamchiaidosa',
    callee_username VARCHAR(64) NOT NULL DEFAULT '@D_admin_aka',
    purpose VARCHAR(128) NOT NULL DEFAULT 'morning_briefing',
    status VARCHAR(32) NOT NULL,
    duration_seconds INTEGER NOT NULL DEFAULT 0,
    transcript_text TEXT NOT NULL DEFAULT '',
    error_detail TEXT,
    attempt_number INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS daily_reports (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    report_date DATE NOT NULL,
    total_tasks INTEGER NOT NULL DEFAULT 0,
    completed_tasks INTEGER NOT NULL DEFAULT 0,
    calls_made INTEGER NOT NULL DEFAULT 0,
    calls_answered INTEGER NOT NULL DEFAULT 0,
    summary_text TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pending_confirmations (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    action_type VARCHAR(32) NOT NULL,
    target_reminder_id INTEGER,
    payload_json TEXT NOT NULL DEFAULT '{}',
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
