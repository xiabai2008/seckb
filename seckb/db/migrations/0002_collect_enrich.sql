ALTER TABLE assets ADD COLUMN source_id TEXT;
CREATE UNIQUE INDEX idx_assets_source_id ON assets(source, source_id)
  WHERE source_id IS NOT NULL;

CREATE TABLE sources (
  name TEXT PRIMARY KEY,
  last_cursor TEXT,
  last_run_at TEXT,
  etag TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  health TEXT NOT NULL DEFAULT 'ok'
);

CREATE TABLE runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  fetched INTEGER NOT NULL DEFAULT 0,
  imported INTEGER NOT NULL DEFAULT 0,
  skipped INTEGER NOT NULL DEFAULT 0,
  failed INTEGER NOT NULL DEFAULT 0,
  error TEXT
);

CREATE TABLE jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT
);
CREATE INDEX idx_jobs_status ON jobs(status);

CREATE TABLE cards (
  asset_id INTEGER PRIMARY KEY REFERENCES assets(id) ON DELETE CASCADE,
  summary TEXT NOT NULL,
  key_takeaways TEXT NOT NULL DEFAULT '[]',
  card_json TEXT NOT NULL,
  model TEXT,
  generated_at TEXT NOT NULL
);

CREATE TABLE repos (
  asset_id INTEGER PRIMARY KEY REFERENCES assets(id) ON DELETE CASCADE,
  owner TEXT,
  name TEXT,
  stars INTEGER,
  forks INTEGER,
  language TEXT,
  topics TEXT,
  clone_url TEXT,
  license TEXT,
  archived INTEGER NOT NULL DEFAULT 0,
  last_commit TEXT
);

CREATE TABLE cves (
  asset_id INTEGER PRIMARY KEY REFERENCES assets(id) ON DELETE CASCADE,
  cve_id TEXT,
  cvss REAL,
  cwe TEXT,
  affected TEXT,
  poc_refs TEXT,
  in_kev INTEGER NOT NULL DEFAULT 0
);
