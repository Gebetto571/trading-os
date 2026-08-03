# Güncel durum — 2026-08-03

## Yerleşim ve yönetişim

Ana yerel Git deposunun `/Users/scm/Projects/trading-os` konumunda olduğu,
`main` dalının `origin/main` izlediği ve eski
2026-08-03 tarihinde yerel olarak doğrulanmıştır. Çalışma dosyaları tamamen
lokaldir; sürüm ve uzak yedek GitHub'dadır.

TOS-DEC-003, ilk iletişim modeli için tarihsel başvuru durumundadır; ayrı Markdown
olay dosyası üretme hükümleri TOS-DEC-004 tarafından geçersiz kılınmıştır. Mevcut
yaşayan kayıt ve merkezi fihrist önceliklidir.

## Köprü durumu

Köprünün hedef sözleşmesi kullanıcı talimatlı proje kaynağı/GitHub devri;
yerel `claim` ve `recover`; tam zarf doğrulaması, içerik özeti, süreli sahiplik,
karantina ve karar sürümlemesidir. Bunların üretime hazır sayılması için CLI
davranışları, `migrations/002_bridge_integrity.sql` uygulaması ve uçtan uca yerel
devir deneyi ayrıca doğrulanmalıdır. Bu belge yalnız hedefi kaydeder; doğrulanmamış kod sonucunu
tamamlanmış ilan etmez.

BTCUSDT spot 1m veri katmanı `crates/market-data` altında uygulanmıştır. Rust format,
Clippy ve 20 otomatik test geçmektedir. Günlük ve 2024 Ocak gerçek Binance verileri
yerel PostgreSQL/Parquet katmanına aktarılmış; eksik ve mükerrer kayıt bulunmamıştır.
İkinci çalıştırmalarda veritabanı sayıları ve Parquet SHA-256 değerleri değişmemiştir.

Yerel PostgreSQL 16 servisi sağlıklıdır. Varsayılan üç yıllık kanonik aktarım
tamamlanmıştır: 1m `1.578.477`, 15m `105.231`, 1h `26.307`, 4h `6.576`,
1d `1.096` kayıt vardır. Toplam `185` aylık Parquet bölümü PostgreSQL sayılarıyla
eşleşmektedir. Kesin aralık ve kalite kanıtı
`docs/reports/2026-08-03-btcusdt-data-integrity.md` dosyasındadır.

Bilinen kalan işler: farklı içerik çatışmasının gerçek PostgreSQL entegrasyon testi,
manifest durum makinesinin bütün geçişleri, yapılandırılabilir indirme eşzamanlılığı,
başarılı fallback sonrası manifest durumunun düzeltilmesi ve Binance üst zaman dilimi
örnek karşılaştırmalarıdır.
