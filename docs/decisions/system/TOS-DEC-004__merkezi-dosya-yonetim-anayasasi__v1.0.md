---
id: TOS-DEC-004
title: Merkezi Dosya Yönetim Anayasası
status: sealed
version: 1.0
date: 2026-08-03
authority: project-constitution
scope:
  - all-chats
  - drive
  - local-git
  - github
  - markdown-governance
supersedes_in_conflict:
  - TOS-DEC-003
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

`/Users/scm/Drive'ım/Trading OS/07_KOD/trading-os`

Drive `03_KARARLAR`, karar ve yönetim belgelerinin bulut sohbetlerce erişilen görünümüdür. Kod dosyaları `03_KARARLAR` altında tutulmaz.

| İçerik | Birincil konum |
|---|---|
| Kaynak kodu ve test | Git deposu |
| Veritabanı şeması/geçişi | Git deposu `schemas/` ve `migrations/` |
| Teknik ana belgeler | Git deposu `docs/` |
| Merkezi sistem kuralları | Drive `03_KARARLAR/00_SISTEM_KURALLARI` ve GitHub karşılığı |
| Sohbetin yaşayan kaydı | Drive `01_SOHBET_KARARLARI` ve gerekiyorsa GitHub karşılığı |
| Büyük ek/başvuru belgesi | Drive `03_BAGLI_BELGELER` |

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

Diğer sohbetler dosya konumundan emin değilse yeni dosya açmak yerine `docs-manager` için mevcut sohbet kaydına yönlendirme notu bırakır veya kullanıcıdan dosya yöneticisine talimat vermesini ister.

## 11. Mühür ve değişiklik usulü

Bu anayasa `status: sealed` durumundadır. Bağlayıcıdır ve sessizce değiştirilemez.

Değişiklik için:

1. Kullanıcı açıkça anayasa değişikliği ister.
2. Değişiklik aynı dosyada yapılır; sırf yeni sürüm için ayrı Markdown dosyası açılmaz.
3. Aşağıdaki geçmişe tarih, sürüm ve kısa gerekçe eklenir.
4. Drive ve GitHub kopyaları birlikte güncellenir.

## 12. Değişiklik geçmişi

| Tarih | Sürüm | Değişiklik | Onay |
|---|---:|---|---|
| 2026-08-03 | 1.0 | İlk anayasa; mevcut dosyayı kullanma ve gerekçesiz yeni dosya yasağı mühürlendi. | Kullanıcı talimatı |

---

**Mühür:** Trading OS dosya yönetiminde sadelik, tekillik, izlenebilirlik ve gereklilik esastır. Yeni dosya son çaredir.
