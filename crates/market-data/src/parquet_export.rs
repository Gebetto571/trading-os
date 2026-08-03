use crate::{candle::Candle, SCHEMA_VERSION};
use anyhow::Context;
use arrow_array::{
    ArrayRef, Decimal128Array, Int64Array, RecordBatch, StringArray, TimestampMicrosecondArray,
};
use arrow_schema::{DataType, Field, Schema, TimeUnit};
use parquet::{
    arrow::ArrowWriter,
    basic::{Compression, ZstdLevel},
    file::properties::WriterProperties,
};
use std::{
    fs::File,
    path::{Path, PathBuf},
    sync::Arc,
};

fn decimal_array(
    candles: &[Candle],
    f: impl Fn(&Candle) -> rust_decimal::Decimal,
) -> anyhow::Result<ArrayRef> {
    let values = candles
        .iter()
        .map(|c| -> anyhow::Result<i128> {
            let mut d = f(c);
            d.rescale(18);
            anyhow::ensure!(
                d.scale() == 18,
                "decimal value cannot be represented exactly at scale 18"
            );
            Ok(d.mantissa())
        })
        .collect::<anyhow::Result<Vec<_>>>()?;
    Ok(Arc::new(
        Decimal128Array::from(values).with_precision_and_scale(38, 18)?,
    ))
}
pub fn export(candles: &[Candle], target: &Path) -> anyhow::Result<u64> {
    std::fs::create_dir_all(target.parent().context("Parquet path has no parent")?)?;
    let part = part_path(target);
    let _ = std::fs::remove_file(&part);
    let fields = vec![
        Field::new("schema_version", DataType::Utf8, false),
        Field::new("venue", DataType::Utf8, false),
        Field::new("market_type", DataType::Utf8, false),
        Field::new("symbol", DataType::Utf8, false),
        Field::new("interval", DataType::Utf8, false),
        Field::new(
            "open_time",
            DataType::Timestamp(TimeUnit::Microsecond, Some("UTC".into())),
            false,
        ),
        Field::new("open", DataType::Decimal128(38, 18), false),
        Field::new("high", DataType::Decimal128(38, 18), false),
        Field::new("low", DataType::Decimal128(38, 18), false),
        Field::new("close", DataType::Decimal128(38, 18), false),
        Field::new("base_asset_volume", DataType::Decimal128(38, 18), false),
        Field::new(
            "close_time",
            DataType::Timestamp(TimeUnit::Microsecond, Some("UTC".into())),
            false,
        ),
        Field::new("quote_asset_volume", DataType::Decimal128(38, 18), false),
        Field::new("trade_count", DataType::Int64, false),
        Field::new("taker_buy_base_volume", DataType::Decimal128(38, 18), false),
        Field::new(
            "taker_buy_quote_volume",
            DataType::Decimal128(38, 18),
            false,
        ),
        Field::new("source", DataType::Utf8, false),
        Field::new("source_file", DataType::Utf8, false),
    ];
    let schema = Arc::new(Schema::new(fields));
    let strings = |f: fn(&Candle) -> &str| {
        Arc::new(StringArray::from_iter_values(candles.iter().map(f))) as ArrayRef
    };
    let ts = |f: fn(&Candle) -> i64| {
        Arc::new(
            TimestampMicrosecondArray::from(candles.iter().map(f).collect::<Vec<_>>())
                .with_timezone("UTC"),
        ) as ArrayRef
    };
    let cols = vec![
        Arc::new(StringArray::from(vec![SCHEMA_VERSION; candles.len()])) as ArrayRef,
        strings(|c| &c.venue),
        strings(|c| &c.market_type),
        strings(|c| &c.symbol),
        strings(|c| &c.interval),
        ts(|c| c.open_time.timestamp_micros()),
        decimal_array(candles, |c| c.open)?,
        decimal_array(candles, |c| c.high)?,
        decimal_array(candles, |c| c.low)?,
        decimal_array(candles, |c| c.close)?,
        decimal_array(candles, |c| c.base_asset_volume)?,
        ts(|c| c.close_time.timestamp_micros()),
        decimal_array(candles, |c| c.quote_asset_volume)?,
        Arc::new(Int64Array::from_iter_values(
            candles.iter().map(|c| c.trade_count),
        )),
        decimal_array(candles, |c| c.taker_buy_base_volume)?,
        decimal_array(candles, |c| c.taker_buy_quote_volume)?,
        strings(|c| &c.source),
        strings(|c| &c.source_file),
    ];
    let batch = RecordBatch::try_new(schema.clone(), cols)?;
    let props = WriterProperties::builder()
        .set_compression(Compression::ZSTD(ZstdLevel::default()))
        .build();
    let file = File::create(&part)?;
    let mut writer = ArrowWriter::try_new(file, schema, Some(props))?;
    writer.write(&batch)?;
    writer.close()?;
    std::fs::rename(&part, target)?;
    Ok(candles.len() as u64)
}
fn part_path(path: &Path) -> PathBuf {
    let mut p = path.as_os_str().to_owned();
    p.push(".part");
    PathBuf::from(p)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::validation::tests::candle;
    #[test]
    fn export_is_idempotent() {
        let d = tempfile::tempdir().unwrap();
        let p = d.path().join("x.parquet");
        let cs = vec![candle("2024-01-01T00:00:00Z")];
        assert_eq!(export(&cs, &p).unwrap(), 1);
        let a = std::fs::read(&p).unwrap();
        assert_eq!(export(&cs, &p).unwrap(), 1);
        assert_eq!(a, std::fs::read(&p).unwrap());
    }

    #[test]
    fn rejects_decimal_that_cannot_reach_scale_18() {
        let mut c = candle("2024-01-01T00:00:00Z");
        c.open = rust_decimal::Decimal::MAX;
        assert!(decimal_array(&[c], |row| row.open).is_err());
    }
}
