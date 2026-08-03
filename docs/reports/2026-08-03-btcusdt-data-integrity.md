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

## Çekirdek kalite kapısı yeniden doğrulaması — 2026-08-03

Sabit aralık `[2023-08-03T00:00:00Z, 2026-08-03T03:57:00Z)` olarak
donduruldu. Sonuç **geçti**.

### Kanonik 1m

- Beklenen, gerçek ve benzersiz satır: `1.578.477`
- İlk/son open time: `2023-08-03T00:00:00Z` /
  `2026-08-03T03:56:00Z`
- İç boşluk, mükerrer grup ve dakika hizası hatası: `0`
- Geçersiz süre, OHLC, negatif hacim/işlem ve toplamı aşan taker hacmi: `0`
- İkinci çalıştırmada yeni boşluk bulunmadı; REST onarımı gerekmedi. Kanonik veri
  setinde ilk aktarımda REST ile tamamlanan `237` adet 2026-08-03 mumu korunmaktadır.

### PostgreSQL–Parquet

- `37` ay × `5` zaman dilimi = `185` Parquet dosyası doğrulandı.
- Toplam `1.717.687` satır, PostgreSQL ile Parquet arasında geçici salt-okunur
  doğrulayıcıyla sıralı ve hücre düzeyinde karşılaştırıldı; fark `0`.
- Karşılaştırma, DB'deki `ingested_at` dışında ihraç edilen `17` ortak alanı kapsadı.
  Parquet'e özgü `schema_version=1` ayrıca doğrulandı; toplam `18` kolon kontrol edildi.
- Decimal alanlar exact scale `18`, timestamp alanları epoch mikrosaniye olarak
  karşılaştırıldı. Eksik/fazla bölüm, symlink, sıfır bayt ve `.part` dosyası: `0`.
- Bu tam karşılaştırma ad hoc kalite kanıtıdır; henüz kalıcı CLI/CI kapısı değildir.

### Aggregation

- Tüm sabit aralıkta kanonik 1m'den bağımsız SQL ile yeniden hesaplama sonucu:
  15m `105.231`, 1h `26.307`, 4h `6.576`, 1d `1.096`.
- Dört zaman diliminde eksik, fazla veya farklı satır: `0`.
- Resmî Binance karşılaştırması 2024-01-01 UTC günü örneğinde tüm OHLC, kapanış
  zamanı, hacim ve işlem alanlarında geçti: 15m `96`, 1h `24`, 4h `6`, 1d `1`.
- Resmî ZIP SHA-256: 15m
  `eb05070a1ea95c6f302053ed113d61088732275c444eddaba6a65baa607ea2db`, 1h
  `2ec7867e1dc5454505b39898a15a06bad23142114ea917f87ef013b58867969a`, 4h
  `04e4ac196c22e5421304bcc9068d4744172b52c5f2a2939e8e659c9f8f9948d6`, 1d
  `6322fa0e83995518b01066a110dca5c03ff837a6ef915a792b718fa76f0de205`.

### İkinci çalışma idempotency sonucu

- Sabit üç yıllık `run` ikinci kez başarıyla tamamlandı.
- Beş zaman diliminin satır/benzersizlik sayıları, içerik parmak izleri ve en son
  `ingested_at` değerleri değişmedi.
- `185` Parquet dosyasının ve `194` cache ZIP/checksum kanıtının SHA-256 listeleri
  byte düzeyinde değişmedi.
- Terminal manifest adetleri `validated=97`, `fallback_complete=2`, `failed=0`
  olarak kaldı. `attempt_count` toplamları doğrulanmış kayıtlarda `100→196`, fallback
  kayıtlarında `4→6` yükseldi; sayaç cache kontrol girişimini de deneme saymaktadır.
  Bu nedenle idempotency veri ve dosya çıktıları için geçer, operasyon metadata'sı
  byte düzeyinde idempotent değildir.

### Açık teknik nüanslar

- Manifest `row_count`, yeni eklenen satır değil işlenen aday satırdır. Önceki günlük
  2024-01-01 testi ile aylık arşiv çakışması kaynak atfında zararsız `1.440` satır
  farkı üretir; kanonik satır sayımı olarak kullanılmamalıdır.
- Mevcut iki fallback final boşluksuz doğrulamadan geçti. Bununla birlikte
  `fallback_complete` terminal geçişinin beklenen takvim günü ve kanonik kapsam
  doğrulamasına doğrudan bağlanması takip iyileştirmesidir.
- Resmî Binance üst zaman dilimi kanıtı bir günlük örnektir; üç yıllık dış arşiv
  karşılaştırması değildir. Üç yıllık kapsam için bağımsız 1m→aggregate SQL kanıtı
  kullanılmıştır.

## Kalite kapısı

- `cargo fmt --all -- --check`: geçti
- `cargo clippy --workspace --all-targets --all-features -- -D warnings`: geçti
- `cargo test --workspace --all-targets --all-features`: 24 geçti, 0 başarısız
- `python3 -m unittest discover -s tests -v`: 36 geçti, 0 başarısız
- Gerçek PostgreSQL farklı içerik çelişmesi: doğru biçimde reddedildi
- Manifest tam yaşam döngüsü ve fallback yaşam döngüsü: geçti
- 2024-01-01 Binance karşılaştırması: 15m `96`, 1h `24`, 4h `6`, 1d `1` mum
  birebir eşleşti
- Migration 1-3: başarılı
- Manifest sonucu: `validated` 97, `fallback_complete` 2, `failed` 0

## Tamamlanan önceki açıklar

Farklı içerik çakışması gerçek PostgreSQL servisinde sınanmış ve reddedilmiştir.
Manifestin normal, yeniden deneme, hata ve mevcut iki fallback geçişi uygulanmış;
başarılı kayıtlar uzlaştırılmıştır. Kapsama bağlı terminalleştirme yukarıdaki teknik
nüansla izlenmektedir. İndirme eşzamanlılığı 1-16 arasında ayarlanabilir hale
getirilmiştir. Üst zaman dilimleri gerçek Binance günlük örneğiyle karşılaştırılmıştır.
