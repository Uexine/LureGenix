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

INSERT INTO admins(username, password_hash)
VALUES('admin', '$2b$12$lG0bY9z3kLp5qR7sT8uVwXyZ2aB4cD6eF8hJ1kM3nP5qR7sT9uVwX');