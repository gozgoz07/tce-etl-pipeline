-- TCE Logical Data Model (ERD) - 6 tables schema

CREATE TABLE IF NOT EXISTS entities (
  entity_id      BIGSERIAL PRIMARY KEY,
  canonical_name TEXT NOT NULL,
  type           TEXT NOT NULL CHECK (type IN ('ORG','MODEL','PRODUCT','LIBRARY','PERSON','DATASET','TECHNIQUE')),
  aliases        TEXT[] NOT NULL DEFAULT '{}',
  status         TEXT NOT NULL DEFAULT 'validated' CHECK (status IN ('candidate','validated','rejected')),
  UNIQUE (canonical_name, type)
);

CREATE TABLE IF NOT EXISTS items (
  item_id        BIGSERIAL PRIMARY KEY,
  source         TEXT NOT NULL CHECK (source IN ('hn','arxiv','rss','hf')),
  source_item_id TEXT NOT NULL,
  url            TEXT NOT NULL,
  url_hash       TEXT NOT NULL UNIQUE,
  title          TEXT NOT NULL,
  summary        TEXT,
  lang           TEXT,
  published_at   TIMESTAMPTZ NOT NULL,
  fetched_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  points         INTEGER NOT NULL DEFAULT 0,
  comments       INTEGER NOT NULL DEFAULT 0,
  keywords       TEXT[] NOT NULL DEFAULT '{}',
  entity_ids     BIGINT[] NOT NULL DEFAULT '{}',
  UNIQUE (source, source_item_id)
);
CREATE INDEX IF NOT EXISTS items_published_at_idx ON items (published_at);
CREATE INDEX IF NOT EXISTS items_entity_ids_idx ON items USING GIN (entity_ids);
CREATE INDEX IF NOT EXISTS items_fts_idx ON items
  USING GIN (to_tsvector('simple', title || ' ' || coalesce(summary, '')));

CREATE TABLE IF NOT EXISTS topics (
  topic_id      BIGSERIAL PRIMARY KEY,
  name          TEXT NOT NULL UNIQUE,
  category      TEXT NOT NULL,
  keywords      TEXT[] NOT NULL DEFAULT '{}',
  entity_ids    BIGINT[] NOT NULL DEFAULT '{}',
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS item_topics (
  item_id     BIGINT NOT NULL REFERENCES items(item_id) ON DELETE CASCADE,
  topic_id    BIGINT NOT NULL REFERENCES topics(topic_id) ON DELETE CASCADE,
  match_score REAL NOT NULL,
  PRIMARY KEY (item_id, topic_id)
);
CREATE INDEX IF NOT EXISTS item_topics_topic_idx ON item_topics (topic_id, item_id);

CREATE TABLE IF NOT EXISTS topic_snapshots (
  topic_id         BIGINT NOT NULL REFERENCES topics(topic_id) ON DELETE CASCADE,
  snapshot_date    DATE NOT NULL,
  c24              INTEGER NOT NULL,
  baseline7        NUMERIC(10,3) NOT NULL,
  std7             NUMERIC(10,3) NOT NULL,
  distinct_sources INTEGER NOT NULL,
  engagement_sum   INTEGER NOT NULL,
  velocity_score   NUMERIC(10,3) NOT NULL,
  PRIMARY KEY (topic_id, snapshot_date)
);

CREATE TABLE IF NOT EXISTS scopes (
  scope_id   BIGSERIAL PRIMARY KEY,
  user_id    TEXT NOT NULL,
  name       TEXT NOT NULL,
  topic_ids  BIGINT[] NOT NULL DEFAULT '{}',
  keywords   TEXT[] NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS scopes_user_idx ON scopes (user_id);
