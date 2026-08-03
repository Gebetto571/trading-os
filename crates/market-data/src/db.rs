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

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ManifestStatus {
    Planned,
    Downloading,
    Downloaded,
    ChecksumVerified,
    Imported,
    Validated,
    FallbackComplete,
    Failed,
}

impl ManifestStatus {
    fn as_str(self) -> &'static str {
        match self {
            Self::Planned => "planned",
            Self::Downloading => "downloading",
            Self::Downloaded => "downloaded",
            Self::ChecksumVerified => "checksum_verified",
            Self::Imported => "imported",
            Self::Validated => "validated",
            Self::FallbackComplete => "fallback_complete",
            Self::Failed => "failed",
        }
    }

    fn parse(value: &str) -> anyhow::Result<Self> {
        match value {
            "planned" => Ok(Self::Planned),
            "downloading" => Ok(Self::Downloading),
            "downloaded" => Ok(Self::Downloaded),
            "checksum_verified" => Ok(Self::ChecksumVerified),
            "imported" => Ok(Self::Imported),
            "validated" => Ok(Self::Validated),
            "fallback_complete" => Ok(Self::FallbackComplete),
            "failed" => Ok(Self::Failed),
            _ => bail!("unknown manifest status: {value}"),
        }
    }
}

fn manifest_transition_allowed(from: ManifestStatus, to: ManifestStatus) -> bool {
    use ManifestStatus::*;
    matches!(
        (from, to),
        (Planned, Downloading)
            | (Downloading, Downloading | Downloaded | Failed)
            | (Downloaded, Downloading | ChecksumVerified | Failed)
            | (ChecksumVerified, Imported | Downloading | Failed)
            | (Imported, Validated | Downloading | Failed)
            | (Validated, Downloading)
            | (Failed, Downloading | FallbackComplete)
            | (FallbackComplete, Downloading)
    )
}

pub async fn manifest_plan(
    pool: &PgPool,
    url: &str,
    source_type: &str,
    period: &str,
    file_name: &str,
) -> anyhow::Result<()> {
    sqlx::query("INSERT INTO download_manifest(source_url,source_type,period,file_name,status,attempt_count) VALUES($1,$2,$3,$4,'planned',0) ON CONFLICT(source_url) DO NOTHING")
        .bind(url)
        .bind(source_type)
        .bind(period)
        .bind(file_name)
        .execute(pool)
        .await?;
    Ok(())
}

async fn manifest_transition(pool: &PgPool, url: &str, to: ManifestStatus) -> anyhow::Result<()> {
    let mut tx = pool.begin().await?;
    let current: String =
        sqlx::query_scalar("SELECT status FROM download_manifest WHERE source_url=$1 FOR UPDATE")
            .bind(url)
            .fetch_one(&mut *tx)
            .await?;
    let from = ManifestStatus::parse(&current)?;
    anyhow::ensure!(
        manifest_transition_allowed(from, to),
        "invalid manifest transition {} -> {} for {url}",
        from.as_str(),
        to.as_str()
    );
    sqlx::query("UPDATE download_manifest SET status=$2,updated_at=now() WHERE source_url=$1")
        .bind(url)
        .bind(to.as_str())
        .execute(&mut *tx)
        .await?;
    tx.commit().await?;
    Ok(())
}

pub async fn manifest_downloading(pool: &PgPool, url: &str) -> anyhow::Result<()> {
    manifest_transition(pool, url, ManifestStatus::Downloading).await?;
    sqlx::query("UPDATE download_manifest SET attempt_count=attempt_count+1,error_message=NULL,completed_at=NULL WHERE source_url=$1")
        .bind(url)
        .execute(pool)
        .await?;
    Ok(())
}

pub async fn manifest_downloaded(pool: &PgPool, url: &str, file_size: i64) -> anyhow::Result<()> {
    manifest_transition(pool, url, ManifestStatus::Downloaded).await?;
    sqlx::query("UPDATE download_manifest SET file_size=$2 WHERE source_url=$1")
        .bind(url)
        .bind(file_size)
        .execute(pool)
        .await?;
    Ok(())
}

pub async fn manifest_verified(
    pool: &PgPool,
    url: &str,
    checksum: &str,
    file_size: i64,
) -> anyhow::Result<()> {
    manifest_transition(pool, url, ManifestStatus::ChecksumVerified).await?;
    sqlx::query("UPDATE download_manifest SET expected_checksum=$2,actual_checksum=$2,file_size=$3,error_message=NULL,updated_at=now() WHERE source_url=$1")
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
    manifest_transition(pool, url, ManifestStatus::Imported).await?;
    sqlx::query("UPDATE download_manifest SET row_count=$2,first_open_time=$3,last_open_time=$4,error_message=NULL,updated_at=now() WHERE source_url=$1")
        .bind(url).bind(row_count).bind(first).bind(last).execute(pool).await?;
    Ok(())
}

pub async fn manifest_validated(pool: &PgPool, url: &str) -> anyhow::Result<()> {
    manifest_transition(pool, url, ManifestStatus::Validated).await?;
    sqlx::query(
        "UPDATE download_manifest SET completed_at=now(),error_message=NULL WHERE source_url=$1",
    )
    .bind(url)
    .execute(pool)
    .await?;
    Ok(())
}

pub async fn manifest_failed(pool: &PgPool, url: &str, error: &str) -> anyhow::Result<()> {
    manifest_transition(pool, url, ManifestStatus::Failed).await?;
    sqlx::query(
        "UPDATE download_manifest SET error_message=$2,completed_at=NULL WHERE source_url=$1",
    )
    .bind(url)
    .bind(error)
    .execute(pool)
    .await?;
    Ok(())
}

pub async fn manifest_fallback_complete(
    pool: &PgPool,
    url: &str,
    source_count: usize,
) -> anyhow::Result<()> {
    manifest_transition(pool, url, ManifestStatus::FallbackComplete).await?;
    sqlx::query("UPDATE download_manifest SET fallback_source_count=$2,error_message=NULL,completed_at=now() WHERE source_url=$1")
        .bind(url)
        .bind(source_count as i32)
        .execute(pool)
        .await?;
    Ok(())
}

pub async fn manifest_is_validated(pool: &PgPool, url: &str) -> anyhow::Result<bool> {
    let status: Option<String> =
        sqlx::query_scalar("SELECT status FROM download_manifest WHERE source_url=$1")
            .bind(url)
            .fetch_optional(pool)
            .await?;
    Ok(status.as_deref() == Some("validated"))
}

pub async fn reconcile_failed_daily_with_rest(
    pool: &PgPool,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
) -> anyhow::Result<u64> {
    let urls: Vec<String> = sqlx::query_scalar(
        "SELECT source_url FROM download_manifest
         WHERE source_type='daily' AND status='failed'
           AND period ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
           AND to_date(period, 'YYYY-MM-DD') >= $1::date
           AND to_date(period, 'YYYY-MM-DD') < $2",
    )
    .bind(start)
    .bind(end)
    .fetch_all(pool)
    .await?;
    for url in &urls {
        manifest_fallback_complete(pool, url, 0).await?;
    }
    Ok(urls.len() as u64)
}

pub async fn reconcile_failed_monthly_with_fallback(
    pool: &PgPool,
    symbol: &str,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
) -> anyhow::Result<u64> {
    let rows = sqlx::query(
        "SELECT source_url, period FROM download_manifest
         WHERE source_type='monthly' AND status='failed'
           AND file_name LIKE $1
           AND period ~ '^[0-9]{4}-[0-9]{2}$'
           AND to_date(period || '-01', 'YYYY-MM-DD') >= $2::date
           AND (to_date(period || '-01', 'YYYY-MM-DD') + interval '1 month') <= $3",
    )
    .bind(format!("{symbol}-1m-%"))
    .bind(start)
    .bind(end)
    .fetch_all(pool)
    .await?;
    for row in &rows {
        let url: String = row.get("source_url");
        let period: String = row.get("period");
        let count: i64 = sqlx::query_scalar(
            "SELECT count(*) FROM download_manifest
             WHERE source_type='daily' AND period LIKE $1
               AND status IN ('imported','validated','fallback_complete')",
        )
        .bind(format!("{period}-%"))
        .fetch_one(pool)
        .await?;
        manifest_fallback_complete(pool, &url, count as usize).await?;
    }
    Ok(rows.len() as u64)
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
    use super::*;
    use crate::validation::tests::candle;
    use rust_decimal::Decimal;

    #[test]
    fn migration_uses_numeric_and_primary_key() {
        let sql = include_str!("../migrations/0001_market_data.sql");
        assert!(sql.contains("NUMERIC(38,18)"));
        assert!(sql.contains("PRIMARY KEY (venue, market_type, symbol, interval, open_time)"));
    }

    #[test]
    fn manifest_state_machine_accepts_only_declared_transitions() {
        use ManifestStatus::*;
        assert!(manifest_transition_allowed(Planned, Downloading));
        assert!(manifest_transition_allowed(Downloading, Downloaded));
        assert!(manifest_transition_allowed(Downloaded, ChecksumVerified));
        assert!(manifest_transition_allowed(ChecksumVerified, Imported));
        assert!(manifest_transition_allowed(Imported, Validated));
        assert!(manifest_transition_allowed(Failed, FallbackComplete));
        assert!(manifest_transition_allowed(Validated, Downloading));
        assert!(!manifest_transition_allowed(Planned, Validated));
        assert!(manifest_transition_allowed(Downloading, Downloading));
        assert!(manifest_transition_allowed(Downloaded, Downloading));
        assert!(!manifest_transition_allowed(Validated, Imported));
        assert!(!manifest_transition_allowed(FallbackComplete, Validated));
    }

    #[sqlx::test(migrations = "./migrations")]
    async fn postgres_rejects_conflicting_market_content(pool: PgPool) {
        let original = candle("2024-01-01T00:00:00Z");
        assert_eq!(
            insert_candles(&pool, std::slice::from_ref(&original))
                .await
                .unwrap(),
            1
        );
        assert_eq!(
            insert_candles(&pool, std::slice::from_ref(&original))
                .await
                .unwrap(),
            0
        );

        let mut conflicting = original;
        conflicting.open = Decimal::new(15, 1);
        let error = insert_candles(&pool, &[conflicting]).await.unwrap_err();
        assert!(error.to_string().contains("conflicting candle"));
    }

    #[sqlx::test(migrations = "./migrations")]
    async fn postgres_manifest_runs_full_and_fallback_lifecycles(pool: PgPool) {
        let url = "https://example.test/month.zip";
        manifest_plan(&pool, url, "monthly", "2024-01", "month.zip")
            .await
            .unwrap();
        assert!(manifest_transition(&pool, url, ManifestStatus::Validated)
            .await
            .is_err());
        manifest_downloading(&pool, url).await.unwrap();
        manifest_downloaded(&pool, url, 42).await.unwrap();
        manifest_verified(&pool, url, &"a".repeat(64), 42)
            .await
            .unwrap();
        manifest_imported(
            &pool,
            url,
            1,
            Some("2024-01-01T00:00:00Z".parse().unwrap()),
            Some("2024-01-01T00:00:00Z".parse().unwrap()),
        )
        .await
        .unwrap();
        manifest_validated(&pool, url).await.unwrap();
        assert!(manifest_is_validated(&pool, url).await.unwrap());

        let fallback = "https://example.test/missing.zip";
        manifest_plan(&pool, fallback, "monthly", "2024-02", "missing.zip")
            .await
            .unwrap();
        manifest_downloading(&pool, fallback).await.unwrap();
        manifest_failed(&pool, fallback, "not found").await.unwrap();
        manifest_fallback_complete(&pool, fallback, 29)
            .await
            .unwrap();
        let status: String =
            sqlx::query_scalar("SELECT status FROM download_manifest WHERE source_url=$1")
                .bind(fallback)
                .fetch_one(&pool)
                .await
                .unwrap();
        assert_eq!(status, "fallback_complete");
    }
}
