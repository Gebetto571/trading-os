# Güncel durum — 2026-08-03

BTCUSDT spot 1m veri katmanı `crates/market-data` altında uygulanmıştır. Rust format,
Clippy ve 20 otomatik test geçmektedir. Günlük ve 2024 Ocak gerçek Binance verileri
yerel PostgreSQL/Parquet katmanına aktarılmış; eksik ve mükerrer kayıt bulunmamıştır.
İkinci çalıştırmalarda veritabanı sayıları ve Parquet SHA-256 değerleri değişmemiştir.

Yerel PostgreSQL 16 servisi sağlıklıdır. Varsayılan üç yıllık kanonik aktarım henüz
tamamlanmamıştır. Kesin sayılar ve kalite kanıtı
`docs/reports/2026-08-03-btcusdt-data-integrity.md` dosyasındadır.

Bilinen kalan işler: farklı içerik çatışmasının gerçek PostgreSQL entegrasyon testi,
manifest durum makinesinin bütün geçişleri, yapılandırılabilir indirme eşzamanlılığı,
gerçek REST onarım senaryosu ve Binance üst zaman dilimi örnek karşılaştırmalarıdır.
