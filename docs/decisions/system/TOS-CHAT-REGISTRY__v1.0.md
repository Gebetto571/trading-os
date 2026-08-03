---
id: TOS-CHAT-REGISTRY
version: 1.1
updated_at: 2026-08-03T04:30:00Z
---

# Trading OS Sohbet Kimlik Defteri

| role_key | Rol | Yazma kapsamı | Eskalasyon | Yaşayan kayıt | Durum |
|---|---|---|---|---|---|
| `orchestrator` | Ana ajan; görev bölme, kanıt birleştirme ve kullanıcı iletişimi | Yetkili görev kapsamı; merkezi belgelerde `docs-manager` sıfatıyla tek yazar | Kullanıcı | `docs-manager` kaydı | active |
| `docs-manager` | Drive, belge, klasör, adlandırma, tasnif ve senkronizasyon | AGENTS, DEC-004, sicil, fihrist ve bunların Drive karşılıkları | Kullanıcı | `TOS-CHATDEC-20260803-001...md` | active |
| `cloud-planner` | Analiz, planlama ve Codex görev kartı hazırlama | Plan ve tavsiye; kod veya merkezi belge yazmaz | orchestrator | Mevcut cloud-planner kaydı | active |
| `codex-dev` | Kodlama, test, Git ve GitHub uygulaması | Ana ajanın verdiği ayrık kod yolları | orchestrator | `TOS-CHATDEC-20260803-002...md` | active |
| `bridge-engineer` | Mesaj köprüsü, SQLite ve Drive adaptörü uzmanı | Atanmış köprü kodu, migration ve test yolları | orchestrator | Kalıcı ayrı kayıt yok | specialist |
| `operations-engineer` | Lokal taşıma, Docker, veri koruma ve temizlik uzmanı | Atanmış operasyon hedefleri; merkezi belge yazmaz | orchestrator | Kalıcı ayrı kayıt yok | specialist |
| `governance-reviewer` | Kural, fihrist ve belge tutarlılığı uzmanı | Salt okunur; değişiklik önerisini docs-manager'a verir | orchestrator | Kalıcı ayrı kayıt yok | specialist |
| `devils-advocate` | Planı ve uygulama kanıtını çürütmeye çalışan bağımsız denetçi | Salt okunur; uygulamayı kendi adına onaylayamaz | kullanıcı/orchestrator | Kalıcı ayrı kayıt yok | specialist |
| `external-sync` | ChatGPT proje kaynağı gibi dış sistem eşitlemesi | Salt okunur kaynak üretir; proje dosyası yazmaz | docs-manager | not-applicable | virtual |
| `all-chats` | Bütün Trading OS sohbetleri | Yalnız eylemsiz bilgi yayını; görev alıcısı olamaz | not-applicable | not-applicable | virtual |

Yeni sohbet için anahtar ekleme biçimi:

```text
<yuzey>-<islev>-<istege-bagli-konu>
```

Örnek: `codex-dev-risk`, `cloud-planner-polymarket`.

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
