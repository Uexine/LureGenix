CREATE TABLE admins(
 id SERIAL PRIMARY KEY,
 username TEXT UNIQUE,
 password TEXT
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

INSERT INTO admins(username,password)
VALUES ('admin','admin123')
ON CONFLICT DO NOTHING;