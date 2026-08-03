use crate::candle::Candle;
use anyhow::{bail, Context};
use chrono::{DateTime, Duration as ChronoDuration, Utc};
use reqwest::{Client, StatusCode};
use serde_json::Value;
use std::time::Duration;

#[derive(Clone)]
pub struct BinanceRest {
    client: Client,
    base_url: String,
    max_attempts: u32,
}
impl BinanceRest {
    pub fn new() -> anyhow::Result<Self> {
        Ok(Self {
            client: Client::builder()
                .timeout(Duration::from_secs(20))
                .user_agent("trading-os-market-data/0.1")
                .build()?,
            base_url: "https://api.binance.com".into(),
            max_attempts: 5,
        })
    }
    #[cfg(test)]
    fn with_base(base_url: String, max_attempts: u32) -> anyhow::Result<Self> {
        Ok(Self {
            client: Client::builder().timeout(Duration::from_secs(2)).build()?,
            base_url,
            max_attempts,
        })
    }
    pub async fn fetch(
        &self,
        symbol: &str,
        start: DateTime<Utc>,
        end: DateTime<Utc>,
    ) -> anyhow::Result<Vec<Candle>> {
        anyhow::ensure!(
            end - start <= chrono::Duration::days(7),
            "REST repair is limited to gaps of seven days; restore archives first"
        );
        self.fetch_interval(symbol, "1m", start, end).await
    }

    pub async fn fetch_interval(
        &self,
        symbol: &str,
        interval: &str,
        start: DateTime<Utc>,
        end: DateTime<Utc>,
    ) -> anyhow::Result<Vec<Candle>> {
        let step = interval_duration(interval)?;
        anyhow::ensure!(start < end, "REST range must not be empty");
        anyhow::ensure!(
            end - start <= ChronoDuration::days(31),
            "REST comparison is limited to 31 days"
        );
        let mut out = Vec::new();
        let mut cursor = start;
        while cursor < end {
            let rows = self.page(symbol, interval, cursor, end).await?;
            if rows.is_empty() {
                break;
            }
            let last = rows.last().unwrap().open_time;
            anyhow::ensure!(last >= cursor, "REST page did not advance");
            anyhow::ensure!(
                rows.windows(2).all(|w| w[0].open_time < w[1].open_time),
                "REST page is not strictly chronological"
            );
            out.extend(rows);
            cursor = last + step;
        }
        out.retain(|c| c.open_time >= start && c.open_time < end);
        Ok(out)
    }
    async fn page(
        &self,
        symbol: &str,
        interval: &str,
        start: DateTime<Utc>,
        end: DateTime<Utc>,
    ) -> anyhow::Result<Vec<Candle>> {
        let mut last_error = None;
        for attempt in 0..self.max_attempts {
            let response = self
                .client
                .get(format!("{}/api/v3/klines", self.base_url))
                .query(&[
                    ("symbol", symbol),
                    ("interval", interval),
                    ("startTime", &start.timestamp_millis().to_string()),
                    ("endTime", &(end.timestamp_millis() - 1).to_string()),
                    ("limit", "1000"),
                ])
                .send()
                .await;
            match response {
                Ok(r) if r.status().is_success() => {
                    let values: Vec<Vec<Value>> = r.json().await?;
                    let mut candles = Vec::with_capacity(values.len());
                    for v in values {
                        if v.len() != 12 {
                            bail!("REST kline has {} fields", v.len())
                        }
                        let text = v
                            .iter()
                            .map(|x| match x {
                                Value::String(s) => s.clone(),
                                _ => x.to_string(),
                            })
                            .collect::<Vec<_>>()
                            .join(",");
                        let mut parsed = crate::candle::read_csv(
                            text.as_bytes(),
                            symbol,
                            start - chrono::Duration::days(1),
                            end + chrono::Duration::days(1),
                            "rest",
                            "api/v3/klines",
                        )?;
                        for candle in &mut parsed {
                            candle.interval = interval.to_owned();
                        }
                        candles.extend(parsed);
                    }
                    return Ok(candles);
                }
                Ok(r) => {
                    let status = r.status();
                    let retry = r
                        .headers()
                        .get(reqwest::header::RETRY_AFTER)
                        .and_then(|x| x.to_str().ok())
                        .and_then(|x| x.parse().ok())
                        .unwrap_or(1);
                    last_error = Some(anyhow::anyhow!("REST HTTP {status}"));
                    if status != StatusCode::TOO_MANY_REQUESTS && !status.is_server_error() {
                        break;
                    }
                    tokio::time::sleep(
                        Duration::from_secs(retry.min(30))
                            + Duration::from_millis(100 * attempt as u64),
                    )
                    .await;
                }
                Err(e) => {
                    last_error = Some(e.into());
                    tokio::time::sleep(Duration::from_millis(200 * 2u64.pow(attempt.min(6)))).await;
                }
            }
        }
        Err(last_error.unwrap_or_else(|| anyhow::anyhow!("REST retry limit reached")))
            .context("Binance REST request failed")
    }
}

fn interval_duration(interval: &str) -> anyhow::Result<ChronoDuration> {
    match interval {
        "1m" => Ok(ChronoDuration::minutes(1)),
        "15m" => Ok(ChronoDuration::minutes(15)),
        "1h" => Ok(ChronoDuration::hours(1)),
        "4h" => Ok(ChronoDuration::hours(4)),
        "1d" => Ok(ChronoDuration::days(1)),
        _ => bail!("unsupported Binance interval: {interval}"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use httpmock::prelude::*;
    #[tokio::test]
    async fn retries_429_and_honors_limit() {
        let s = MockServer::start();
        let m = s.mock(|w, t| {
            w.path("/api/v3/klines");
            t.status(429).header("Retry-After", "0");
        });
        let r = BinanceRest::with_base(s.base_url(), 2).unwrap();
        assert!(r
            .fetch(
                "BTCUSDT",
                "2024-01-01T00:00:00Z".parse().unwrap(),
                "2024-01-01T00:01:00Z".parse().unwrap()
            )
            .await
            .is_err());
        m.assert_hits(2);
    }
}
