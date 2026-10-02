use crate::{candle::Candle, db};
use chrono::{DateTime, Timelike, Utc};
use rust_decimal::Decimal;
use serde::Serialize;
use sqlx::PgPool;

pub const QUERY_SCHEMA_VERSION: u32 = 1;

#[derive(Debug, Serialize)]
pub struct QueryPage {
    pub schema_version: u32,
    pub venue: &'static str,
    pub market_type: &'static str,
    pub symbol: String,
    pub interval: String,
    pub range_start: DateTime<Utc>,
    pub range_end: DateTime<Utc>,
    pub cursor: Option<DateTime<Utc>>,
    pub limit: i64,
    pub returned: usize,
    pub has_more: bool,
    pub next_cursor: Option<DateTime<Utc>>,
    pub candles: Vec<QueryCandle>,
}

#[derive(Debug, Serialize)]
pub struct QueryCandle {
    pub open_time: DateTime<Utc>,
    #[serde(with = "rust_decimal::serde::str")]
    pub open: Decimal,
    #[serde(with = "rust_decimal::serde::str")]
    pub high: Decimal,
    #[serde(with = "rust_decimal::serde::str")]
    pub low: Decimal,
    #[serde(with = "rust_decimal::serde::str")]
    pub close: Decimal,
    #[serde(with = "rust_decimal::serde::str")]
    pub base_asset_volume: Decimal,
    pub close_time: DateTime<Utc>,
    #[serde(with = "rust_decimal::serde::str")]
    pub quote_asset_volume: Decimal,
    pub trade_count: i64,
    #[serde(with = "rust_decimal::serde::str")]
    pub taker_buy_base_volume: Decimal,
    #[serde(with = "rust_decimal::serde::str")]
    pub taker_buy_quote_volume: Decimal,
    pub source: String,
    pub source_file: String,
}

impl From<Candle> for QueryCandle {
    fn from(candle: Candle) -> Self {
        Self {
            open_time: candle.open_time,
            open: candle.open,
            high: candle.high,
            low: candle.low,
            close: candle.close,
            base_asset_volume: candle.base_asset_volume,
            close_time: candle.close_time,
            quote_asset_volume: candle.quote_asset_volume,
            trade_count: candle.trade_count,
            taker_buy_base_volume: candle.taker_buy_base_volume,
            taker_buy_quote_volume: candle.taker_buy_quote_volume,
            source: candle.source,
            source_file: candle.source_file,
        }
    }
}

pub fn parse_cursor(value: Option<&str>) -> anyhow::Result<Option<DateTime<Utc>>> {
    let Some(value) = value else {
        return Ok(None);
    };
    let cursor: DateTime<Utc> = value.parse()?;
    anyhow::ensure!(
        cursor.second() == 0 && cursor.nanosecond() == 0,
        "cursor must be aligned to a UTC minute boundary"
    );
    Ok(Some(cursor))
}

pub async fn load_page(
    pool: &PgPool,
    symbol: &str,
    interval: &str,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
    cursor: Option<DateTime<Utc>>,
    limit: i64,
) -> anyhow::Result<QueryPage> {
    anyhow::ensure!((1..=4096).contains(&limit), "invalid query limit");
    if let Some(cursor) = cursor {
        anyhow::ensure!(
            cursor >= start && cursor < end,
            "cursor must be inside the requested range"
        );
    }

    let rows = db::load_candles_page(pool, symbol, interval, start, end, cursor, limit).await?;
    let last_open = rows.last().map(|row| row.open_time);
    let has_more = if rows.len() as i64 == limit {
        !db::load_candles_page(pool, symbol, interval, start, end, last_open, 1)
            .await?
            .is_empty()
    } else {
        false
    };
    Ok(build_page(
        symbol, interval, start, end, cursor, limit, rows, has_more,
    ))
}

#[allow(clippy::too_many_arguments)]
fn build_page(
    symbol: &str,
    interval: &str,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
    cursor: Option<DateTime<Utc>>,
    limit: i64,
    rows: Vec<Candle>,
    has_more: bool,
) -> QueryPage {
    let next_cursor = has_more.then(|| rows.last().expect("non-empty continued page").open_time);
    let returned = rows.len();
    QueryPage {
        schema_version: QUERY_SCHEMA_VERSION,
        venue: "binance",
        market_type: "spot",
        symbol: symbol.to_owned(),
        interval: interval.to_owned(),
        range_start: start,
        range_end: end,
        cursor,
        limit,
        returned,
        has_more,
        next_cursor,
        candles: rows.into_iter().map(Into::into).collect(),
    }
}

pub fn write_csv<W: std::io::Write>(page: &QueryPage, writer: W) -> anyhow::Result<()> {
    let mut csv = csv::Writer::from_writer(writer);
    for candle in &page.candles {
        csv.serialize(candle)?;
    }
    csv.flush()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::validation::tests::candle;
    use chrono::Duration;

    #[test]
    fn cursor_must_be_minute_aligned() {
        assert!(parse_cursor(Some("2024-01-01T00:00:01Z")).is_err());
        assert_eq!(
            parse_cursor(Some("2024-01-01T00:00:00Z")).unwrap(),
            Some("2024-01-01T00:00:00Z".parse().unwrap())
        );
    }

    #[test]
    fn response_contract_preserves_decimals_and_continuation_cursor() {
        let start: DateTime<Utc> = "2024-01-01T00:00:00Z".parse().unwrap();
        let rows = vec![
            candle("2024-01-01T00:00:00Z"),
            candle("2024-01-01T00:01:00Z"),
        ];
        let page = build_page(
            "BTCUSDT",
            "1m",
            start,
            start + Duration::minutes(3),
            None,
            2,
            rows,
            true,
        );
        assert_eq!(page.returned, 2);
        assert_eq!(page.next_cursor, Some(start + Duration::minutes(1)));
        let json = serde_json::to_value(&page).unwrap();
        assert_eq!(json["candles"][0]["open"], "1");

        let mut csv = Vec::new();
        write_csv(&page, &mut csv).unwrap();
        let csv = String::from_utf8(csv).unwrap();
        assert!(csv.starts_with("open_time,open,high,low,close,"));
        assert!(csv.contains(",1,2,1,1,"));
    }

    #[sqlx::test(migrations = "./migrations")]
    async fn returns_stable_cursor_pages_and_decimal_strings(pool: PgPool) {
        let start: DateTime<Utc> = "2024-01-01T00:00:00Z".parse().unwrap();
        let rows = (0..3)
            .map(|minute| candle(&(start + Duration::minutes(minute)).to_rfc3339()))
            .collect::<Vec<_>>();
        db::insert_candles(&pool, &rows).await.unwrap();

        let first = load_page(
            &pool,
            "BTCUSDT",
            "1m",
            start,
            start + Duration::minutes(3),
            None,
            2,
        )
        .await
        .unwrap();
        assert_eq!(first.returned, 2);
        assert!(first.has_more);
        assert_eq!(first.next_cursor, Some(start + Duration::minutes(1)));
        let second = load_page(
            &pool,
            "BTCUSDT",
            "1m",
            start,
            start + Duration::minutes(3),
            first.next_cursor,
            2,
        )
        .await
        .unwrap();
        assert_eq!(second.returned, 1);
        assert!(!second.has_more);
        assert_eq!(second.candles[0].open_time, start + Duration::minutes(2));
    }
}
