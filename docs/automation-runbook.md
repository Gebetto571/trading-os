# Talimatla çalışan bulut sohbet–Codex devri

## Çalışma biçimi

Codex yalnız kullanıcı “Kodlama emrini işleme koy”, “Trading OS gelen kutusunu
kontrol et” dediğinde veya açık bir GitHub görev/commit/PR bağlantısı verdiğinde
işi kontrol eder. Yazılım gerçeği `/Users/scm/Projects/trading-os` yerel Git
deposudur. Güncel Drive `Trading OS` alanı AI hafızası ve görev–sonuç koordinasyon
katmanıdır; eski Drive kod deposu yolları geçersizdir. Katman sahipliği TOS-DEC-004
bölüm 7'ye tabidir. Arka planda zamanlanmış veya periyodik kontrol yapılmaz.

1. ChatGPT, kullanıcı talimatıyla onaylı JSON görev zarfını Drive
   `01_CHATGPT_GELEN` klasörüne yazar ve geri okur; GitHub bağlantısı teknik
   referans olarak eklenebilir.
2. Kullanıcı Codex'e işleme emri verir. Drive bağlayıcısıyla veya elle alınan zarf
   yerel gelen kutusuna konur; yerel köprü Drive'ı izlemez, taramaz veya eşitlemez.
3. Yerel JSON zarfında şema sürümü, UUID, zaman, gönderici, alıcı, tür, dosya yolu ve varsa artefakt
   SHA-256 değerleri doğrulanır. Geçersiz veya aynı UUID ile farklı içerik taşıyan
   zarf işlenmez; `quarantine` alanına ve denetim kaydına alınır.
4. Aynı UUID ve aynı özet daha önce kaydedilmişse güvenli tekrar sayılır; görev
   ikinci kez çalıştırılmaz.
5. Geçerli yeni mesaj `received` olur. Genel mesaj bir uygulayıcı `claim` ile;
   proje değiştiren onaylı görev ise yalnız `claim-task` ve `chief-engineer`
   aktif yazarıyla süreli sahiplik almadan `processing` durumuna geçemez.
6. Sahiplik; ajan kimliği, alınma ve sona erme zamanı, deneme sayısı ile tutulur.
   Süresi dolmuş veya yarım kalmış sahiplik ancak kullanıcı talimatlı `recover`
   işlemiyle yeniden kullanılabilir hâle gelir.
7. Güvenli ve yetkili görev, sahip olunan repository-göreli yollar içinde
   gerçekleştirilir; kod değişikliği varsa test edilir. Aktif başka görevin yolu
   üst/alt klasör olarak örtüşüyorsa ikinci görev başlamaz.
   Son durum yalnız claim sahibi ve süresi geçmemiş lease ile yazılabilir.
8. Sonuç aynı etkin `correlation_id` ile Drive `02_CODEX_GELEN` klasörüne ve mevcut
   yerel işlem kaydına yazılır; geri okunur ve görev bağlantısı doğrulanır.
9. Sonuç geri okunmadan Drive görevi tamamlanmış sayılmaz. Doğrulanmış özgün zarf
   mevcut arşiv alanına alınabilir; `received`, `processing`, `completed`, `failed`
   veya mevcut eşdeğer durum korunur. Hatalı zarf karantinada kanıt olarak tutulur.

## Otomatik yürütme sınırı

Şunlar otomatik yapılabilir:

- Proje dosyalarını okumak, düzenlemek ve test etmek
- Teknik belge, rapor ve analiz üretmek
- Yerel depoda protokole uygun mesaj ve proje belgesi güncellemek

Şunlar açık kullanıcı onayı olmadan yapılmaz:

- Canlı alım-satım emri, para veya kripto varlık transferi
- Risk limiti yükseltme veya canlı moda geçme
- Sır, token, özel anahtar ya da kişisel veri paylaşma
- Kalıcı silme, genel erişim açma veya yeni ücretli hizmet başlatma
- Proje kapsamı dışında kişi ya da sistemlere mesaj gönderme
- Commit, push, merge, pull request veya deployment

Bu durumlarda Codex görevi uygulamak yerine `status` türünde `approval_required` yanıtı üretir.

## Çalıştırma

- Ana talimat: `Kodlama emrini işleme koy.`
- Salt okunur kontrol: `Trading OS gelen kutusunu kontrol et.`
- Alternatif talimat: `Şu GitHub görevini/PR'ını incele: <bağlantı>.`
- İstenirse tek mesaj UUID'si belirtilerek yalnız o mesaj işlenebilir.
- Yeni mesaj yoksa Codex bunu kısa biçimde bildirir.
- Başarısız çalışma kullanıcıya gerekçesiyle bildirilir.
- Yerel veritabanı: `var/trading_os.db`

## Komut eşlemesi

```text
claim      Sıradaki alınmış mesaj için süreli işlem sahipliği alır
claim-task Kayıtlı/onaylı Chief Engineer görevini hat, base commit ve yollarla alır
result     Doğrulama raporundan korelasyonlu ve yetki sınırları kapalı sonuç üretir
status     Claim sahibinin mesajı completed veya failed olarak kapatmasını sağlar
recover    Belirtilen veya süresi dolmuş sahipliği kullanıcı talimatıyla kurtarır
check      Belirtilen UUID'nin yerel kaydını salt okunur gösterir
```

Mevcut `send`, `ingest`, `list` ve `status` komutları yerel zarf üretme, içe alma
ve inceleme için korunur. `claim-task` yalnız `schemas/conversation-map.json`
üzerindeki `chief-engineer/00`–`chief-engineer/08` hatlarını ve onaylı görevleri
alır. Hiçbir komut arka planda periyodik Drive, proje kaynağı veya GitHub taraması
başlatmaz.

## Yerel arşiv ve karantina sınırı

- Doğrulanıp yerel kayda alınan özgün zarflar `var/archive/` altında tutulur;
  işlem durumu SQLite'ta izlenir.
- Karantina, arşiv değildir. Şema/bütünlük sorunu çözülmeden dosya tamamlanmış
  kabul edilmez ve ikinci kez çalıştırılmaz. Karantina olayı ve ham dosya özeti
  SQLite denetim kaydında tutulur.
