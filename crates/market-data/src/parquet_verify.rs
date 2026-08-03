use crate::{candle::Candle, db, parquet_export, SCHEMA_VERSION};
use anyhow::Context;
use arrow_array::{
    Array, Decimal128Array, Int64Array, RecordBatch, StringArray, TimestampMicrosecondArray,
};
use chrono::{DateTime, Datelike, NaiveDate, TimeZone, Utc};
use parquet::arrow::arrow_reader::ParquetRecordBatchReaderBuilder;
use serde::Serialize;
use sqlx::PgPool;
use std::{
    collections::HashSet,
    fs::File,
    path::{Path, PathBuf},
    time::Instant,
};

const BATCH_SIZE: usize = 4_096;
const INTERVALS: [&str; 5] = ["1m", "15m", "1h", "4h", "1d"];

#[derive(Debug, Serialize)]
pub struct VerificationReport {
    pub passed: bool,
    pub schema_version: &'static str,
    pub requested_start: DateTime<Utc>,
    pub requested_end: DateTime<Utc>,
    pub partitions_expected: u64,
    pub partitions_checked: u64,
    pub rows_compared: u64,
    pub mismatch_count: u64,
    pub issues: Vec<String>,
    pub elapsed_ms: u128,
}

pub async fn verify(
    pool: &PgPool,
    root: &Path,
    symbol: &str,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
) -> VerificationReport {
    let started = Instant::now();
    let months = touched_months(start, end);
    let mut report = VerificationReport {
        passed: true,
        schema_version: SCHEMA_VERSION,
        requested_start: start,
        requested_end: end,
        partitions_expected: (months.len() * INTERVALS.len()) as u64,
        partitions_checked: 0,
        rows_compared: 0,
        mismatch_count: 0,
        issues: Vec::new(),
        elapsed_ms: 0,
    };
    if let Err(error) = inventory_scope(root, symbol, &months) {
        report.passed = false;
        report.mismatch_count = 1;
        report.issues.push(format!("Parquet inventory: {error:#}"));
        report.elapsed_ms = started.elapsed().as_millis();
        return report;
    }
    for (month_start, month_end) in months {
        for interval in INTERVALS {
            let path = partition_path(root, symbol, interval, month_start);
            report.partitions_checked += 1;
            match verify_partition(pool, symbol, interval, month_start, month_end, &path).await {
                Ok(rows) => {
                    report.rows_compared += rows;
                }
                Err(error) => {
                    report.mismatch_count += 1;
                    if report.issues.len() < 20 {
                        report.issues.push(format!("{}: {error:#}", path.display()));
                    }
                }
            }
        }
    }
    report.passed = report.mismatch_count == 0;
    report.elapsed_ms = started.elapsed().as_millis();
    report
}

fn inventory_scope(
    root: &Path,
    symbol: &str,
    months: &[(DateTime<Utc>, DateTime<Utc>)],
) -> anyhow::Result<()> {
    let selected = months
        .iter()
        .map(|(month, _)| (month.year(), month.month()))
        .collect::<HashSet<_>>();
    let symbol_root = root
        .join("venue=binance/market_type=spot")
        .join(format!("symbol={symbol}"));
    ensure_directory_chain(root, &symbol_root)?;
    let allowed_intervals = INTERVALS
        .iter()
        .map(|interval| format!("interval={interval}"))
        .collect::<HashSet<_>>();
    for entry in std::fs::read_dir(&symbol_root).context("inventory symbol directory")? {
        let entry = entry?;
        let name = entry.file_name().to_string_lossy().into_owned();
        let metadata = std::fs::symlink_metadata(entry.path())?;
        anyhow::ensure!(
            !metadata.file_type().is_symlink(),
            "symlinked scope entry {}",
            entry.path().display()
        );
        anyhow::ensure!(
            metadata.is_dir(),
            "unexpected file in symbol scope: {}",
            entry.path().display()
        );
        anyhow::ensure!(
            allowed_intervals.contains(&name),
            "unexpected interval directory {name}"
        );
    }
    for interval in INTERVALS {
        let interval_root = symbol_root.join(format!("interval={interval}"));
        ensure_plain_directory(&interval_root)?;
        for entry in std::fs::read_dir(&interval_root)? {
            let entry = entry?;
            let metadata = std::fs::symlink_metadata(entry.path())?;
            anyhow::ensure!(
                !metadata.file_type().is_symlink(),
                "symlinked scope entry {}",
                entry.path().display()
            );
            anyhow::ensure!(
                metadata.is_dir(),
                "unexpected file in interval scope: {}",
                entry.path().display()
            );
            let year = parse_partition_number(&entry.file_name(), "year=", 4)? as i32;
            if selected
                .iter()
                .any(|(selected_year, _)| *selected_year == year)
            {
                inventory_year(&entry.path(), year, &selected)?;
            }
        }
        for year in selected
            .iter()
            .map(|(year, _)| *year)
            .collect::<HashSet<_>>()
        {
            ensure_plain_directory(&interval_root.join(format!("year={year:04}")))?;
        }
    }
    Ok(())
}

fn inventory_year(path: &Path, year: i32, selected: &HashSet<(i32, u32)>) -> anyhow::Result<()> {
    for entry in std::fs::read_dir(path)? {
        let entry = entry?;
        let metadata = std::fs::symlink_metadata(entry.path())?;
        anyhow::ensure!(
            !metadata.file_type().is_symlink(),
            "symlinked scope entry {}",
            entry.path().display()
        );
        anyhow::ensure!(
            metadata.is_dir(),
            "unexpected file in year scope: {}",
            entry.path().display()
        );
        let month = parse_partition_number(&entry.file_name(), "month=", 2)?;
        anyhow::ensure!((1..=12).contains(&month), "invalid month partition {month}");
        if selected.contains(&(year, month)) {
            inventory_partition(&entry.path().join("candles.parquet"))?;
        }
    }
    for (_, month) in selected
        .iter()
        .filter(|(selected_year, _)| *selected_year == year)
    {
        inventory_partition(&path.join(format!("month={month:02}/candles.parquet")))?;
    }
    Ok(())
}

fn parse_partition_number(
    name: &std::ffi::OsStr,
    prefix: &str,
    digits: usize,
) -> anyhow::Result<u32> {
    let name = name.to_str().context("partition name is not UTF-8")?;
    let value = name
        .strip_prefix(prefix)
        .with_context(|| format!("unexpected partition directory {name}"))?;
    anyhow::ensure!(value.len() == digits, "invalid partition directory {name}");
    value
        .parse()
        .with_context(|| format!("invalid partition directory {name}"))
}

fn ensure_directory_chain(root: &Path, target: &Path) -> anyhow::Result<()> {
    let relative = target
        .strip_prefix(root)
        .context("scope is outside Parquet root")?;
    let mut cursor = root.to_path_buf();
    ensure_plain_directory(&cursor)?;
    for component in relative.components() {
        cursor.push(component);
        ensure_plain_directory(&cursor)?;
    }
    Ok(())
}

fn ensure_plain_directory(path: &Path) -> anyhow::Result<()> {
    let metadata = std::fs::symlink_metadata(path)
        .with_context(|| format!("missing partition directory {}", path.display()))?;
    anyhow::ensure!(
        !metadata.file_type().is_symlink(),
        "symlinked partition directory {}",
        path.display()
    );
    anyhow::ensure!(
        metadata.is_dir(),
        "partition path is not a directory: {}",
        path.display()
    );
    Ok(())
}

fn inventory_partition(target: &Path) -> anyhow::Result<()> {
    let parent = target
        .parent()
        .context("partition has no parent directory")?;
    ensure_plain_directory(parent)?;
    let entries = std::fs::read_dir(parent).context("inventory partition directory")?;
    let mut found = 0_u8;
    for entry in entries {
        let entry = entry?;
        let path = entry.path();
        let metadata = std::fs::symlink_metadata(&path)?;
        anyhow::ensure!(
            !metadata.file_type().is_symlink(),
            "symlinked partition entry {}",
            path.display()
        );
        anyhow::ensure!(
            path == target,
            "unexpected partition entry {}",
            path.display()
        );
        anyhow::ensure!(metadata.is_file(), "partition entry is not a regular file");
        anyhow::ensure!(metadata.len() > 0, "Parquet partition is empty");
        found += 1;
    }
    anyhow::ensure!(
        found == 1,
        "expected exactly one candles.parquet entry, found {found}"
    );
    Ok(())
}

async fn verify_partition(
    pool: &PgPool,
    symbol: &str,
    interval: &str,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
    path: &Path,
) -> anyhow::Result<u64> {
    let file = open_partition(path)?;
    let builder = ParquetRecordBatchReaderBuilder::try_new(file).context("read Parquet footer")?;
    anyhow::ensure!(
        builder.schema().as_ref() == parquet_export::schema().as_ref(),
        "Parquet schema differs from schema version {SCHEMA_VERSION}"
    );
    let reader = builder.with_batch_size(BATCH_SIZE).build()?;
    let mut after_db = None;
    let mut previous_parquet = None;
    let mut rows = 0_u64;
    for batch in reader {
        let batch = batch.context("read Parquet record batch")?;
        if batch.num_rows() == 0 {
            continue;
        }
        for index in 0..batch.num_rows() {
            let parquet_open = timestamp(&batch, 5)?.value(index);
            if let Some(previous) = previous_parquet {
                anyhow::ensure!(
                    parquet_open > previous,
                    "Parquet rows are duplicate or out of order at {parquet_open}"
                );
            }
            previous_parquet = Some(parquet_open);
        }
        let db_rows = db::load_candles_page(
            pool,
            symbol,
            interval,
            start,
            end,
            after_db,
            batch.num_rows() as i64,
        )
        .await?;
        anyhow::ensure!(
            db_rows.len() == batch.num_rows(),
            "row count differs near row {rows}: parquet={}, PostgreSQL={}",
            batch.num_rows(),
            db_rows.len()
        );
        for (index, expected) in db_rows.iter().enumerate() {
            compare_row(&batch, index, expected)
                .with_context(|| format!("cell mismatch at {}", expected.open_time))?;
        }
        after_db = db_rows.last().map(|row| row.open_time);
        rows += batch.num_rows() as u64;
    }
    let extra = db::load_candles_page(pool, symbol, interval, start, end, after_db, 1).await?;
    anyhow::ensure!(
        extra.is_empty(),
        "PostgreSQL contains rows missing from Parquet"
    );
    Ok(rows)
}

fn open_partition(path: &Path) -> anyhow::Result<File> {
    anyhow::ensure!(!part_path(path).exists(), "unpublished .part file exists");
    let metadata = std::fs::symlink_metadata(path).context("missing Parquet partition")?;
    anyhow::ensure!(
        !metadata.file_type().is_symlink(),
        "Parquet partition is a symlink"
    );
    anyhow::ensure!(
        metadata.is_file(),
        "Parquet partition is not a regular file"
    );
    anyhow::ensure!(metadata.len() > 0, "Parquet partition is empty");
    File::open(path).context("open Parquet partition")
}

fn compare_row(batch: &RecordBatch, row: usize, expected: &Candle) -> anyhow::Result<()> {
    let check_string = |column: usize, value: &str| -> anyhow::Result<()> {
        anyhow::ensure!(
            string(batch, column)?.value(row) == value,
            "column {} differs",
            batch.schema().field(column).name()
        );
        Ok(())
    };
    check_string(0, SCHEMA_VERSION)?;
    check_string(1, &expected.venue)?;
    check_string(2, &expected.market_type)?;
    check_string(3, &expected.symbol)?;
    check_string(4, &expected.interval)?;
    anyhow::ensure!(
        timestamp(batch, 5)?.value(row) == expected.open_time.timestamp_micros(),
        "open_time differs"
    );
    check_decimal(batch, 6, row, expected.open)?;
    check_decimal(batch, 7, row, expected.high)?;
    check_decimal(batch, 8, row, expected.low)?;
    check_decimal(batch, 9, row, expected.close)?;
    check_decimal(batch, 10, row, expected.base_asset_volume)?;
    anyhow::ensure!(
        timestamp(batch, 11)?.value(row) == expected.close_time.timestamp_micros(),
        "close_time differs"
    );
    check_decimal(batch, 12, row, expected.quote_asset_volume)?;
    anyhow::ensure!(
        int64(batch, 13)?.value(row) == expected.trade_count,
        "trade_count differs"
    );
    check_decimal(batch, 14, row, expected.taker_buy_base_volume)?;
    check_decimal(batch, 15, row, expected.taker_buy_quote_volume)?;
    check_string(16, &expected.source)?;
    check_string(17, &expected.source_file)?;
    Ok(())
}

fn check_decimal(
    batch: &RecordBatch,
    column: usize,
    row: usize,
    mut expected: rust_decimal::Decimal,
) -> anyhow::Result<()> {
    anyhow::ensure!(
        expected.scale() <= 18,
        "PostgreSQL decimal has more than 18 fractional digits"
    );
    expected.rescale(18);
    anyhow::ensure!(
        expected.scale() == 18,
        "PostgreSQL decimal cannot be represented at scale 18"
    );
    anyhow::ensure!(
        decimal(batch, column)?.value(row) == expected.mantissa(),
        "column {} differs",
        batch.schema().field(column).name()
    );
    Ok(())
}

fn string(batch: &RecordBatch, column: usize) -> anyhow::Result<&StringArray> {
    typed(batch, column)
}
fn timestamp(batch: &RecordBatch, column: usize) -> anyhow::Result<&TimestampMicrosecondArray> {
    typed(batch, column)
}
fn decimal(batch: &RecordBatch, column: usize) -> anyhow::Result<&Decimal128Array> {
    typed(batch, column)
}
fn int64(batch: &RecordBatch, column: usize) -> anyhow::Result<&Int64Array> {
    typed(batch, column)
}
fn typed<T: 'static>(batch: &RecordBatch, column: usize) -> anyhow::Result<&T> {
    batch
        .column(column)
        .as_any()
        .downcast_ref::<T>()
        .with_context(|| format!("unexpected Arrow type for column {column}"))
}

fn partition_path(root: &Path, symbol: &str, interval: &str, month: DateTime<Utc>) -> PathBuf {
    root.join("venue=binance/market_type=spot")
        .join(format!("symbol={symbol}"))
        .join(format!(
            "interval={interval}/year={:04}/month={:02}/candles.parquet",
            month.year(),
            month.month()
        ))
}

fn part_path(path: &Path) -> PathBuf {
    let mut value = path.as_os_str().to_owned();
    value.push(".part");
    PathBuf::from(value)
}

fn month_floor(time: DateTime<Utc>) -> DateTime<Utc> {
    Utc.from_utc_datetime(
        &NaiveDate::from_ymd_opt(time.year(), time.month(), 1)
            .expect("valid month")
            .and_hms_opt(0, 0, 0)
            .expect("valid midnight"),
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::validation::tests::candle;
    use arrow_array::{RecordBatch as TestRecordBatch, StringArray as TestStringArray};
    use arrow_schema::{DataType, Field, Schema};
    use parquet::arrow::ArrowWriter;
    use rust_decimal::Decimal;
    use std::sync::Arc;

    #[test]
    fn selected_range_expands_to_complete_month_partitions() {
        let start = "2024-01-31T23:59:00Z".parse().unwrap();
        let end = "2024-02-01T00:01:00Z".parse().unwrap();
        let months = touched_months(start, end);
        assert_eq!(months.len(), 2);
        assert_eq!(
            months[0].0,
            "2024-01-01T00:00:00Z".parse::<DateTime<Utc>>().unwrap()
        );
        assert_eq!(
            months[1].0,
            "2024-02-01T00:00:00Z".parse::<DateTime<Utc>>().unwrap()
        );
    }

    #[test]
    fn partition_contract_is_stable() {
        let root = Path::new("data/parquet");
        let month = "2024-02-01T00:00:00Z".parse().unwrap();
        assert_eq!(
            partition_path(root, "BTCUSDT", "1h", month),
            Path::new("data/parquet/venue=binance/market_type=spot/symbol=BTCUSDT/interval=1h/year=2024/month=02/candles.parquet")
        );
    }

    #[test]
    fn rejects_zero_byte_and_unpublished_partitions() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("candles.parquet");
        std::fs::write(&path, []).unwrap();
        assert!(open_partition(&path)
            .unwrap_err()
            .to_string()
            .contains("empty"));
        std::fs::write(&path, [1]).unwrap();
        std::fs::write(part_path(&path), [1]).unwrap();
        assert!(open_partition(&path)
            .unwrap_err()
            .to_string()
            .contains(".part"));
    }

    #[cfg(unix)]
    #[test]
    fn rejects_symlinked_partition() {
        use std::os::unix::fs::symlink;
        let temp = tempfile::tempdir().unwrap();
        let target = temp.path().join("target.parquet");
        let link = temp.path().join("candles.parquet");
        std::fs::write(&target, [1]).unwrap();
        symlink(target, &link).unwrap();
        assert!(open_partition(&link)
            .unwrap_err()
            .to_string()
            .contains("symlink"));
    }

    #[sqlx::test(migrations = "./migrations")]
    async fn verifies_every_exported_cell_and_rejects_differences(pool: PgPool) {
        let root = tempfile::tempdir().unwrap();
        let start = "2024-01-01T00:00:00Z".parse().unwrap();
        let end = "2024-01-02T00:00:00Z".parse().unwrap();
        for interval in INTERVALS {
            let mut row = candle("2024-01-01T00:00:00Z");
            row.interval = interval.into();
            db::insert_candles(&pool, std::slice::from_ref(&row))
                .await
                .unwrap();
            parquet_export::export(
                std::slice::from_ref(&row),
                &partition_path(root.path(), "BTCUSDT", interval, start),
            )
            .unwrap();
        }

        let report = verify(&pool, root.path(), "BTCUSDT", start, end).await;
        assert!(report.passed, "{:?}", report.issues);
        assert_eq!(report.partitions_expected, 5);
        assert_eq!(report.partitions_checked, 5);
        assert_eq!(report.rows_compared, 5);

        let hourly_path = partition_path(root.path(), "BTCUSDT", "1h", start);
        std::fs::remove_file(&hourly_path).unwrap();
        let report = verify(&pool, root.path(), "BTCUSDT", start, end).await;
        assert!(!report.passed);
        assert!(report
            .issues
            .iter()
            .any(|issue| issue.contains("exactly one")));

        let mut hourly = candle("2024-01-01T00:00:00Z");
        hourly.interval = "1h".into();
        parquet_export::export(std::slice::from_ref(&hourly), &hourly_path).unwrap();
        let extra = hourly_path.parent().unwrap().join("unexpected.parquet");
        std::fs::write(&extra, [1]).unwrap();
        let report = verify(&pool, root.path(), "BTCUSDT", start, end).await;
        assert!(!report.passed);
        assert!(report
            .issues
            .iter()
            .any(|issue| issue.contains("unexpected partition entry")));
        std::fs::remove_file(extra).unwrap();

        write_wrong_schema(&hourly_path);
        let report = verify(&pool, root.path(), "BTCUSDT", start, end).await;
        assert!(!report.passed);
        assert!(report
            .issues
            .iter()
            .any(|issue| issue.contains("schema differs")));
        parquet_export::export(std::slice::from_ref(&hourly), &hourly_path).unwrap();

        let mut second = candle("2024-01-01T01:00:00Z");
        second.interval = "1h".into();
        db::insert_candles(&pool, std::slice::from_ref(&second))
            .await
            .unwrap();
        let report = verify(&pool, root.path(), "BTCUSDT", start, end).await;
        assert!(!report.passed, "DB-only row must fail verification");
        parquet_export::export(&[hourly.clone(), second.clone()], &hourly_path).unwrap();

        let mut parquet_only = candle("2024-01-01T02:00:00Z");
        parquet_only.interval = "1h".into();
        parquet_export::export(
            &[hourly.clone(), second.clone(), parquet_only],
            &hourly_path,
        )
        .unwrap();
        let report = verify(&pool, root.path(), "BTCUSDT", start, end).await;
        assert!(!report.passed, "Parquet-only row must fail verification");

        parquet_export::export(&[second.clone(), hourly.clone()], &hourly_path).unwrap();
        let report = verify(&pool, root.path(), "BTCUSDT", start, end).await;
        assert!(!report.passed);
        assert!(report
            .issues
            .iter()
            .any(|issue| issue.contains("out of order")));

        parquet_export::export(
            &[hourly.clone(), hourly.clone(), second.clone()],
            &hourly_path,
        )
        .unwrap();
        let report = verify(&pool, root.path(), "BTCUSDT", start, end).await;
        assert!(!report.passed);
        assert!(report
            .issues
            .iter()
            .any(|issue| issue.contains("duplicate")));

        let mut changed = candle("2024-01-01T00:00:00Z");
        changed.interval = "1h".into();
        changed.close = Decimal::new(15, 1);
        parquet_export::export(
            &[changed, second],
            &partition_path(root.path(), "BTCUSDT", "1h", start),
        )
        .unwrap();
        let report = verify(&pool, root.path(), "BTCUSDT", start, end).await;
        assert!(!report.passed);
        assert!(report.issues.iter().any(|error| error.contains("close")));
    }

    fn write_wrong_schema(path: &Path) {
        let schema = Arc::new(Schema::new(vec![Field::new(
            "wrong",
            DataType::Utf8,
            false,
        )]));
        let batch = TestRecordBatch::try_new(
            schema.clone(),
            vec![Arc::new(TestStringArray::from(vec!["wrong"]))],
        )
        .unwrap();
        let file = File::create(path).unwrap();
        let mut writer = ArrowWriter::try_new(file, schema, None).unwrap();
        writer.write(&batch).unwrap();
        writer.close().unwrap();
    }
}
