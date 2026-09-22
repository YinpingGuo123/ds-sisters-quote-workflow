-- Case persistence: current state in `cases`, append-only history in `case_events`.
-- Not event sourcing: a case is never rebuilt from its events. The queryable
-- columns on `cases` are denormalised copies of fields inside case_json so the
-- queue view never has to parse every blob.

CREATE TABLE IF NOT EXISTS cases (
    case_id            TEXT PRIMARY KEY,
    status             TEXT NOT NULL,
    assigned_to        TEXT,
    customer_name      TEXT,
    total_quoted_value REAL,
    created_at         TEXT NOT NULL,   -- ISO 8601
    updated_at         TEXT NOT NULL,
    schema_version     INTEGER NOT NULL,
    case_json          TEXT NOT NULL    -- QuoteCase minus events
);

CREATE TABLE IF NOT EXISTS case_events (
    event_id    INTEGER PRIMARY KEY,
    case_id     TEXT NOT NULL REFERENCES cases(case_id),
    at          TEXT NOT NULL,
    stage       TEXT NOT NULL,
    level       TEXT NOT NULL,
    from_status TEXT,
    to_status   TEXT,
    message     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_case_events_case ON case_events(case_id, event_id);
CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status);
