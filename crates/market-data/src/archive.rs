use chrono::{DateTime, Datelike, Duration, NaiveDate, TimeZone, Utc};
use serde::{Deserialize, Serialize};

const ROOT: &str = "https://data.binance.vision/data/spot";

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum SourceType {
    Monthly,
    Daily,
    Rest,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ArchiveItem {
    pub source_type: SourceType,
    pub period: String,
    pub url: String,
    pub file_name: String,
    pub start: DateTime<Utc>,
    pub end: DateTime<Utc>,
}

fn month_start(year: i32, month: u32) -> DateTime<Utc> {
    Utc.from_utc_datetime(
        &NaiveDate::from_ymd_opt(year, month, 1)
            .unwrap()
            .and_hms_opt(0, 0, 0)
            .unwrap(),
    )
}
fn next_month(t: DateTime<Utc>) -> DateTime<Utc> {
    if t.month() == 12 {
        month_start(t.year() + 1, 1)
    } else {
        month_start(t.year(), t.month() + 1)
    }
}

pub fn plan_archives(
    symbol: &str,
    interval: &str,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
    now: DateTime<Utc>,
) -> Vec<ArchiveItem> {
    let mut items = Vec::new();
    let mut cursor = start;
    while cursor < end {
        let this_month = month_start(cursor.year(), cursor.month());
        let month_end = next_month(this_month);
        let complete_month = cursor == this_month && month_end <= end && month_end <= now;
        if complete_month {
            let period = format!("{:04}-{:02}", cursor.year(), cursor.month());
            let file_name = format!("{symbol}-{interval}-{period}.zip");
            items.push(ArchiveItem {
                source_type: SourceType::Monthly,
                period,
                url: format!("{ROOT}/monthly/klines/{symbol}/{interval}/{file_name}"),
                file_name,
                start: cursor,
                end: month_end,
            });
            cursor = month_end;
        } else {
            let day_end = (cursor.date_naive() + Duration::days(1))
                .and_hms_opt(0, 0, 0)
                .unwrap()
                .and_utc();
            let item_end = day_end.min(end);
            let period = cursor.format("%Y-%m-%d").to_string();
            let file_name = format!("{symbol}-{interval}-{period}.zip");
            items.push(ArchiveItem {
                source_type: SourceType::Daily,
                period,
                url: format!("{ROOT}/daily/klines/{symbol}/{interval}/{file_name}"),
                file_name,
                start: cursor,
                end: item_end,
            });
            cursor = item_end;
        }
    }
    items
}

pub fn daily_fallback(monthly: &ArchiveItem) -> Vec<ArchiveItem> {
    let mut out = Vec::new();
    let mut cursor = monthly.start;
    while cursor < monthly.end {
        let end = (cursor + Duration::days(1)).min(monthly.end);
        let period = cursor.format("%Y-%m-%d").to_string();
        let symbol = monthly.file_name.split('-').next().unwrap_or("BTCUSDT");
        let interval = "1m";
        let file_name = format!("{symbol}-{interval}-{period}.zip");
        out.push(ArchiveItem {
            source_type: SourceType::Daily,
            period,
            url: format!("{ROOT}/daily/klines/{symbol}/{interval}/{file_name}"),
            file_name,
            start: cursor,
            end,
        });
        cursor = end;
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn full_month_uses_monthly() {
        let s = "2024-01-01T00:00:00Z".parse().unwrap();
        let e = "2024-02-01T00:00:00Z".parse().unwrap();
        let p = plan_archives(
            "BTCUSDT",
            "1m",
            s,
            e,
            "2024-03-01T00:00:00Z".parse().unwrap(),
        );
        assert_eq!(p.len(), 1);
        assert_eq!(p[0].source_type, SourceType::Monthly);
    }
    #[test]
    fn partial_range_uses_days() {
        let s = "2024-01-02T00:00:00Z".parse().unwrap();
        let e = "2024-01-04T00:00:00Z".parse().unwrap();
        assert_eq!(plan_archives("BTCUSDT", "1m", s, e, e).len(), 2);
    }
    #[test]
    fn monthly_has_daily_fallback() {
        let s = "2024-01-01T00:00:00Z".parse().unwrap();
        let e = "2024-02-01T00:00:00Z".parse().unwrap();
        let p = plan_archives("BTCUSDT", "1m", s, e, e).remove(0);
        assert_eq!(daily_fallback(&p).len(), 31);
    }
}
