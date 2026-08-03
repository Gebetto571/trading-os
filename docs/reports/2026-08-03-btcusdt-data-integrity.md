# BTCUSDT veri bütünlüğü raporu — 2026-08-03

## Hedef

- Binance Global spot / BTCUSDT / 1m
- Varsayılan aralık: `[2023-08-03T00:00:00Z, latest-closed)`
- Kanonik kaynak: PostgreSQL

## Tamamlanan gerçek veri kanıtı

- Dönem: `[2024-01-01T00:00:00Z, 2024-01-02T00:00:00Z)`
- Arşiv: 1 günlük ZIP, 68.923 bayt
- CSV: 1.440 satır
- İlk/son open time: `00:00:00Z` / `23:59:00Z`
- SHA-256: `4ec2915e610ab4e9a4d5e86a5ada1c15bbf6b5db343cdb385681d6ac97166a4e`
- İkinci çalıştırma: checksum doğrulanmış önbellek yeniden kullanıldı

## Kalite kapısı

- `cargo fmt --all -- --check`: geçti
- `cargo clippy --workspace --all-targets --all-features -- -D warnings`: geçti
- `cargo test --workspace --all-features`: 20 geçti, 0 başarısız

## Ortam engeli

Docker ve PostgreSQL bu geliştirme ortamında bulunmadığından üç yıllık PostgreSQL
aktarımı yapılmadı. PostgreSQL/Parquet sayıları, kanonik eksik-mükerrer taraması,
REST onarımları ve gerçek üst zaman dilimi karşılaştırmaları **ölçülmedi**; sıfır
olarak değerlendirilmemelidir.

## Bilinen açıklar

- PostgreSQL idempotency ve farklı içerik çatışması gerçek servis üzerinde sınanmadı.
- Manifestin `planned/downloaded/validated` geçişleri ve tam resume semantiği eksik.
- İndirme güvenli fakat sıralı; CLI eşzamanlılık ayarı henüz yok.
- Üst zaman dilimleri gerçek Binance örnekleriyle karşılaştırılmadı.
