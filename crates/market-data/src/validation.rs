use crate::candle::Candle;
use chrono::{DateTime, Duration, Timelike, Utc};
use std::collections::BTreeMap;

#[derive(Debug, Clone, Default, serde::Serialize)]
pub struct ValidationReport {
    pub rows: usize,
    pub first_open_time: Option<DateTime<Utc>>,
    pub last_open_time: Option<DateTime<Utc>>,
    pub gaps: Vec<(DateTime<Utc>, DateTime<Utc>)>,
    pub duplicates: Vec<DateTime<Utc>>,
    pub errors: Vec<String>,
}
impl ValidationReport {
    pub fn is_valid(&self) -> bool {
        self.gaps.is_empty() && self.duplicates.is_empty() && self.errors.is_empty()
    }
}

pub fn validate(
    candles: &[Candle],
    requested_start: DateTime<Utc>,
    requested_end: DateTime<Utc>,
) -> ValidationReport {
    let mut report = ValidationReport {
        rows: candles.len(),
        ..Default::default()
    };
    let mut ordered = BTreeMap::new();
    let mut input_previous = None;
    for c in candles {
        if input_previous.is_some_and(|p| c.open_time <= p) {
            report.errors.push(format!(
                "input is not strictly chronological at {}",
                c.open_time
            ));
        }
        input_previous = Some(c.open_time);
        if ordered.insert(c.open_time, c).is_some() {
            report.duplicates.push(c.open_time);
        }
        if c.open_time < requested_start || c.open_time >= requested_end {
            report
                .errors
                .push(format!("{} outside requested range", c.open_time));
        }
        if c.open_time.second() != 0 || c.open_time.nanosecond() != 0 {
            report
                .errors
                .push(format!("{} is not minute-aligned", c.open_time));
        }
        if c.high < c.open
            || c.high < c.close
            || c.low > c.open
            || c.low > c.close
            || c.high < c.low
        {
            report
                .errors
                .push(format!("OHLC invariant failed at {}", c.open_time));
        }
        if c.open <= rust_decimal::Decimal::ZERO
            || c.high <= rust_decimal::Decimal::ZERO
            || c.low <= rust_decimal::Decimal::ZERO
            || c.close <= rust_decimal::Decimal::ZERO
        {
            report
                .errors
                .push(format!("non-positive price at {}", c.open_time));
        }
        if c.base_asset_volume < rust_decimal::Decimal::ZERO
            || c.quote_asset_volume < rust_decimal::Decimal::ZERO
            || c.taker_buy_base_volume < rust_decimal::Decimal::ZERO
            || c.taker_buy_quote_volume < rust_decimal::Decimal::ZERO
            || c.trade_count < 0
        {
            report
                .errors
                .push(format!("negative volume/count at {}", c.open_time));
        }
        let duration = c.close_time.timestamp_micros() - c.open_time.timestamp_micros();
        if !(59_999_000..=59_999_999).contains(&duration) {
            report
                .errors
                .push(format!("invalid close time at {}", c.open_time));
        }
    }
    report.first_open_time = ordered.keys().next().copied();
    report.last_open_time = ordered.keys().next_back().copied();
    let mut previous = None;
    if let Some(first) = report.first_open_time {
        if first > requested_start {
            report.gaps.push((requested_start, first));
        }
    }
    for time in ordered.keys().copied() {
        if let Some(p) = previous {
            if time != p + Duration::minutes(1) {
                report.gaps.push((p + Duration::minutes(1), time));
            }
        }
        previous = Some(time);
    }
    if let Some(last) = report.last_open_time {
        let next = last + Duration::minutes(1);
        if next < requested_end {
            report.gaps.push((next, requested_end));
        }
    }
    if candles.is_empty() && requested_start < requested_end {
        report.gaps.push((requested_start, requested_end));
    }
    report
}

#[cfg(test)]
pub(crate) mod tests {
    use super::*;
    use rust_decimal::Decimal;
    pub(crate) fn candle(time: &str) -> Candle {
        let t = time.parse().unwrap();
        Candle {
            venue: "binance".into(),
            market_type: "spot".into(),
            symbol: "BTCUSDT".into(),
            interval: "1m".into(),
            open_time: t,
            open: Decimal::ONE,
            high: Decimal::TWO,
            low: Decimal::ONE,
            close: Decimal::ONE,
            base_asset_volume: Decimal::ZERO,
            close_time: t + Duration::milliseconds(59999),
            quote_asset_volume: Decimal::ZERO,
            trade_count: 0,
            taker_buy_base_volume: Decimal::ZERO,
            taker_buy_quote_volume: Decimal::ZERO,
            source: "test".into(),
            source_file: "test".into(),
        }
    }
    #[test]
    fn finds_gap_and_duplicate() {
        let a = candle("2024-01-01T00:00:00Z");
        let b = candle("2024-01-01T00:02:00Z");
        let r = validate(
            &[a.clone(), a.clone(), b],
            a.open_time,
            "2024-01-01T00:03:00Z".parse().unwrap(),
        );
        assert_eq!(r.gaps.len(), 1);
        assert_eq!(r.duplicates.len(), 1);
    }
    #[test]
    fn finds_ohlc_error() {
        let mut a = candle("2024-01-01T00:00:00Z");
        a.high = Decimal::ZERO;
        let r = validate(
            &[a.clone()],
            a.open_time,
            a.open_time + Duration::minutes(1),
        );
        assert!(!r.errors.is_empty());
    }
}
