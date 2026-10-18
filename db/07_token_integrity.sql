-- Состояние файла отделено от состояния доставки: размещённая приманка может быть изменена.
ALTER TABLE honeytoken_deployments ADD COLUMN IF NOT EXISTS integrity_status TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE honeytoken_deployments ADD COLUMN IF NOT EXISTS last_event_at TIMESTAMP;
