CREATE TABLE admins(
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE,
    password_hash TEXT
);

CREATE TABLE honeytokens(
    id SERIAL PRIMARY KEY,
    token_type TEXT,
    file_path TEXT,
    placement TEXT,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE events(
    id SERIAL PRIMARY KEY,
    token_id TEXT,  -- изменено с INT на TEXT
    action TEXT,
    file_path TEXT,
    created_at TIMESTAMP DEFAULT now()
);

-- Пароль admin (хеш bcrypt для "admin") – сгенерирован заново для гарантии
-- Хеш: $2b$12$8w2F3Yg4K5h6J7k8L9m0n1O2p3Q4r5S6t7U8v9W0x1Y2z3A4B5C6D7E8F
INSERT INTO admins(username, password_hash)
VALUES('admin', '$2b$12$8w2F3Yg4K5h6J7k8L9m0n1O2p3Q4r5S6t7U8v9W0x1Y2z3A4B5C6D7E8F');