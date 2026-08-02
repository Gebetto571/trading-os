# Talimatla çalışan Drive–Codex köprüsü

## Çalışma biçimi

Codex yalnız kullanıcı “Trading OS gelen kutusunu kontrol et” veya aynı anlamda açık bir talimat verdiğinde `01_CHATGPT_GELEN` klasörünü kontrol eder. Arka planda zamanlanmış kontrol yapılmaz.

1. Yalnız `.json` mesaj zarflarını okur.
2. Şema sürümü, UUID, gönderici, alıcı ve mesaj türünü doğrular.
3. Yerel SQLite kaydında aynı UUID varsa mesajı tekrar çalıştırmaz.
4. Yeni mesajı `received`, ardından `processing` durumuna geçirir.
5. Güvenli ve yetkili proje görevini gerçekleştirir; kod değişikliği varsa test eder ve Git/GitHub'a kaydeder.
6. Sonucu aynı `correlation_id` ile `02_CODEX_GELEN` klasörüne koyar.
7. Başarılı işlenen giriş dosyasını `90_ARSIV` klasörüne taşır.
8. Yerel mesaj durumunu `completed` veya `failed` olarak kapatır.

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
