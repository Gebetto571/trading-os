# Talimatla çalışan bulut sohbet–Codex devri

## Çalışma biçimi

Codex yalnız kullanıcı “Trading OS proje kaynağındaki görevi incele” dediğinde
veya açık bir GitHub görev/commit/PR bağlantısı verdiğinde işi kontrol eder. Arka
planda zamanlanmış veya periyodik kontrol yapılmaz.

1. Kullanıcı görev kartını ChatGPT proje kaynağına ekler ya da GitHub bağlantısıyla
   Codex'e devreder.
2. Yerel JSON zarfı kullanılıyorsa şema sürümü, UUID, zaman, gönderici, alıcı, tür, dosya yolu ve varsa artefakt
   SHA-256 değerleri doğrulanır. Geçersiz veya aynı UUID ile farklı içerik taşıyan
   zarf işlenmez; `quarantine` alanına ve denetim kaydına alınır.
3. Aynı UUID ve aynı özet daha önce kaydedilmişse güvenli tekrar sayılır; görev
   ikinci kez çalıştırılmaz.
4. Geçerli yeni mesaj `received` olur. Bir uygulayıcı `claim` ile süreli sahiplik
   almadan mesaj `processing` durumuna geçemez.
5. Sahiplik; ajan kimliği, alınma ve sona erme zamanı, deneme sayısı ile tutulur.
   Süresi dolmuş veya yarım kalmış sahiplik ancak kullanıcı talimatlı `recover`
   işlemiyle yeniden kullanılabilir hâle gelir.
6. Güvenli ve yetkili görev gerçekleştirilir; kod değişikliği varsa test edilir
   ve proje Git politikasına göre kaydedilir.
7. Sonuç aynı `correlation_id` ile yerel kayda yazılır; commit/PR bağlantısı ve
   doğrulama özeti kullanıcıya teslim edilir.
8. Başarılı giriş, durum `completed` olarak kalıcılaştırıldıktan sonra yerel
   arşive taşınır. Hata `failed` olur; özgün zarf kanıt olarak korunur.

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

- Ana talimat: `Trading OS proje kaynağındaki görevi incele.`
- Alternatif talimat: `Şu GitHub görevini/PR'ını incele: <bağlantı>.`
- İstenirse tek mesaj UUID'si belirtilerek yalnız o mesaj işlenebilir.
- Yeni mesaj yoksa Codex bunu kısa biçimde bildirir.
- Başarısız çalışma kullanıcıya gerekçesiyle bildirilir.
- Yerel veritabanı: `var/trading_os.db`

## Komut eşlemesi

```text
claim      Tek bir mesaj için süreli işlem sahipliği alır
recover    Süresi dolmuş/yarım kalmış sahipliği kullanıcı talimatıyla kurtarır
check      Şema, bütünlük ve yerleşim kontrollerini salt okunur çalıştırır
```

Mevcut `send`, `ingest`, `list` ve `status` komutları yerel zarf üretme, içe alma
ve inceleme için korunur. Hiçbiri arka planda periyodik kaynak veya GitHub
taraması başlatmaz.

## Yerel arşiv ve karantina sınırı

- Tamamlanmış iletişim zarfları yerel `var/archive/` altında tutulur.
- Karantina, arşiv değildir. Şema/bütünlük sorunu çözülmeden dosya tamamlanmış
  kabul edilmez ve ikinci kez çalıştırılmaz.
