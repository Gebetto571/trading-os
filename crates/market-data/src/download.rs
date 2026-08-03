use anyhow::{bail, Context};
use rand::Rng;
use reqwest::{Client, StatusCode};
use sha2::{Digest, Sha256};
use std::{
    future::Future,
    path::{Path, PathBuf},
    time::Duration,
};
use tokio::{fs, io::AsyncWriteExt};

#[derive(Debug, Clone)]
pub struct DownloadConfig {
    pub max_attempts: u32,
    pub timeout: Duration,
    pub base_backoff: Duration,
}
impl Default for DownloadConfig {
    fn default() -> Self {
        Self {
            max_attempts: 5,
            timeout: Duration::from_secs(30),
            base_backoff: Duration::from_millis(500),
        }
    }
}

#[derive(Debug, thiserror::Error)]
pub enum DownloadError {
    #[error("not found: {0}")]
    NotFound(String),
    #[error("checksum mismatch: expected {expected}, got {actual}")]
    ChecksumMismatch { expected: String, actual: String },
    #[error(transparent)]
    Other(#[from] anyhow::Error),
}

#[derive(Clone)]
pub struct Downloader {
    client: Client,
    config: DownloadConfig,
}
impl Downloader {
    pub fn new(config: DownloadConfig) -> anyhow::Result<Self> {
        let client = Client::builder()
            .timeout(config.timeout)
            .user_agent("trading-os-market-data/0.1")
            .build()?;
        Ok(Self { client, config })
    }

    async fn get_bytes(&self, url: &str) -> Result<Vec<u8>, DownloadError> {
        let mut last = None;
        for attempt in 0..self.config.max_attempts {
            match self.client.get(url).send().await {
                Ok(response) if response.status() == StatusCode::NOT_FOUND => {
                    return Err(DownloadError::NotFound(url.into()))
                }
                Ok(response) if response.status().is_success() => {
                    return Ok(response.bytes().await.context("read response")?.to_vec())
                }
                Ok(response) => {
                    let status = response.status();
                    let retry_after = response
                        .headers()
                        .get(reqwest::header::RETRY_AFTER)
                        .and_then(|v| v.to_str().ok())
                        .and_then(|v| v.parse::<u64>().ok())
                        .map(Duration::from_secs);
                    last = Some(anyhow::anyhow!("HTTP {status} for {url}"));
                    if status != StatusCode::TOO_MANY_REQUESTS && !status.is_server_error() {
                        break;
                    }
                    self.backoff(attempt, retry_after).await;
                }
                Err(err) => {
                    last = Some(err.into());
                    self.backoff(attempt, None).await;
                }
            }
        }
        Err(DownloadError::Other(
            last.unwrap_or_else(|| anyhow::anyhow!("retry limit is zero")),
        ))
    }

    async fn backoff(&self, attempt: u32, retry_after: Option<Duration>) {
        let exponential = self
            .config
            .base_backoff
            .saturating_mul(2u32.saturating_pow(attempt.min(8)));
        let jitter = Duration::from_millis(rand::thread_rng().gen_range(0..=250));
        tokio::time::sleep(retry_after.unwrap_or(exponential) + jitter).await;
    }

    async fn download_to_part<F, Fut>(
        &self,
        url: &str,
        part: &Path,
        on_attempt: &mut F,
    ) -> Result<(u64, String), DownloadError>
    where
        F: FnMut() -> Fut,
        Fut: Future<Output = anyhow::Result<()>>,
    {
        let mut last = None;
        for attempt in 0..self.config.max_attempts {
            on_attempt().await.map_err(DownloadError::Other)?;
            match self.client.get(url).send().await {
                Ok(response) if response.status() == StatusCode::NOT_FOUND => {
                    return Err(DownloadError::NotFound(url.into()));
                }
                Ok(mut response) if response.status().is_success() => {
                    let _ = fs::remove_file(part).await;
                    let mut file = fs::File::create(part).await.context("create part file")?;
                    let mut digest = Sha256::new();
                    let mut size = 0_u64;
                    let mut failed = None;
                    loop {
                        match response.chunk().await {
                            Ok(Some(chunk)) => {
                                digest.update(&chunk);
                                size += chunk.len() as u64;
                                if let Err(error) = file.write_all(&chunk).await {
                                    failed = Some(anyhow::Error::from(error));
                                    break;
                                }
                            }
                            Ok(None) => break,
                            Err(error) => {
                                failed = Some(anyhow::Error::from(error));
                                break;
                            }
                        }
                    }
                    if let Some(error) = failed {
                        last = Some(error);
                        drop(file);
                        let _ = fs::remove_file(part).await;
                        self.backoff(attempt, None).await;
                        continue;
                    }
                    file.sync_all().await.context("sync part file")?;
                    return Ok((size, hex::encode(digest.finalize())));
                }
                Ok(response) => {
                    let status = response.status();
                    let retry_after = response
                        .headers()
                        .get(reqwest::header::RETRY_AFTER)
                        .and_then(|v| v.to_str().ok())
                        .and_then(|v| v.parse::<u64>().ok())
                        .map(Duration::from_secs);
                    last = Some(anyhow::anyhow!("HTTP {status} for {url}"));
                    if status != StatusCode::TOO_MANY_REQUESTS && !status.is_server_error() {
                        break;
                    }
                    self.backoff(attempt, retry_after).await;
                }
                Err(error) => {
                    last = Some(error.into());
                    self.backoff(attempt, None).await;
                }
            }
        }
        Err(DownloadError::Other(
            last.unwrap_or_else(|| anyhow::anyhow!("retry limit is zero")),
        ))
    }

    pub async fn download_verified(&self, url: &str, target: &Path) -> Result<u64, DownloadError> {
        self.download_verified_tracked(url, target, || async { Ok(()) })
            .await
    }

    pub async fn download_verified_tracked<F, Fut>(
        &self,
        url: &str,
        target: &Path,
        mut on_attempt: F,
    ) -> Result<u64, DownloadError>
    where
        F: FnMut() -> Fut,
        Fut: Future<Output = anyhow::Result<()>>,
    {
        fs::create_dir_all(target.parent().context("download target has no parent")?)
            .await
            .context("create download directory")?;
        let checksum_text = String::from_utf8(self.get_bytes(&format!("{url}.CHECKSUM")).await?)
            .context("checksum is not UTF-8")?;
        let expected = checksum_text
            .split_whitespace()
            .next()
            .context("empty checksum file")?
            .to_ascii_lowercase();
        if expected.len() != 64 || !expected.chars().all(|c| c.is_ascii_hexdigit()) {
            return Err(DownloadError::Other(anyhow::anyhow!(
                "invalid SHA-256 in checksum file"
            )));
        }
        if target.exists() {
            let existing = fs::read(target).await.context("read cached archive")?;
            if sha256(&existing) == expected {
                fs::write(checksum_path(target), &expected)
                    .await
                    .context("write checksum proof")?;
                return Ok(existing.len() as u64);
            }
        }
        let part = part_path(target);
        let (size, actual) = self.download_to_part(url, &part, &mut on_attempt).await?;
        if actual != expected {
            let _ = fs::remove_file(&part).await;
            return Err(DownloadError::ChecksumMismatch { expected, actual });
        }
        fs::rename(&part, target)
            .await
            .context("atomically publish archive")?;
        fs::write(checksum_path(target), &expected)
            .await
            .context("write checksum proof")?;
        Ok(size)
    }
}

fn part_path(path: &Path) -> PathBuf {
    let mut p = path.as_os_str().to_owned();
    p.push(".part");
    PathBuf::from(p)
}
fn checksum_path(path: &Path) -> PathBuf {
    let mut p = path.as_os_str().to_owned();
    p.push(".sha256");
    PathBuf::from(p)
}
fn sha256(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}

pub fn verify_cached(path: &Path) -> anyhow::Result<u64> {
    let expected = std::fs::read_to_string(checksum_path(path))?;
    let bytes = std::fs::read(path)?;
    let actual = sha256(&bytes);
    anyhow::ensure!(
        actual == expected.trim(),
        "cached archive checksum mismatch"
    );
    Ok(bytes.len() as u64)
}

pub fn cached_checksum(path: &Path) -> anyhow::Result<String> {
    Ok(std::fs::read_to_string(checksum_path(path))?
        .trim()
        .to_owned())
}

pub fn extract_single_csv(zip_path: &Path) -> anyhow::Result<Vec<u8>> {
    let file = std::fs::File::open(zip_path)?;
    let mut archive = zip::ZipArchive::new(file)?;
    if archive.len() != 1 {
        bail!("expected exactly one file in ZIP, found {}", archive.len());
    }
    let mut entry = archive.by_index(0)?;
    const MAX_UNCOMPRESSED_CSV: u64 = 2 * 1024 * 1024 * 1024;
    if entry.size() > MAX_UNCOMPRESSED_CSV {
        bail!("ZIP entry exceeds the 2 GiB safety limit");
    }
    if entry.compressed_size() > 0 && entry.size() / entry.compressed_size() > 250 {
        bail!("ZIP compression ratio exceeds safety limit");
    }
    let enclosed = entry
        .enclosed_name()
        .context("ZIP entry contains unsafe path")?;
    if enclosed.extension().and_then(|x| x.to_str()) != Some("csv") {
        bail!("ZIP entry is not a CSV");
    }
    let mut bytes = Vec::new();
    std::io::copy(&mut entry, &mut bytes)?;
    Ok(bytes)
}

#[cfg(test)]
mod tests {
    use super::*;
    use httpmock::prelude::*;
    use std::sync::{
        atomic::{AtomicUsize, Ordering},
        Arc,
    };
    #[tokio::test]
    async fn rejects_wrong_checksum() {
        let s = MockServer::start();
        let u = format!("{}/x.zip", s.base_url());
        s.mock(|w, t| {
            w.path("/x.zip.CHECKSUM");
            t.body(format!("{} x.zip", "0".repeat(64)));
        });
        s.mock(|w, t| {
            w.path("/x.zip");
            t.body("bytes");
        });
        let d = Downloader::new(DownloadConfig {
            base_backoff: Duration::ZERO,
            ..Default::default()
        })
        .unwrap();
        let temp = tempfile::tempdir().unwrap();
        assert!(matches!(
            d.download_verified(&u, &temp.path().join("x.zip")).await,
            Err(DownloadError::ChecksumMismatch { .. })
        ));
    }
    #[tokio::test]
    async fn resumes_by_replacing_part_and_reuses_verified_file() {
        let s = MockServer::start();
        let u = format!("{}/x.zip", s.base_url());
        let sum = sha256(b"bytes");
        s.mock(|w, t| {
            w.path("/x.zip.CHECKSUM");
            t.body(format!("{sum} x.zip"));
        });
        let data = s.mock(|w, t| {
            w.path("/x.zip");
            t.body("bytes");
        });
        let d = Downloader::new(Default::default()).unwrap();
        let temp = tempfile::tempdir().unwrap();
        let target = temp.path().join("x.zip");
        let attempts = Arc::new(AtomicUsize::new(0));
        std::fs::write(part_path(&target), b"partial").unwrap();
        for _ in 0..2 {
            let attempts = Arc::clone(&attempts);
            d.download_verified_tracked(&u, &target, move || {
                attempts.fetch_add(1, Ordering::SeqCst);
                async { Ok(()) }
            })
            .await
            .unwrap();
        }
        data.assert_hits(1);
        assert_eq!(attempts.load(Ordering::SeqCst), 1);
    }

    #[tokio::test]
    async fn tracked_callback_counts_each_zip_attempt() {
        let s = MockServer::start();
        let u = format!("{}/x.zip", s.base_url());
        s.mock(|w, t| {
            w.path("/x.zip.CHECKSUM");
            t.body(format!("{} x.zip", "0".repeat(64)));
        });
        let data = s.mock(|w, t| {
            w.path("/x.zip");
            t.status(500);
        });
        let d = Downloader::new(DownloadConfig {
            max_attempts: 2,
            base_backoff: Duration::ZERO,
            ..Default::default()
        })
        .unwrap();
        let attempts = Arc::new(AtomicUsize::new(0));
        let observed = Arc::clone(&attempts);
        let temp = tempfile::tempdir().unwrap();
        assert!(d
            .download_verified_tracked(&u, &temp.path().join("x.zip"), move || {
                observed.fetch_add(1, Ordering::SeqCst);
                async { Ok(()) }
            })
            .await
            .is_err());
        data.assert_hits(2);
        assert_eq!(attempts.load(Ordering::SeqCst), 2);
    }
    #[tokio::test]
    async fn honors_retry_limit() {
        let s = MockServer::start();
        let u = format!("{}/x", s.base_url());
        let m = s.mock(|w, t| {
            w.path("/x");
            t.status(500);
        });
        let d = Downloader::new(DownloadConfig {
            max_attempts: 2,
            base_backoff: Duration::ZERO,
            ..Default::default()
        })
        .unwrap();
        assert!(d.get_bytes(&u).await.is_err());
        m.assert_hits(2);
    }
}
