ALTER TABLE event_log ADD COLUMN IF NOT EXISTS source_hostname TEXT;
ALTER TABLE event_log ADD COLUMN IF NOT EXISTS read_at TIMESTAMP;

CREATE INDEX IF NOT EXISTS idx_event_log_read_at ON event_log(read_at);
