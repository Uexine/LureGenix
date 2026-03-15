-- Таблица нод для обнаружения агентов (если в init.sql её ещё нет)
CREATE TABLE IF NOT EXISTS nodes (
    id SERIAL PRIMARY KEY,
    hostname TEXT NOT NULL,
    ip TEXT NOT NULL,
    last_heartbeat TIMESTAMP DEFAULT now(),
    UNIQUE(hostname, ip)
);
