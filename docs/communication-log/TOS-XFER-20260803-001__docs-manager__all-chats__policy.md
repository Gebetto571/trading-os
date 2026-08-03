---
id: TOS-XFER-20260803-001
record_type: information
created_at: 2026-08-02T23:51:01Z
sender_chat: docs-manager
recipient_chats:
  - all-chats
subject: Yeni sohbet karar ve aktarım kayıt politikası
status: sent
correlation_id: TOS-CHATDEC-20260803-001
decision_refs:
  - TOS-DEC-003
document_refs:
  - TOS-CHAT-REGISTRY
requires_action: true
lifecycle: historical-reference
superseded_in_part_by: TOS-DEC-004
---

> **Tarihsel kayıt:** Bu duyurunun ayrı Markdown olay dosyası üretme talimatı
> yürürlükten kalkmıştır. Güncel dosya yönetimi TOS-DEC-004 ve merkezi fihriste
> tabidir.

# Aktarım özeti

Trading OS sohbetleri için dosya tabanlı karar ve iletişim günlüğü yürürlüğe girmiştir.

## Beklenen eylem

Her sohbet karar veya aktarım kaydederken sohbet kimlik defterini ve güncel
iletişim sözleşmesini kullanır; mevcut yaşayan kaydı günceller. Ayrı Markdown
yalnız TOS-DEC-004 istisnasında ve eşzamanlı fihrist kaydıyla oluşturulur.

## Tamamlanma

Alıcı sohbet okuma teyidini ilişkili JSON olayı/veritabanı durumu olarak üretir;
sırf teyit amacıyla yeni Markdown açmaz. Okuma teyidi uygulama teyidi sayılmaz.
