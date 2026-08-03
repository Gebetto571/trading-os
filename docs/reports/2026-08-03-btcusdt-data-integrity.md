# BTCUSDT veri bütünlüğü raporu — 2026-08-03

## Hedef

- Binance Global spot / BTCUSDT / 1m
- Varsayılan aralık: `[2023-08-03T00:00:00Z, latest-closed)`
- Kanonik kaynak: PostgreSQL

## Tamamlanan gerçek veri kanıtı

- Dönem: `[2024-01-01T00:00:00Z, 2024-01-02T00:00:00Z)`
- Arşiv: 1 günlük ZIP, 68.923 bayt
- CSV: 1.440 satır
- İlk/son open time: `00:00:00Z` / `23:59:00Z`
- SHA-256: `4ec2915e610ab4e9a4d5e86a5ada1c15bbf6b5db343cdb385681d6ac97166a4e`
- İkinci çalıştırma: checksum doğrulanmış önbellek yeniden kullanıldı

## PostgreSQL ve Parquet entegrasyon kanıtı

Yerel PostgreSQL 16 servisi üzerinde iki aşamalı kapı çalıştırıldı:

- 1 günlük aralık: 1m `1.440`, 15m `96`, 1h `24`, 4h `6`, 1d `1`
- 2024 Ocak: 1m `44.640`, 15m `2.976`, 1h `744`, 4h `186`, 1d `31`
- Her iki aralıkta eksik 1m: `0`
- Her zaman diliminde satır sayısı = benzersiz open time sayısı
- Günlük ve aylık manifest: `imported`, checksum eşleşiyor, hata yok
- PostgreSQL ile beş Parquet bölümünün satır sayıları birebir eşleşiyor
- Günlük ve aylık ikinci çalıştırmalarda PostgreSQL sayıları değişmedi
- İkinci çalıştırmalarda beş Parquet dosyasının SHA-256 değerleri değişmedi
- Artakalan `.part` Parquet dosyası: `0`

## Üç yıllık aktarım sonucu

- Aralık: `[2023-08-03T00:00:00Z, 2026-08-03T03:57:00Z)`
- Kanonik 1m: `1.578.477`; ilk/son: `2023-08-03T00:00:00Z` /
  `2026-08-03T03:56:00Z`
- Üst zaman dilimleri: 15m `105.231`, 1h `26.307`, 4h `6.576`, 1d `1.096`
- Her zaman diliminde satır sayısı = benzersiz open time sayısı
- Tam dönem 1m boşluk ve veri kuralı doğrulaması: geçti
- Parquet: `185` aylık bölüm; PostgreSQL ile tüm zaman dilimi toplamları eşleşiyor
- Artakalan `.part` Parquet dosyası: `0`
- 2026 Temmuz aylık arşivi henüz yoktu; `44.640` satır günlük arşivlerden tamamlandı
- 2026-08-03 günlük arşivi henüz yoktu; kapanmış `237` dakika REST ile tamamlandı

## Kalite kapısı

- `cargo fmt --all -- --check`: geçti
- `cargo clippy --workspace --all-targets --all-features -- -D warnings`: geçti
- `cargo test --workspace --all-targets --all-features`: 24 geçti, 0 başarısız
- Gerçek PostgreSQL farklı içerik çelişmesi: doğru biçimde reddedildi
- Manifest tam yaşam döngüsü ve fallback yaşam döngüsü: geçti
- 2024-01-01 Binance karşılaştırması: 15m `96`, 1h `24`, 4h `6`, 1d `1` mum
  birebir eşleşti
- Migration 1-3: başarılı
- Manifest sonucu: `validated` 97, `fallback_complete` 2, `failed` 0

## Tamamlanan önceki açıklar

Farklı içerik çakışması gerçek PostgreSQL servisinde sınanmış ve reddedilmiştir.
Manifestin bütün normal, yeniden deneme, hata ve fallback geçişleri uygulanmıştır.
Başarılı fallback kayıtları uzlaştırılmıştır. İndirme eşzamanlılığı 1-16 arasında
ayarlanabilir hale getirilmiştir. Üst zaman dilimleri gerçek Binance örneğiyle
karşılaştırılmıştır.
