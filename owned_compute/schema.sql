-- One cross-project resource queue in the existing PostgreSQL, not one DB per task.
CREATE TABLE IF NOT EXISTS visual_memory_v2.compute_requests (
    id TEXT PRIMARY KEY,
    project TEXT NOT NULL,
    task_key TEXT NOT NULL,
    token TEXT NOT NULL,
    priority INTEGER NOT NULL CHECK(priority BETWEEN 0 AND 3),
    is_retry BOOLEAN NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('queued','reserved','running','released','expired')),
    deadline TIMESTAMPTZ NOT NULL,
    stall_seconds INTEGER NOT NULL CHECK(stall_seconds>0),
    candidates JSONB NOT NULL,
    spec JSONB NOT NULL,
    binding JSONB,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    ready_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    receipt JSONB,
    proof JSONB,
    result JSONB,
    UNIQUE(project,task_key)
);
CREATE INDEX IF NOT EXISTS compute_requests_ready ON visual_memory_v2.compute_requests(priority,is_retry,deadline,created_at) WHERE state='queued';
CREATE INDEX IF NOT EXISTS compute_requests_owned ON visual_memory_v2.compute_requests(state) WHERE state IN ('reserved','running');
CREATE TABLE IF NOT EXISTS visual_memory_v2.compute_path_migrations (
    host TEXT NOT NULL,
    old_path TEXT NOT NULL,
    new_path TEXT NOT NULL,
    project TEXT NOT NULL,
    kind TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('registered','waiting_owner','staged','cutover','retired','failed')),
    owner JSONB,
    proof JSONB,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY(host,old_path),
    UNIQUE(host,new_path)
);
CREATE TABLE IF NOT EXISTS visual_memory_v2.compute_runtime_installations (
    host TEXT PRIMARY KEY,
    physical_host TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_commit TEXT NOT NULL,
    runtime_path TEXT NOT NULL,
    bin_path TEXT NOT NULL,
    proof JSONB NOT NULL,
    installed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
