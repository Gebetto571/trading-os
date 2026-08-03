use crate::{
    aggregate::aggregate_complete,
    archive::{daily_fallback, plan_archives, ArchiveItem, SourceType},
    candle::read_csv,
    cli::{Cli, Command},
    db,
    download::{cached_checksum, extract_single_csv, verify_cached, DownloadError, Downloader},
    parquet_export, parquet_verify,
    rest::BinanceRest,
    validation::{validate, ValidationReport},
};
use anyhow::{bail, Context};
use chrono::{DateTime, Datelike, NaiveDate, TimeZone, Utc};
use sqlx::PgPool;
use std::{
    path::{Path, PathBuf},
    sync::Arc,
};
use tokio::sync::Semaphore;
use tokio::task::JoinSet;
use tracing::{info, warn};

fn source_name(t: &SourceType) -> &'static str {
    match t {
        SourceType::Monthly => "monthly",
        SourceType::Daily => "daily",
        SourceType::Rest => "rest",
    }
}
fn cache_path(root: &Path, item: &ArchiveItem) -> PathBuf {
    root.join(source_name(&item.source_type))
        .join(&item.file_name)
}

fn month_floor(time: DateTime<Utc>) -> DateTime<Utc> {
    Utc.from_utc_datetime(
        &NaiveDate::from_ymd_opt(time.year(), time.month(), 1)
            .unwrap()
            .and_hms_opt(0, 0, 0)
            .unwrap(),
    )
}

fn next_month(time: DateTime<Utc>) -> DateTime<Utc> {
    if time.month() == 12 {
        Utc.with_ymd_and_hms(time.year() + 1, 1, 1, 0, 0, 0)
            .unwrap()
    } else {
        Utc.with_ymd_and_hms(time.year(), time.month() + 1, 1, 0, 0, 0)
            .unwrap()
    }
}

fn touched_months(start: DateTime<Utc>, end: DateTime<Utc>) -> Vec<(DateTime<Utc>, DateTime<Utc>)> {
    let mut months = Vec::new();
    let mut cursor = month_floor(start);
    while cursor < end {
        let next = next_month(cursor);
        months.push((cursor, next));
        cursor = next;
    }
    months
}

pub async fn execute(cli: &Cli) -> anyhow::Result<()> {
    cli.validate_scope()?;
    let (start, end) = cli.range()?;
    if matches!(cli.command, Command::Plan) {
        let p = plan_archives(&cli.symbol, &cli.interval, start, end, Utc::now());
        println!("{}", serde_json::to_string_pretty(&p)?);
        return Ok(());
    }
    let pool = if matches!(cli.command, Command::Download) {
        None
    } else {
        let p = db::connect(&cli.database_url()?).await?;
        db::migrate(&p).await?;
        Some(p)
    };
    match cli.command {
        Command::Download => {
            download(cli, start, end, None).await?;
        }
        Command::Import => {
            import_cached(cli, start, end, pool.as_ref().unwrap()).await?;
        }
        Command::Validate => {
            ensure_valid(pool.as_ref().unwrap(), &cli.symbol, start, end).await?;
        }
        Command::Repair => {
            repair(pool.as_ref().unwrap(), &cli.symbol, start, end).await?;
        }
        Command::Aggregate => {
            aggregate(pool.as_ref().unwrap(), &cli.symbol, start, end).await?;
        }
        Command::ExportParquet => {
            ensure_valid(pool.as_ref().unwrap(), &cli.symbol, start, end).await?;
            export_all(pool.as_ref().unwrap(), cli, start, end).await?;
        }
        Command::VerifyParquet => {
            let report = parquet_verify::verify(
                pool.as_ref().unwrap(),
                &cli.parquet_root,
                &cli.symbol,
                start,
                end,
            )
            .await;
            println!("{}", serde_json::to_string(&report)?);
            anyhow::ensure!(report.passed, "PostgreSQL-Parquet verification failed");
        }
        Command::CompareBinance => {
            compare_aggregates_with_binance(pool.as_ref().unwrap(), &cli.symbol, start, end)
                .await?;
        }
        Command::Status => {
            println!(
                "{}",
                serde_json::to_string_pretty(
                    &db::status(pool.as_ref().unwrap(), &cli.symbol, start, end).await?
                )?
            );
        }
        Command::Run => {
            let p = pool.as_ref().unwrap();
            download(cli, start, end, Some(p)).await?;
            import_cached(cli, start, end, p).await?;
            repair(p, &cli.symbol, start, end).await?;
            let report = ensure_valid(p, &cli.symbol, start, end).await?;
            info!(rows = report.rows, "canonical 1m data validated");
            aggregate(p, &cli.symbol, start, end).await?;
            export_all(p, cli, start, end).await?;
        }
        Command::Plan => unreachable!(),
    }
    Ok(())
}

async fn download(
    cli: &Cli,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
    pool: Option<&PgPool>,
) -> anyhow::Result<Vec<ArchiveItem>> {
    let downloader = Downloader::new(Default::default())?;
    let planned = plan_archives(&cli.symbol, "1m", start, end, Utc::now());
    if let Some(pool) = pool {
        for item in &planned {
            db::manifest_plan(
                pool,
                &item.url,
                source_name(&item.source_type),
                &item.period,
                &item.file_name,
            )
            .await?;
        }
    }
    info!(files = planned.len(), "archive plan created");
    let semaphore = Arc::new(Semaphore::new(cli.download_concurrency));
    let mut tasks = JoinSet::new();
    for item in planned {
        let semaphore = Arc::clone(&semaphore);
        let downloader = downloader.clone();
        let cli = cli.clone();
        let pool = pool.cloned();
        tasks.spawn(async move {
            download_planned_item(&downloader, &cli, pool.as_ref(), item, semaphore).await
        });
    }
    let mut downloaded = Vec::new();
    while let Some(result) = tasks.join_next().await {
        downloaded.extend(result.context("download task failed")??);
    }
    Ok(downloaded)
}

async fn download_planned_item(
    downloader: &Downloader,
    cli: &Cli,
    pool: Option<&PgPool>,
    item: ArchiveItem,
    semaphore: Arc<Semaphore>,
) -> anyhow::Result<Vec<ArchiveItem>> {
    match fetch_one(downloader, cli, pool, &item, Arc::clone(&semaphore)).await {
        Ok(()) => Ok(vec![item]),
        Err(DownloadError::NotFound(_)) if item.source_type == SourceType::Monthly => {
            warn!(period=%item.period,"monthly archive missing; using daily archives");
            let daily_items = daily_fallback(&item);
            if let Some(pool) = pool {
                for daily in &daily_items {
                    db::manifest_plan_fallback(
                        pool,
                        &daily.url,
                        source_name(&daily.source_type),
                        &daily.period,
                        &daily.file_name,
                        &item.url,
                    )
                    .await?;
                }
            }
            let mut tasks = JoinSet::new();
            for daily in daily_items {
                let semaphore = Arc::clone(&semaphore);
                let downloader = downloader.clone();
                let cli = cli.clone();
                let pool = pool.cloned();
                tasks.spawn(async move {
                    let result =
                        fetch_one(&downloader, &cli, pool.as_ref(), &daily, semaphore).await;
                    (daily, result)
                });
            }
            let mut downloaded = Vec::new();
            while let Some(result) = tasks.join_next().await {
                let (daily, result) = result.context("daily fallback task failed")?;
                match result {
                    Ok(()) => downloaded.push(daily),
                    Err(DownloadError::NotFound(_)) => {
                        warn!(period=%daily.period,"daily archive missing; REST will fill it");
                        if let Some(pool) = pool {
                            db::manifest_fallback_pending(pool, &daily.url).await?;
                        }
                    }
                    Err(error) => return Err(error.into()),
                }
            }
            if let Some(pool) = pool {
                db::manifest_fallback_pending(pool, &item.url).await?;
            }
            Ok(downloaded)
        }
        Err(DownloadError::NotFound(_)) => {
            warn!(period=%item.period,"daily archive missing; REST will fill it");
            if let Some(pool) = pool {
                db::manifest_fallback_pending(pool, &item.url).await?;
            }
            Ok(Vec::new())
        }
        Err(error) => Err(error.into()),
    }
}

async fn fetch_one(
    d: &Downloader,
    cli: &Cli,
    pool: Option<&PgPool>,
    item: &ArchiveItem,
    semaphore: Arc<Semaphore>,
) -> Result<(), DownloadError> {
    let _permit = semaphore
        .acquire_owned()
        .await
        .map_err(|error| DownloadError::Other(error.into()))?;
    let target = cache_path(&cli.cache_root, item);
    if let Some(p) = pool {
        db::manifest_downloading(p, &item.url)
            .await
            .map_err(DownloadError::Other)?;
    }
    let result = if let Some(pool) = pool {
        let pool = pool.clone();
        let url = item.url.clone();
        d.download_verified_tracked(&item.url, &target, move || {
            let pool = pool.clone();
            let url = url.clone();
            async move { db::manifest_download_attempt(&pool, &url).await }
        })
        .await
    } else {
        d.download_verified(&item.url, &target).await
    };
    match result {
        Ok(bytes) => {
            info!(period=%item.period,bytes,"archive verified");
            if let Some(p) = pool {
                db::manifest_downloaded(p, &item.url, bytes as i64)
                    .await
                    .map_err(DownloadError::Other)?;
                let checksum = cached_checksum(&target).map_err(DownloadError::Other)?;
                db::manifest_verified(p, &item.url, &checksum, bytes as i64)
                    .await
                    .map_err(DownloadError::Other)?;
            }
            Ok(())
        }
        Err(e) => {
            if let Some(p) = pool {
                let _ = db::manifest_failed(p, &item.url, &e.to_string()).await;
            }
            Err(e)
        }
    }
}

async fn import_cached(
    cli: &Cli,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
    pool: &PgPool,
) -> anyhow::Result<u64> {
    let mut items = plan_archives(&cli.symbol, "1m", start, end, Utc::now());
    let monthly = items.clone();
    for m in monthly {
        if m.source_type == SourceType::Monthly && !cache_path(&cli.cache_root, &m).exists() {
            items.extend(daily_fallback(&m));
        }
    }
    let mut inserted = 0;
    items.sort_by_key(|x| x.start);
    for item in items {
        let path = cache_path(&cli.cache_root, &item);
        if !path.exists() {
            continue;
        }
        verify_cached(&path).with_context(|| format!("verify cached {}", path.display()))?;
        let csv =
            extract_single_csv(&path).with_context(|| format!("extract {}", path.display()))?;
        let period_start = chrono::NaiveDate::parse_from_str(&item.period, "%Y-%m-%d")
            .ok()
            .map(|d| d.and_hms_opt(0, 0, 0).unwrap().and_utc())
            .unwrap_or(item.start);
        let period_end = if item.source_type == SourceType::Daily {
            period_start + chrono::Duration::days(1)
        } else {
            item.end
        };
        let mut candles = read_csv(
            csv.as_slice(),
            &cli.symbol,
            period_start,
            period_end,
            source_name(&item.source_type),
            &item.file_name,
        )?;
        let r = validate(&candles, period_start, period_end);
        if !r.errors.is_empty() || !r.duplicates.is_empty() {
            bail!(
                "archive {} failed validation: {}",
                item.file_name,
                serde_json::to_string(&r)?
            )
        }
        if !r.gaps.is_empty() {
            warn!(file=%item.file_name,gaps=r.gaps.len(),"archive gaps will be repaired with REST");
        }
        candles.retain(|c| c.open_time >= start && c.open_time < end);
        inserted += db::insert_candles(pool, &candles).await?;
        if !db::manifest_is_validated(pool, &item.url).await? {
            db::manifest_imported(
                pool,
                &item.url,
                candles.len() as i64,
                candles.first().map(|c| c.open_time),
                candles.last().map(|c| c.open_time),
            )
            .await?;
            db::manifest_validated(pool, &item.url).await?;
        }
    }
    info!(inserted, "archives imported");
    Ok(inserted)
}

async fn repair(
    pool: &PgPool,
    symbol: &str,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
) -> anyhow::Result<u64> {
    let report = db::validate_range(pool, symbol, "1m", start, end).await?;
    let rest = BinanceRest::new()?;
    let mut repaired = 0;
    for (gap_start, gap_end) in report.gaps {
        info!(%gap_start,%gap_end,"repairing gap with REST");
        let rows = rest.fetch(symbol, gap_start, gap_end).await?;
        let repair_report = validate(&rows, gap_start, gap_end);
        if !repair_report.is_valid() {
            bail!(
                "REST repair failed validation: {}",
                serde_json::to_string_pretty(&repair_report)?
            );
        }
        repaired += db::insert_candles(pool, &rows).await?;
    }
    let final_report = db::validate_range(pool, symbol, "1m", start, end).await?;
    anyhow::ensure!(
        final_report.is_valid(),
        "REST repair did not produce a complete canonical range"
    );
    let daily_reconciled = db::reconcile_pending_daily_with_rest(pool, symbol, start, end).await?;
    let monthly_reconciled =
        db::reconcile_pending_monthly_with_fallback(pool, symbol, start, end).await?;
    info!(
        daily_reconciled,
        monthly_reconciled, "fallback manifest entries reconciled"
    );
    info!(repaired, "REST repair complete");
    Ok(repaired)
}

async fn compare_aggregates_with_binance(
    pool: &PgPool,
    symbol: &str,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
) -> anyhow::Result<()> {
    let rest = BinanceRest::new()?;
    for interval in ["15m", "1h", "4h", "1d"] {
        let canonical = db::load_candles(pool, symbol, interval, start, end).await?;
        anyhow::ensure!(
            !canonical.is_empty(),
            "no canonical {interval} candles in comparison range"
        );
        let published = rest.fetch_interval(symbol, interval, start, end).await?;
        compare_market_values(interval, &canonical, &published)?;
        info!(
            interval,
            rows = canonical.len(),
            "Binance aggregate comparison passed"
        );
    }
    Ok(())
}

fn compare_market_values(
    interval: &str,
    canonical: &[crate::candle::Candle],
    published: &[crate::candle::Candle],
) -> anyhow::Result<()> {
    anyhow::ensure!(
        canonical.len() == published.len(),
        "{interval} row count differs: canonical={}, Binance={}",
        canonical.len(),
        published.len()
    );
    for (left, right) in canonical.iter().zip(published) {
        anyhow::ensure!(
            left.open_time == right.open_time && left.same_market_values(right),
            "{interval} differs from Binance at {}",
            left.open_time
        );
    }
    Ok(())
}
async fn ensure_valid(
    pool: &PgPool,
    symbol: &str,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
) -> anyhow::Result<ValidationReport> {
    let r = db::validate_range(pool, symbol, "1m", start, end).await?;
    if !r.is_valid() {
        bail!(
            "canonical data invalid: {}",
            serde_json::to_string_pretty(&r)?
        )
    }
    Ok(r)
}
async fn aggregate(
    pool: &PgPool,
    symbol: &str,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
) -> anyhow::Result<()> {
    for (month_start, month_end) in touched_months(start, end) {
        let base = db::load_candles(pool, symbol, "1m", month_start, month_end).await?;
        for interval in ["15m", "1h", "4h", "1d"] {
            let rows = aggregate_complete(&base, interval)?;
            let inserted = db::insert_candles(pool, &rows).await?;
            info!(interval,month=%month_start.format("%Y-%m"),rows=rows.len(),inserted,"aggregate complete");
        }
    }
    Ok(())
}
async fn export_all(
    pool: &PgPool,
    cli: &Cli,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
) -> anyhow::Result<u64> {
    let mut total = 0;
    for (month_start, month_end) in touched_months(start, end) {
        for interval in ["1m", "15m", "1h", "4h", "1d"] {
            let mut rows =
                db::load_candles(pool, &cli.symbol, interval, month_start, month_end).await?;
            if rows.is_empty() {
                continue;
            }
            rows.sort_by_key(|c| c.open_time);
            let year = month_start.year();
            let month = month_start.month();
            let path = cli
                .parquet_root
                .join("venue=binance/market_type=spot")
                .join(format!("symbol={}", cli.symbol))
                .join(format!(
                    "interval={interval}/year={year:04}/month={month:02}/candles.parquet"
                ));
            total += parquet_export::export(&rows, &path)?;
        }
    }
    info!(rows = total, "Parquet export complete");
    Ok(total)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::validation::tests::candle;
    use rust_decimal::Decimal;
    #[test]
    fn daily_is_rest_fallback_candidate() {
        let item = ArchiveItem {
            source_type: SourceType::Daily,
            period: "x".into(),
            url: "x".into(),
            file_name: "x".into(),
            start: Utc::now(),
            end: Utc::now(),
        };
        assert_eq!(source_name(&item.source_type), "daily");
    }

    #[test]
    fn aggregate_comparison_detects_market_value_difference() {
        let mut canonical = candle("2024-01-01T00:00:00Z");
        canonical.interval = "15m".into();
        let published = canonical.clone();
        compare_market_values(
            "15m",
            std::slice::from_ref(&canonical),
            std::slice::from_ref(&published),
        )
        .unwrap();

        let mut changed = published;
        changed.close = Decimal::new(11, 1);
        assert!(compare_market_values("15m", &[canonical], &[changed]).is_err());
    }
}
