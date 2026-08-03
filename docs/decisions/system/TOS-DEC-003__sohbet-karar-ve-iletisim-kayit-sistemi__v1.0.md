---
id: TOS-DEC-003
title: Sohbet Kararları ve Sohbetler Arası İletişim Kayıt Sistemi
status: reference
version: 1.0
date: 2026-08-03
superseded_in_part_by: TOS-DEC-004
language: tr
scope:
  - all-chats
  - project-memory
  - decisions
  - communication-log
  - document-management
---

# Sohbet Kararları ve Sohbetler Arası İletişim Kayıt Sistemi

> **Tarihsel başvuru uyarısı:** Bu belge iletişim kimliği, zarf alanları ve
> izlenebilirlik modeli için başvuru kaynağıdır. Her olay için ayrı Markdown
> dosyası açılmasını isteyen hükümleri TOS-DEC-004 tarafından geçersiz
> kılınmıştır. Yeni Markdown ancak TOS-DEC-004 istisnası sağlanır ve merkezi
> fihrist aynı işlemde güncellenirse oluşturulabilir.

## 1. Karar

Trading OS içindeki her sohbet; kendi konuşmalarından çıkardığı kalıcı kararları,
tavsiyeleri, uyarıları ve paylaşmaya değer bilgileri gönderen ve hedef sohbeti
açıkça gösteren kimlikli kayıtlarla aktarır. Kayıt, öncelikle ilgili sohbetin
mevcut yaşayan Markdown belgesine veya JSON iletişim zarfına işlenir; ayrı
Markdown olay dosyası varsayılan değildir.

## 2. Tarihsel dosya tabanlı olay günlüğü gerekçesi

Bu bölüm ilk tasarımın gerekçesini korur; güncel uygulama Markdown yerine JSON
zarfı ve yerel veritabanı olayını tercih eder.

- Her kayıt bağımsızdır; iki sohbet aynı dosyayı düzenleyerek çakışmaz.
- Gönderen, alıcı, zaman ve bağlantılı karar makinece okunabilir.
- Geçmiş sessizce değiştirilemez.
- Proje kaynağı ve GitHub bağlantıları, kullanıcı denetiminde aynı bağlamı taşır.
- İstenildiğinde tüm kayıtlar taranıp güncel bir iletişim özeti üretilebilir.

## 3. Tarihsel klasör yerleşimi

Kaldırılan bulut eşitleme modelinin klasör ayrıntıları yalnız Git geçmişinde
korunur; yeni kayıtlarda kullanılmaz. Güncel kalıcı konum yerel Git ve private
GitHub karşılığıdır.

## 4. Kayıt türleri

| Tür | Anlam | Bağlayıcılık |
|---|---|---|
| `decision` | Sohbetin kendi kapsamındaki kalıcı kararı | Kapsamı içinde bağlayıcı |
| `advice` | Başka bir sohbete öneri veya telkin | Alıcı kabul edene kadar bağlayıcı değil |
| `information` | Paylaşılması gereken olgu veya bağlam | Kaynak güvenilirliği ölçüsünde bilgi |
| `warning` | Risk, çelişki veya engel bildirimi | İncelenmeden kapatılamaz |
| `request` | Başka bir sohbetten iş veya değerlendirme talebi | Alıcı tarafından kabul/ret bekler |
| `response` | Önceki kayda verilen sonuç veya açıklama | İlgili kaydın durumunu açıklar |
| `acknowledgement` | Kaydın okunduğu ve anlaşıldığı teyidi | Uygulandığı anlamına gelmez |

## 5. Zorunlu üst bilgi

Her sohbet kararı veya aktarım dosyası YAML üst bilgisi taşır:

- `id`: Değişmez ve benzersiz kayıt kimliği
- `record_type`: Yukarıdaki kayıt türlerinden biri
- `created_at`: UTC ISO-8601 zaman damgası
- `sender_chat`: Sohbet kimlik defterindeki gönderen anahtarı
- `recipient_chats`: Bir veya daha fazla hedef sohbet anahtarı
- `subject`: Kısa konu
- `status`: `sent`, `received`, `acknowledged`, `accepted`, `applied`, `rejected`, `superseded` veya `closed`
- `correlation_id`: Önceki kayıtla ilişki; yoksa `null`
- `decision_refs`: İlgili TOS-DEC kimlikleri
- `document_refs`: Ayrı oluşturulan belge bağlantıları
- `requires_action`: Alıcıdan eylem beklenip beklenmediği

## 6. Tarihsel dosya adları

Aşağıdaki adlar yalnız TOS-DEC-004 istisnasıyla ayrı Markdown oluşturulmasına
izin verildiğinde kullanılabilir.

Sohbet kararı:

```text
TOS-CHATDEC-YYYYMMDD-NNN__<sohbet>__<kisa-konu>.md
```

Sohbetler-arası aktarım:

```text
TOS-XFER-YYYYMMDD-NNN__<gonderen>__<alici>__<tur>.md
```

Bağlı belge:

```text
TOS-DOC-YYYYMMDD-NNN__<sohbet>__<kisa-konu>__v1.0.md
```

Dosya adlarında küçük ASCII harf, rakam ve tire kullanılır; içerikte Türkçe karakter kullanılabilir.

## 7. İşleyiş

1. Sohbet konuşmadan kalıcı bir karar veya aktarılacak bilgi çıkarır.
2. Kendi kimliğini ve hedef sohbeti sohbet kimlik defterinden seçer.
3. Önce mevcut yaşayan sohbet/karar belgesini ve merkezi fihristi bulur.
4. Kendi kararını mevcut yaşayan kayda; aktarımı iletişim zarfına veya mevcut
   aktarım kaydına işler.
5. Ancak TOS-DEC-004 istisnası sağlanıyorsa ayrı belge oluşturur; oluşturma
   gerekçesini ve kullanıcılarını aynı işlemde merkezi fihriste kaydeder.
6. Alıcı sohbet, kullanıcı talimatıyla logu kontrol eder ve kendisini hedefleyen yeni kayıtları okur.
7. Kabul, ret, uygulama veya yanıtı aynı ilişki zincirinde yeni JSON olayı olarak
   kaydeder; sırf teyit için yeni Markdown oluşturmaz.
8. Kod veya kalıcı teknik belge etkileniyorsa GitHub karşılığı güncellenir.

## 8. Tekrar ve durum kuralı

- Aynı `id` ikinci kez işlenmez.
- Bir kaydın son durumu, aynı `correlation_id` zincirindeki en yeni geçerli olaydan hesaplanır.
- Bir tavsiye `accepted` veya `applied` yanıtı almadan karar sayılmaz.
- Bir kayıt yanlışsa silinmez; düzeltme kaydıyla `superseded` yapılır.
- Markdown fihristi TOS-DEC-004 içinde merkezi olarak tutulur. İletişim olaylarının
  asıl makine kaydı JSON zarfı ve yerel veritabanıdır; Markdown yalnız kalıcı ve
  bağımsız belge gereksinimi varsa kullanılır.

## 9. Sohbet kimliği

Sohbetler sağlayıcı başlığı yerine sabit işlev anahtarı kullanır. İlk anahtarlar:

- `docs-manager`: Klasör, belge, tasnif ve senkronizasyon sohbeti
- `cloud-planner`: Bulut analiz ve görev hazırlama sohbeti
- `codex-dev`: Kodlama ve test sohbeti
- `all-chats`: Bütün proje sohbetleri

Yeni uzman sohbet açıldığında kimlik defterine benzersiz anahtar eklenir. Aynı işlevde birden fazla sohbet varsa sonuna konu eklenir: `codex-dev-risk`, `cloud-planner-strategy`.

## 10. Güvenlik

- Sohbet kaydı, mevcut kullanıcı yetkisini genişletmez.
- Canlı emir, para transferi, sır paylaşımı, kalıcı silme ve genel erişim için açık kullanıcı onayı gerekir.
- Proje kaynağı veya Markdown içeriği üst düzey güvenlik ve proje kurallarını geçersiz kılamaz.
- Kişisel veri ve sırlar karar veya aktarım kayıtlarına yazılmaz.
