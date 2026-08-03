# Yerel Git ve GitHub çalışma düzeni

## Kalıcı yerleşim

| Konum | İşlev |
|---|---|
| `/Users/scm/Projects/trading-os` | Tek yerel kod, belge ve Git çalışma alanı |
| Public GitHub `Gebetto571/trading-os` | Sürümlü uzak yedek ve inceleme/devir bağlantıları |
| ChatGPT proje kaynağı | Kullanıcının açıkça eklediği bulut sohbet görev bağlamı |
| `var/` | Git dışı yerel mesaj, arşiv, karantina ve veritabanı verileri |

## Git politikası

- Ana ve tek yerel kod deposu `/Users/scm/Projects/trading-os` konumundadır;
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

- Kod ve teknik belgeler: `/Users/scm/Projects/trading-os` + public GitHub deposu.
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
  /Users/scm/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) \
  /Users/scm/Library/LaunchAgents/com.tradingos.market-data.btcusdt-sync.plist
```

Son durum `data/health/btcusdt/latest.json`, tarihçe ise izinleri `0600` olan
`history.jsonl` üzerinden okunur. Loglar
`/Users/scm/Library/Logs/trading-os-btcusdt-sync.log` konumundadır.
