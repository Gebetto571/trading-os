# Yerel Git ve GitHub çalışma düzeni

## Kalıcı yerleşim

| Konum | İşlev |
|---|---|
| `/Users/m2pro/Projects/trading-os` | Tek yerel kod, belge ve Git çalışma alanı |
| Public GitHub `Gebetto571/trading-os` | Sürümlü uzak yedek ve inceleme/devir bağlantıları |
| ChatGPT proje kaynağı | Kullanıcının açıkça eklediği bulut sohbet görev bağlamı |
| `var/` | Git dışı yerel mesaj, arşiv, karantina ve veritabanı verileri |

## Git politikası

- Ana ve tek yerel kod deposu `/Users/m2pro/Projects/trading-os` konumundadır;
  standart `.git` metadata'sını kullanır ve public GitHub deposuna
  `origin` adıyla bağlıdır. Normal, etkileşimsiz Git komutları kullanılır.
- Ana dal: `main`.
- İş dalları: `agent/<kısa-konu>` veya `feature/<kısa-konu>`.
- Küçük, tek amaçlı kayıtlar yapılır.
- `sources/` aynalanmış referanstır; yerelde değiştirilmez.
- Veritabanı, günlük, anahtar ve ham özel veri Git'e eklenmez.

Örnek:

```bash
git status
git log --oneline
```

## GitHub politikası

- Depo: <https://github.com/Gebetto571/trading-os>
- Depo kullanıcı onayıyla **public** yapılmıştır; kaynak kod ve belgeler herkesçe
  okunabilir. Sırlar, ham piyasa verisi ve çalışma veritabanları Git dışında kalır.
- `main` doğrudan günlük geliştirme için kullanılmaz; değişiklikler dal ve inceleme üzerinden birleşir.
- GitHub kodun ve teknik belgelerin uzak, sürümlü kopyası ve devir kanalıdır.
- Bulut sohbet görevi kullanıcı tarafından proje kaynağına eklenir veya GitHub
  issue/commit/PR bağlantısıyla Codex'e verilir.
- Anahtarlar daha sonra GitHub Secrets içinde tutulur, dosyaya yazılmaz.

## Yedekleme

- Kod ve teknik belgeler: `/Users/m2pro/Projects/trading-os` + public GitHub deposu.
- SQLite: uygulama kapalıyken tarih damgalı şifreli yedek; GitHub'a gönderilmez.
- Yerel karar/raporlar: Git üzerinden sürümlenir ve GitHub'a yedeklenir.

## Talimatlı devir

Proje kaynağı veya GitHub görev bağlantısı periyodik olarak taranmaz. Kontrol
yalnız kullanıcının açık talimatıyla başlar. Yerel iletişim zarfları `var/`
altında kalır; kalıcı kod ve belge değişikliği Git/GitHub geçmişinden izlenir.

## BTCUSDT otomatik veri eşitleme

Yerel görev `com.tradingos.market-data.btcusdt-sync` etiketiyle 15 dakikada bir
çalışır. Takip edilen şablon
`ops/launchd/com.tradingos.market-data.btcusdt-sync.plist`, çalıştırıcı ise
`scripts/sync-btcusdt.sh` dosyasıdır. Görev Docker veya PostgreSQL'i kendiliğinden
başlatmaz; servis kapalıysa başarısız sağlık kaydı bırakır ve sonraki zamanlamayı
bekler. Mac uyandığında kanonik PostgreSQL watermark'ından devam eder.

Kurulumdan önce release binary üretilir ve plist kullanıcı alanına kopyalanır:

```bash
cargo build --release -p trading-os-market-data --bin market-data-import
cp ops/launchd/com.tradingos.market-data.btcusdt-sync.plist \
  /Users/m2pro/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) \
  /Users/m2pro/Library/LaunchAgents/com.tradingos.market-data.btcusdt-sync.plist
```

Son durum `data/health/btcusdt/latest.json`, tarihçe ise izinleri `0600` olan
`history.jsonl` üzerinden okunur. Loglar
`/Users/m2pro/Library/Logs/trading-os-btcusdt-sync.log` konumundadır.

## 2026-09-14 Mac mini devri

Aktif çalışma klasörü `/Users/m2pro/Projects/trading-os`; MacBook kaynak kopyası korunmuştur. Kaynak Git revizyonu `3c6416b703f9f468d1a60790f95992c832ac1908`, dal `preservation/pre-integration-20260821-8da4648`dir. Makine uyarlamaları henüz commit edilmemiştir. `sources/` salt okunur kalır.

Aktarım ve test kanıtları `/Users/m2pro/Projects/.trading-os-migration-20260914` klasöründedir. Önce `transfer-verification.json` ve son `migration-result.json` okunur. Önceki görev bağlamı aynı klasörün `evidence/continuation.json` dosyasındadır; eski LCOS kayıtları `chatgpt-context/` altında tarihli referanstır ve kendiliğinden etkinleştirilmez.

Geliştirme araçları Rust 1.88.0 (ARM64) ve Python 3.12dir. Terminal başlangıcında `source ~/.cargo/env` ile Rust araçları açılır. Araştırma ortamı `research/engine/.venv/bin/python` üzerinden kullanılır; köprü ve araştırma testleri de bu doğrulanmış ortamla çalıştırılabilir. Yeni `.env` örneği mevcut ayarların üstüne kopyalanmaz.

H1 önceki görevde tamamlandı. D1, kanonik değerlendirme corpus'u ve hesap yöntemi kararı beklemektedir. Taşımanın tamamlanması bu eksikliği çözülmüş veya canlı işlem kapılarını açılmış saymaz.

MacBook eşitlemesi devir sırasında durdurulmuştur. Mac mini eşitlemesinin son etkinlik ve kabul durumu `migration-result.json` içindedir; iki makinede eşzamanlı çalıştırılmaz. Geri dönüş gerekirse önce Mac mini eşitlemesi durdurulur, sonra korunmuş MacBook kaynağı yeniden etkinleştirilir.

Kabul sonucu: 1.776 dosya birebir doğrulandı; beş SQLite bütünlük kontrolü, 148 Python ve 114 Rust testi geçti. PostgreSQL’deki dört tablonun içeriği geri yükleme sonrasında kaynakla birebir eşleşti. Mac mini’de ilk otomatik eşitleme başarıyla tamamlandı: 32.946 yeni mum kaydı, sıfır kalan boşluk. MacBook eşitlemesi kalıcı olarak devre dışı; Mac mini zamanlaması 900 saniyedir. Kaynak proje ve eski yedekler korunmuştur.
