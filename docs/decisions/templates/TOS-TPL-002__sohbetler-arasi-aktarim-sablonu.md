---
template_status: deprecated
deprecated_by: TOS-DEC-004
id: TOS-XFER-YYYYMMDD-NNN
record_type: advice
created_at: YYYY-MM-DDTHH:MM:SSZ
sender_chat: gonderen-chat-key
recipient_chats:
  - alici-chat-key
subject: Kısa aktarım konusu
status: sent
correlation_id: null
decision_refs: []
document_refs: []
requires_action: true
---

> **Kullanımdan kaldırıldı:** Rutin aktarım ve teyitler JSON zarfı ile yerel
> iletişim günlüğüne yazılır; yeni Markdown açılmaz. Bu şablon yalnız
> TOS-DEC-004'teki ayrı belge istisnası sağlanır ve merkezi fihrist aynı işlemde
> güncellenirse `docs-manager` gözetiminde kullanılabilir.

# Aktarım özeti

Alıcının bilmesi gereken kısa bilgi.

## Gerekçe ve kanıt

Bu aktarımın dayanağı.

## Beklenen eylem

Alıcıdan istenen somut işlem veya değerlendirme.

## Kabul ölçütü

Aktarımın tamamlandığını gösterecek sonuç.
