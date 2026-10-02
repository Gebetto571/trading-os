# Güncel durum — 2026-10-02

## Devam için önce bu bölüm okunur

- Kanonik çalışma klasörü `/Users/m2pro/Projects/trading-os`; MacBook kaynak
  kopyası tarihsel ve korunmuş durumdadır. `sources/` değiştirilmez.
- PostgreSQL'in 2026-09-24 kesintisi giderildi; 2026-10-02 veri toplama yeniden
  başarılı oldu. İlk kurtarma çalışması 11.571 mum ekledi ve sıfır boşluk bildirdi.
  Bu tarihli kanıttır; her yeni oturumda `check-system.py` güncel sağlık ve veri
  yaşını salt okunur denetler.
- Dört PostgreSQL tablosunun içeriği ayrı geri yükleme veritabanıyla SHA-256
  bakımından eşleşti. SQLite yedeği sağlam; başka fiziksel cihazdaki şifreli
  kurtarma paketi şifre açma ve kaynak dosya karşılaştırmasından geçti.
- H1 lineage daha önce tamamlandı. R1→C0 sözleşmesi ve ağsız replay uygulanmıştır;
  aşağıdaki 2026-08-20 P1 maddesi tarihsel tasarım notudur.
- D1 gerçek çıktı hesaplama yolu `research_engine.d1` ile eklendi. Mühürlü 24 aylık
  2024–2025 BTCUSDT 1h corpus'u, 17.544 mum ve 17 veri alanıyla kanonik PostgreSQL
  içeriğine eşleşti. Önceden sabitlenen dört aday, chronological fold/holdout,
  20 CSCV, PBO, koşullu işaret testi, rejim, komşu ve iki kat maliyet stresi
  gerçek fiyatlardan hesaplandı. Yeni impulse ailesinin sonucu **REJECT**:
  örnek kapsamı ve PBO geçse de fold, rejim, komşu, anlamlılık ve maliyet stresi
  geçmedi. Mühendislik kabulü strateji kabulü değildir; H1 registry terfisi veya
  reusable C3 aktarımı yapılmış sayılmaz. PAPER, LIVE_CANARY ve LIVE kapalıdır.
- İlk gerçek çalışmanın yöntem SHA-256 değeri
  `36095f85511d4ac20ecd11f240ca4fd191917617543926cd24a333ca7343c73a`, snapshot
  kimliği `087ba8552325a93ee68414015928da6b155dd03cd67b1be38b5e8a987418bb6a`.
  Kanıtlar `/Users/m2pro/Projects/.trading-os-reliability-20261002/` altındadır;
  ham veri ve sonuçlar Git'e gönderilmez. Yöntem, sonuç görüldükten sonra ayarlanmaz.
- Kurulum, sürüm etkinleştirme, ayrı veritabanında tam test ve yedek komutları
  `docs/operations.md` içindedir. Rutin geliştirme çalışan ikiliyi değiştirmez.
  Bütün çalışma diliminin test, etkinleştirme ve GitHub kabulü aynı operasyon
  belgesindeki tarihli son kayıttan ve güncel sağlık kontrolünden okunur.

Sıradaki araştırma işi, reddedilmiş yöntem üzerinde eşikleri oynatmak değildir.
Yeni bir hipotez gerekiyorsa tek görev, açık kabul ölçütü ve sonuç görülmeden
belirlenmiş ayrı değerlendirme dönemiyle başlatılır. Önceki 102 görevli workgraph
tarihsel provenance olarak korunur; bütün ağaç her görevde yeniden açılmaz.

Aşağıdaki kayıtlar kendi tarihlerindeki kanıtlardır; bugünkü makine sağlığı veya
test sayısı olarak kullanılmaz.

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
- P1 (tarihsel; R1/C0 ile tamamlandı): Salt okunur veri snapshot’ı → research sonucu → normalize replay girdisi için sürümlü sözleşme; canlı adaptör içermez.
- P2: Execution-core büyük durumlarda kopyalama, hash ve açık emir taraması için release ölçümleri (1k/10k/100k) eklemek; eşik aşılmadan refactor yapmamak.
- P3: Market-data arşiv/CSV ve research tablo yükleri için veri boyutu, tepe bellek ve telemetri bütçelerini ölçmek.
- P4/P5: İşletim betikleri/compose taşınabilirlik kontrolleri ile research SQLite eşzamanlılığı ve Rust MSRV değerlendirmesini ihtiyaç halinde açmak.

## Kapsam ve yaşayan belge hizalaması — 2026-08-21

İlk aktif ürün ve adaptör Binance Global BTCUSDT spot olarak sabitlendi. Adaptör
public/private akış, LIMIT GTC yaşam döngüsü, bakiye/fill mutabakatı,
reconnect/backfill ve rate-limit/error mapping ile sınırlıdır; strateji veya risk
kuralı taşımaz. İlk strateji yönü price-action araştırmasıdır. Kanıtlanmış strateji
ve ayrı kabul kartı olmadan PAPER, LIVE_CANARY ve LIVE kapalıdır. XAU/USD ayrı
ürün/adaptör disposition kararıyla ikincil; BTCUSDT isolated margin ise kabul
edilmiş spot production kanıtı ve ayrı margin kararından sonraki koşullu hedeftir.

Drive'daki TOS-DEC-001 v0.2, TOS-DEC-004 v2.1, sohbet sicili v1.7, Task Tree v1.2,
Chief Engineer Packs v1.1 ve tarihsel araştırma raporu kullanıcı onayıyla yerinde
güncellendi; Master Blueprint v1.1 ve Roadmap v1.1 ile birlikte ham-byte geri
okumada eski ürün/sağlayıcı kalıntısı bulunmadı. TOS-DEC-001 v0.2 geri okuma
SHA-256 değeri `88f7aa28e5a4fe79b346d22d5bdcd866a480077e95ee89c598cfc34f6cd461b2`dir.
ChatGPT projesine bağlı `03_KARARLAR` Drive klasörü yeniden eşitlemeye alındı;
arayüz işlemi `kısmi senkronizasyon` olarak bildirdi. Yerel `sources/preview.md`
dış-eşitleme sahibindeki salt-okunur aynadır; güncel aynanın ham SHA-256 değeri
`4d1e8663f57d652bbbce807a4b595dabec6882c8fb8f9a5d5de88f08f7defe5b` olup
doğrudan ve anlamsal kalıntı taraması temizdir. Drive kararı ile yerel aynanın
byte-for-byte aynı olması sahiplik kuralı değildir; sonraki dış eşitlemede aynı
sıfır-kalıntı taraması tekrarlanacaktır.

`TOS-WORKGRAPH-001@2.0` değiştirilmedi: 102 görev, 246 bağımlılık, sıfır çevrim ve
SHA-256 `8589142094750f01106fcf02583f69452522ff8779c60f8c0a095cf2e1e4c11f`.
İçindeki eski `@1.0` otorite referansları değişmez derleme provenance'ıdır; güncel
ürün ve strateji anlamını TOS-DEC-001 v0.2 ile geri okunmuş Blueprint, Task Tree,
Roadmap ve Packs sürümleri belirler. F7'deki ikinci hedef yalnız BTCUSDT ürün hattını
anlatır; global ürün sırası değildir.

Kapsam temizliği kapanışında Rust format, workspace check ve Clippy; execution-core'un
51 testi; sağlıklı yerel PostgreSQL ile market-data'nın 50 testi; kök Python
yönetişim/köprü paketinin 78 testi ve geçici izole ortamda research engine'in 38
testi geçti. Bu bölüm yalnız 2026-08-21 kapsam temizliği kanıtıdır; sonraki strateji
ve araştırma sözleşmesi değişiklikleri aşağıdaki yaşayan kayıtla izlenir.

## R1/C0 araştırma ve replay hizalaması — 2026-08-21

Sonraki uygulama dilimlerinde proje yolları ve anlamı şu şekilde sabitlendi:

- `research/engine/research_engine/screening.py`, R0 snapshot'tan salt-okunur R1
  aday/manifest/frozen-trace kanıtı üretir; SQLite, runtime artefaktı, emir, venue,
  ağ veya PAPER/LIVE davranışı üretmez.
- `schemas/r1-c0-materialization-v1.schema.json` ve golden vektörü, R1 kanıtını
  `schemas/strategy-contract-v1.schema.json` C0 sözleşmesine tek yönlü bağlar.
- `crates/strategy-runtime/`, C0 kanonik bayt doğrulaması ve bellekte deterministic
  replay/projeksiyon katmanıdır; bağımsız execution-core veya market-data adaptörü
  değildir ve canlı yetki vermez.
- `tests/test_r1_c0_materialization.py`, `tests/test_strategy_contract.py` ve
  `crates/strategy-runtime/tests/` ilgili şema, kimlik, replay, sınır ve performans
  kapılarını taşır.

2026-08-21 tam doğrulamasında kök Python paketi 89 test, research engine 55 test ve
Rust workspace tüm hedefleri geçti. İlk strateji yönü hâlâ BTCUSDT price-action
araştırmasıdır; R1/C0/replay kanıtı ayrı strateji kabul kartı olmadan PAPER,
LIVE_CANARY veya LIVE yetkisi doğurmaz. XAU/USD ve isolated-margin karar kapıları
önceki ayrı disposition ve insan onayı sırasını korur.
