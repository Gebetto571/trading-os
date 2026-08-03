use crate::{
    aggregate::aggregate_complete,
    archive::{daily_fallback, plan_archives, ArchiveItem, SourceType},
    candle::read_csv,
    cli::{Cli, Command},
    db,
    download::{cached_checksum, extract_single_csv, verify_cached, DownloadError, Downloader},
    health::{self, HealthReport, HealthStatus},
    parquet_export, parquet_verify,
    rest::BinanceRest,
    validation::{validate, ValidationReport},
};
use anyhow::{bail, Context};
use chrono::{DateTime, Datelike, Duration, NaiveDate, TimeZone, Utc};
use sqlx::PgPool;
use std::{
    path::{Path, PathBuf},
    sync::Arc,
    time::Instant,
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
    if matches!(cli.command, Command::Sync) {
        return sync_with_health(cli, start, end).await;
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
            let mut counts = db::SyncRunCounts::default();
            repair(pool.as_ref().unwrap(), &cli.symbol, start, end, &mut counts).await?;
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
            let mut counts = db::SyncRunCounts::default();
            repair(p, &cli.symbol, start, end, &mut counts).await?;
            let report = ensure_valid(p, &cli.symbol, start, end).await?;
            info!(rows = report.rows, "canonical 1m data validated");
            aggregate(p, &cli.symbol, start, end).await?;
            export_all(p, cli, start, end).await?;
        }
        Command::Sync => unreachable!(),
        Command::Plan => unreachable!(),
    }
    Ok(())
}

#[derive(Debug)]
struct SyncOutcome {
    status: &'static str,
    range_start: Option<DateTime<Utc>>,
    range_end: DateTime<Utc>,
    last_open_before: Option<DateTime<Utc>>,
    last_open_after: Option<DateTime<Utc>>,
    counts: db::SyncRunCounts,
}

#[derive(Debug)]
struct SyncFailure {
    error: anyhow::Error,
    range_start: Option<DateTime<Utc>>,
    range_end: Option<DateTime<Utc>>,
    last_open_before: Option<DateTime<Utc>>,
    last_open_after: Option<DateTime<Utc>>,
    counts: db::SyncRunCounts,
}

impl From<anyhow::Error> for SyncFailure {
    fn from(error: anyhow::Error) -> Self {
        Self {
            error,
            range_start: None,
            range_end: None,
            last_open_before: None,
            last_open_after: None,
            counts: Default::default(),
        }
    }
}

impl SyncFailure {
    fn with_error(mut self, error: anyhow::Error) -> Self {
        self.error = error;
        self
    }
}

impl std::fmt::Display for SyncFailure {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self.error.fmt(formatter)
    }
}

fn sync_work_start(
    end: DateTime<Utc>,
    latest: DateTime<Utc>,
    recent_gaps: &[(DateTime<Utc>, DateTime<Utc>)],
) -> Option<DateTime<Utc>> {
    let tail_start = latest + Duration::minutes(1);
    match (
        recent_gaps.first().map(|gap| gap.0),
        (tail_start < end).then_some(tail_start),
    ) {
        (Some(left), Some(right)) => Some(left.min(right)),
        (Some(value), None) | (None, Some(value)) => Some(value),
        (None, None) => None,
    }
}

fn archive_catchup_end(tail_start: DateTime<Utc>, end: DateTime<Utc>) -> Option<DateTime<Utc>> {
    let archive_end = end - Duration::days(7);
    (tail_start < archive_end).then_some(archive_end)
}

fn ensure_rest_repairable(gaps: &[(DateTime<Utc>, DateTime<Utc>)]) -> anyhow::Result<()> {
    anyhow::ensure!(
        gaps.iter()
            .all(|(start, end)| { *start < *end && *end - *start <= Duration::days(7) }),
        "an unresolved gap exceeds the seven-day REST repair limit; restore archives first"
    );
    Ok(())
}

fn validate_repair_batch(
    rows: &[crate::candle::Candle],
    start: DateTime<Utc>,
    end: DateTime<Utc>,
) -> anyhow::Result<()> {
    let report = validate(rows, start, end);
    anyhow::ensure!(
        report.is_valid(),
        "REST repair failed validation: {}",
        serde_json::to_string_pretty(&report)?
    );
    Ok(())
}

async fn sync_locked(
    pool: &PgPool,
    cli: &Cli,
    requested_start: DateTime<Utc>,
    end: DateTime<Utc>,
) -> Result<SyncOutcome, SyncFailure> {
    db::interrupt_stale_sync_runs(pool, &cli.symbol).await?;
    let latest = db::latest_open_time(pool, &cli.symbol, "1m").await?;
    let Some(latest) = latest else {
        let run_id = db::begin_sync_run(pool, &cli.symbol, None, end).await?;
        let error = "canonical 1m database is empty; run the historical bootstrap first";
        db::finish_sync_run(
            pool,
            run_id,
            "failed",
            "bootstrap_required",
            Default::default(),
            Some(error),
        )
        .await?;
        return Err(anyhow::anyhow!(error).into());
    };

    let recent_start = requested_start.max(end - Duration::days(7));
    let recent = db::validate_range(pool, &cli.symbol, "1m", recent_start, end).await?;
    if !recent.errors.is_empty() || !recent.duplicates.is_empty() {
        return Err(anyhow::anyhow!("recent canonical range contains invalid rows").into());
    }
    let tail_start = latest + Duration::minutes(1);
    let work_start = sync_work_start(end, latest, &recent.gaps);
    let Some(work_start) = work_start else {
        let run_id = db::begin_sync_run(pool, &cli.symbol, None, end).await?;
        db::finish_sync_run(pool, run_id, "noop", "complete", Default::default(), None).await?;
        return Ok(SyncOutcome {
            status: "noop",
            range_start: None,
            range_end: end,
            last_open_before: Some(latest),
            last_open_after: Some(latest),
            counts: Default::default(),
        });
    };

    let run_id = db::begin_sync_run(pool, &cli.symbol, Some(work_start), end).await?;
    let mut counts = db::SyncRunCounts::default();
    let result: anyhow::Result<SyncOutcome> = async {
        if let Some(archive_end) = archive_catchup_end(tail_start, end) {
            db::update_sync_stage(pool, run_id, "archive_catchup").await?;
            download(cli, tail_start, archive_end, Some(pool)).await?;
            counts.rows_inserted += import_cached(cli, tail_start, archive_end, pool).await?;
        }

        db::update_sync_stage(pool, run_id, "rest_repair").await?;
        repair(pool, &cli.symbol, work_start, end, &mut counts).await?;
        db::reconcile_pending_daily_with_rest(pool, &cli.symbol, requested_start, end).await?;
        db::reconcile_pending_monthly_with_fallback(pool, &cli.symbol, requested_start, end)
            .await?;

        db::update_sync_stage(pool, run_id, "validate").await?;
        ensure_valid(pool, &cli.symbol, work_start, end).await?;
        db::update_sync_stage(pool, run_id, "aggregate").await?;
        aggregate(pool, &cli.symbol, work_start, end).await?;
        db::update_sync_stage(pool, run_id, "export_parquet").await?;
        export_all(pool, cli, work_start, end).await?;
        db::update_sync_stage(pool, run_id, "verify_parquet").await?;
        let verification =
            parquet_verify::verify(pool, &cli.parquet_root, &cli.symbol, work_start, end).await;
        anyhow::ensure!(
            verification.passed,
            "post-sync PostgreSQL-Parquet verification failed: {}",
            serde_json::to_string(&verification)?
        );
        counts.partitions_verified = verification.partitions_checked;
        let final_report = db::validate_range(pool, &cli.symbol, "1m", work_start, end).await?;
        counts.gaps_remaining = final_report.gaps.len() as u64;
        anyhow::ensure!(final_report.is_valid(), "post-sync gaps remain");
        let last_after = db::latest_open_time(pool, &cli.symbol, "1m").await?;
        Ok(SyncOutcome {
            status: "succeeded",
            range_start: Some(work_start),
            range_end: end,
            last_open_before: Some(latest),
            last_open_after: last_after,
            counts,
        })
    }
    .await;

    match result {
        Ok(outcome) => {
            db::finish_sync_run(pool, run_id, "succeeded", "complete", counts, None).await?;
            Ok(outcome)
        }
        Err(error) => {
            let message = format!("{error:#}");
            let _ =
                db::finish_sync_run(pool, run_id, "failed", "failed", counts, Some(&message)).await;
            let last_after = db::latest_open_time(pool, &cli.symbol, "1m")
                .await
                .unwrap_or(Some(latest));
            Err(SyncFailure {
                error,
                range_start: Some(work_start),
                range_end: Some(end),
                last_open_before: Some(latest),
                last_open_after: last_after,
                counts,
            })
        }
    }
}

async fn sync_with_health(
    cli: &Cli,
    requested_start: DateTime<Utc>,
    end: DateTime<Utc>,
) -> anyhow::Result<()> {
    let started = Instant::now();
    let database_url = match cli.database_url() {
        Ok(url) => url,
        Err(error) => {
            let mut report = HealthReport::new(HealthStatus::Failed, &cli.symbol)
                .with_error("database configuration unavailable");
            report.range_end = Some(end);
            report.duration_ms = started.elapsed().as_millis() as u64;
            health::publish(&cli.health_root, &report)?;
            return Err(error);
        }
    };
    let pool = match db::connect(&database_url).await {
        Ok(pool) => pool,
        Err(error) => {
            let mut report = HealthReport::new(HealthStatus::Failed, &cli.symbol)
                .with_error("database unavailable");
            report.range_end = Some(end);
            report.duration_ms = started.elapsed().as_millis() as u64;
            health::publish(&cli.health_root, &report)?;
            return Err(error);
        }
    };
    if let Err(error) = db::migrate(&pool).await {
        let mut report = HealthReport::new(HealthStatus::Failed, &cli.symbol)
            .with_database_reachable(true)
            .with_error("database migration unavailable");
        report.range_end = Some(end);
        report.duration_ms = started.elapsed().as_millis() as u64;
        health::publish(&cli.health_root, &report)?;
        return Err(error);
    }

    let lock = match db::try_sync_lock(
        &pool,
        &format!("market-data-sync:binance:spot:{}:1m", cli.symbol),
    )
    .await
    {
        Ok(lock) => lock,
        Err(error) => {
            let mut report = HealthReport::new(HealthStatus::Failed, &cli.symbol)
                .with_database_reachable(false)
                .with_error("database unavailable while acquiring sync lock");
            report.range_end = Some(end);
            report.duration_ms = started.elapsed().as_millis() as u64;
            health::publish(&cli.health_root, &report)?;
            return Err(error);
        }
    };
    let Some(lock) = lock else {
        if let Err(error) = db::record_skipped_sync_run(&pool, &cli.symbol, end).await {
            let mut report = HealthReport::new(HealthStatus::Failed, &cli.symbol)
                .with_database_reachable(false)
                .with_error("database unavailable while recording skipped sync");
            report.range_end = Some(end);
            report.duration_ms = started.elapsed().as_millis() as u64;
            health::publish(&cli.health_root, &report)?;
            return Err(error);
        }
        let mut report =
            HealthReport::new(HealthStatus::Skipped, &cli.symbol).with_database_reachable(true);
        report.range_end = Some(end);
        report.duration_ms = started.elapsed().as_millis() as u64;
        health::publish(&cli.health_root, &report)?;
        return Ok(());
    };

    let result = sync_locked(&pool, cli, requested_start, end).await;
    let release = lock.release().await;
    let result = match (result, release) {
        (Ok(outcome), Ok(())) => Ok(outcome),
        (Err(failure), Ok(())) => Err(failure),
        (Ok(_), Err(error)) => Err(SyncFailure::from(
            error.context("release sync advisory lock"),
        )),
        (Err(failure), Err(release_error)) => {
            let error = anyhow::anyhow!(
                "{:#}; also failed to release sync advisory lock: {release_error:#}",
                failure.error
            );
            Err(failure.with_error(error))
        }
    };

    match result {
        Ok(outcome) => {
            let status = if outcome.status == "noop" {
                HealthStatus::Noop
            } else {
                HealthStatus::Succeeded
            };
            let mut report = HealthReport::new(status, &cli.symbol)
                .with_database_reachable(true)
                .with_last_open_before(outcome.last_open_before)
                .with_last_open_after(outcome.last_open_after);
            report.range_start = outcome.range_start;
            report.range_end = Some(outcome.range_end);
            report.rows_fetched = outcome.counts.rows_fetched;
            report.rows_inserted = outcome.counts.rows_inserted;
            report.rows_repaired = outcome.counts.rows_repaired;
            report.gaps_remaining = outcome.counts.gaps_remaining;
            report.partitions_verified = outcome.counts.partitions_verified;
            report.duration_ms = started.elapsed().as_millis() as u64;
            health::publish(&cli.health_root, &report)?;
            Ok(())
        }
        Err(failure) => {
            let mut report = HealthReport::new(HealthStatus::Failed, &cli.symbol)
                .with_database_reachable(true)
                .with_last_open_before(failure.last_open_before)
                .with_last_open_after(failure.last_open_after)
                .with_error("market-data synchronization failed");
            report.range_start = failure.range_start;
            report.range_end = failure.range_end.or(Some(end));
            report.rows_fetched = failure.counts.rows_fetched;
            report.rows_inserted = failure.counts.rows_inserted;
            report.rows_repaired = failure.counts.rows_repaired;
            report.gaps_remaining = failure.counts.gaps_remaining;
            report.partitions_verified = failure.counts.partitions_verified;
            report.duration_ms = started.elapsed().as_millis() as u64;
            let publish = health::publish(&cli.health_root, &report);
            if let Err(publish_error) = publish {
                return Err(failure.error.context(format!(
                    "also failed to publish health report: {publish_error:#}"
                )));
            }
            Err(failure.error)
        }
    }
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
    counts: &mut db::SyncRunCounts,
) -> anyhow::Result<()> {
    let report = db::validate_range(pool, symbol, "1m", start, end).await?;
    counts.gaps_remaining = report.gaps.len() as u64;
    ensure_rest_repairable(&report.gaps)?;
    let rest = BinanceRest::new()?;
    for (gap_start, gap_end) in report.gaps {
        info!(%gap_start,%gap_end,"repairing gap with REST");
        let rows = rest.fetch(symbol, gap_start, gap_end).await?;
        counts.rows_fetched += rows.len() as u64;
        validate_repair_batch(&rows, gap_start, gap_end)?;
        let inserted = db::insert_candles(pool, &rows).await?;
        counts.rows_inserted += inserted;
        counts.rows_repaired += inserted;
        counts.gaps_remaining = counts.gaps_remaining.saturating_sub(1);
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
    info!(repaired = counts.rows_repaired, "REST repair complete");
    Ok(())
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
    use clap::Parser;
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

    #[test]
    fn sync_window_uses_tail_or_earliest_recent_gap() {
        let end: DateTime<Utc> = "2026-08-03T12:00:00Z".parse().unwrap();
        let latest = end - Duration::minutes(10);
        assert_eq!(
            sync_work_start(end, latest, &[]),
            Some(end - Duration::minutes(9))
        );
        let gap = (end - Duration::hours(2), end - Duration::hours(1));
        assert_eq!(sync_work_start(end, latest, &[gap]), Some(gap.0));
        assert_eq!(sync_work_start(end, end - Duration::minutes(1), &[]), None);
    }

    #[test]
    fn sync_archive_threshold_is_strictly_seven_days() {
        let end: DateTime<Utc> = "2026-08-03T12:00:00Z".parse().unwrap();
        assert_eq!(
            archive_catchup_end(end - Duration::days(7) - Duration::minutes(1), end),
            Some(end - Duration::days(7))
        );
        assert_eq!(archive_catchup_end(end - Duration::days(7), end), None);
    }

    #[test]
    fn unresolved_archive_gap_over_seven_days_fails_closed() {
        let start: DateTime<Utc> = "2026-07-01T00:00:00Z".parse().unwrap();
        assert!(ensure_rest_repairable(&[(start, start + Duration::days(7))]).is_ok());
        assert!(ensure_rest_repairable(&[(
            start,
            start + Duration::days(7) + Duration::minutes(1)
        )])
        .is_err());
    }

    #[test]
    fn rest_rows_are_rejected_before_insert_when_incomplete() {
        let start: DateTime<Utc> = "2026-08-01T00:00:00Z".parse().unwrap();
        let rows = vec![candle("2026-08-01T00:00:00Z")];
        assert!(validate_repair_batch(&rows, start, start + Duration::minutes(2)).is_err());
    }

    #[test]
    fn touched_months_cover_both_sides_of_month_boundary() {
        let start: DateTime<Utc> = "2026-07-31T23:59:00Z".parse().unwrap();
        let end: DateTime<Utc> = "2026-08-01T00:01:00Z".parse().unwrap();
        let months = touched_months(start, end);
        assert_eq!(months.len(), 2);
        assert_eq!(
            months[0].0,
            "2026-07-01T00:00:00Z".parse::<DateTime<Utc>>().unwrap()
        );
        assert_eq!(
            months[1].0,
            "2026-08-01T00:00:00Z".parse::<DateTime<Utc>>().unwrap()
        );
    }

    #[sqlx::test(migrations = "./migrations")]
    async fn sync_rejects_empty_database_without_network_bootstrap(pool: PgPool) {
        let cli = Cli::parse_from([
            "market-data-import",
            "sync",
            "--start",
            "2024-01-01T00:00:00Z",
            "--end",
            "2024-01-01T00:01:00Z",
        ]);
        let error = sync_locked(
            &pool,
            &cli,
            "2024-01-01T00:00:00Z".parse().unwrap(),
            "2024-01-01T00:01:00Z".parse().unwrap(),
        )
        .await
        .unwrap_err();
        assert!(error.to_string().contains("historical bootstrap"));
        let status: String =
            sqlx::query_scalar("SELECT status FROM market_data_sync_runs ORDER BY id DESC LIMIT 1")
                .fetch_one(&pool)
                .await
                .unwrap();
        assert_eq!(status, "failed");
    }

    #[sqlx::test(migrations = "./migrations")]
    async fn sync_noop_records_terminal_run(pool: PgPool) {
        let row = candle("2024-01-01T00:00:00Z");
        db::insert_candles(&pool, std::slice::from_ref(&row))
            .await
            .unwrap();
        let cli = Cli::parse_from([
            "market-data-import",
            "sync",
            "--start",
            "2024-01-01T00:00:00Z",
            "--end",
            "2024-01-01T00:01:00Z",
        ]);
        let outcome = sync_locked(
            &pool,
            &cli,
            "2024-01-01T00:00:00Z".parse().unwrap(),
            "2024-01-01T00:01:00Z".parse().unwrap(),
        )
        .await
        .unwrap();
        assert_eq!(outcome.status, "noop");
        let status: String =
            sqlx::query_scalar("SELECT status FROM market_data_sync_runs ORDER BY id DESC LIMIT 1")
                .fetch_one(&pool)
                .await
                .unwrap();
        assert_eq!(status, "noop");
    }
}
