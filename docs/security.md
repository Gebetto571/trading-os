# Güvenlik politikası

- Canlı borsa anahtarları, cüzdan özel anahtarları, seed phrase ve erişim tokenları
  proje kaynağına veya Git'e yazılmaz.
- `.env` yalnız yereldir; depoda sadece `.env.example` bulunur.
- GitHub deposu kullanıcı onayıyla public durumdadır. Bu nedenle Git'e eklenen her
  içerik herkese açık kabul edilir; sır, ham piyasa verisi, çalışma veritabanı,
  kişisel veri ve yerel günlükler commit edilmez.
- Proje kaynaklarında hesap numarası ve kişisel veri en aza indirilir.
- Artefakt bütünlüğü SHA-256 ile doğrulanabilir.
- AI bileşeni canlı emir gönderemez, risk limiti yükseltemez ve sistemi kendi başına canlı moda alamaz.
- Yanlışlıkla sır kaydedilirse yalnız dosyayı silmek yeterli değildir; sır derhal iptal edilip yenilenir.

## Yerel sırlar

- Sırlar yalnız `/Users/m2pro/Projects/trading-os` çalışma alanındaki Git dışı
  `.env` veya işletim sistemi sır deposunda tutulur; proje kaynaklarına yazılmaz.
- `.env` dosyası yalnız sahibi tarafından okunabilir olmalı; uygulama gevşek dosya
  izninde güvenli biçimde durmalıdır.
- İşletim komutları `.env` dosyasını shell kodu olarak çalıştırmaz; yalnız izinli
  anahtarları veri olarak okur. Normal dosya, mevcut kullanıcı sahipliği ve tam
  `0600` izni gerekir; sembolik bağlantı, FIFO ve desteklenmeyen sözdizimi reddedilir.
- Collector'ın ham stdout/stderr çıktısı saklanmaz; güvenli sağlık kaydı hata
  kodunu taşır. Eski ya da başarısız kayıt sağlık kontrolünden geçmez.
- Başka cihazdaki kurtarma paketi şifreli tutulur; Anahtarlık anahtarı Git'e,
  manifestin içine veya günlük çıktısına yazılmaz. Anahtar erişimi olmadan paket
  geri yüklenemez; yedek kabulünde şifre açma doğrulaması zorunludur.
- Hata mesajları ve iletişim zarfları sır değerini yankılamaz.

## Dosya yolu ve bütünlük koruması

- Gelen zarfın adı güvenli bir temel ad olmalı; `..`, mutlak yol, sembolik bağlantı
  kaçışı ve izin verilen kökün dışına çözümleme reddedilir.
- Yerel içe aktarma kökü açıkça verilir ve işlem öncesi gerçek yolu doğrulanır.
- Zarf doğrulayıcı artefaktın SHA-256 alan biçimini denetler; artefaktı açacak veya
  çalıştıracak tüketici, dosya içeriğinin özetini kullanım öncesi yeniden hesaplayıp
  zarf değeriyle eşleştirmek zorundadır. Köprü henüz artefakt indirme veya çalıştırma
  yapmaz. Aynı mesaj UUID'si farklı içerik özetiyle gelirse tekrar değil
  `integrity_conflict` sayılır ve karantinaya alınır.
- Tamamlanmış veya karantinadaki özgün zarf denetim kanıtıdır; sessizce değiştirilmez.
