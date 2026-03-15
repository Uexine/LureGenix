-- Миграция: source_hostname и прочтение для event_log; для уже развернутых БД.
-- Запуск: docker exec -i luregenix-postgres-1 psql -U admin -d luregenix < db/04_event_log_read_retention.sql

ALTER TABLE event_log ADD COLUMN IF NOT EXISTS source_hostname TEXT;
ALTER TABLE event_log ADD COLUMN IF NOT EXISTS read_at TIMESTAMP;

CREATE INDEX IF NOT EXISTS idx_event_log_read_at ON event_log(read_at);
