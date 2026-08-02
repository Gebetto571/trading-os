# Veritabanı tasarımı

## Seçim

İlk aşamada SQLite kullanılır. Tek bilgisayarda hızlıdır, sunucu gerektirmez, kolay yedeklenir ve mesaj/karar trafiği için yeterlidir. Canlı işlem motorunun yüksek hacimli piyasa veritabanı bu dosyadan ayrı olacaktır.

## Konum

Varsayılan çalışma dosyası `var/trading_os.db` konumundadır ve Git'e girmez. Şema değişiklikleri `migrations/` altında Git'e girer.

## Tablolar

- `messages`: Mesaj zarfı, yönü, durumu ve ilişki kimliği.
- `artifacts`: Mesaj veya kararla bağlantılı dosyaların konumu ve özeti.
- `decisions`: Kabul edilmiş mimari/ürün kararları ve sürümleri.
- `sync_runs`: Drive alma/gönderme denemelerinin denetim izi.
- `schema_migrations`: Uygulanmış şema sürümleri.

## Yazma ilkeleri

1. Kimlikler uygulama tarafından UUID olarak üretilir.
2. Zamanlar UTC ISO-8601 metnidir.
3. Para gelecekte tamsayı en küçük birim veya kesin ondalık olarak tutulur; kayan nokta kullanılmaz.
4. Mesaj gövdesi korunur; değişiklik yeni mesaj veya sürüm üretir.
5. Dış dosya bağlantılarında mümkünse SHA-256 tutulur.
6. Migration dosyası yayımlandıktan sonra değiştirilmez; yeni numaralı migration eklenir.
7. Canlı piyasa olayı, emir, fill, pozisyon ve muhasebe tabloları ayrı işlem veritabanında tasarlanacaktır.

