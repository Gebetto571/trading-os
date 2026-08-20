# Güncel durum — 2026-08-04

## Yerleşim ve yönetişim

Ana yerel Git deposunun `/Users/scm/Projects/trading-os` konumunda olduğu ve eski
Drive kod çalışma kopyasının yerelde bulunmadığı doğrulanmıştır. Yazılım ve
Git-kanonik teknik belgeler yereldir; sürüm ve uzak kaynak public GitHub'dadır.
Güncel Drive `Trading OS` alanı TOS-DEC-004 bölüm 7 uyarınca AI hafızası ve
kullanıcı denetimli görev–sonuç koordinasyon katmanıdır; kod deposu değildir.

TOS-DEC-003, ilk iletişim modeli için tarihsel başvuru durumundadır; ayrı Markdown
olay dosyası üretme hükümleri TOS-DEC-004 tarafından geçersiz kılınmıştır. Mevcut
yaşayan kayıt ve merkezi fihrist önceliklidir.

## Köprü durumu

Köprü kullanıcı talimatlı Drive görev zarfı/GitHub teknik referansı devri; yerel `claim`, `recover`,
tam zarf doğrulaması, içerik özeti, süreli sahiplik, karantina ve karar sürümlemesi
ile uygulanmıştır. Migration yükseltmesi, tekrar/çatışma, durum geçişi, eşzamanlı
claim/terminal yarışları, atomik migration rollback'i, özel dosya izinleri,
arşivleme hatası, karantina denetimi ve inbox dışına kaçış senaryolarını kapsayan
toplam 36 Python testi geçmiştir.
Sürekli Drive adaptörü ve eşitleme komutları yoktur; Drive kontrolü yalnız açık
kullanıcı talimatıyla mevcut `01_CHATGPT_GELEN` ve `02_CODEX_GELEN` klasörlerinde yapılır.
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

GitHub deposu public durumdadır ve PR birleşince çalışma dallarını otomatik silme
ayarı açıktır. Kalite kapısı PR iş akışı ve işletim disipliniyle uygulanır.

## Dış piyasa entegrasyonu temizliği — 2026-08-20

Eski üçüncü taraf piyasa entegrasyonu odağı; çalıştırılabilir kod, bağımlılık,
ayar, kimlik bilgisi, uç nokta, veri akışı ve bağlayıcı kaynak metni bakımından
tarandı. Aktif bir bağlantı bulunmadı. Karar sicilindeki eski örnek kaldırıldı;
kaynak karar kartı `0.2` sürümüne yükseltilerek ilk uygulama odağı BTCUSDT spot
veri doğrulaması ve ayrı kabul kartlarıyla yürütülen ağsız PAPER/REPLAY araştırmasıyla
hizalandı. Eski ürüne özgü dil spot işlem, likidite, risk, takas ve saklama
kavramlarıyla değiştirildi. Aktif ana çalışma ağacında ad, istemci, alan adı, paket,
dosya adı ve ilgili ürün terimi desenlerinde eşleşme bulunmadı; bu sonuç strateji
kabulü veya canlı işlem yetkisi anlamına gelmez. `cargo check --workspace --locked`,
yürütme çekirdeği testleri ve yönetişim testleri 2026-08-20 doğrulamasında geçti.
Market-data paketinin PostgreSQL kullanan testleri test veritabanı bağlantı zaman
aşımı nedeniyle ayrıca tamamlanamadı; bu çevresel engel belge değişikliğine bağlı
değildir.
Ayrı çalışma ağaçları ile Git geçmişindeki tarihsel kopyalar değiştirilmedi;
bunların kaldırılması ayrı, açık onaylı bir geçmiş/çalışma ağacı operasyonu
gerektirir. Sonraki dış kaynak eşitlemesinde `0.2` metni korunmalı; kaynak yeniden
üretilirse sıfır-iz taraması tekrarlanmalıdır.

## Mimari takip — 2026-08-20

Bu temizlikte kod, CI veya performans optimizasyonu uygulanmadı. Ayrı backlog:

- P0: Research Engine testleri ve bağımlılığı CI kalite kapısında mevcut; bağımlılık kilitleme, fixture kapsamı ve quality-job zorunluluğu düzenli korunmalı.
- P1: Salt okunur veri snapshot’ı → research sonucu → normalize PAPER/REPLAY girdisi için sürümlü sözleşme tasarlamak; canlı adaptör eklememek.
- P2: Execution-core büyük durumlarda kopyalama, hash ve açık emir taraması için release ölçümleri (1k/10k/100k) eklemek; eşik aşılmadan refactor yapmamak.
- P3: Market-data arşiv/CSV ve research tablo yükleri için veri boyutu, tepe bellek ve telemetri bütçelerini ölçmek.
- P4/P5: İşletim betikleri/compose taşınabilirlik kontrolleri ile research SQLite eşzamanlılığı ve Rust MSRV değerlendirmesini ihtiyaç halinde açmak.

## Kapsam ve yaşayan belge hizalaması — 2026-08-21

Son anlam/kural incelemesinde ilk aktif ürün ve adaptör Binance Global BTCUSDT
spot olarak sabitlendi. Adaptör public/private akış, LIMIT GTC yaşam döngüsü,
bakiye/fill mutabakatı, reconnect/backfill ve rate-limit/error mapping ile
sınırlıdır; strateji veya risk kuralı taşımaz. İlk strateji yönü price-action
araştırmasıdır ve `hipotez → veri kalite testi → causal event study → walk-forward
→ holdout → replay → PAPER → LIVE_CANARY → sınırlı LIVE` kanıt sırasına bağlıdır.
Kanıtlanmış strateji ve ayrı kabul kartı olmadan PAPER, LIVE_CANARY ve LIVE kapalıdır.
XAU/USD ayrı ürün/adaptör kararıyla ikincil; BTCUSDT isolated margin spot production
kanıtı ve ayrı margin kararı sonrasıdır. Perpetual, futures, cross margin ve
BIST/hisse aktif ilk yol haritasında değildir.

Yerel `README.md`, `docs/architecture.md` ve `sources/preview.md` bu sınırlarla
uyumlandı. `TOS-CHAT-REGISTRY` eski örneği nötrleştirilmiş adapter örneği olarak
tutuyor; `TOS-DEC-004` MD-004/MD-025'i external-sync ve `MD-026`yı
`proposed / branch-only` olarak kaydediyor. `sources/` yerel ayna değil dış
eşitleme sahibi olduğundan, upstream sürüm korunmadan yerel metin kanonik kabul
edilmez.

Drive'daki Master Blueprint, Task Tree, Roadmap ve Chief Engineer Packs tarandı;
yasaklı marka veya eski ürün terimi bulunmadı. Blueprint'te BTCUSDT bağlamı
mevcut olsa da bu turdaki XAU/USD ve price-action ayrıntıları henüz yansımamıştır.
Blueprint'i aynı ürün sırası ve adaptör sınırıyla güncelleme girişimi güvenlik
katmanı tarafından reddedildi; dış belgeye tam içerik yüklemesi için ayrıca açık
hedef/payload onayı gerekir. Bu nedenle Drive belgesi taranmış, ancak güncelleme
başarılı gibi gösterilmemiştir.

Workgraph doğrulaması dış salt-okunur geri okumada `TOS-WORKGRAPH-001`, revision
`2.0`, `DRAFT`, 102 görev, 246 bağımlılık, çevrimsiz DAG ve SHA-256
`8589142094750f01106fcf02583f69452522ff8779c60f8c0a095cf2e1e4c11f` olarak
kaydedildi; `var/lcos` yerel aynası yoktur. Bu görevde kod, CI veya performans
optimizasyonu uygulanmadı; P0–P5 backlog'u yukarıdaki bölümde korunur.
