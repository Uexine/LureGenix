CREATE TABLE IF NOT EXISTS honeytoken_deployments (
    id SERIAL PRIMARY KEY,
    honeytoken_file_id INTEGER UNIQUE NOT NULL REFERENCES honeytoken_files(id) ON DELETE CASCADE,
    node_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    token_id TEXT UNIQUE NOT NULL,
    filename TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    target_path TEXT NOT NULL DEFAULT '',
    target_kind TEXT NOT NULL DEFAULT 'directory' CHECK (target_kind IN ('directory', 'file')),
    content_base64 TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    generation_source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'deployed', 'failed')),
    deployed_path TEXT,
    error TEXT,
    created_at TIMESTAMP DEFAULT now(),
    completed_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_honeytoken_deployments_node_status
    ON honeytoken_deployments(node_id, status);
