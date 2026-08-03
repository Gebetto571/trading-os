use crate::candle::Candle;
use chrono::{DateTime, Duration, Utc};
use std::collections::BTreeMap;

fn bucket_start(t: DateTime<Utc>, minutes: i64) -> DateTime<Utc> {
    let epoch = t.timestamp();
    let bucket = minutes * 60;
    DateTime::from_timestamp(epoch - epoch.rem_euclid(bucket), 0).unwrap()
}
pub fn aggregate_complete(candles: &[Candle], interval: &str) -> anyhow::Result<Vec<Candle>> {
    let minutes = match interval {
        "15m" => 15,
        "1h" => 60,
        "4h" => 240,
        "1d" => 1440,
        _ => anyhow::bail!("unsupported aggregate interval: {interval}"),
    };
    let mut groups: BTreeMap<DateTime<Utc>, Vec<&Candle>> = BTreeMap::new();
    for c in candles {
        groups
            .entry(bucket_start(c.open_time, minutes))
            .or_default()
            .push(c);
    }
    let mut out = Vec::new();
    for (start, mut group) in groups {
        group.sort_by_key(|c| c.open_time);
        if group.len() != minutes as usize {
            continue;
        }
        if group
            .iter()
            .enumerate()
            .any(|(i, c)| c.open_time != start + Duration::minutes(i as i64))
        {
            continue;
        }
        let first = group[0];
        let last = group[group.len() - 1];
        let mut c = (*first).clone();
        c.interval = interval.into();
        c.open_time = start;
        c.close = last.close;
        c.close_time = start + Duration::minutes(minutes) - Duration::milliseconds(1);
        c.high = group.iter().map(|x| x.high).max().unwrap();
        c.low = group.iter().map(|x| x.low).min().unwrap();
        c.base_asset_volume = group.iter().map(|x| x.base_asset_volume).sum();
        c.quote_asset_volume = group.iter().map(|x| x.quote_asset_volume).sum();
        c.taker_buy_base_volume = group.iter().map(|x| x.taker_buy_base_volume).sum();
        c.taker_buy_quote_volume = group.iter().map(|x| x.taker_buy_quote_volume).sum();
        c.trade_count = group.iter().map(|x| x.trade_count).sum();
        c.source = "aggregate".into();
        c.source_file = "canonical:1m".into();
        out.push(c);
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::validation::tests::candle;
    #[test]
    fn utc_boundaries_and_incomplete() {
        let base = "2024-01-01T00:00:00Z".parse::<DateTime<Utc>>().unwrap();
        let cs: Vec<_> = (0..15)
            .map(|i| candle(&(base + Duration::minutes(i)).to_rfc3339()))
            .collect();
        assert_eq!(aggregate_complete(&cs, "15m").unwrap().len(), 1);
        assert!(aggregate_complete(&cs[..14], "15m").unwrap().is_empty());
    }
    #[test]
    fn supported_boundaries() {
        for (name, n) in [("1h", 60), ("4h", 240), ("1d", 1440)] {
            let base = "2024-01-01T00:00:00Z".parse::<DateTime<Utc>>().unwrap();
            let cs: Vec<_> = (0..n)
                .map(|i| candle(&(base + Duration::minutes(i)).to_rfc3339()))
                .collect();
            assert_eq!(aggregate_complete(&cs, name).unwrap().len(), 1);
        }
    }
}
