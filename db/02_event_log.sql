CREATE TABLE IF NOT EXISTS event_log (
    id SERIAL PRIMARY KEY,
    token_id TEXT,
    action TEXT,
    file_path TEXT,
    created_at TIMESTAMP DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_event_log_created_at ON event_log(created_at);
