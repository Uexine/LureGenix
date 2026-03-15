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

-- Тестовый админ: логин admin, пароль password
-- (хэш сгенерирован через passlib bcrypt rounds=12)
INSERT INTO admins(username,password_hash)
VALUES(
'admin',
'$2b$12$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi'
)
ON CONFLICT DO NOTHING;