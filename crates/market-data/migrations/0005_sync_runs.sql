CREATE TABLE market_data_sync_runs (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    venue TEXT NOT NULL,
    market_type TEXT NOT NULL,
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    range_start TIMESTAMPTZ,
    range_end TIMESTAMPTZ NOT NULL,
    stage TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'running', 'succeeded', 'failed', 'noop', 'skipped_locked', 'interrupted'
    )),
    rows_fetched BIGINT NOT NULL DEFAULT 0 CHECK (rows_fetched >= 0),
    rows_inserted BIGINT NOT NULL DEFAULT 0 CHECK (rows_inserted >= 0),
    rows_repaired BIGINT NOT NULL DEFAULT 0 CHECK (rows_repaired >= 0),
    gaps_remaining BIGINT NOT NULL DEFAULT 0 CHECK (gaps_remaining >= 0),
    partitions_verified BIGINT NOT NULL DEFAULT 0 CHECK (partitions_verified >= 0),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    error_message TEXT,
    CHECK (range_start IS NULL OR range_start < range_end),
    CHECK (
        (status = 'running' AND finished_at IS NULL)
        OR (status <> 'running' AND finished_at IS NOT NULL)
    )
);

CREATE INDEX market_data_sync_runs_scope_started
    ON market_data_sync_runs (venue, market_type, symbol, interval, started_at DESC);
