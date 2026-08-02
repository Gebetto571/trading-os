# Sistem mimarisi

## Tek cümlelik tasarım

Git kodun gerçeğini, SQLite yerel çalışma gerçeğini, Google Drive ise ChatGPT ile Codex arasındaki taşınabilir iletişim gerçeğini tutar.

## Sorumluluk sınırları

| Katman | Tuttuğu bilgi | Tutmaması gereken bilgi |
|---|---|---|
| Yerel Git | Kod, şema, migration, kalıcı belgeler | Anahtar, gerçek hesap verisi, çalışma DB'si |
| GitHub | İncelenebilir ve sürümlü depo kopyası | API anahtarı, özel piyasa verisi, ham günlük |
| SQLite | Mesaj durumu, karar izi, artefakt dizini, senkron geçmişi | Büyük ikili dosyalar, anahtarlar |
| Google Drive | Sohbetler arası görevler, yanıtlar, kararlar, raporlar | Canlı emir anahtarı, borsa sırrı |
| `sources/` | ChatGPT projesinden gelen bağlayıcı referanslar | Yerel düzenleme |

## Akış

1. ChatGPT bir mesaj zarfını `01_CHATGPT_GELEN` klasörüne bırakır.
2. Codex zarfı `var/inbox` üzerinden SQLite'a alır ve işlemeye başlar.
3. Üretilen kod ve kalıcı belgeler Git'e kaydedilir.
4. Codex yanıt zarfını `var/outbox` üzerinden `02_CODEX_GELEN` klasörüne koyar.
5. Kabul edilmiş kararlar ayrıca `03_KARARLAR` altında saklanır.
6. Bitmiş iletişim dosyaları `90_ARSIV` klasörüne taşınır.

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

