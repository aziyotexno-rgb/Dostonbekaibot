-- 002_voice_cron_pro_upgrade.sql — Interaktiv ovozli qo'ng'iroq, tinch vaqt, idempotency va PRO sinov rejimi

ALTER TABLE bot_settings
    ADD COLUMN IF NOT EXISTS response_wait_seconds INTEGER NOT NULL DEFAULT 15,
    ADD COLUMN IF NOT EXISTS quiet_hours_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS quiet_hours_start VARCHAR(5) NOT NULL DEFAULT '23:00',
    ADD COLUMN IF NOT EXISTS quiet_hours_end VARCHAR(5) NOT NULL DEFAULT '07:00',
    ADD COLUMN IF NOT EXISTS pro_trial_active BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS pro_trial_expires_at TIMESTAMPTZ;

ALTER TABLE reminders
    ADD COLUMN IF NOT EXISTS reminder_policy VARCHAR(32) NOT NULL DEFAULT 'until_completed',
    ADD COLUMN IF NOT EXISTS attempts_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_response_text TEXT,
    ADD COLUMN IF NOT EXISTS awaiting_response BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE call_logs
    ADD COLUMN IF NOT EXISTS reminder_id INTEGER,
    ADD COLUMN IF NOT EXISTS user_voice_reply TEXT,
    ADD COLUMN IF NOT EXISTS detected_intent VARCHAR(48);

CREATE TABLE IF NOT EXISTS notification_dispatches (
    id SERIAL PRIMARY KEY,
    idempotency_key VARCHAR(160) UNIQUE NOT NULL,
    dispatch_type VARCHAR(48) NOT NULL,
    reminder_id INTEGER,
    source VARCHAR(24) NOT NULL DEFAULT 'scheduler',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_reminders_status_scheduled ON reminders (status, scheduled_at);
CREATE INDEX IF NOT EXISTS ix_dispatches_key ON notification_dispatches (idempotency_key);
