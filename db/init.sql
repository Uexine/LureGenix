CREATE TABLE IF NOT EXISTS admins(
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE,
    password_hash TEXT
);

CREATE TABLE IF NOT EXISTS honeytokens(
    id SERIAL PRIMARY KEY,
    token_type TEXT,
    file_path TEXT,
    placement TEXT,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS events(
    id SERIAL PRIMARY KEY,
    token_id TEXT,
    action TEXT,
    file_path TEXT,
    created_at TIMESTAMP DEFAULT now()
);

-- Добавим тестового пользователя (пароль не важен)
INSERT INTO admins(username, password_hash) 
VALUES('admin', 'temporary_hash_not_used') 
ON CONFLICT (username) DO NOTHING;