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
- `cargo test --workspace --all-features`: 20 geçti, 0 başarısız

## Kalan kapsam

Varsayılan üç yıllık PostgreSQL/Parquet aktarımı tamamlandı. REST fallback gerçek
günlük arşiv gecikmesinde çalıştı. Farklı içerik çatışması gerçek PostgreSQL servisine
bilinçli olarak enjekte edilmedi; üst zaman dilimleri Binance'ın yayımladığı örneklerle
ayrıca karşılaştırılmadı.

## Bilinen açıklar

- PostgreSQL tekrar çalıştırma idempotency'si gerçek servis üzerinde sınandı; farklı
  içerik çatışmasının gerçek servis entegrasyon testi hâlâ eksik.
- Manifestin `planned/downloaded/validated` geçişleri ve tam resume semantiği eksik.
- Başarılı fallback sonrasında bulunamayan üst arşiv manifestte `failed` kalıyor.
- İndirme güvenli fakat sıralı; CLI eşzamanlılık ayarı henüz yok.
- Üst zaman dilimleri gerçek Binance örnekleriyle karşılaştırılmadı.
