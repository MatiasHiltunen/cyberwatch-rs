PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;

CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('news', 'cve')),
    cve_id TEXT,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_region TEXT NOT NULL DEFAULT 'Global',
    source_language TEXT NOT NULL DEFAULT 'en',
    source_trust INTEGER NOT NULL DEFAULT 1,
    severity TEXT,
    cvss_score REAL,
    published_at TEXT,
    source_updated_at TEXT,
    ingested_at TEXT NOT NULL,
    exploited INTEGER NOT NULL DEFAULT 0,
    kev_date_added TEXT,
    remediation TEXT,
    due_date TEXT,
    ransomware_use TEXT,
    vendor TEXT,
    product TEXT,
    raw_json TEXT,
    content_hash TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_items_effective_time
    ON items(COALESCE(published_at, source_updated_at, ingested_at) DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_items_kind_time
    ON items(kind, COALESCE(published_at, source_updated_at, ingested_at) DESC);
CREATE INDEX IF NOT EXISTS idx_items_cve_id ON items(cve_id);
CREATE INDEX IF NOT EXISTS idx_items_severity ON items(severity);
CREATE INDEX IF NOT EXISTS idx_items_exploited ON items(exploited);
CREATE INDEX IF NOT EXISTS idx_items_source_id ON items(source_id);

CREATE TABLE IF NOT EXISTS item_categories (
    item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    PRIMARY KEY (item_id, category)
);
CREATE INDEX IF NOT EXISTS idx_item_categories_category ON item_categories(category, item_id);

CREATE TABLE IF NOT EXISTS item_cves (
    item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    cve_id TEXT NOT NULL,
    PRIMARY KEY (item_id, cve_id)
);
CREATE INDEX IF NOT EXISTS idx_item_cves_cve ON item_cves(cve_id, item_id);

CREATE TABLE IF NOT EXISTS cve_evidence (
    cve_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    status TEXT,
    severity TEXT,
    cvss_score REAL,
    exploited INTEGER,
    vendor TEXT,
    product TEXT,
    published_at TEXT,
    updated_at TEXT,
    summary TEXT,
    url TEXT,
    raw_json TEXT,
    authoritative INTEGER NOT NULL DEFAULT 0,
    observed_at TEXT NOT NULL,
    PRIMARY KEY (cve_id, source_id, evidence_type)
);
CREATE INDEX IF NOT EXISTS idx_cve_evidence_cve ON cve_evidence(cve_id);
CREATE INDEX IF NOT EXISTS idx_cve_evidence_source ON cve_evidence(source_id);

CREATE TABLE IF NOT EXISTS cve_validation (
    cve_id TEXT PRIMARY KEY,
    confidence TEXT NOT NULL,
    independent_sources INTEGER NOT NULL,
    authoritative_sources INTEGER NOT NULL,
    severity_disagreement INTEGER NOT NULL DEFAULT 0,
    cvss_disagreement INTEGER NOT NULL DEFAULT 0,
    uncorroborated_exploitation INTEGER NOT NULL DEFAULT 0,
    missing_canonical INTEGER NOT NULL DEFAULT 0,
    canonical_status TEXT,
    epss_probability REAL,
    epss_percentile REAL,
    calculated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cve_validation_confidence ON cve_validation(confidence);
CREATE INDEX IF NOT EXISTS idx_cve_validation_calculated ON cve_validation(calculated_at);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    status TEXT NOT NULL,
    fetched INTEGER NOT NULL DEFAULT 0,
    upserted INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    duration_ms INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_ingestion_runs_source ON ingestion_runs(source_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_ingestion_runs_finished ON ingestion_runs(finished_at);

CREATE TABLE IF NOT EXISTS sync_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_cache (
    source_id TEXT PRIMARY KEY,
    etag TEXT,
    last_modified TEXT,
    content_hash TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
