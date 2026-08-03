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
  - local-project-source
  - github
  - coding-workflow
---

# Bulut ChatGPT ile Codex Arasında Kodlama İş Akışı

> Bu belge Trading OS için bağlayıcı çalışma kuralıdır. Amaç; fikir, analiz, kodlama ve belge yönetimini birbirine karıştırmadan hızlı ve izlenebilir bir akış kurmaktır.

## 1. Tek cümlelik karar

Bulut ChatGPT görevi standart bir görev kartına dönüştürür; kullanıcı kartı proje
kaynağına ekleyerek veya GitHub bağlantısıyla Codex'e devreder. Codex yalnız açık
kullanıcı talimatıyla görevi alır, kodlar, test eder ve sonucu GitHub üzerinden
teslim eder.

## 2. Tek gerçek kaynaklar

| Bilgi | Ana kaynak |
|---|---|
| Kabul edilmiş kararlar | Yerel Git `docs/decisions/` ve public GitHub karşılığı |
| Kod ve teknik belge geçmişi | Public GitHub `Gebetto571/trading-os` |
| Sohbetler arası görev aktarımı | Kullanıcının eklediği proje kaynağı veya GitHub issue/commit/PR |
| Codex sonuç aktarımı | Commit/PR bağlantısı ve kullanıcıya verilen sonuç özeti |
| Tamamlanmış yerel mesajlar | `var/archive/` |
| Geçici yerel çalışma durumu | Yerel SQLite ve çalışma alanı |

GitHub: https://github.com/Gebetto571/trading-os

## 3. Sohbetlerin görevleri

### 3.1. Kullanıcı

- Nihai amacı ve önceliği belirler.
- Bulut sohbete görev hazırlama talimatı verir.
- Görev kartını proje kaynağına ekler veya GitHub bağlantısıyla Codex'e verir.
- Canlı işlem, para, sır, silme ve yeni dış yetki gerektiren işleri ayrıca onaylar.

### 3.2. Bulut ChatGPT planlama sohbeti

- Kabul edilmiş kararları okur.
- Kullanıcı talebini uygulanabilir kodlama görevine çevirir.
- Belirsizlik, kapsam ve kabul kriterlerini açıklar.
- Kod yazmaz ve GitHub'a doğrudan değişiklik göndermez.
- Protokole uygun görev kartını hazırlar; kendiliğinden dış sisteme göndermez.

### 3.3. Codex kodlama sohbeti

- Yalnız kullanıcı talimatıyla belirtilen proje kaynağını veya GitHub devrini kontrol eder.
- Görev UUID'sinin daha önce işlenmediğini doğrular.
- Kararlarla çelişki varsa kodlamadan önce bildirir.
- Kodu uygular, ilgili testleri çalıştırır ve sonucu doğrular.
- Değişiklikleri Git/GitHub'a kaydeder.
- Sonucu commit/PR bağlantısı ve doğrulama özetiyle kullanıcıya verir.
- Yerel zarf kullanıldıysa tamamlanan girişi `var/archive/` altına taşır.

### 3.4. Belge ve dosya yönetimi sohbeti

- Klasör tasnifi, adlandırma ve sürümlemeyi yönetir.
- Yerel Git ve GitHub tutarlılığını kontrol eder.
- Kodlama görevini kendisi üstlenmez; görev kartını doğru kodlama sohbetine yönlendirir.

## 4. Kullanıcının uygulayacağı kısa akış

### Adım 1 — Bulut sohbete söyle

```text
Trading OS için şu talebimi kodlama görevine dönüştür: <TALEP>.
Kabul edilmiş kararları incele. Amaç, kapsam, kapsam dışı konular,
kabul kriterleri, testler ve ilgili kaynakları belirle.
Görev kartını hazırla. Ben kartı ChatGPT proje kaynağına ekleyeceğim veya
GitHub görev bağlantısıyla Codex'e devredeceğim. Sen kodlama yapma.
```

### Adım 2 — Codex kodlama sohbetine söyle

```text
Trading OS proje kaynağındaki yeni kodlama görevini doğrula, uygula, test et
ve public GitHub deposuna kaydet. Sonucu commit/PR bağlantısı ve kısa doğrulama
özetiyle bana bildir.
```

### Adım 3 — Sonucu bulut sohbete değerlendirt

```text
Paylaştığım GitHub commit/PR bağlantısındaki son Codex sonucunu incele.
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
5. Sonuç commit/PR bağlantısıyla kullanıcıya teslim edilmiştir.
6. Yerel görev kaydı tamamlanmış ve gerekiyorsa arşivlenmiştir.
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

- Otomatik veya zamanlanmış proje kaynağı/GitHub taraması yapılmaz.
- Kontrol yalnız kullanıcının açık talimatıyla başlar.
- Aynı UUID ikinci kez çalıştırılmaz.
- Sohbet metni karar kartını sessizce değiştiremez.
- Değişiklik gerekiyorsa gerekçeli yeni sürüm veya yeni karar kartı hazırlanır.

## 9. Pratik özet

```text
Fikri bulut sohbete anlat
→ görev kartını hazırlat
→ kartı proje kaynağına ekle veya GitHub bağlantısıyla Codex'e ver
→ Codex'e açıkça görevi inceleyip uygulamasını söyle
→ Codex kodlasın, test etsin ve GitHub'a kaydetsin
→ commit/PR bağlantısını bulut sohbete değerlendirt
```
