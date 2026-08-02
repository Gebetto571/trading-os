---
id: TOS-DEC-002
title: Bulut ChatGPT ile Codex Arasında Kodlama İş Akışı
status: accepted
version: 1.0
date: 2026-08-03
language: tr
scope:
  - project-memory
  - cloud-chat
  - codex
  - google-drive
  - github
  - coding-workflow
---

# Bulut ChatGPT ile Codex Arasında Kodlama İş Akışı

> Bu belge Trading OS için bağlayıcı çalışma kuralıdır. Amaç; fikir, analiz, kodlama ve belge yönetimini birbirine karıştırmadan hızlı ve izlenebilir bir akış kurmaktır.

## 1. Tek cümlelik karar

Bulut ChatGPT görevi analiz edip standart bir görev kartı olarak Drive'a bırakır; kullanıcı Codex kodlama sohbetine kontrol talimatı verdiğinde Codex görevi alır, kodlar, test eder, GitHub'a kaydeder ve sonucu Drive'a geri bırakır.

## 2. Tek gerçek kaynaklar

| Bilgi | Ana kaynak |
|---|---|
| Kabul edilmiş kararlar | Drive `03_KARARLAR` ve GitHub `docs/decisions/` |
| Kod ve teknik belge geçmişi | Private GitHub `Gebetto571/trading-os` |
| Sohbetler arası görev aktarımı | Drive `01_CHATGPT_GELEN` |
| Codex sonuç aktarımı | Drive `02_CODEX_GELEN` |
| Tamamlanmış mesajlar | Drive `90_ARSIV` |
| Geçici yerel çalışma durumu | Yerel SQLite ve çalışma alanı |

Drive klasör bağlantıları:

- Kararlar: https://drive.google.com/drive/folders/13DHSKG4ZUaPdK9OTT3jHEwK3oJ-oHnAt
- ChatGPT → Codex: https://drive.google.com/drive/folders/15Cam8bRRlplbVLp4W0uRahzQ2N22Oyp9
- Codex → ChatGPT: https://drive.google.com/drive/folders/1zzRg0QITT9Z7Z17fMMvEVc9qNp5_9ks6
- Arşiv: https://drive.google.com/drive/folders/1kkY1pDi9HM5y_GooskKG8qDwlZcfmHy8
- GitHub: https://github.com/Gebetto571/trading-os

## 3. Sohbetlerin görevleri

### 3.1. Kullanıcı

- Nihai amacı ve önceliği belirler.
- Bulut sohbete görev hazırlama talimatı verir.
- Codex'e gelen kutusunu kontrol etme talimatı verir.
- Canlı işlem, para, sır, silme ve yeni dış yetki gerektiren işleri ayrıca onaylar.

### 3.2. Bulut ChatGPT planlama sohbeti

- Kabul edilmiş kararları okur.
- Kullanıcı talebini uygulanabilir kodlama görevine çevirir.
- Belirsizlik, kapsam ve kabul kriterlerini açıklar.
- Kod yazmaz ve GitHub'a doğrudan değişiklik göndermez.
- Protokole uygun JSON görev zarfını `01_CHATGPT_GELEN` klasörüne koyar.

### 3.3. Codex kodlama sohbeti

- Yalnız kullanıcı talimatıyla Drive gelen kutusunu kontrol eder.
- Görev UUID'sinin daha önce işlenmediğini doğrular.
- Kararlarla çelişki varsa kodlamadan önce bildirir.
- Kodu uygular, ilgili testleri çalıştırır ve sonucu doğrular.
- Değişiklikleri Git/GitHub'a kaydeder.
- Sonuç zarfını `02_CODEX_GELEN` klasörüne koyar.
- Tamamlanan giriş mesajını `90_ARSIV` klasörüne taşır.

### 3.4. Belge ve dosya yönetimi sohbeti

- Klasör tasnifi, adlandırma, sürümleme ve senkronizasyonu yönetir.
- Karar ve teknik belgelerin Drive–GitHub tutarlılığını kontrol eder.
- Kodlama görevini kendisi üstlenmez; görev kartını doğru kodlama sohbetine yönlendirir.

## 4. Kullanıcının uygulayacağı kısa akış

### Adım 1 — Bulut sohbete söyle

```text
Trading OS için şu talebimi kodlama görevine dönüştür: <TALEP>.
Kabul edilmiş kararları incele. Amaç, kapsam, kapsam dışı konular,
kabul kriterleri, testler ve ilgili kaynakları belirle.
Görevi protokole uygun JSON olarak Trading OS / 01_CHATGPT_GELEN
Drive klasörüne bırak. Sen kodlama yapma.
```

### Adım 2 — Codex kodlama sohbetine söyle

```text
Trading OS gelen kutusunu kontrol et. Yeni kodlama görevini doğrula,
uygula, test et ve private GitHub deposuna kaydet.
Sonucu Drive'daki Codex çıkış klasörüne bırak.
```

### Adım 3 — Sonucu bulut sohbete değerlendirt

```text
Trading OS / 02_CODEX_GELEN klasöründeki son Codex sonucunu incele.
Görevin kabul kriterlerini karşılayıp karşılamadığını değerlendir.
Eksik varsa yeni bir takip görev kartı oluştur; yeterliyse sonucu özetle.
```

## 5. Görev kartında bulunması gerekenler

- Benzersiz UUID ve oluşturulma zamanı
- Kısa konu başlığı
- Amaç ve beklenen kullanıcı sonucu
- Kapsam ve kapsam dışı maddeler
- İlgili karar/belge bağlantıları
- Kabul kriterleri
- Çalıştırılacak testler
- Güvenlik ve yetki sınırları
- Varsa önceki görevle ilişki kimliği

Eksik görev kartı doğrudan kodlanmaz; Codex açıklama veya düzeltme ister.

## 6. Tamamlanma tanımı

Bir kodlama görevi ancak aşağıdakilerin tamamında bitmiş sayılır:

1. İstenen davranış uygulanmıştır.
2. İlgili otomatik kontroller geçmiştir.
3. Kullanıcıya ait ilgisiz dosyalar korunmuştur.
4. Kod ve kalıcı belge GitHub'a kaydedilmiştir.
5. Sonuç zarfı Drive'a yüklenmiştir.
6. Giriş mesajı arşivlenmiştir.
7. Bilinen riskler ve yapılmayan işler açıkça yazılmıştır.

## 7. Güvenlik sınırı

Codex açık kullanıcı onayı olmadan:

- Canlı alım-satım emri veremez.
- Para veya kripto varlık transfer edemez.
- Risk limiti yükseltemez veya sistemi LIVE moda alamaz.
- API anahtarı, token, özel anahtar ya da kişisel veri paylaşamaz.
- Kalıcı dosya silemez veya depoyu herkese açamaz.
- Ücretli hizmet başlatamaz.

Bu tür bir istek geldiğinde işlem yapmak yerine `approval_required` durum mesajı üretilir.

## 8. İşletim kuralı

- Otomatik veya zamanlanmış Drive taraması yapılmaz.
- Kontrol yalnız kullanıcının açık talimatıyla başlar.
- Aynı UUID ikinci kez çalıştırılmaz.
- Sohbet metni karar kartını sessizce değiştiremez.
- Değişiklik gerekiyorsa gerekçeli yeni sürüm veya yeni karar kartı hazırlanır.

## 9. Pratik özet

```text
Fikri bulut sohbete anlat
→ görev kartını Drive'a bıraktır
→ Codex'e "gelen kutusunu kontrol et" de
→ Codex kodlasın, test etsin ve GitHub'a kaydetsin
→ sonucu Drive'dan bulut sohbete değerlendir
```

