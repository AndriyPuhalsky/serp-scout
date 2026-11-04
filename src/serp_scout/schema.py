"""DDL SQLite точно за docs/02: таблиці, UNIQUE-обмеження, представлення v_latest і v_history."""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS keywords (
    id       INTEGER PRIMARY KEY,
    keyword  TEXT NOT NULL UNIQUE,
    cluster  TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date      TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    status        TEXT NOT NULL DEFAULT 'running',  -- running | ok | partial | budget_exceeded | failed
    mode          TEXT,
    serp_calls    INTEGER NOT NULL DEFAULT 0,
    urls_total    INTEGER NOT NULL DEFAULT 0,
    urls_new      INTEGER NOT NULL DEFAULT 0,
    pages_fetched INTEGER NOT NULL DEFAULT 0,
    pages_failed  INTEGER NOT NULL DEFAULT 0,
    labels_new    INTEGER NOT NULL DEFAULT 0,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd      REAL NOT NULL DEFAULT 0,
    errors_json   TEXT,
    git_sha       TEXT
);

CREATE TABLE IF NOT EXISTS urls (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    url           TEXT NOT NULL UNIQUE,
    domain        TEXT NOT NULL,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    best_position INTEGER
);

CREATE TABLE IF NOT EXISTS serp_results (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date   TEXT NOT NULL,
    keyword_id INTEGER NOT NULL REFERENCES keywords(id),
    position   INTEGER NOT NULL,
    url_id     INTEGER NOT NULL REFERENCES urls(id),
    title      TEXT,
    snippet    TEXT,
    UNIQUE (run_date, keyword_id, position)
);

CREATE TABLE IF NOT EXISTS pages (
    url_id             INTEGER NOT NULL UNIQUE REFERENCES urls(id),
    fetched_at         TEXT,
    method             TEXT,          -- httpx | reader | snippet
    http_status        INTEGER,
    text_hash          TEXT,
    text_len           INTEGER,
    text_path          TEXT,
    emails_json        TEXT,
    contact_links_json TEXT,
    error              TEXT,
    final_url          TEXT           -- кінцева адреса після редиректів (goto Google → сайт)
);

CREATE TABLE IF NOT EXISTS labels (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    url_id                 INTEGER NOT NULL REFERENCES urls(id),
    prompt_version         TEXT NOT NULL,
    text_hash              TEXT NOT NULL,
    site_type              TEXT,
    relevant               INTEGER,
    confidence             REAL,
    reason                 TEXT,
    brands_json            TEXT,
    contact_json           TEXT,
    placement_signals_json TEXT,
    needs_review           INTEGER,
    model                  TEXT,
    input_tokens           INTEGER,
    output_tokens          INTEGER,
    cost_usd               REAL,
    labeled_at             TEXT,
    UNIQUE (url_id, prompt_version, text_hash)
);

CREATE TABLE IF NOT EXISTS affiliate_links (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    url_id       INTEGER NOT NULL REFERENCES urls(id),
    href         TEXT NOT NULL,
    anchor       TEXT,
    final_url    TEXT,
    final_domain TEXT,
    brand        TEXT,
    hops         INTEGER,
    resolved_at  TEXT,
    error        TEXT,
    UNIQUE (url_id, href)
);

CREATE INDEX IF NOT EXISTS idx_serp_results_url ON serp_results(url_id);
CREATE INDEX IF NOT EXISTS idx_serp_results_date ON serp_results(run_date);
CREATE INDEX IF NOT EXISTS idx_labels_url ON labels(url_id);

-- Історія позицій: ключ × URL × дата
CREATE VIEW IF NOT EXISTS v_history AS
SELECT k.id AS keyword_id, k.keyword, k.cluster, u.id AS url_id, u.url, u.domain,
       s.run_date, s.position
FROM serp_results s
JOIN keywords k ON k.id = s.keyword_id
JOIN urls u ON u.id = s.url_id
ORDER BY k.id, s.run_date, s.position;

-- Останній снапшот + остання розмітка на URL
CREATE VIEW IF NOT EXISTS v_latest AS
WITH last_run AS (SELECT MAX(run_date) AS run_date FROM serp_results),
     last_label AS (
         SELECT l.* FROM labels l
         JOIN (SELECT url_id, MAX(id) AS id FROM labels GROUP BY url_id) m ON m.id = l.id
     )
SELECT s.run_date, k.id AS keyword_id, k.keyword, k.cluster, s.position,
       u.id AS url_id, u.url, u.domain, u.first_seen, u.last_seen, u.best_position,
       s.title, s.snippet,
       ll.site_type, ll.relevant, ll.confidence, ll.reason, ll.brands_json, ll.contact_json,
       ll.placement_signals_json, ll.needs_review, ll.model, ll.labeled_at,
       p.method, p.http_status, p.emails_json, p.contact_links_json, p.error AS page_error
FROM serp_results s
JOIN last_run lr ON lr.run_date = s.run_date
JOIN keywords k ON k.id = s.keyword_id
JOIN urls u ON u.id = s.url_id
LEFT JOIN last_label ll ON ll.url_id = u.id
LEFT JOIN pages p ON p.url_id = u.id
ORDER BY k.id, s.position;
"""
