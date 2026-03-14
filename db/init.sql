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

INSERT INTO admins(username,password_hash)
VALUES(
'admin',
'$2b$12$KIXQ4s0M4s4c9l9b7y6vYONuXz3iU0nW7SgqkVvY2Yp7V4YkM4q8y'
);