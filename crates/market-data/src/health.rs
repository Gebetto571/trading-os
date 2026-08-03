use anyhow::Context;
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::{
    fs::{self, File, OpenOptions},
    io::Write,
    os::unix::fs::{OpenOptionsExt, PermissionsExt},
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

pub const HEALTH_SCHEMA_VERSION: u32 = 1;
pub const DEFAULT_HEALTH_DIR: &str = "./data/health/btcusdt";
pub const HEALTH_DIR_ENV: &str = "TRADING_OS_MARKET_DATA_HEALTH_DIR";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum HealthStatus {
    Succeeded,
    Noop,
    Skipped,
    Failed,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct HealthReport {
    pub schema_version: u32,
    pub observed_at: DateTime<Utc>,
    pub status: HealthStatus,
    pub database_reachable: bool,
    pub symbol: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub range_start: Option<DateTime<Utc>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub range_end: Option<DateTime<Utc>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub last_open_before: Option<DateTime<Utc>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub last_open_after: Option<DateTime<Utc>>,
    pub rows_fetched: u64,
    pub rows_inserted: u64,
    pub rows_repaired: u64,
    pub gaps_remaining: u64,
    pub partitions_verified: u64,
    pub duration_ms: u64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

impl HealthReport {
    pub fn new(status: HealthStatus, symbol: impl Into<String>) -> Self {
        Self {
            schema_version: HEALTH_SCHEMA_VERSION,
            observed_at: Utc::now(),
            status,
            database_reachable: false,
            symbol: symbol.into(),
            range_start: None,
            range_end: None,
            last_open_before: None,
            last_open_after: None,
            rows_fetched: 0,
            rows_inserted: 0,
            rows_repaired: 0,
            gaps_remaining: 0,
            partitions_verified: 0,
            duration_ms: 0,
            error: None,
        }
    }

    pub fn with_database_reachable(mut self, value: bool) -> Self {
        self.database_reachable = value;
        self
    }

    pub fn with_range(mut self, start: DateTime<Utc>, end: DateTime<Utc>) -> Self {
        self.range_start = Some(start);
        self.range_end = Some(end);
        self
    }

    pub fn with_last_open_before(mut self, value: Option<DateTime<Utc>>) -> Self {
        self.last_open_before = value;
        self
    }

    pub fn with_last_open_after(mut self, value: Option<DateTime<Utc>>) -> Self {
        self.last_open_after = value;
        self
    }

    pub fn with_error(mut self, value: impl Into<String>) -> Self {
        self.error = Some(value.into());
        self
    }
}

pub fn health_dir() -> PathBuf {
    std::env::var_os(HEALTH_DIR_ENV)
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(DEFAULT_HEALTH_DIR))
}

pub fn publish(root: &Path, report: &HealthReport) -> anyhow::Result<()> {
    publish_to(root, report)
}

pub fn publish_default(report: &HealthReport) -> anyhow::Result<()> {
    publish(&health_dir(), report)
}

fn publish_to(directory: &Path, report: &HealthReport) -> anyhow::Result<()> {
    let mut encoded = serde_json::to_vec(report).context("serialize health report")?;
    encoded.push(b'\n');

    // A JSON line on stdout lets launchd and manual callers observe every outcome,
    // including failures that happen before PostgreSQL is reachable.
    let stdout = std::io::stdout();
    let mut stdout = stdout.lock();
    stdout
        .write_all(&encoded)
        .context("write health JSON to stdout")?;
    stdout.flush().context("flush health JSON to stdout")?;

    fs::create_dir_all(directory).context("create health directory")?;
    fs::set_permissions(directory, fs::Permissions::from_mode(0o700))
        .context("protect health directory")?;
    write_latest(directory, &encoded)?;
    append_history(directory, &encoded)?;
    Ok(())
}

fn write_latest(directory: &Path, encoded: &[u8]) -> anyhow::Result<()> {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .context("system clock is before Unix epoch")?
        .as_nanos();
    let temporary = directory.join(format!(
        ".latest.json.{}.{}.part",
        std::process::id(),
        nonce
    ));
    let latest = directory.join("latest.json");
    let result = (|| -> anyhow::Result<()> {
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&temporary)
            .context("create temporary health snapshot")?;
        file.write_all(encoded)
            .context("write temporary health snapshot")?;
        file.sync_all().context("sync temporary health snapshot")?;
        fs::rename(&temporary, &latest).context("publish health snapshot atomically")?;
        fs::set_permissions(&latest, fs::Permissions::from_mode(0o600))
            .context("protect health snapshot")?;
        File::open(directory)
            .and_then(|directory| directory.sync_all())
            .context("sync health directory")?;
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result
}

fn append_history(directory: &Path, encoded: &[u8]) -> anyhow::Result<()> {
    let history = directory.join("history.jsonl");
    let mut file = OpenOptions::new()
        .append(true)
        .create(true)
        .mode(0o600)
        .open(&history)
        .context("open health history")?;
    fs::set_permissions(&history, fs::Permissions::from_mode(0o600))
        .context("protect health history")?;
    file.write_all(encoded).context("append health history")?;
    file.sync_data().context("sync health history")?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn atomically_replaces_latest_and_appends_private_history() {
        let directory = tempfile::tempdir().unwrap();
        let first =
            HealthReport::new(HealthStatus::Failed, "BTCUSDT").with_error("database unavailable");
        publish(directory.path(), &first).unwrap();

        let second = HealthReport::new(HealthStatus::Noop, "BTCUSDT")
            .with_database_reachable(true)
            .with_last_open_after(Some("2026-08-03T12:00:00Z".parse().unwrap()));
        publish(directory.path(), &second).unwrap();

        let latest: HealthReport =
            serde_json::from_slice(&fs::read(directory.path().join("latest.json")).unwrap())
                .unwrap();
        assert_eq!(latest, second);

        let history = fs::read_to_string(directory.path().join("history.jsonl")).unwrap();
        let records = history
            .lines()
            .map(|line| serde_json::from_str::<HealthReport>(line).unwrap())
            .collect::<Vec<_>>();
        assert_eq!(records, vec![first, second]);

        let history_mode = fs::metadata(directory.path().join("history.jsonl"))
            .unwrap()
            .permissions()
            .mode()
            & 0o777;
        let latest_mode = fs::metadata(directory.path().join("latest.json"))
            .unwrap()
            .permissions()
            .mode()
            & 0o777;
        assert_eq!(history_mode, 0o600);
        assert_eq!(latest_mode, 0o600);
        assert!(fs::read_dir(directory.path()).unwrap().all(|entry| !entry
            .unwrap()
            .file_name()
            .to_string_lossy()
            .ends_with(".part")));
    }

    #[test]
    fn supports_outcomes_without_database_fields() {
        for status in [HealthStatus::Skipped, HealthStatus::Failed] {
            let record = HealthReport::new(status, "BTCUSDT");
            let json = serde_json::to_value(record).unwrap();
            assert_eq!(json["database_reachable"], false);
            assert!(json.get("range_start").is_none());
            assert!(json.get("last_open_after").is_none());
        }
    }
}
