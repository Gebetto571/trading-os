# Trading OS

Trading OS; araştırma, risk, yürütme ve yapay zekâ destekli denetim bileşenlerini sade ve izlenebilir bir çalışma düzeninde birleştirir.

Trading OS üç sade katmanda çalışır:

- **Yerel çalışma alanı:** `/Users/scm/Projects/trading-os`; kod, testler, SQLite
  kayıtları ve hızlı geliştirme burada tutulur.
- **GitHub:** Kodun ve kalıcı teknik belgelerin sürüm geçmişi ve uzak yedeği.
- **Google Drive:** Yapay zekâ hafızası ve kullanıcı denetimli görev–sonuç
  koordinasyonu. Drive bir kod deposu veya canlı uygulama kaynağı değildir.

Public GitHub deposu: <https://github.com/Gebetto571/trading-os>

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

Sohbetler arası aktarım kendiliğinden çalışmaz. ChatGPT, kullanıcının talimatıyla
JSON görev zarfını Drive `01_CHATGPT_GELEN` klasörüne bırakabilir; kullanıcı Codex'e
kontrol emri verir. Sonuç aynı kimlikle `02_CODEX_GELEN` klasörüne döner. Yerel
köprü Drive'ı taramaz; zarf kullanıcı denetiminde yerel gelen kutusuna alındıktan
sonra şu komutlar kullanılır:

```bash
python3 -m trading_os_bridge claim --worker codex-dev
python3 -m trading_os_bridge claim-task --lane chief-engineer/00 \
  --base-commit "$(git rev-parse HEAD)" --owned-path trading_os_bridge
python3 -m trading_os_bridge result MESSAGE_UUID --report result-report.json
python3 -m trading_os_bridge status MESSAGE_UUID completed --worker codex-dev
python3 -m trading_os_bridge recover --id MESSAGE_UUID
python3 -m trading_os_bridge check MESSAGE_UUID
```

`send`, `ingest`, `list` ve `status` yerel işlemler için korunur. `status` yalnız
claim sahibi ve geçerli süreyle `completed`/`failed` yazabilir. `claim`, bir
mesajın aynı anda iki uygulayıcı tarafından çalıştırılmasını önler; `recover`
yalnız kullanıcı talimatıyla yarım kalmış veya süresi dolmuş sahipliği kurtarır.
Geçersiz ve bütünlüğü bozuk zarflar çalıştırılmaz, karantinaya alınır.

Proje dosyası değiştiren kullanıcı-devirli görevler `schemas/conversation-map.json` ile
`chief-engineer/00`–`chief-engineer/08` hatlarına yönlenir. Bunlar yalnız
`claim-task` ile, `chief-engineer` tek aktif yazarı ve açık dosya sahipliğiyle
alınabilir. `result`, commit/push/merge/deployment/canlı işlem yetkilerini kapalı
tutan korelasyonlu sonuç zarfını üretir. Görev kaynağı güncel Drive
`01_CHATGPT_GELEN` zarfı veya GitHub teknik referansıdır; eski Drive kod deposu
yolları kullanılmaz.

## Temel belgeler

- [Sistem mimarisi](docs/architecture.md)
- [ChatGPT ↔ Codex iletişim protokolü](docs/communication-protocol.md)
- [Veritabanı tasarımı](docs/database.md)
- [Yerel Git ve GitHub çalışma düzeni](docs/operations.md)
- [Güvenlik politikası](docs/security.md)
- [Talimatla çalışan bulut sohbet–Codex devri](docs/automation-runbook.md)

`sources/` klasörü ChatGPT projesinden eşlenen salt okunur kaynaktır; değiştirilmez.

Kod ve Git-kanonik teknik belgeler lokaldir; sürüm ve uzak kaynak GitHub'dadır.
Drive'daki yaşayan AI hafızasının kanonik sahibi Drive'dır. Katmanlar arasında
bağımsız düzenlenen iki yaşayan kopya oluşturulmaz; TOS-DEC-004 bölüm 7 uygulanır.
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

Tarihsel kurulumdan sonra yeni kapanmış mumları artımlı almak için
`market-data-import sync` kullanılır. Yerel macOS görevi bunu 15 dakikada bir
çalıştırır; kesinti sonrası PostgreSQL'deki son kanonik dakikadan devam eder ve
her çalışmada `data/health/btcusdt/` altında kısa sağlık kaydı bırakır.
