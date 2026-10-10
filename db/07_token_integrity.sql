ALTER TABLE honeytoken_deployments ADD COLUMN IF NOT EXISTS integrity_status TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE honeytoken_deployments ADD COLUMN IF NOT EXISTS last_event_at TIMESTAMP;
