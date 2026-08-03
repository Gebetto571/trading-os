---
id: TOS-DEC-004
title: Merkezi Dosya Yönetim Anayasası
status: sealed
version: 1.2
date: 2026-08-03
last_updated: 2026-08-03
authority: project-constitution
scope:
  - all-chats
  - drive
  - local-git
  - github
  - markdown-governance
supersedes_in_conflict:
  - TOS-DEC-003
  - TOS-CHATDEC-20260803-001
  - TOS-XFER-20260803-001
  - TOS-TPL-001
  - TOS-TPL-002
---

# Trading OS Merkezi Dosya Yönetim Anayasası

## 1. Anayasal ilke

Trading OS içinde yeni dosya oluşturmak istisnadır. Varsayılan işlem; uygun mevcut dosyayı bulmak, aynı dosyayı düzenlemek ve yeni bilgiyi açık tarihli bir bölüm olarak eklemektir.

Bir sohbette geçen “`.md oluştur`”, “kaydet”, “belgele”, “karar yaz” veya benzeri bir ifade, tek başına yeni bir dosya açma emri sayılmaz. İstenen sonuç mevcut uygun dosyada gerçekleştirilebiliyorsa yeni dosya oluşturulmaz.

## 2. Yetki ve öncelik

Bu belge, Trading OS içindeki bütün sohbetler ve ajanlar için dosya yönetimi konusunda en üst proje kuralıdır. TOS-DEC-003 veya başka bir belgede “her karar/aktarım için ayrı dosya” yönünde bir hüküm varsa bu anayasa uygulanır.

Sistem ve güvenlik talimatları her zaman bu belgenin üzerindedir. Bu belge, kullanıcı yetkisini genişletmez.

## 3. Zorunlu karar sırası

Bir sohbet dosyaya yazmadan önce sırayla şu denetimi yapar:

1. **Kalıcılık:** Bilginin dosyada tutulması gerçekten gerekli mi? Geçici konuşma, kısa teyit veya günlük durumsa yalnızca sohbet içinde bırakılır.
2. **Mevcut dosya:** Aynı sohbete, konuya, karara, göreve veya bileşene ait uygun bir dosya var mı? Varsa o dosya güncellenir.
3. **Ana belge:** Bilgi; README, mimari, veritabanı, operasyon, güvenlik veya mevcut karar belgesinin bir bölümüne eklenebilir mi? Eklenebiliyorsa yeni dosya açılmaz.
4. **Birleştirme:** Ayrı dosya yerine mevcut belgeye tarihli başlık, kayıt satırı veya değişiklik notu eklemek yeterli mi? Yeterliyse mevcut belge kullanılır.
5. **İstisna testi:** Ancak 5. bölümdeki koşullardan biri karşılanıyorsa yeni dosya oluşturulur.

Bu denetim tamamlanmadan dosya oluşturulamaz.

## 4. Sohbetlerin tek dosya ilkesi

- Bir sohbetin mevcut bir Markdown kayıt dosyası varsa yeni karar, tavsiye, telkin, bilgi, uyarı, talep, yanıt ve teyitler öncelikle o dosyaya eklenir.
- Aynı sohbet için günlük, görevlik veya mesajlık yeni Markdown dosyaları açılmaz.
- Sohbetler arası aktarım; gönderen, alıcı, tür, tarih, durum ve varsa `correlation_id` alanlarıyla gönderen sohbetin mevcut dosyasındaki **Aktarımlar** bölümüne yazılabilir.
- Alıcının cevabı yeni dosya değildir; ilgili kaydın altına veya alıcının mevcut dosyasına bağlantılı bir kayıt olarak eklenir.
- Sohbetin henüz uygun dosyası yoksa önce kalıcılık değerlendirilir. Kalıcı kayıt zorunlu değilse dosya açılmaz. Zorunluysa o sohbet için bir kez ana kayıt dosyası oluşturulur ve sonraki kayıtlar orada biriktirilir.

Mevcut sohbet dosyaları korunur. Dosyalar sırf yeni ad standardına uydurmak için çoğaltılmaz.

## 5. Yeni dosya açılabilecek durumlar

Yeni dosya yalnızca aşağıdaki gerekçelerden en az biri varsa açılabilir:

1. Kullanıcı açıkça **ayrı bir dosya** istedi.
2. İçerik bağımsız bir yazılım bileşeni, kaynak kodu, veritabanı geçişi, test, sözleşme veya teslim edilebilir ürün niteliğinde.
3. İçeriğin farklı sahibi, erişim yetkisi, onay süreci veya saklama süresi var.
4. Güvenlik, denetim veya değişmez kayıt gereksinimi mevcut dosyadan ayrılmasını zorunlu kılıyor.
5. Uygun mevcut dosya yok ve bilginin kalıcı tutulmaması proje için açık bir kayıp veya risk doğuruyor.
6. Mevcut dosyaya eklemek belgenin amacını belirgin biçimde bozacak veya kullanılmasını güçleştirecek.

Yeni Markdown dosyasında kısa bir `creation_reason` alanı bulunur ve yukarıdaki gerekçelerden hangisinin uygulandığı belirtilir. “Düzenli görünmesi” veya “ileride lazım olabilir” tek başına yeterli gerekçe değildir.

## 6. Yeni dosya oluşturulmayacak durumlar

Şunlar için ayrı Markdown dosyası açılmaz:

- Okundu, tamamlandı, kabul edildi gibi kısa durum bildirimleri
- Aynı kararın özeti, yeniden anlatımı veya küçük revizyonu
- Tek seferlik sohbet cevabı ve geçici çalışma notu
- Mevcut README, karar, mimari, veritabanı veya operasyon belgesine sığan bilgi
- Aynı içeriğin Drive, lokal ve GitHub içinde farklı adlarla çoğaltılması
- Kullanılacağı doğrulanmamış şablonlar
- Yalnızca sohbetler arası aktarım yapıldığını göstermek amacıyla açılan olay dosyaları

## 7. Konumlandırma

Kod ve kodla birlikte sürümlenecek teknik içerik yerel Git deposunda hazırlanır ve GitHub’a gönderilir:

`/Users/scm/Projects/trading-os`

Drive yalnız kullanıcı talimatıyla çalışan iletişim, karar ve paylaşım katmanıdır. Git
çalışma ağacı, `.git`, `.env`, veritabanları, derleme çıktıları ve ham çalışma verileri
Drive ağacında tutulmaz. Drive `03_KARARLAR`, karar ve yönetim belgelerinin bulut
sohbetlerce erişilen görünümüdür.

| İçerik | Birincil konum |
|---|---|
| Kaynak kodu ve test | Git deposu |
| Veritabanı şeması/geçişi | Git deposu `schemas/` ve `migrations/` |
| Teknik ana belgeler | Git deposu `docs/` |
| Merkezi sistem kuralları | Drive `03_KARARLAR/00_SISTEM_KURALLARI` ve GitHub karşılığı |
| Sohbetin yaşayan kaydı | Drive `01_SOHBET_KARARLARI` ve gerekiyorsa GitHub karşılığı |
| Büyük ek/başvuru belgesi | Drive `03_BAGLI_BELGELER` |
| Yerel sırlar, çalışma DB'si ve ham veri | Lokal; Git ve Drive dışında |

## 8. Adlandırma ve sürümleme

- Mevcut dosyanın adı korunur; her değişiklikte yeni sürüm dosyası açılmaz.
- Güncelleme geçmişi aynı dosyanın içindeki **Değişiklik Geçmişi** bölümünde ve Git geçmişinde tutulur.
- Dosya adı açık, kısa ve tek anlamlı olur.
- Taslak kopyalar, `final-final`, `new`, `copy` gibi adlar ve aynı içeriğin numaralı kopyaları oluşturulmaz.
- Geçersizleşen dosya silinmez; gerekiyorsa `90_ARSIV` altına taşınır ve yerine geçen belge belirtilir.

## 9. Senkronizasyon kuralı

- Aynı belgenin Drive ve GitHub kopyası varsa içerikleri eş tutulur.
- Yerel Git deposu ile GitHub arasındaki teknik geçmişi Git yönetir.
- Drive senkronizasyonu tamamlanmadan aynı dosya başka cihazda değiştirilmez.
- Çakışmada en yeni dosya körlemesine seçilmez; değişiklikler karşılaştırılıp birleştirilir.
- Sırlar, parolalar, API anahtarları ve kişisel veriler Markdown belgelerine veya Git'e yazılmaz.

## 10. Dosya yöneticisinin görevi

`docs-manager` sohbeti:

- Yeni dosya taleplerinde bu anayasayı uygular.
- Uygun mevcut dosyayı ve doğru klasörü belirler.
- Gereksiz kopyaları, adlandırma sapmalarını ve senkronizasyon çakışmalarını önler.
- Yeni sohbetlere kimlik verir ve mevcut ana kayıt dosyalarını gösterir.
- Açık kullanıcı talimatı olmadan periyodik kontrol yapmaz.
- `AGENTS.md`, bu anayasa, sohbet sicili, merkezi fihrist ve bunların Drive
  karşılıklarında tek yazardır. Çok ajanlı çalışmada ana ajan `docs-manager` rolünü
  üstlenir ve bu değişiklikleri seri uygular.

Diğer sohbetler dosya konumundan emin değilse yeni dosya açmak yerine `docs-manager` için mevcut sohbet kaydına yönlendirme notu bırakır veya kullanıcıdan dosya yöneticisine talimat vermesini ister.

Alt ajanlar merkezi belgelere veya yaşayan sohbet dosyalarına doğrudan yazmaz. Bulguyu
ana ajana yapılandırılmış mesajla teslim eder. Ana ajan kanıtı doğruladıktan sonra
gerekliyse mevcut belgeyi günceller. Böylece aynı sicil numarasının ayrılması veya aynı
dosyanın eşzamanlı düzenlenmesi engellenir.

## 11. Markdown Sicili ve Fihrist Protokolü

Bu anayasa aynı zamanda Trading OS içindeki insanlar veya sohbetler tarafından yönetilen Markdown belgelerinin merkezi fihristidir. Yeni bir Markdown dosyası oluşturma ve aşağıdaki fihriste kaydetme işlemleri birbirinden ayrılamaz.

### 11.1. Zorunlu kayıt alanları

Her yeni Markdown belgesi için fihriste şu bilgiler işlenir:

- `registry_id`: Değişmez `MD-NNN` kimliği
- `document`: Dosya adı veya kısa belge adı
- `canonical_location`: Belgenin esas konumu; Drive, GitHub veya ikisi
- `owner_chat`: Belgenin bakımından sorumlu sohbet
- `consumer_chats`: Belgeyi kullanacak sohbetler
- `purpose`: Belgenin tek cümlelik amacı
- `creation_reason`: Neden mevcut bir dosyanın yeterli olmadığı
- `protocol_or_scope`: Hangi iş, protokol veya bileşen için kullanılacağı
- `lifecycle`: `proposed`, `active`, `reference`, `superseded`, `archived` veya `generated`
- `availability`: `branch-only`, `main`, `drive-only`, `drive+main` veya `external-sync`
- `git_ref` ve `commit_sha`: Git belgesinin doğrulandığı dal ve içerik commit'i; Git
  karşılığı yoksa `not-applicable`
- `created_at` ve `last_updated`: Tarih bilgileri
- `replaces_or_related`: Yerine geçtiği veya ilişkili olduğu belgeler

`active` yaşam döngüsü yalnız kanonik konumu gerçekten mevcut ve doğrulanmış belgeye
verilir. Yalnız iş dalında bulunan belge `proposed` + `branch-only` olarak kaydedilir.
Anayasa öncesi belgelerde bilinmeyen geçmiş alanları tahmin edilmez; `legacy-unknown`
olarak gösterilir.

### 11.2. Kayıt işlemi

Yeni bir Markdown dosyası oluşturacak sohbet:

1. Bu anayasayı ve fihristi okur.
2. Aynı amaca hizmet eden mevcut dosyayı ad, amaç, sohbet ve protokol alanlarında arar.
3. Mevcut dosya yeterliyse onu günceller ve yeni dosya oluşturmaz.
4. Yeni dosya istisnası oluşmuşsa `docs-manager`dan sıradaki `MD-NNN` kimliğini ister;
   kimliği yalnız `docs-manager` ayırır.
5. Dosyada `creation_reason`, sahibi, kullanıcıları ve amacı belirtir.
6. Dosyayı oluşturduğu işlem içinde fihriste yeni satır ekler.
7. Drive ve GitHub karşılıkları gerekiyorsa ikisini birlikte günceller.
8. Dosyanın ve fihrist kaydının erişilebilir olduğunu doğrular.

Fihrist güncellenemiyorsa zorunlu olmayan yeni Markdown dosyası oluşturulmaz. Zorunlu teknik üretimde dosya oluşturulabilir ancak aynı görev tamamlanmadan fihrist kaydı da tamamlanır. Sıradaki sicil numarası metinde sabitlenmez; mevcut en yüksek doğrulanmış `MD-NNN` değerinden seri biçimde hesaplanır.

### 11.3. Sonraki işlemler

- Mevcut belge güncellendiğinde yeni fihrist satırı açılmaz; kapsam, kullanıcı veya durum değişmişse mevcut satır güncellenir.
- Dosya taşınır veya yeniden adlandırılırsa `canonical_location` aynı işlemde değiştirilir.
- Dosya arşivlenir veya başka belge tarafından geçersiz kılınırsa durumu ve yerine geçen belge yazılır.
- Fihristte olmayan yönetilen bir Markdown dosyası tespit edilirse yeni kopya açılmaz; mevcut dosya fihriste eklenir.
- Açık kullanıcı talimatı olmadan periyodik fihrist taraması yapılmaz.

### 11.4. Kapsam dışı dosyalar

`.git`, `target`, `build`, `dist`, `node_modules`, `vendor`, önbellek ve benzeri klasörlerde araçlar veya bağımlılıklar tarafından otomatik üretilen Markdown dosyaları fihriste alınmaz. Salt okunur ve otomatik eşitlenen `sources/` içeriği tek tek yönetilmez; kaynak grubu olarak gösterilebilir.

## 12. Merkezi Markdown Fihristi

| Sicil | Belge | Kanonik konum | Sahip / kullananlar | Amaç / kapsam | Oluşturma gerekçesi | Yaşam / erişim | Git kanıtı | Tarih | İlişki |
|---|---|---|---|---|---|---|---|---|---|
| MD-001 | `BASLANGIC-BURADAN.md` | Drive `00_KONTROL_MERKEZI/` | docs-manager / all-chats | Projeye giriş | legacy/pre-constitution | active / drive-only | not-applicable | legacy-unknown / 2026-08-03 | MD-017, MD-021 |
| MD-002 | `README.md` | Git kökü | codex-dev / all-chats | Yazılım başlangıcı | legacy/pre-constitution | active / main | `main@983712d` | legacy-unknown / 2026-08-03 | MD-020 |
| MD-003 | `AGENTS.md` | Git kökü | docs-manager / all-chats | Bağlayıcı ajan talimatı | legacy/pre-constitution | active / main | `main@983712d` | legacy-unknown / 2026-08-03 | MD-007, MD-008 |
| MD-004 | `TOS-DEC-001__bot-calisma-sistemi-ve-karlilik-disiplini__v0.1.md` | Drive `00_SISTEM_KURALLARI/` | cloud-planner / cloud-planner,codex-dev | Bot ve kârlılık kararı | legacy/pre-constitution | active / drive-only | not-applicable | legacy-unknown / 2026-08-03 | MD-025 |
| MD-005 | `TOS-DEC-002__bulut-chatgpt-codex-kodlama-is-akisi__v1.0.md` | Drive + `docs/decisions/` | docs-manager / cloud-planner,codex-dev | Bulut–Codex akışı | legacy/pre-constitution | active / drive+main | `main@983712d` | legacy-unknown / 2026-08-03 | MD-017, MD-020 |
| MD-006 | `TOS-DEC-003__sohbet-karar-ve-iletisim-kayit-sistemi__v1.0.md` | Drive + `docs/decisions/system/` | docs-manager / all-chats | Tarihsel iletişim modeli | legacy/pre-constitution | reference / drive+main | `main@983712d` | legacy-unknown / 2026-08-03 | superseded-in-part by MD-007 |
| MD-007 | `TOS-DEC-004__merkezi-dosya-yonetim-anayasasi__v1.0.md` | Drive + `docs/decisions/system/` | docs-manager / all-chats | Dosya anayasası ve fihrist | Kullanıcı tarafından merkezi yönetişim istendi | active / drive+main | `main@983712d` | 2026-08-03 / 2026-08-03 | supersedes MD-006,011,012,013 |
| MD-008 | `TOS-CHAT-REGISTRY__v1.0.md` | Drive + `docs/decisions/system/` | docs-manager / all-chats | Rol ve sohbet sicili | Sohbetler arası izlenebilirlik | active / drive+main | `main@983712d` | 2026-08-03 / 2026-08-03 | MD-003, MD-007 |
| MD-009 | `TOS-CHATDEC-20260803-001__docs-manager__sohbet-iletisim-log-sistemi.md` | Drive + `docs/decisions/chats/` | docs-manager / docs-manager,all-chats | Yaşayan docs-manager kaydı | legacy/pre-constitution | active / drive+main | `main@983712d` | 2026-08-03 / 2026-08-03 | MD-006, MD-007 |
| MD-010 | `TOS-CHATDEC-20260803-002__codex-dev__btcusdt-veri-katmani.md` | `docs/decisions/chats/` | codex-dev / codex-dev,cloud-planner | BTCUSDT yaşayan kararı | Bağımsız yazılım bileşeni kararı | active / main | `main@983712d` | 2026-08-03 / 2026-08-03 | MD-015, MD-024 |
| MD-011 | `TOS-XFER-20260803-001__docs-manager__all-chats__policy.md` | Drive + `docs/communication-log/` | docs-manager / all-chats | Tarihsel ilk aktarım | legacy/pre-constitution | reference / drive+main | `main@983712d` | 2026-08-03 / 2026-08-03 | superseded by MD-007 |
| MD-012 | `TOS-TPL-001__sohbet-karari-sablonu.md` | Drive + şablon klasörü | docs-manager / all-chats | Tarihsel karar şablonu | legacy/pre-constitution | reference / drive+main | `main@983712d` | 2026-08-03 / 2026-08-03 | MD-006, MD-007 |
| MD-013 | `TOS-TPL-002__sohbetler-arasi-aktarim-sablonu.md` | Drive + şablon klasörü | docs-manager / all-chats | Tarihsel aktarım şablonu | legacy/pre-constitution | reference / drive+main | `main@983712d` | 2026-08-03 / 2026-08-03 | MD-006, MD-007 |
| MD-014 | `architecture.md` | Drive `04_TEKNIK_TASARIM/` + `docs/` | codex-dev / cloud-planner,codex-dev | Sistem mimarisi | Bağımsız teknik ana belge | active / drive+main | `main@983712d` | legacy-unknown / 2026-08-03 | MD-015, MD-016 |
| MD-015 | `market-data.md` | `docs/architecture/` | codex-dev / cloud-planner,codex-dev | Piyasa verisi mimarisi | Bağımsız yazılım bileşeni | active / main | `main@983712d` | 2026-08-03 / 2026-08-03 | MD-010, MD-024 |
| MD-016 | `database.md` | Drive `04_TEKNIK_TASARIM/` + `docs/` | codex-dev / cloud-planner,codex-dev | Veritabanı tasarımı | Bağımsız teknik ana belge | active / drive+main | `main@983712d` | legacy-unknown / 2026-08-03 | MD-014, MD-020 |
| MD-017 | `communication-protocol.md` | Drive `04_TEKNIK_TASARIM/` + `docs/` | docs-manager / all-chats | Drive–Codex protokolü | Bağımsız iletişim sözleşmesi | active / drive+main | `main@983712d` | legacy-unknown / 2026-08-03 | MD-005, MD-020 |
| MD-018 | `operations.md` | Drive `04_TEKNIK_TASARIM/` + `docs/` | codex-dev / docs-manager,codex-dev | İşletim kuralları | Bağımsız operasyon belgesi | active / drive+main | `main@983712d` | legacy-unknown / 2026-08-03 | MD-002, MD-020 |
| MD-019 | `talimatla-calisan-drive-codex-koprusu.md` | Drive `04_TEKNIK_TASARIM/` | docs-manager / cloud-planner,codex-dev | Talimatlı köprü açıklaması | Bulut sohbet erişimi | active / drive-only | not-applicable | legacy-unknown / 2026-08-03 | MD-017, MD-020 |
| MD-020 | `automation-runbook.md` | `docs/` | codex-dev / docs-manager,codex-dev | Köprü işletim rehberi | Bağımsız operasyon akışı | active / main | `main@983712d` | legacy-unknown / 2026-08-03 | MD-017, MD-018 |
| MD-021 | `cloud-control.md` | `docs/` | codex-dev / cloud-planner,codex-dev | Bulut kontrol kartı | Bulut sohbet çalışma kartı | active / main | `main@983712d` | legacy-unknown / 2026-08-03 | MD-001, MD-017 |
| MD-022 | `security.md` | `docs/` | codex-dev / all-chats | Güvenlik politikası | Ayrı güvenlik sorumluluğu | active / main | `main@983712d` | legacy-unknown / 2026-08-03 | MD-003, MD-020 |
| MD-023 | `CURRENT.md` | `docs/status/` | codex-dev / all-chats | Tekil güncel durum | Yaşayan durum kaydı | active / main | `main@983712d` | 2026-08-03 / 2026-08-03 | MD-024 |
| MD-024 | `2026-08-03-btcusdt-data-integrity.md` | `docs/reports/` | codex-dev / cloud-planner,codex-dev | BTCUSDT bütünlük kanıtı | Bağımsız doğrulama raporu | active / main | `main@983712d` | 2026-08-03 / 2026-08-03 | MD-010, MD-015, MD-023 |
| MD-025 | `sources/` Markdown grubu | `sources/` | external-sync / all-chats | Salt okunur kaynak aynası | Dış sistem eşitlemesi | reference / external-sync | `main@983712d` | legacy-unknown / 2026-08-03 | MD-004 |

Yeni sicil kimliği, fihristteki en yüksek doğrulanmış sayının bir fazlasıdır; metinde sabit bir “sıradaki numara” tutulmaz. Bir satırın fihriste eklenmesi belgenin içeriğinin doğruluğunu onaylamaz; yalnız varlığını, amacını, yaşam döngüsünü ve sorumluluğunu kayıt altına alır.

## 13. Mühür ve değişiklik usulü

Bu anayasa `status: sealed` durumundadır. Bağlayıcıdır ve sessizce değiştirilemez.

Değişiklik için:

1. Kullanıcı açıkça anayasa değişikliği ister.
2. Değişiklik aynı dosyada yapılır; sırf yeni sürüm için ayrı Markdown dosyası açılmaz.
3. Aşağıdaki geçmişe tarih, sürüm ve kısa gerekçe eklenir.
4. Drive ve GitHub kopyaları birlikte güncellenir.

## 14. Değişiklik geçmişi

| Tarih | Sürüm | Değişiklik | Onay |
|---|---:|---|---|
| 2026-08-03 | 1.2 | Kod deposu lokal alana taşındı; Drive seçici belge/iletişim katmanı yapıldı; docs-manager tek-yazıcı, çok-ajan sınırı ve doğrulanabilir fihrist yaşam döngüsü mühürlendi. | Kullanıcı talimatı |
| 2026-08-03 | 1.1 | Markdown Sicili ve Fihrist Protokolü eklendi; mevcut yönetilen belgeler MD-001–MD-025 olarak kaydedildi. | Kullanıcı talimatı |
| 2026-08-03 | 1.0 | İlk anayasa; mevcut dosyayı kullanma ve gerekçesiz yeni dosya yasağı mühürlendi. | Kullanıcı talimatı |

---

**Mühür:** Trading OS dosya yönetiminde sadelik, tekillik, izlenebilirlik ve gereklilik esastır. Yeni dosya son çaredir; oluşturulan her yönetilen Markdown belgesi merkezi fihriste kayıtlıdır.
