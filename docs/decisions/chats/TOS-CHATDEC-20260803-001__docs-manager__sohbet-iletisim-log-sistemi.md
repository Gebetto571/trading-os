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
lifecycle: historical-reference
superseded_in_part_by: TOS-DEC-004
---

> **Tarihsel kayıt:** Bu karar, sistemin ilk olay-dosyası yaklaşımını gösterir.
> Her karar veya aktarım için ayrı Markdown açma hükmü artık uygulanmaz;
> TOS-DEC-004 ve merkezi fihrist esas alınır.

# Karar

Her Trading OS sohbeti, konuşmasından çıkardığı kalıcı kararları ve başka
sohbetlere aktaracağı tavsiye, telkin, bilgi veya uyarıları izlenebilir biçimde
kaydeder. Yeni Markdown açmak yerine mevcut yaşayan sohbet kaydı güncellenir;
ayrı dosya yalnız TOS-DEC-004 istisnasıyla oluşturulur.

## Beklenen uygulama

- Sohbet kendi kimlik anahtarını kullanır.
- Karar mevcut yaşayan Markdown kaydına, aktarım ise JSON zarfı/veritabanı olayına işlenir.
- Alıcı, özgün olayı değiştirmeden ilişkili JSON yanıt/teyit olayı üretir.
- Ayrı açıklama belgesi gerekiyorsa `document_refs` üzerinden bağlanır.
- Yeni yönetilen Markdown oluşursa merkezi fihrist aynı işlemde güncellenir.
