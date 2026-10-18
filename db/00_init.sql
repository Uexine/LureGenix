-- Базовые таблицы. Пароль администратора хранится только в виде bcrypt-хеша.
CREATE TABLE IF NOT EXISTS admins (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT now(),
    last_login TIMESTAMP,
    is_active BOOLEAN DEFAULT true
);

-- Адрес и имя описывают хост; доступность API вычисляет по last_heartbeat.
CREATE TABLE IF NOT EXISTS nodes (
    id SERIAL PRIMARY KEY,
    hostname TEXT NOT NULL,
    ip INET NOT NULL,
    status TEXT DEFAULT 'offline' CHECK (status IN ('online', 'offline')),
    last_heartbeat TIMESTAMP,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now(),
    UNIQUE(hostname, ip)
);
CREATE INDEX IF NOT EXISTS idx_nodes_last_heartbeat ON nodes(last_heartbeat);

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    -- Обновляем служебное время при любом изменении строки ноды.
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- OR REPLACE позволяет безопасно повторять миграцию при запуске контейнеров.
CREATE OR REPLACE TRIGGER update_nodes_updated_at BEFORE UPDATE ON nodes
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
