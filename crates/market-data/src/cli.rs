use chrono::{DateTime, Timelike, Utc};
use clap::{Parser, Subcommand};
use std::path::PathBuf;

#[derive(Debug, Clone, Parser)]
#[command(
    name = "market-data-import",
    about = "Verified Binance spot candle importer"
)]
pub struct Cli {
    #[command(subcommand)]
    pub command: Command,
    #[arg(long, default_value = "binance", global = true)]
    pub venue: String,
    #[arg(long, default_value = "spot", global = true)]
    pub market: String,
    #[arg(long, default_value = "BTCUSDT", global = true)]
    pub symbol: String,
    #[arg(long, default_value = "1m", global = true)]
    pub interval: String,
    #[arg(long, default_value = "2023-08-03T00:00:00Z", global = true)]
    pub start: String,
    #[arg(long, default_value = "latest-closed", global = true)]
    pub end: String,
    #[arg(long, default_value = "DATABASE_URL", global = true)]
    pub postgres_url_env: String,
    #[arg(long, default_value = "./data/parquet", global = true)]
    pub parquet_root: PathBuf,
    #[arg(long, default_value = "./data/cache", global = true)]
    pub cache_root: PathBuf,
    #[arg(long, default_value_t = 4, global = true)]
    pub download_concurrency: usize,
}
#[derive(Debug, Clone, Subcommand)]
pub enum Command {
    Plan,
    Download,
    Import,
    Validate,
    Repair,
    Aggregate,
    ExportParquet,
    CompareBinance,
    Run,
    Status,
}
impl Cli {
    pub fn range(&self) -> anyhow::Result<(DateTime<Utc>, DateTime<Utc>)> {
        let start: DateTime<Utc> = self.start.parse()?;
        let now = Utc::now();
        let latest_closed = now.with_second(0).unwrap().with_nanosecond(0).unwrap();
        let end = if self.end == "latest-closed" {
            latest_closed
        } else {
            self.end.parse()?
        };
        anyhow::ensure!(start < end, "start must be before end");
        anyhow::ensure!(
            start.second() == 0
                && start.nanosecond() == 0
                && end.second() == 0
                && end.nanosecond() == 0,
            "start and end must be aligned to UTC minute boundaries"
        );
        anyhow::ensure!(
            end <= latest_closed,
            "end must not include an open or future candle"
        );
        Ok((start, end))
    }
    pub fn database_url(&self) -> anyhow::Result<String> {
        std::env::var(&self.postgres_url_env).map_err(|_| {
            anyhow::anyhow!("{} environment variable is not set", self.postgres_url_env)
        })
    }
    pub fn validate_scope(&self) -> anyhow::Result<()> {
        anyhow::ensure!(
            self.venue == "binance" && self.market == "spot" && self.interval == "1m",
            "this task supports only binance spot 1m"
        );
        anyhow::ensure!(
            !self.symbol.is_empty()
                && self.symbol.len() <= 20
                && self
                    .symbol
                    .chars()
                    .all(|c| c.is_ascii_uppercase() || c.is_ascii_digit()),
            "symbol must contain only uppercase ASCII letters and digits"
        );
        anyhow::ensure!(
            (1..=16).contains(&self.download_concurrency),
            "download concurrency must be between 1 and 16"
        );
        if matches!(self.command, Command::CompareBinance) {
            anyhow::ensure!(
                start_of_utc_day(self.range()?.0) && start_of_utc_day(self.range()?.1),
                "Binance aggregate comparison requires UTC day boundaries"
            );
        }
        Ok(())
    }
}

fn start_of_utc_day(value: DateTime<Utc>) -> bool {
    value.hour() == 0 && value.minute() == 0 && value.second() == 0 && value.nanosecond() == 0
}
