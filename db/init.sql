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
 token_id INT,
 action TEXT,
 file_path TEXT,
 created_at TIMESTAMP DEFAULT now()
);

INSERT INTO admins(username, password_hash)
VALUES('admin', '$2b$12$KbQi8PpJk8u7kQhZQWz6EuHcQkW1jX7r2p1gC4Fz2r1K3m8zqG0i2');  # Это для 'admin', если не работает — сгенерируй новый: from passlib.hash import bcrypt; print(bcrypt.hash("your_pass"))