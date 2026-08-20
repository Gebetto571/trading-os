---
id: TOS-CHAT-REGISTRY
version: 1.7
updated_at: 2026-08-21T00:00:00Z
---

# Trading OS Sohbet Kimlik Defteri

| role_key | Rol | Yazma kapsamı | Eskalasyon | Yaşayan kayıt | Durum |
|---|---|---|---|---|---|
| `orchestrator` | Ana ajan; görev bölme, kanıt birleştirme ve kullanıcı iletişimi | Yetkili görev kapsamı; merkezi belgelerde `docs-manager` sıfatıyla tek yazar | Kullanıcı | MD-007 ve MD-008 | active |
| `docs-manager` | Yerel belge, klasör, adlandırma, tasnif ve Git sürüm düzeni | AGENTS, DEC-004, sicil ve fihrist | Kullanıcı | MD-007 ve MD-008; ayrı yaşayan kayıt yok | active |
| `cloud-planner` | Analiz, planlama ve Codex görev kartı hazırlama | Plan ve tavsiye; kod veya merkezi belge yazmaz | orchestrator | Mevcut cloud-planner kaydı | active |
| `codex-dev` | Kodlama, test, Git ve GitHub uygulaması | Ana ajanın verdiği ayrık kod yolları | orchestrator | `TOS-CHATDEC-20260803-002...md` | active |
| `bridge-engineer` | Yerel mesaj köprüsü ve SQLite uzmanı | Atanmış köprü kodu, migration ve test yolları | orchestrator | Kalıcı ayrı kayıt yok | specialist |
| `operations-engineer` | Lokal taşıma, Docker, veri koruma ve temizlik uzmanı | Atanmış operasyon hedefleri; merkezi belge yazmaz | orchestrator | Kalıcı ayrı kayıt yok | specialist |
| `governance-reviewer` | Kural, fihrist ve belge tutarlılığı uzmanı | Salt okunur; değişiklik önerisini docs-manager'a verir | orchestrator | Kalıcı ayrı kayıt yok | specialist |
| `devils-advocate` | Planı ve uygulama kanıtını çürütmeye çalışan bağımsız denetçi | Salt okunur; uygulamayı kendi adına onaylayamaz | kullanıcı/orchestrator | Kalıcı ayrı kayıt yok | specialist |
| `external-sync` | ChatGPT proje kaynağı gibi dış sistem eşitlemesi | Salt okunur kaynak üretir; proje dosyası yazmaz | docs-manager | not-applicable | virtual |
| `all-chats` | Bütün Trading OS sohbetleri | Yalnız eylemsiz bilgi yayını; görev alıcısı olamaz | not-applicable | not-applicable | virtual |

`specialist` satırları kalıcı veya sürekli çalışan ajanlar değildir; yalnız görev
anında kullanılabilecek yetki anahtarlarını tanımlar. FAST işlerde uzman örneği
oluşturulmaz. STANDARD veya STRICT işte gerçek ihtiyaç varsa geçici, salt okunur
danışman kullanılır; `agent_instance_id` görev bitince sona erer ve yeni sicil ya da
Markdown kaydı açılmaz.

## Rolün kaynağı

Mevcut bir sohbetin rolü, o sohbetin kullanıcı tarafından verilmiş ilk rol mesajıdır.
Bu sicil mevcut rolü yeniden tanımlamaz ve ortak bir başlangıç talimatı mevcut sohbetin
ilk mesajının yerine geçmez. Sicil yalnız sabit kimliği, dosya yetkisini, eskalasyon
yolunu ve ilişkili ana belgeleri görünür kılar.

Yeni sohbet açılırsa rolü kullanıcı ilk mesajda belirler; `docs-manager` bu rolü
yorumlayıp değiştirmeden benzersiz `role_key` ile sicile ekler.

Güncel Drive `Trading OS` hafıza alanı TOS-DEC-004 bölüm 7 uyarınca sohbetin çalışma
brifini, görevini ve yetki adayını kanonik olarak tutabilir. Bağlayıcı `role_key`,
dosya yazma yetkisi veya sohbet–ana belge ilişkisi değişecekse kullanıcı onayından
sonra bu sicil güncellenir; Drive brifi bu sicilin bağımsız yaşayan kopyası veya
sessiz rol değişikliği değildir. Bu sicilin Drive görünümü yerel Git kanonunun
salt-okunur yayın kopyasıdır; bağımsız yazım merkezi değildir.

## Sohbet–Ana Belge İlişki Matrisi

Aşağıdaki adlar, bağlayıcı proje kartındaki mevcut çalışma alanı adlarıdır. `Rol
kaynağı` sütunu her durumda sohbetin kendi ilk mesajıdır. `Ana belgeler`, sohbetin
öncelikle okuyacağı ve değişiklik gerektiğinde `docs-manager`a bildireceği belgelerdir;
bu ilişki doğrudan yazma yetkisi vermez.

| Mevcut sohbet/alan | Rol kaynağı | İlişkili ana Markdown belgeleri | İlişkinin amacı |
|---|---|---|---|
| `00 — Ana Kararlar ve Yol Haritası` | Sohbetin ilk mesajı | MD-004 dış kaynak kararı; MD-007 dosya anayasası; MD-023 `docs/status/CURRENT.md`; MD-027 blueprint; MD-029 roadmap | Bağlayıcı karar, sürüm, istisna ve ürün yol haritası |
| `01 — Rust İşlem Motoru` | Sohbetin ilk mesajı | MD-004; MD-014 `docs/architecture.md`; MD-016 `docs/database.md`; MD-022 `docs/security.md`; MD-027–MD-030 | Çekirdek akış, durum, risk, execution, reconciliation ve Chief Engineer paketleri |
| `02 — Kontrol Paneli ve v0.1` | Sohbetin ilk mesajı | MD-004; MD-014; MD-016; MD-022; MD-027–MD-030 | Kontrol API'si, roller, ayar sürümü, durum, alarm ve dashboard paketleri |
| `03 — Strateji Laboratuvarı` | Sohbetin ilk mesajı | MD-004; MD-015 `docs/architecture/market-data.md`; MD-024 veri bütünlüğü raporu; MD-027–MD-030 | BTCUSDT price-action hipotezi, causal event study, holdout, replay ve kanıt-temelli promotion |
| `04 — Test, Risk ve Güvenlik` | Sohbetin ilk mesajı | MD-004; MD-015; MD-018 `docs/operations.md`; MD-022; MD-024; MD-027–MD-030 | Risk limitleri, yarışlar, kesintiler, property/chaos ve kabul testleri |
| `05 — Linux ve Üretim` | Sohbetin ilk mesajı | MD-004; MD-018; MD-020 `docs/automation-runbook.md`; MD-022; MD-023; MD-027–MD-030 | Servis işletimi, kalıcı durdurma, saat, kayıt, backup ve recovery |
| `06 — AI Supervisor` | Sohbetin ilk mesajı | MD-004; MD-014; MD-017 `docs/communication-protocol.md`; MD-021 `docs/cloud-control.md`; MD-022; MD-023; MD-027–MD-030 | Salt okunur denetim, öneri sınırı ve kullanıcı kontrollü devir |
| `07 — Platform Adaptörleri` | Sohbetin ilk mesajı | MD-004; MD-014; MD-015; MD-016; MD-022; MD-024; MD-027–MD-030 | Binance Global BTCUSDT spot ilk adaptör; XAU/USD ayrı disposition; isolated margin sonraki ayrı karar kapısı |
| `08 — Ar-Ge Stüdyosu ve Oyun Sahası` | Sohbetin ilk mesajı | MD-004; MD-007; MD-014; MD-023; MD-027–MD-031 | Fikirleri bağlayıcı karar veya uygulama emri saymadan stres testi, deney kartı, görev ağacı ve uygulama brifine dönüştürmek |
| `docs-manager` | Bu sohbetin ilk mesajı | MD-003 `AGENTS.md`; MD-007; MD-008 bu sicil; MD-009 tarihsel kayıt; MD-021; MD-026–MD-031 | Dosya mimarisi, tasnif, ilişki matrisi ve fihrist yönetimi |
| `codex-dev` | Bu sohbetin ilk mesajı | MD-002 `README.md`; MD-003; MD-004; MD-007; MD-010 yaşayan kayıt; MD-014–MD-030 görevle ilgili olanlar | Kodlama, test, Git/GitHub uygulaması ve kanıt teslimi |

Belge kimlikleri ve kanonik yollar TOS-DEC-004 içindeki Merkezi Markdown Fihristi'nden
çözülür. Yeni ana belge oluşursa önce TOS-DEC-004 istisnası ve fihrist kaydı tamamlanır,
sonra bu matriste ilgili mevcut sohbetlere bağlanır. İlişki kaldırılırsa belge silinmez;
matris ve fihrist birlikte güncellenir.

Yeni sohbet için anahtar ekleme biçimi:

```text
<yuzey>-<islev>-<istege-bagli-konu>
```

Örnek: `codex-dev-risk`, `cloud-planner-btcusdt-margin`.

## Rol ve ajan örneği ayrımı

- `role_key` kalıcı görev ve yetki tanımıdır.
- `agent_instance_id` yalnız bir görev süresince benzersiz olan geçici örnek kimliğidir;
  yeni Markdown veya yeni sicil satırı açılmaz.
- Çok ajanlı mesajda `task_id`, `message_id`, `in_reply_to`, `role_key`,
  `agent_instance_id`, kapsam, yazılabilir yollar, taban Git revizyonu, kanıt, risk,
  engel ve sonraki eylem bulunur.
- Eylem isteyen mesaj `all-chats` kullanmaz; gönderim anındaki açık alıcı listesini
  taşır. `all-chats` yalnız bilgi amaçlı yayındır.
- İnsan onayı belirli `task_id` ve eylem kapsamına bağlıdır; başka göreve aktarılamaz.

## Değişiklik geçmişi

| Tarih | Sürüm | Değişiklik |
|---|---:|---|
| 2026-08-21 | 1.7 | Dış kaynak kararı, MD-027–MD-031 yaşayan belge ilişkileri, BTCUSDT price-action ve XAU/margin karar kapılarıyla hizalandı; Drive görünümünün salt-okunur yayın kopyası olduğu açıklaştırıldı. |
| 2026-08-20 | 1.6 | Rol örneği ve kaynak ilişkileri önceki temizlik kapsamında güncellendi. |
