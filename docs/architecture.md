# Sistem mimarisi

## Tek cümlelik tasarım

Yerel Git kod ve belgelerin çalışma gerçeğini, SQLite yerel işlem durumunu,
GitHub ise sürümlü uzak yedeği ve sohbetler arası devir bağlantısını tutar.

## Sorumluluk sınırları

| Katman | Tuttuğu bilgi | Tutmaması gereken bilgi |
|---|---|---|
| Yerel Git | Kod, şema, migration, kalıcı belgeler | Anahtar, gerçek hesap verisi, çalışma DB'si |
| GitHub | İncelenebilir ve sürümlü depo kopyası | API anahtarı, özel piyasa verisi, ham günlük |
| SQLite | Mesaj durumu, karar izi, artefakt dizini, senkron geçmişi | Büyük ikili dosyalar, anahtarlar |
| `sources/` | ChatGPT projesinden gelen bağlayıcı referanslar | Yerel düzenleme |
| `research/engine` R1 yolu | R0 snapshot'tan salt-okunur aday/manifest/trace kanıtı | Bu R1 yolunda SQLite/runtime kalıcılığı, emir, venue veya canlı yetki |
| `crates/strategy-runtime` | C0 sözleşme doğrulaması ve bellekte deterministic replay projeksiyonları | Ağ, broker, venue, emir, PAPER/LIVE yetkisi |

## Akış

1. Bulut ChatGPT görev kartını hazırlar; kullanıcı kartı proje kaynağına ekler
   veya GitHub issue/commit/PR bağlantısıyla Codex'e devreder.
2. Codex yalnız kullanıcının açık talimatıyla kaynağı okur; yerel JSON zarfı varsa
   `var/inbox` üzerinden SQLite'a alır.
3. Üretilen kod ve kalıcı belgeler Git'e kaydedilir.
4. Codex sonucu commit/PR ve kısa sonuç özetiyle kullanıcıya teslim eder.
5. Kullanıcı isterse GitHub bağlantısını bulut sohbete vererek kabul kriterlerini
   yeniden değerlendirtir.

Araştırma akışında R0 snapshot doğrulamasından sonra R1 screening yalnız kanıt
üretir; R1→C0 materialization bu kanıtı sürümlü kanonik sözleşmeye bağlar;
`strategy-runtime` ise sözleşmeyi ağsız ve bellekte replay eder. Bu adımlar PAPER,
LIVE_CANARY veya LIVE emir yetkisi doğurmaz; ayrı kabul kartı ve insan kapıları
zorunludur. R1→C0→replay bugün ayrı kanıt kapılarıdır; market-data ile
execution-core arasında otomatik uçtan uca adapter bağlantısı kurmaz.

Hiçbir sohbet veya yerel araç GitHub'ı ya da proje kaynağını periyodik olarak
taramaz.

## Ürün ve strateji kapıları

- İlk aktif ürün ve adaptör Binance Global BTCUSDT spot'tur. Adaptör public market
  data, private order/user stream, LIMIT GTC submit/cancel/query, balances, fills,
  reconnect/backfill ve rate-limit/error mapping ile sınırlıdır; strateji veya risk
  kuralı içermez.
- İlk strateji yönü price-action araştırmasıdır. Akış `hipotez → veri kalite testi
  → causal event study → walk-forward → holdout → R1 screening → C0 materialization
  → ağsız replay → PAPER → LIVE_CANARY → sınırlı LIVE` sırasını izler. R1/C0/replay
  kanıtı tek başına PAPER değildir; kanıtlanmış strateji ve kabul kartı olmadan
  PAPER, LIVE_CANARY veya LIVE açılmaz. LIVE ayrıca açık insan onayı ve sermaye
  limiti ister.
- Sınırlar `Strategy → TradeIntent → Economic Gate → Risk Authority → Execution →
  Reconciler` olarak ayrıdır. Adaptör ürün bağlantısını, Strategy araştırmayı,
  Risk Authority sermaye/risk kararını, Execution emir yaşam döngüsünü ve Reconciler
  dış gerçek ile iç durumu eşleştirmeyi taşır.
- XAU/USD ikincil ve ayrı adaptör/ürün kararıyla; BTCUSDT isolated margin ise spot
  production kanıtı ve ayrı margin kararıyla ele alınabilir. Perpetual, futures,
  cross margin ve BIST/hisse aktif ilk yol haritasında değildir.

## Gelecek yazılım yerleşimi

Ana Trading OS uygulaması büyürken aşağıdaki sınırlar korunacaktır:

```text
apps/                 kullanıcıya dönük uygulamalar
crates/               Rust işlem çekirdeği, replay ve adaptörler
research/             Salt-okunur araştırma ve screening motoru
packages/             ortak arayüz paketleri
trading_os_bridge/    sohbet ve belge aktarım aracı
config/               güvenli örnek ayarlar
docs/                 kalıcı teknik belgeler
migrations/           sıralı veritabanı değişiklikleri
schemas/              makinece doğrulanabilir veri sözleşmeleri
tests/                otomatik kontroller
var/                  Git dışı çalışma verileri
sources/              salt okunur proje kaynakları
```

İlk günden boş klasör üretmek yerine, yeni bir bileşen gerçekten başladığında ilgili klasör oluşturulur.
