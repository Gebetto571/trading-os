# Trading OS

Trading OS; araştırma, risk, yürütme ve yapay zekâ destekli denetim bileşenlerini sade ve izlenebilir bir çalışma düzeninde birleştirir.

Trading OS üç sade katmanda çalışır:

- **Yerel çalışma alanı:** `/Users/m2pro/Projects/trading-os`; kod, testler, SQLite
  kayıtları ve hızlı geliştirme burada tutulur.
- **GitHub:** Kodun ve kalıcı teknik belgelerin sürüm geçmişi ve uzak yedeği.
- **Google Drive:** Yapay zekâ hafızası ve kullanıcı denetimli görev–sonuç
  koordinasyonu. Drive bir kod deposu veya canlı uygulama kaynağı değildir.

Public GitHub deposu: <https://github.com/Gebetto571/trading-os>

## Hızlı başlangıç

Mac mini çalışma ortamı Python 3.12.14 ve Rust 1.88.0 kullanır. Önce
`scripts/setup-mac-mini.sh` çalıştırılır; mevcut `.env` korunur, yalnız eksikse
özel izinlerle örnek oluşturulur. Docker, uv ve Rust araçları önkoşuldur.
Köprü de `research/engine/.venv/bin/python` ile çalıştırılır; macOS'un sistem
Python'u değiştirilmez. Aşağıdaki köprü komutları yerel SQLite'a yazabilir.

```bash
research/engine/.venv/bin/python -m trading_os_bridge init
research/engine/.venv/bin/python -m trading_os_bridge send --to cloud-planner --subject "İlk görev" --body "Mimariyi değerlendir"
research/engine/.venv/bin/python -m trading_os_bridge list
```

Kullanıcının proje kaynağına eklediği JSON görev zarfları `var/inbox/` içine
alındıktan sonra şu komutla yerel kayda işlenebilir:

```bash
research/engine/.venv/bin/python -m trading_os_bridge ingest var/inbox
```

Sohbetler arası aktarım kendiliğinden çalışmaz. ChatGPT, kullanıcının talimatıyla
JSON görev zarfını Drive `01_CHATGPT_GELEN` klasörüne bırakabilir; kullanıcı Codex'e
kontrol emri verir. Sonuç aynı kimlikle `02_CODEX_GELEN` klasörüne döner. Yerel
köprü Drive'ı taramaz; zarf kullanıcı denetiminde yerel gelen kutusuna alındıktan
sonra şu komutlar kullanılır:

```bash
research/engine/.venv/bin/python -m trading_os_bridge claim --worker codex-dev
research/engine/.venv/bin/python -m trading_os_bridge claim-task --lane chief-engineer/00 \
  --base-commit "$(git rev-parse HEAD)" --owned-path trading_os_bridge
research/engine/.venv/bin/python -m trading_os_bridge result MESSAGE_UUID --report result-report.json
research/engine/.venv/bin/python -m trading_os_bridge status MESSAGE_UUID completed --worker codex-dev
research/engine/.venv/bin/python -m trading_os_bridge recover --id MESSAGE_UUID
research/engine/.venv/bin/python -m trading_os_bridge check MESSAGE_UUID
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

## Ürün ve strateji kapsamı

İlk aktif ürün ve adaptör Binance Global BTCUSDT spot'tur. Adaptör public market
data, private order/user stream, LIMIT GTC submit/cancel/query, balances, fills,
reconnect/backfill ve rate-limit/error mapping sınırında kalır; strateji veya risk
kuralı yazmaz. İlk strateji yönü price-action araştırmasıdır. Kanıtlanmış strateji
ve ayrı kabul kartı yoksa PAPER, LIVE_CANARY ve LIVE kapalıdır; güvenli başlangıç
BACKTEST/REPLAY'dir.

XAU/USD, BTCUSDT spot veri, replay, risk, PAPER ve execution kapıları tamamlandıktan
sonra ayrı ürün ve adaptör kararıyla ele alınabilecek ikincil kapsamdır. BTCUSDT
isolated margin ise spot production kanıtı ve ayrı margin kararı sonrasına bırakılır.
Perpetual, futures, cross margin ve BIST/hisse bu kartın aktif ilk yol haritasında
değildir.

## Araştırma ve replay sözleşmeleri

`research/engine` içindeki R1 katmanı, doğrulanmış salt-okunur veri snapshot'ından
aday, manifest ve dondurulmuş simülasyon izi kanıtı üretir. Paket-yerel test ortamı
gerektiğinde `research/engine/requirements.txt` içindeki Polars bağımlılığıyla
kurulur; bu bağımlılık kök çalışma zamanına taşınmaz.

`crates/strategy-runtime` yalnızca C0 Strategy Contract V1 kanonik baytlarını
doğrular ve bellekte deterministic replay ile idealize/gerçekçi-maliyet/stres
projeksiyonları üretir. Ağ, venue, broker, emir, kalıcı runtime yazımı, PAPER,
LIVE_CANARY veya LIVE yetkisi vermez. R1→C0 bağı yalnız kanıt sözleşmesidir ve
şu şemalarla korunur:

- `schemas/strategy-contract-v1.schema.json` ve golden vektörü
- `schemas/r1-c0-materialization-v1.schema.json` ve golden vektörü

Bu katmanların çıktısı ayrı strateji kabul kartı olmadan ürün stratejisi veya canlı
işlem kararı sayılmaz. R1→C0 ve replay bugün ayrı, salt-kanıt kapılarıdır; bunlar
market-data ile execution-core arasında otomatik uçtan uca adapter çalıştırmaz.

## BTCUSDT tarihsel veri katmanı

Rust veri hattı `crates/market-data` altında bulunur. Binance Global spot `BTCUSDT/1m`
arşivlerini SHA-256 ile doğrular; PostgreSQL'e çelişki kontrollü aktarır, boşlukları
sınırlı REST istekleriyle onarır ve kanonik veriden decimal Parquet ile `15m`, `1h`,
`4h`, `1d` mumları üretir.

```bash
scripts/setup-mac-mini.sh
# Yalnız ilk kurulumda .env içindeki örnek parolayı değiştirin.
docker compose -f compose.market-data.yml up -d postgres
scripts/deploy-market-data.sh build
scripts/test-project.sh
scripts/deploy-market-data.sh activate --report target/test-project/latest.json
scripts/setup-mac-mini.sh --config-only --activate-agent
research/engine/.venv/bin/python scripts/check-system.py
```

Ayrıntılı mimari ve işletim bilgisi:
[BTCUSDT veri katmanı](docs/architecture/market-data.md).

Kanonik mumları salt okunur sorgulamak için:

```bash
source scripts/lib/market-data.sh
tos_init "$PWD"
tos_load_env
"$(tos_release_path)" query-candles --interval 1h \
  --start 2026-08-01T00:00:00Z --end 2026-08-03T00:00:00Z --limit 100
```

Yanıt zaman sıralı JSON'dur. `has_more=true` ise `next_cursor` değeri sonraki
çağrıya `--cursor` olarak verilir; komut veritabanında migration veya yazma yapmaz.
`--format csv` yalnız mum satırlarını başlıklı CSV olarak üretir.

Tarihsel kurulumdan sonra yeni kapanmış mumları artımlı almak için
`market-data-import sync` kullanılır. Yerel macOS görevi bunu 15 dakikada bir
çalıştırır; kesinti sonrası PostgreSQL'deki son kanonik dakikadan devam eder ve
her çalışmada kullanıcı runtime alanının `health/` klasörüne kısa sağlık kaydı bırakır.

Mac mini'de kabul edilmiş çalıştırıcı ve güncel sağlık kayıtları kullanıcıya özel
`~/Library/Application Support/TradingOS/market-data/` alanındadır. Geliştirme
derlemesi çalışan sürümü değiştirmez. Tam test ayrı geçici PostgreSQL kullanır;
miras alınmış `DATABASE_URL` varsa komut başlamayı reddeder. Yeni sürüm ancak
derleme ile aynı kaynak özeti ve Git kaydını taşıyan başarılı test raporuyla
etkinleştirilir. `deploy-market-data.sh rollback` önceki doğrulanmış sürümü seçer.
Yedek almak için `scripts/backup-database.sh` kullanılır; bu komutun arşiv
kontrolü, ayrı bir gerçek geri yükleme ve başka fiziksel cihaz kontrolünün
yerine geçmez. Ayrıntılar [operasyon belgesindedir](docs/operations.md).

D1 gerçek çıktı incelemesi `research_engine.d1` modülündedir. Kanonik 2024–2025
BTCUSDT 1h verisi ile yöntem önce `freeze` ile mühürlenir; `evaluate` bağımsız
SHA-256 ister. Gerçek fiyatlardan hesaplanan sonuçların reddedilmesi normal bir
araştırma sonucudur. Mühendislik kabulü strateji kabulünden ayrıdır; yöntem
koşulları ve varsayımsal işlem maliyetleri raporda açıkça yazılır. Bu modül
veritabanı yazmaz, strateji terfi ettirmez ve PAPER/LIVE açmaz.
