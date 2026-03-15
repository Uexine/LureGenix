-- ============================================================
-- Таблица администраторов
-- ============================================================
CREATE TABLE IF NOT EXISTS admins (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT now(),
    last_login TIMESTAMP,
    is_active BOOLEAN DEFAULT true
);

-- ============================================================
-- Таблица нод (агентов)
-- ============================================================
CREATE TABLE IF NOT EXISTS nodes (
    id SERIAL PRIMARY KEY,
    hostname TEXT NOT NULL,
    ip INET NOT NULL,
    status TEXT DEFAULT 'offline' CHECK (status IN ('online', 'offline')),
    last_heartbeat TIMESTAMP,
    version TEXT,                       -- версия агента
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now(),
    UNIQUE(hostname, ip)                 -- защита от дублирования
);

CREATE INDEX idx_nodes_status ON nodes(status);
CREATE INDEX idx_nodes_last_heartbeat ON nodes(last_heartbeat);

-- ============================================================
-- Таблица типов honeytoken (справочник)
-- ============================================================
CREATE TABLE IF NOT EXISTS token_types (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,           -- 'ssh_key', 'env_file', 'db_dump', ...
    description TEXT
);

-- Предзаполнение базовых типов
INSERT INTO token_types (name, description) VALUES
    ('ssh_key', 'Приватный SSH-ключ с комментарием'),
    ('env_file', 'Файл .env с переменными окружения'),
    ('db_dump', 'Дамп базы данных (SQL)'),
    ('api_key', 'Ключ API (AWS, Google, Yandex)'),
    ('bash_history', 'История команд .bash_history'),
    ('log_file', 'Файл лога (access.log)'),
    ('backup_archive', 'Архив с данными (tar.gz)'),
    ('docker_config', 'Файл конфигурации Docker (~/.docker/config.json)')
ON CONFLICT (name) DO NOTHING;

-- ============================================================
-- Таблица honeytoken (приманки)
-- ============================================================
CREATE TABLE IF NOT EXISTS honeytokens (
    id SERIAL PRIMARY KEY,
    node_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    token_type_id INTEGER NOT NULL REFERENCES token_types(id),
    name TEXT,                             -- пользовательское название (опционально)
    file_path TEXT NOT NULL,                -- путь к файлу на целевой системе
    content TEXT,                           -- сгенерированное содержимое (если применимо)
    xattr_value TEXT UNIQUE,                 -- значение расширенного атрибута (UUID или хеш)
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'triggered', 'deleted')),
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now(),
    triggered_at TIMESTAMP,                  -- время первого срабатывания (если было)
    UNIQUE(node_id, file_path)                -- на одной ноде путь уникален
);

CREATE INDEX idx_honeytokens_node_id ON honeytokens(node_id);
CREATE INDEX idx_honeytokens_status ON honeytokens(status);
CREATE INDEX idx_honeytokens_token_type ON honeytokens(token_type_id);
CREATE INDEX idx_honeytokens_xattr ON honeytokens(xattr_value);

-- ============================================================
-- Таблица событий (срабатываний honeytoken)
-- ============================================================
CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    honeytoken_id INTEGER NOT NULL REFERENCES honeytokens(id) ON DELETE CASCADE,
    node_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,                 -- 'open', 'read', 'modify', 'delete', 'execute'
    process_info JSONB,                        -- информация о процессе: {pid, user, cmdline}
    source_ip INET,                             -- IP-адрес источника (если доступен)
    created_at TIMESTAMP DEFAULT now(),
    is_alert BOOLEAN DEFAULT true,              -- считать ли это тревогой
    acknowledged BOOLEAN DEFAULT false          -- отметка о просмотре администратором
);

CREATE INDEX idx_events_honeytoken_id ON events(honeytoken_id);
CREATE INDEX idx_events_node_id ON events(node_id);
CREATE INDEX idx_events_created_at ON events(created_at);
CREATE INDEX idx_events_acknowledged ON events(acknowledged) WHERE NOT acknowledged;
CREATE INDEX idx_events_is_alert ON events(is_alert) WHERE is_alert;

-- ============================================================
-- Таблица истории сканирований сети
-- ============================================================
CREATE TABLE IF NOT EXISTS scans (
    id SERIAL PRIMARY KEY,
    scan_time TIMESTAMP DEFAULT now(),
    subnet CIDR,                              -- диапазон сканирования
    status TEXT DEFAULT 'running',            -- 'running', 'completed', 'failed'
    result JSONB,                              -- список обнаруженных хостов с портами
    created_by INTEGER REFERENCES admins(id) ON DELETE SET NULL
);

CREATE INDEX idx_scans_scan_time ON scans(scan_time);

-- ============================================================
-- Триггер для автоматического обновления updated_at
-- ============================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_nodes_updated_at BEFORE UPDATE ON nodes
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_honeytokens_updated_at BEFORE UPDATE ON honeytokens
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- Представление для дашборда (агрегированные показатели)
-- ============================================================
CREATE OR REPLACE VIEW dashboard_stats AS
SELECT
    (SELECT COUNT(*) FROM nodes WHERE status = 'online') AS online_nodes,
    (SELECT COUNT(*) FROM honeytokens WHERE status = 'active') AS active_honeytokens,
    (SELECT COUNT(*) FROM events WHERE created_at > now() - interval '24 hours') AS events_last_24h,
    (SELECT COUNT(*) FROM events WHERE is_alert AND NOT acknowledged) AS unacknowledged_alerts;