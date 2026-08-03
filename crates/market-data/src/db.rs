use crate::candle::Candle;
use anyhow::{bail, Context};
use chrono::{DateTime, Duration, Utc};
use sqlx::{PgPool, Postgres, QueryBuilder, Row};
use std::collections::HashMap;

pub async fn connect(url: &str) -> anyhow::Result<PgPool> {
    PgPool::connect(url).await.context("connect PostgreSQL")
}
pub async fn migrate(pool: &PgPool) -> anyhow::Result<()> {
    sqlx::migrate!().run(pool).await?;
    Ok(())
}

pub async fn insert_candles(pool: &PgPool, candles: &[Candle]) -> anyhow::Result<u64> {
    if candles.is_empty() {
        return Ok(0);
    }
    anyhow::ensure!(
        candles.iter().all(|c| {
            c.venue == candles[0].venue
                && c.market_type == candles[0].market_type
                && c.symbol == candles[0].symbol
                && c.interval == candles[0].interval
        }),
        "insert batch must contain one venue, market, symbol and interval"
    );
    let mut input = HashMap::new();
    for candle in candles {
        if let Some(previous) = input.insert(candle.open_time, candle) {
            if !previous.same_market_values(candle) {
                bail!(
                    "conflicting duplicate candle in input at {}",
                    candle.open_time
                );
            }
        }
    }
    let unique = input.into_values().collect::<Vec<_>>();
    let mut tx = pool.begin().await?;
    sqlx::query("SELECT pg_advisory_xact_lock(hashtext($1))")
        .bind(format!(
            "{}:{}:{}:{}",
            candles[0].venue, candles[0].market_type, candles[0].symbol, candles[0].interval
        ))
        .execute(&mut *tx)
        .await?;
    let start = candles.iter().map(|c| c.open_time).min().unwrap();
    let end = candles.iter().map(|c| c.open_time).max().unwrap();
    let existing=sqlx::query("SELECT open_time,open,high,low,close,base_asset_volume,close_time,quote_asset_volume,trade_count,taker_buy_base_volume,taker_buy_quote_volume FROM market_candles WHERE venue=$1 AND market_type=$2 AND symbol=$3 AND interval=$4 AND open_time BETWEEN $5 AND $6")
      .bind(&candles[0].venue).bind(&candles[0].market_type).bind(&candles[0].symbol).bind(&candles[0].interval).bind(start).bind(end).fetch_all(&mut *tx).await?;
    let mut map = HashMap::new();
    for r in existing {
        let t: DateTime<Utc> = r.get("open_time");
        map.insert(
            t,
            (
                r.get("open"),
                r.get("high"),
                r.get("low"),
                r.get("close"),
                r.get("base_asset_volume"),
                r.get("close_time"),
                r.get("quote_asset_volume"),
                r.get("trade_count"),
                r.get("taker_buy_base_volume"),
                r.get("taker_buy_quote_volume"),
            ),
        );
    }
    for c in candles {
        if let Some(v) = map.get(&c.open_time) {
            let incoming = (
                c.open,
                c.high,
                c.low,
                c.close,
                c.base_asset_volume,
                c.close_time,
                c.quote_asset_volume,
                c.trade_count,
                c.taker_buy_base_volume,
                c.taker_buy_quote_volume,
            );
            if *v != incoming {
                bail!("conflicting candle at {}", c.open_time);
            }
        }
    }
    let mut inserted = 0;
    for chunk in unique.chunks(500) {
        let mut q=QueryBuilder::<Postgres>::new("INSERT INTO market_candles (venue,market_type,symbol,interval,open_time,open,high,low,close,base_asset_volume,close_time,quote_asset_volume,trade_count,taker_buy_base_volume,taker_buy_quote_volume,source,source_file) ");
        q.push_values(chunk, |mut b, c| {
            b.push_bind(&c.venue)
                .push_bind(&c.market_type)
                .push_bind(&c.symbol)
                .push_bind(&c.interval)
                .push_bind(c.open_time)
                .push_bind(c.open)
                .push_bind(c.high)
                .push_bind(c.low)
                .push_bind(c.close)
                .push_bind(c.base_asset_volume)
                .push_bind(c.close_time)
                .push_bind(c.quote_asset_volume)
                .push_bind(c.trade_count)
                .push_bind(c.taker_buy_base_volume)
                .push_bind(c.taker_buy_quote_volume)
                .push_bind(&c.source)
                .push_bind(&c.source_file);
        });
        q.push(" ON CONFLICT DO NOTHING");
        inserted += q.build().execute(&mut *tx).await?.rows_affected();
    }
    tx.commit().await?;
    Ok(inserted)
}

pub async fn load_candles(
    pool: &PgPool,
    symbol: &str,
    interval: &str,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
) -> anyhow::Result<Vec<Candle>> {
    let rows=sqlx::query_as::<_,DbCandle>("SELECT venue,market_type,symbol,interval,open_time,open,high,low,close,base_asset_volume,close_time,quote_asset_volume,trade_count,taker_buy_base_volume,taker_buy_quote_volume,source,source_file FROM market_candles WHERE venue='binance' AND market_type='spot' AND symbol=$1 AND interval=$2 AND open_time >= $3 AND open_time < $4 ORDER BY open_time").bind(symbol).bind(interval).bind(start).bind(end).fetch_all(pool).await?;
    Ok(rows.into_iter().map(Into::into).collect())
}

pub async fn validate_range(
    pool: &PgPool,
    symbol: &str,
    interval: &str,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
) -> anyhow::Result<crate::validation::ValidationReport> {
    let summary = sqlx::query(
        "SELECT count(*)::bigint AS rows, min(open_time) AS first, max(open_time) AS last,
         count(*) FILTER (WHERE date_trunc('minute', open_time) <> open_time
           OR close_time - open_time < interval '59.999 seconds'
           OR close_time - open_time >= interval '60 seconds')::bigint AS invalid
         FROM market_candles WHERE venue='binance' AND market_type='spot'
           AND symbol=$1 AND interval=$2 AND open_time >= $3 AND open_time < $4",
    )
    .bind(symbol)
    .bind(interval)
    .bind(start)
    .bind(end)
    .fetch_one(pool)
    .await?;
    let rows = summary.get::<i64, _>("rows") as usize;
    let first = summary.try_get::<DateTime<Utc>, _>("first").ok();
    let last = summary.try_get::<DateTime<Utc>, _>("last").ok();
    let invalid = summary.get::<i64, _>("invalid");
    let gap_rows = sqlx::query(
        "SELECT previous + interval '1 minute' AS gap_start, open_time AS gap_end FROM (
           SELECT open_time, lag(open_time) OVER (ORDER BY open_time) AS previous
           FROM market_candles WHERE venue='binance' AND market_type='spot'
             AND symbol=$1 AND interval=$2 AND open_time >= $3 AND open_time < $4
         ) ordered WHERE previous IS NOT NULL AND open_time > previous + interval '1 minute'",
    )
    .bind(symbol)
    .bind(interval)
    .bind(start)
    .bind(end)
    .fetch_all(pool)
    .await?;
    let mut gaps = gap_rows
        .into_iter()
        .map(|row| (row.get("gap_start"), row.get("gap_end")))
        .collect::<Vec<_>>();
    match (first, last) {
        (Some(first), Some(last)) => {
            if first > start {
                gaps.insert(0, (start, first));
            }
            let after_last = last + Duration::minutes(1);
            if after_last < end {
                gaps.push((after_last, end));
            }
        }
        _ if start < end => gaps.push((start, end)),
        _ => {}
    }
    let mut errors = Vec::new();
    if invalid > 0 {
        errors.push(format!(
            "{invalid} rows violate timestamp alignment or duration"
        ));
    }
    Ok(crate::validation::ValidationReport {
        rows,
        first_open_time: first,
        last_open_time: last,
        gaps,
        duplicates: Vec::new(),
        errors,
    })
}

pub async fn manifest_update(
    pool: &PgPool,
    url: &str,
    source_type: &str,
    period: &str,
    file_name: &str,
    status: &str,
    error: Option<&str>,
) -> anyhow::Result<()> {
    sqlx::query("INSERT INTO download_manifest(source_url,source_type,period,file_name,status,attempt_count,error_message,completed_at) VALUES($1,$2,$3,$4,$5,1,$6,CASE WHEN $5 IN ('imported','validated') THEN now() END) ON CONFLICT(source_url) DO UPDATE SET status=EXCLUDED.status,attempt_count=download_manifest.attempt_count+1,error_message=EXCLUDED.error_message,completed_at=EXCLUDED.completed_at,updated_at=now()")
 .bind(url).bind(source_type).bind(period).bind(file_name).bind(status).bind(error).execute(pool).await?;
    Ok(())
}

pub async fn manifest_verified(
    pool: &PgPool,
    url: &str,
    checksum: &str,
    file_size: i64,
) -> anyhow::Result<()> {
    sqlx::query("UPDATE download_manifest SET expected_checksum=$2,actual_checksum=$2,file_size=$3,status='checksum_verified',error_message=NULL,updated_at=now() WHERE source_url=$1")
        .bind(url).bind(checksum).bind(file_size).execute(pool).await?;
    Ok(())
}

pub async fn manifest_imported(
    pool: &PgPool,
    url: &str,
    row_count: i64,
    first: Option<DateTime<Utc>>,
    last: Option<DateTime<Utc>>,
) -> anyhow::Result<()> {
    sqlx::query("UPDATE download_manifest SET row_count=$2,first_open_time=$3,last_open_time=$4,status='imported',completed_at=now(),error_message=NULL,updated_at=now() WHERE source_url=$1")
        .bind(url).bind(row_count).bind(first).bind(last).execute(pool).await?;
    Ok(())
}

pub async fn status(
    pool: &PgPool,
    symbol: &str,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
) -> anyhow::Result<serde_json::Value> {
    let row=sqlx::query("SELECT count(*)::bigint AS rows,min(open_time) AS first,max(open_time) AS last FROM market_candles WHERE venue='binance' AND market_type='spot' AND symbol=$1 AND interval='1m' AND open_time >= $2 AND open_time < $3").bind(symbol).bind(start).bind(end).fetch_one(pool).await?;
    let failed: i64 =
        sqlx::query_scalar("SELECT count(*)::bigint FROM download_manifest WHERE status='failed'")
            .fetch_one(pool)
            .await?;
    Ok(
        serde_json::json!({"rows":row.get::<i64,_>("rows"),"first":row.try_get::<DateTime<Utc>,_>("first").ok(),"last":row.try_get::<DateTime<Utc>,_>("last").ok(),"failed_periods":failed}),
    )
}

#[derive(sqlx::FromRow)]
struct DbCandle {
    venue: String,
    market_type: String,
    symbol: String,
    interval: String,
    open_time: DateTime<Utc>,
    open: rust_decimal::Decimal,
    high: rust_decimal::Decimal,
    low: rust_decimal::Decimal,
    close: rust_decimal::Decimal,
    base_asset_volume: rust_decimal::Decimal,
    close_time: DateTime<Utc>,
    quote_asset_volume: rust_decimal::Decimal,
    trade_count: i64,
    taker_buy_base_volume: rust_decimal::Decimal,
    taker_buy_quote_volume: rust_decimal::Decimal,
    source: String,
    source_file: String,
}
impl From<DbCandle> for Candle {
    fn from(x: DbCandle) -> Self {
        Self {
            venue: x.venue,
            market_type: x.market_type,
            symbol: x.symbol,
            interval: x.interval,
            open_time: x.open_time,
            open: x.open,
            high: x.high,
            low: x.low,
            close: x.close,
            base_asset_volume: x.base_asset_volume,
            close_time: x.close_time,
            quote_asset_volume: x.quote_asset_volume,
            trade_count: x.trade_count,
            taker_buy_base_volume: x.taker_buy_base_volume,
            taker_buy_quote_volume: x.taker_buy_quote_volume,
            source: x.source,
            source_file: x.source_file,
        }
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn migration_uses_numeric_and_primary_key() {
        let sql = include_str!("../migrations/0001_market_data.sql");
        assert!(sql.contains("NUMERIC(38,18)"));
        assert!(sql.contains("PRIMARY KEY (venue, market_type, symbol, interval, open_time)"));
    }
}
