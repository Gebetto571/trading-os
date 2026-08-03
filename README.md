# Trading OS

Trading OS; araştırma, risk, yürütme ve yapay zekâ destekli denetim bileşenlerini sade ve izlenebilir bir çalışma düzeninde birleştirir.

Bu depo üç katmanlıdır:

- **Yerel çalışma alanı:** Kod, testler, SQLite kayıtları ve hızlı geliştirme.
- **Google Drive:** ChatGPT bulut sohbetleri ile Codex arasında kontrollü mesaj ve belge aktarımı.
- **GitHub:** Kodun ve kalıcı teknik belgelerin sürüm geçmişi ve uzak yedeği.

Private GitHub deposu: <https://github.com/Gebetto571/trading-os>

## Hızlı başlangıç

Python 3.11 veya daha yeni bir sürüm yeterlidir; harici paket gerekmez.

```bash
python3 -m trading_os_bridge init
python3 -m trading_os_bridge send --to chatgpt --subject "İlk görev" --body "Mimariyi değerlendir"
python3 -m trading_os_bridge list
```

Üretilen aktarım dosyaları `var/outbox/` altında oluşur. Drive'a gelen dosyalar `var/inbox/` içine konup şu komutla kayda alınır:

```bash
python3 -m trading_os_bridge ingest var/inbox
```

## Temel belgeler

- [Sistem mimarisi](docs/architecture.md)
- [ChatGPT ↔ Codex iletişim protokolü](docs/communication-protocol.md)
- [Veritabanı tasarımı](docs/database.md)
- [Drive, Git ve GitHub çalışma düzeni](docs/operations.md)
- [Güvenlik politikası](docs/security.md)
- [Talimatla çalışan Drive–Codex köprüsü](docs/automation-runbook.md)

`sources/` klasörü ChatGPT projesinden eşlenen salt okunur kaynaktır; değiştirilmez.

## BTCUSDT tarihsel veri katmanı

Rust veri hattı `crates/market-data` altında bulunur. Binance Global spot `BTCUSDT/1m`
arşivlerini SHA-256 ile doğrular; PostgreSQL'e çelişki kontrollü aktarır, boşlukları
sınırlı REST istekleriyle onarır ve kanonik veriden decimal Parquet ile `15m`, `1h`,
`4h`, `1d` mumları üretir.

```bash
cp .env.example .env
# .env içindeki parolayı değiştirin
docker compose -f compose.market-data.yml up -d postgres
set -a; source .env; set +a
cargo run --release -p trading-os-market-data --bin market-data-import -- run \
  --start 2023-08-03T00:00:00Z --end latest-closed
```

Ayrıntılı mimari ve işletim bilgisi:
[BTCUSDT veri katmanı](docs/architecture/market-data.md).
