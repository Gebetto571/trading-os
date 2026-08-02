---
id: TOS-CHATDEC-20260803-001
record_type: decision
created_at: 2026-08-02T23:51:01Z
sender_chat: docs-manager
recipient_chats:
  - all-chats
subject: Sohbet kararları ve sohbetler arası aktarım günlüğü
status: accepted
correlation_id: null
decision_refs:
  - TOS-DEC-003
document_refs: []
requires_action: true
---

# Karar

Her Trading OS sohbeti, konuşmasından çıkardığı kalıcı kararları ve başka sohbetlere aktaracağı tavsiye, telkin, bilgi veya uyarıları TOS-DEC-003 biçiminde kaydeder.

## Beklenen uygulama

- Sohbet kendi kimlik anahtarını kullanır.
- Her karar veya aktarım ayrı Markdown dosyasıdır.
- Alıcı, özgün kaydı değiştirmeden yeni yanıt/teyit kaydı üretir.
- Ayrı açıklama belgesi gerekiyorsa `document_refs` üzerinden bağlanır.

