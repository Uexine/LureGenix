-- Записи приманок. file_path -- путь на Linux-ноде, а не внутри контейнера приложения.
-- placement сохранён для совместимости с ранее созданными записями.
CREATE TABLE IF NOT EXISTS honeytoken_files (
    id SERIAL PRIMARY KEY,
    token_type TEXT NOT NULL,
    file_path TEXT NOT NULL,
    placement TEXT,
    created_at TIMESTAMP DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_honeytoken_files_created_at ON honeytoken_files(created_at);
