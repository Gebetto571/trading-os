# Güncel durum — 2026-08-03

BTCUSDT spot 1m veri katmanı `crates/market-data` altında uygulanmıştır. Rust format,
Clippy ve 20 otomatik test geçmektedir. Tek günlük gerçek Binance arşivi checksum ile
doğrulanmış ve ikinci çalıştırmada önbellekten güvenle tekrar kullanılmıştır.

Geliştirme ortamında Docker/PostgreSQL bulunmadığı için varsayılan üç yıllık kanonik
PostgreSQL aktarımı ve Parquet/üst zaman dilimi üretimi henüz tamamlanmış değildir.
Kesin durum `docs/reports/2026-08-03-btcusdt-data-integrity.md` dosyasındadır.

Bilinen kalan işler: gerçek PostgreSQL idempotency entegrasyon testi, manifest durum
makinesinin bütün geçişleri, yapılandırılabilir indirme eşzamanlılığı ve Binance üst
zaman dilimi örnek karşılaştırmalarıdır.
