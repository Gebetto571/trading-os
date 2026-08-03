CREATE TABLE IF NOT EXISTS market_candles (
    venue TEXT NOT NULL,
    market_type TEXT NOT NULL,
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    open_time TIMESTAMPTZ NOT NULL,
    open NUMERIC(38,18) NOT NULL,
    high NUMERIC(38,18) NOT NULL,
    low NUMERIC(38,18) NOT NULL,
    close NUMERIC(38,18) NOT NULL,
    base_asset_volume NUMERIC(38,18) NOT NULL,
    close_time TIMESTAMPTZ NOT NULL,
    quote_asset_volume NUMERIC(38,18) NOT NULL,
    trade_count BIGINT NOT NULL,
    taker_buy_base_volume NUMERIC(38,18) NOT NULL,
    taker_buy_quote_volume NUMERIC(38,18) NOT NULL,
    source TEXT NOT NULL,
    source_file TEXT NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (venue, market_type, symbol, interval, open_time),
    CHECK (high >= open AND high >= close AND low <= open AND low <= close),
    CHECK (high >= low AND open > 0 AND high > 0 AND low > 0 AND close > 0),
    CHECK (base_asset_volume >= 0 AND quote_asset_volume >= 0),
    CHECK (taker_buy_base_volume >= 0 AND taker_buy_quote_volume >= 0),
    CHECK (trade_count >= 0)
);

CREATE INDEX IF NOT EXISTS market_candles_lookup
    ON market_candles (symbol, interval, open_time);

CREATE TABLE IF NOT EXISTS download_manifest (
    source_url TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    period TEXT NOT NULL,
    file_name TEXT NOT NULL,
    expected_checksum TEXT,
    actual_checksum TEXT,
    file_size BIGINT,
    status TEXT NOT NULL CHECK (status IN
      ('planned','downloading','downloaded','checksum_verified','imported','validated','failed')),
    row_count BIGINT,
    first_open_time TIMESTAMPTZ,
    last_open_time TIMESTAMPTZ,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
