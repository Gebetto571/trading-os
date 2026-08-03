# Talimatla çalışan bulut sohbet–Codex devri

## Çalışma biçimi

Codex yalnız kullanıcı “Trading OS gelen kutusunu kontrol et” dediğinde veya açık
bir GitHub görev/commit/PR bağlantısı verdiğinde işi kontrol eder. Drive'ın güncel
`Trading OS` alanı AI hafızası ve görev–sonuç koordinasyonudur; kod deposu değildir.
Arka planda zamanlanmış, periyodik veya tüm Drive'ı tarayan kontrol yapılmaz.

1. ChatGPT, kullanıcı talimatıyla JSON görev zarfını Drive `01_CHATGPT_GELEN`
   klasörüne yazar ve geri okuyarak doğrular.
2. Kullanıcı Codex'e kontrol emri verir; Drive bağlayıcısı veya elle alınan zarf
   yerel `var/inbox/` alanına konur. Yerel köprü Drive'ı kendiliğinden taramaz.
3. Yerel JSON zarfında şema sürümü, UUID, zaman, gönderici, alıcı, tür, dosya yolu ve varsa artefakt
   SHA-256 değerleri doğrulanır. Geçersiz veya aynı UUID ile farklı içerik taşıyan
   zarf işlenmez; `quarantine` alanına ve denetim kaydına alınır.
4. Aynı UUID ve aynı özet daha önce kaydedilmişse güvenli tekrar sayılır; görev
   ikinci kez çalıştırılmaz.
5. Geçerli yeni mesaj `received` olur. Bir uygulayıcı `claim` ile süreli sahiplik
   almadan mesaj `processing` durumuna geçemez.
6. Sahiplik; ajan kimliği, alınma ve sona erme zamanı, deneme sayısı ile tutulur.
   Süresi dolmuş veya yarım kalmış sahiplik ancak kullanıcı talimatlı `recover`
   işlemiyle yeniden kullanılabilir hâle gelir.
7. Güvenli ve yetkili görev gerçekleştirilir; kod değişikliği varsa test edilir
   ve proje Git politikasına göre kaydedilir.
   Son durum yalnız claim sahibi ve süresi geçmemiş lease ile yazılabilir.
8. Sonuç aynı `correlation_id` ile Drive `02_CODEX_GELEN` klasörüne yazılır ve
   geri okunur; commit/PR bağlantısı ve doğrulama özeti kullanıcıya teslim edilir.
   Sonuç geri okunmadan Drive görevi tamamlanmış sayılmaz.
9. Doğrulanıp SQLite'a alınan özgün zarf tekrar çalıştırılmaması için yerel ham
   arşive taşınır; işin `received`, `processing`, `completed` veya `failed` durumu
   veritabanında izlenir. Hatalı zarf karantinada kanıt olarak korunur.

## Otomatik yürütme sınırı

Şunlar otomatik yapılabilir:

- Proje dosyalarını okumak, düzenlemek ve test etmek
- Yeni dal, commit ve taslak pull request hazırlamak
- Teknik belge, rapor ve analiz üretmek
- Yerel depoda protokole uygun mesaj ve proje belgesi güncellemek

Şunlar açık kullanıcı onayı olmadan yapılmaz:

- Canlı alım-satım emri, para veya kripto varlık transferi
- Risk limiti yükseltme veya canlı moda geçme
- Sır, token, özel anahtar ya da kişisel veri paylaşma
- Kalıcı silme, genel erişim açma veya yeni ücretli hizmet başlatma
- Proje kapsamı dışında kişi ya da sistemlere mesaj gönderme

Bu durumlarda Codex görevi uygulamak yerine `status` türünde `approval_required` yanıtı üretir.

## Çalıştırma

- Ana talimat: `Trading OS gelen kutusunu kontrol et.`
- Alternatif talimat: `Şu GitHub görevini/PR'ını incele: <bağlantı>.`
- İstenirse tek mesaj UUID'si belirtilerek yalnız o mesaj işlenebilir.
- Yeni mesaj yoksa Codex bunu kısa biçimde bildirir.
- Başarısız çalışma kullanıcıya gerekçesiyle bildirilir.
- Yerel veritabanı: `var/trading_os.db`

## Komut eşlemesi

```text
claim      Sıradaki alınmış mesaj için süreli işlem sahipliği alır
status     Claim sahibinin mesajı completed veya failed olarak kapatmasını sağlar
recover    Belirtilen veya süresi dolmuş sahipliği kullanıcı talimatıyla kurtarır
check      Belirtilen UUID'nin yerel kaydını salt okunur gösterir
```

Mevcut `send`, `ingest`, `list` ve `status` komutları yerel zarf üretme, içe alma
ve inceleme için korunur. Hiçbiri arka planda periyodik kaynak veya GitHub
taraması başlatmaz.

## Yerel arşiv ve karantina sınırı

- Doğrulanıp yerel kayda alınan özgün zarflar `var/archive/` altında tutulur;
  işlem durumu SQLite'ta izlenir.
- Karantina, arşiv değildir. Şema/bütünlük sorunu çözülmeden dosya tamamlanmış
  kabul edilmez ve ikinci kez çalıştırılmaz. Karantina olayı ve ham dosya özeti
  SQLite denetim kaydında tutulur.
