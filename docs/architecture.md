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

## Akış

1. Bulut ChatGPT görev kartını hazırlar; kullanıcı kartı proje kaynağına ekler
   veya GitHub issue/commit/PR bağlantısıyla Codex'e devreder.
2. Codex yalnız kullanıcının açık talimatıyla kaynağı okur; yerel JSON zarfı varsa
   `var/inbox` üzerinden SQLite'a alır.
3. Üretilen kod ve kalıcı belgeler Git'e kaydedilir.
4. Codex sonucu commit/PR ve kısa sonuç özetiyle kullanıcıya teslim eder.
5. Kullanıcı isterse GitHub bağlantısını bulut sohbete vererek kabul kriterlerini
   yeniden değerlendirtir.

Hiçbir sohbet veya yerel araç GitHub'ı ya da proje kaynağını periyodik olarak
taramaz.

## Gelecek yazılım yerleşimi

Ana Trading OS uygulaması büyürken aşağıdaki sınırlar korunacaktır:

```text
apps/                 kullanıcıya dönük uygulamalar
crates/               Rust işlem çekirdeği ve adaptörler
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
