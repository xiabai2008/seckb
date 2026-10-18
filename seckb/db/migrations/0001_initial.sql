CREATE TABLE assets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  type TEXT NOT NULL,
  title TEXT NOT NULL,
  lang TEXT NOT NULL DEFAULT 'zh',
  source TEXT NOT NULL DEFAULT 'manual',
  source_url TEXT,
  path TEXT,
  md_path TEXT,
  sha256 TEXT NOT NULL UNIQUE,
  simhash INTEGER,
  size INTEGER NOT NULL DEFAULT 0,
  format TEXT NOT NULL,
  published_at TEXT,
  imported_at TEXT NOT NULL,
  tags TEXT NOT NULL DEFAULT '[]',
  category TEXT,
  status TEXT NOT NULL DEFAULT 'ok'
);
CREATE INDEX idx_assets_type ON assets(type);
CREATE INDEX idx_assets_simhash ON assets(simhash);

CREATE TABLE chunks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
  seq INTEGER NOT NULL,
  heading_path TEXT NOT NULL DEFAULT '',
  page_from INTEGER,
  page_to INTEGER,
  token_count INTEGER NOT NULL,
  content_md TEXT NOT NULL,
  UNIQUE(asset_id, seq)
);
CREATE INDEX idx_chunks_asset ON chunks(asset_id);

CREATE TABLE snippets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
  chunk_id INTEGER REFERENCES chunks(id) ON DELETE SET NULL,
  kind TEXT NOT NULL,
  lang TEXT,
  tool TEXT,
  content TEXT NOT NULL,
  context TEXT
);

CREATE TABLE entities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  name TEXT NOT NULL,
  canonical TEXT NOT NULL,
  UNIQUE(kind, canonical)
);

CREATE TABLE asset_entities (
  asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
  entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  weight REAL NOT NULL DEFAULT 1.0,
  PRIMARY KEY (asset_id, entity_id)
);

CREATE TABLE books (
  asset_id INTEGER PRIMARY KEY REFERENCES assets(id) ON DELETE CASCADE,
  isbn TEXT,
  authors TEXT,
  publisher TEXT,
  year INTEGER,
  pages INTEGER,
  edition TEXT,
  cover_path TEXT,
  reading_status TEXT NOT NULL DEFAULT 'unread'
);

CREATE TABLE posts (
  asset_id INTEGER PRIMARY KEY REFERENCES assets(id) ON DELETE CASCADE,
  site TEXT,
  author TEXT,
  board TEXT,
  views INTEGER,
  replies INTEGER,
  original_html_path TEXT
);

CREATE VIRTUAL TABLE chunks_fts USING fts5(
  content,
  heading_path,
  asset_id UNINDEXED,
  tokenize = 'trigram'
);

PRAGMA user_version = 1;
