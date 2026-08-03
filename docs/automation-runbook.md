# Talimatla çalışan Drive–Codex köprüsü

## Çalışma biçimi

Codex yalnız kullanıcı “Trading OS gelen kutusunu kontrol et” veya aynı anlamda açık bir talimat verdiğinde `01_CHATGPT_GELEN` klasörünü kontrol eder. Arka planda zamanlanmış kontrol yapılmaz.

1. `sync-pull` yalnız `.json` mesaj zarflarını Drive'dan yerel bekleme alanına alır.
2. Şema sürümü, UUID, zaman, gönderici, alıcı, tür, dosya yolu ve varsa artefakt
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
7. Sonuç aynı `correlation_id` ile yerel giden kutusuna yazılır; `sync-push`
   komutu kullanıcı talimatıyla `02_CODEX_GELEN` klasörüne gönderir.
8. Başarılı giriş, durum `completed` olarak kalıcılaştırıldıktan sonra Drive'daki
   aktarım arşivine taşınır. Hata `failed` olur; özgün zarf kanıt olarak korunur.

## Otomatik yürütme sınırı

Şunlar otomatik yapılabilir:

- Proje dosyalarını okumak, düzenlemek ve test etmek
- Yeni dal, commit ve taslak pull request hazırlamak
- Teknik belge, rapor ve analiz üretmek
- Drive içinde protokole uygun mesaj ve proje belgesi oluşturmak

Şunlar açık kullanıcı onayı olmadan yapılmaz:

- Canlı alım-satım emri, para veya kripto varlık transferi
- Risk limiti yükseltme veya canlı moda geçme
- Sır, token, özel anahtar ya da kişisel veri paylaşma
- Kalıcı silme, genel erişim açma veya yeni ücretli hizmet başlatma
- Proje kapsamı dışında kişi ya da sistemlere mesaj gönderme

Bu durumlarda Codex görevi uygulamak yerine `status` türünde `approval_required` yanıtı üretir.

## Çalıştırma

- Ana komut: `Trading OS gelen kutusunu kontrol et.`
- Alternatif komut: `Drive görevlerini al.`
- İstenirse tek mesaj UUID'si belirtilerek yalnız o mesaj işlenebilir.
- Yeni mesaj yoksa Codex bunu kısa biçimde bildirir.
- Başarısız çalışma kullanıcıya gerekçesiyle bildirilir.
- Yerel veritabanı: `var/trading_os.db`
- Drive klasör kimlikleri: `config/drive-folders.json`

## Komut eşlemesi

```text
sync-pull  Drive gelen kutusundan doğrulanmış zarfları alır
claim      Tek bir mesaj için süreli işlem sahipliği alır
recover    Süresi dolmuş/yarım kalmış sahipliği kullanıcı talimatıyla kurtarır
sync-push  Yerel giden zarfları Drive'a gönderir
check      Şema, bütünlük ve yerleşim kontrollerini salt okunur çalıştırır
```

Mevcut `send`, `ingest`, `list` ve `status` komutları yerel zarf üretme, içe alma
ve inceleme için korunur. Hiçbiri arka planda periyodik Drive taraması başlatmaz.

## Arşiv ve karantina sınırı

- Tamamlanmış iletişim zarfları:
  `/Users/scm/Drive'ım/Trading OS/90_ARSIV`
- Geçersizleşmiş karar ve yönetilen belgeler:
  `/Users/scm/Drive'ım/Trading OS/03_KARARLAR/90_ARSIV`
- Karantina, arşiv değildir. Şema/bütünlük sorunu çözülmeden dosya tamamlanmış
  kabul edilmez ve ikinci kez çalıştırılmaz.
