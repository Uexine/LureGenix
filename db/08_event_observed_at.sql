-- Время обнаружения агентом сохраняется отдельно от времени доставки на сервер.
-- Это позволяет правильно показать события, накопленные без связи.
ALTER TABLE event_log ADD COLUMN IF NOT EXISTS observed_at TIMESTAMPTZ;
