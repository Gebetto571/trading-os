# Güncel durum — 2026-08-03

## Yerleşim ve yönetişim

Ana yerel Git deposunun `/Users/scm/Projects/trading-os` konumunda olduğu ve eski
Drive çalışma kopyasının yerelde bulunmadığı 2026-08-03 tarihinde doğrulanmıştır.
Çalışma dosyaları tamamen lokaldir; izlenen kod ve belgelerin sürüm ve uzak yedeği
GitHub'dadır.

TOS-DEC-003, ilk iletişim modeli için tarihsel başvuru durumundadır; ayrı Markdown
olay dosyası üretme hükümleri TOS-DEC-004 tarafından geçersiz kılınmıştır. Mevcut
yaşayan kayıt ve merkezi fihrist önceliklidir.

## Köprü durumu

Köprü kullanıcı talimatlı proje kaynağı/GitHub devri; yerel `claim`, `recover`,
tam zarf doğrulaması, içerik özeti, süreli sahiplik, karantina ve karar sürümlemesi
ile uygulanmıştır. Migration yükseltmesi, tekrar/çatışma, durum geçişi, eşzamanlı
claim/terminal yarışları, atomik migration rollback'i, özel dosya izinleri,
arşivleme hatası, karantina denetimi ve inbox dışına kaçış senaryolarını kapsayan
toplam 36 Python testi geçmiştir.
Drive adaptörü ve eşitleme komutları kaldırılmıştır.
Gerçek bir `cloud-planner -> codex-dev` test mesajı gelen kutusu, arşiv, claim,
süreli sahiplik ve `completed` durumundan geçirilerek yerel köprü uçtan uca
doğrulanmıştır.

BTCUSDT spot 1m veri katmanı `crates/market-data` altında uygulanmıştır. Rust format,
Clippy ve 24 otomatik test geçmektedir. Günlük ve 2024 Ocak gerçek Binance verileri
yerel PostgreSQL/Parquet katmanına aktarılmış; eksik ve mükerrer kayıt bulunmamıştır.
İkinci çalıştırmalarda veritabanı sayıları ve Parquet SHA-256 değerleri değişmemiştir.

Yerel PostgreSQL 16 servisi sağlıklıdır. Varsayılan üç yıllık kanonik aktarım
tamamlanmıştır: 1m `1.578.477`, 15m `105.231`, 1h `26.307`, 4h `6.576`,
1d `1.096` kayıt vardır. Toplam `185` aylık Parquet bölümü PostgreSQL sayılarıyla
eşleşmektedir. Kesin aralık ve kalite kanıtı
`docs/reports/2026-08-03-btcusdt-data-integrity.md` dosyasındadır.

Ham veri `/Users/scm/Projects/trading-os/data` altında 379 dosya ve yaklaşık
220 MB olarak tutulur. PostgreSQL kalıcı diski
`trading-os_trading_os_market_data` adlı yerel Docker volume'üdür. Doğrulanmış
özel-format yedek `/Users/scm/Projects/trading-os-backups/2026-08-03/` altında,
yalnız kullanıcı erişimli dosya izniyle saklanır. Yedek geçici PostgreSQL veritabanına
gerçekten geri yüklenmiş; beş zaman diliminin satır sayıları ve tarih aralıkları ana
veritabanıyla birebir eşleşmiştir. Ana veri ve yedek aynı fiziksel diskte olduğundan
bu düzen veritabanı/volume kaybına karşı korur, fiziksel disk arızasına karşı ikinci
cihaz yedeği sayılmaz.

Piyasa veri katmanının önceki beş açığı kapatılmıştır: farklı içerik çatışması gerçek
PostgreSQL üzerinde reddedilmiş, manifestin bütün geçişleri sınanmış, indirme
eşzamanlılığı yapılandırılabilir yapılmış, başarılı fallback kayıtları düzeltilmiş ve
15m/1h/4h/1d mumları 2024-01-01 Binance örneğiyle birebir karşılaştırılmıştır.

Fiziksel olarak ayrı yedek hedefi henüz bağlı değildir. Doğrulanmış yerel yedek bu
hedef bağlanana kadar korunur; Drive veri yedeği olarak kullanılmaz.

GitHub deposu özel kalmıştır ve PR birleşince çalışma dallarını otomatik silme ayarı
açılmıştır. Mevcut GitHub planı özel depoda ana dal koruma kuralını desteklemediği
için kalite kapısı PR iş akışı ve işletim disipliniyle uygulanır.
