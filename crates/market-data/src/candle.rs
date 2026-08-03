use std::str::FromStr;

use chrono::{DateTime, TimeZone, Utc};
use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Candle {
    pub venue: String,
    pub market_type: String,
    pub symbol: String,
    pub interval: String,
    pub open_time: DateTime<Utc>,
    pub open: Decimal,
    pub high: Decimal,
    pub low: Decimal,
    pub close: Decimal,
    pub base_asset_volume: Decimal,
    pub close_time: DateTime<Utc>,
    pub quote_asset_volume: Decimal,
    pub trade_count: i64,
    pub taker_buy_base_volume: Decimal,
    pub taker_buy_quote_volume: Decimal,
    pub source: String,
    pub source_file: String,
}

#[derive(Debug, Error)]
pub enum ParseCandleError {
    #[error("CSV row has {0} fields; expected at least 11")]
    FieldCount(usize),
    #[error("invalid decimal in {field}: {value}")]
    Decimal { field: &'static str, value: String },
    #[error("invalid integer in {field}: {value}")]
    Integer { field: &'static str, value: String },
    #[error("timestamp unit is ambiguous for value {value} in expected range {start}..{end}")]
    AmbiguousTimestamp {
        value: i64,
        start: DateTime<Utc>,
        end: DateTime<Utc>,
    },
    #[error("timestamp is outside chrono range: {0}")]
    Timestamp(i64),
}

fn decimal(value: &str, field: &'static str) -> Result<Decimal, ParseCandleError> {
    Decimal::from_str(value).map_err(|_| ParseCandleError::Decimal {
        field,
        value: value.into(),
    })
}

fn integer(value: &str, field: &'static str) -> Result<i64, ParseCandleError> {
    value.parse().map_err(|_| ParseCandleError::Integer {
        field,
        value: value.into(),
    })
}

pub fn parse_timestamp(
    value: i64,
    expected_start: DateTime<Utc>,
    expected_end: DateTime<Utc>,
) -> Result<DateTime<Utc>, ParseCandleError> {
    let millis = Utc.timestamp_millis_opt(value).single();
    let micros = Utc.timestamp_micros(value).single();
    let margin = chrono::Duration::days(2);
    let in_range = |t: &DateTime<Utc>| *t >= expected_start - margin && *t < expected_end + margin;
    match (millis.filter(in_range), micros.filter(in_range)) {
        (Some(t), None) | (None, Some(t)) => Ok(t),
        _ => Err(ParseCandleError::AmbiguousTimestamp {
            value,
            start: expected_start,
            end: expected_end,
        }),
    }
}

impl Candle {
    pub fn from_binance_record(
        row: &csv::StringRecord,
        symbol: &str,
        expected_start: DateTime<Utc>,
        expected_end: DateTime<Utc>,
        source: &str,
        source_file: &str,
    ) -> Result<Self, ParseCandleError> {
        if row.len() != 12 {
            return Err(ParseCandleError::FieldCount(row.len()));
        }
        let open_raw = integer(&row[0], "open_time")?;
        let close_raw = integer(&row[6], "close_time")?;
        Ok(Self {
            venue: "binance".into(),
            market_type: "spot".into(),
            symbol: symbol.into(),
            interval: "1m".into(),
            open_time: parse_timestamp(open_raw, expected_start, expected_end)?,
            open: decimal(&row[1], "open")?,
            high: decimal(&row[2], "high")?,
            low: decimal(&row[3], "low")?,
            close: decimal(&row[4], "close")?,
            base_asset_volume: decimal(&row[5], "base_asset_volume")?,
            close_time: parse_timestamp(close_raw, expected_start, expected_end)?,
            quote_asset_volume: decimal(&row[7], "quote_asset_volume")?,
            trade_count: integer(&row[8], "trade_count")?,
            taker_buy_base_volume: decimal(&row[9], "taker_buy_base_volume")?,
            taker_buy_quote_volume: decimal(&row[10], "taker_buy_quote_volume")?,
            source: source.into(),
            source_file: source_file.into(),
        })
    }

    pub fn same_market_values(&self, other: &Self) -> bool {
        self.open == other.open
            && self.high == other.high
            && self.low == other.low
            && self.close == other.close
            && self.base_asset_volume == other.base_asset_volume
            && self.close_time == other.close_time
            && self.quote_asset_volume == other.quote_asset_volume
            && self.trade_count == other.trade_count
            && self.taker_buy_base_volume == other.taker_buy_base_volume
            && self.taker_buy_quote_volume == other.taker_buy_quote_volume
    }
}

pub fn read_csv<R: std::io::Read>(
    reader: R,
    symbol: &str,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
    source: &str,
    file: &str,
) -> anyhow::Result<Vec<Candle>> {
    let mut csv = csv::ReaderBuilder::new()
        .has_headers(false)
        .flexible(false)
        .from_reader(reader);
    let mut out = Vec::new();
    for (index, result) in csv.records().enumerate() {
        let row = result?;
        if index == 0
            && row
                .get(0)
                .is_some_and(|v| v.eq_ignore_ascii_case("open_time"))
        {
            continue;
        }
        out.push(Candle::from_binance_record(
            &row, symbol, start, end, source, file,
        )?);
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn range() -> (DateTime<Utc>, DateTime<Utc>) {
        (
            "2024-01-01T00:00:00Z".parse().unwrap(),
            "2024-02-01T00:00:00Z".parse().unwrap(),
        )
    }
    #[test]
    fn parses_milliseconds() {
        let (s, e) = range();
        assert_eq!(parse_timestamp(1704067200000, s, e).unwrap(), s);
    }
    #[test]
    fn parses_microseconds() {
        let s = "2025-01-01T00:00:00Z".parse().unwrap();
        let e = "2025-02-01T00:00:00Z".parse().unwrap();
        assert_eq!(parse_timestamp(1735689600000000, s, e).unwrap(), s);
    }
    #[test]
    fn rejects_ambiguous_unit() {
        let (s, e) = range();
        assert!(matches!(
            parse_timestamp(42, s, e),
            Err(ParseCandleError::AmbiguousTimestamp { .. })
        ));
    }
    #[test]
    fn handles_header_and_no_header() {
        let (s, e) = range();
        let row = "1704067200000,1,2,0.5,1.5,0,1704067259999,0,0,0,0,0\n";
        assert_eq!(
            read_csv(row.as_bytes(), "BTCUSDT", s, e, "monthly", "x")
                .unwrap()
                .len(),
            1
        );
        let with_header = format!(
            "open_time,open,high,low,close,volume,close_time,quote,trades,tbb,tbq,ignore\n{row}"
        );
        assert_eq!(
            read_csv(with_header.as_bytes(), "BTCUSDT", s, e, "monthly", "x")
                .unwrap()
                .len(),
            1
        );
    }
    #[test]
    fn rejects_bad_csv() {
        let (s, e) = range();
        assert!(read_csv("x,1\n".as_bytes(), "BTCUSDT", s, e, "monthly", "x").is_err());
    }
}
