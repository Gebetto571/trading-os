# Trading OS

Trading OS; araştırma, risk, yürütme ve yapay zekâ destekli denetim bileşenlerini sade ve izlenebilir bir çalışma düzeninde birleştirir.

Bu depo iki kalıcı katmanlıdır:

- **Yerel çalışma alanı:** `/Users/scm/Projects/trading-os`; kod, testler, SQLite
  kayıtları ve hızlı geliştirme burada tutulur.
- **GitHub:** Kodun ve kalıcı teknik belgelerin sürüm geçmişi ve uzak yedeği.

Private GitHub deposu: <https://github.com/Gebetto571/trading-os>

## Hızlı başlangıç

Python 3.11 veya daha yeni bir sürüm yeterlidir; harici paket gerekmez.

```bash
python3 -m trading_os_bridge init
python3 -m trading_os_bridge send --to cloud-planner --subject "İlk görev" --body "Mimariyi değerlendir"
python3 -m trading_os_bridge list
```

Kullanıcının proje kaynağına eklediği JSON görev zarfları `var/inbox/` içine
alındıktan sonra şu komutla yerel kayda işlenebilir:

```bash
python3 -m trading_os_bridge ingest var/inbox
```

Sohbetler arası aktarım kendiliğinden çalışmaz. Kullanıcı görev metnini proje
kaynağına ekler veya GitHub issue/commit/PR bağlantısını Codex'e verir. Yerel
işleme için şu komutlar kullanılır:

```bash
python3 -m trading_os_bridge claim --worker codex-dev
python3 -m trading_os_bridge status MESSAGE_UUID completed --worker codex-dev
python3 -m trading_os_bridge recover --id MESSAGE_UUID
python3 -m trading_os_bridge check MESSAGE_UUID
```

`send`, `ingest`, `list` ve `status` yerel işlemler için korunur. `status` yalnız
claim sahibi ve geçerli süreyle `completed`/`failed` yazabilir. `claim`, bir
mesajın aynı anda iki uygulayıcı tarafından çalıştırılmasını önler; `recover`
yalnız kullanıcı talimatıyla yarım kalmış veya süresi dolmuş sahipliği kurtarır.
Geçersiz ve bütünlüğü bozuk zarflar çalıştırılmaz, karantinaya alınır.

## Temel belgeler

- [Sistem mimarisi](docs/architecture.md)
- [ChatGPT ↔ Codex iletişim protokolü](docs/communication-protocol.md)
- [Veritabanı tasarımı](docs/database.md)
- [Yerel Git ve GitHub çalışma düzeni](docs/operations.md)
- [Güvenlik politikası](docs/security.md)
- [Talimatla çalışan bulut sohbet–Codex devri](docs/automation-runbook.md)

`sources/` klasörü ChatGPT projesinden eşlenen salt okunur kaynaktır; değiştirilmez.

Kod, belgeler ve çalışma dosyaları lokaldir; sürüm ve uzak yedek GitHub'dadır.
Yeni Markdown varsayılan olarak açılmaz; TOS-DEC-004 istisnası ve merkezi fihrist
kaydı birlikte gerekir.

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
