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

-- Добавим тестового пользователя
INSERT INTO admins(username,password_hash)
VALUES(
'admin',
'$2b$12$uCwS7Yq3Ck9nJxW7CqkB4e6qC7s0yS6L3vV9YdYF3x0V4vJ3p1yqK'
)
ON CONFLICT DO NOTHING;