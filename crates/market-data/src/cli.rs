use chrono::{DateTime, Timelike, Utc};
use clap::{Parser, Subcommand, ValueEnum};
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
    #[arg(
        long,
        env = "TRADING_OS_MARKET_DATA_HEALTH_DIR",
        default_value = "./data/health/btcusdt",
        global = true
    )]
    pub health_root: PathBuf,
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
    VerifyParquet,
    QueryCandles {
        #[arg(long, default_value_t = 500)]
        limit: i64,
        #[arg(long)]
        cursor: Option<String>,
        #[arg(long, value_enum, default_value_t = QueryFormat::Json)]
        format: QueryFormat,
    },
    Sync,
    CompareBinance,
    Run,
    Status,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, ValueEnum)]
pub enum QueryFormat {
    Json,
    Csv,
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
        let query_limit = match &self.command {
            Command::QueryCandles { limit, .. } => Some(*limit),
            _ => None,
        };
        anyhow::ensure!(
            self.venue == "binance" && self.market == "spot",
            "this task supports only binance spot"
        );
        if let Some(limit) = query_limit {
            anyhow::ensure!(
                matches!(self.interval.as_str(), "1m" | "15m" | "1h" | "4h" | "1d"),
                "query-candles supports 1m, 15m, 1h, 4h and 1d intervals"
            );
            anyhow::ensure!(
                (1..=4096).contains(&limit),
                "query limit must be between 1 and 4096"
            );
        } else {
            anyhow::ensure!(
                self.interval == "1m",
                "this task supports only binance spot 1m"
            );
        }
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn query_accepts_all_materialized_intervals() {
        for interval in ["1m", "15m", "1h", "4h", "1d"] {
            let cli = Cli::parse_from([
                "market-data-import",
                "query-candles",
                "--interval",
                interval,
                "--limit",
                "25",
            ]);
            cli.validate_scope().unwrap();
        }
    }

    #[test]
    fn non_query_commands_remain_scoped_to_one_minute() {
        let cli = Cli::parse_from(["market-data-import", "validate", "--interval", "1h"]);
        assert!(cli.validate_scope().is_err());
    }

    #[test]
    fn query_rejects_unbounded_page_sizes() {
        for limit in ["0", "4097"] {
            let cli = Cli::parse_from(["market-data-import", "query-candles", "--limit", limit]);
            assert!(cli.validate_scope().is_err());
        }
    }
}
