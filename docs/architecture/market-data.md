# BTCUSDT veri katmanı

## Sorumluluk sınırı

Mesajlaşma ve karar izleri mevcut SQLite veritabanında kalır. Yüksek hacimli piyasa
verisi ayrı PostgreSQL servisinde tutulur. PostgreSQL doğrulanmış kanonik kaynaktır;
ZIP dosyaları tekrar kullanılabilir ham önbellek, Parquet ise türetilmiş arşivdir.

## Akış

```text
deterministik plan
  -> 1-16 arasında ayarlanabilir, varsayılan 4 eşzamanlı indirme
  -> tamamlanmış ay için aylık ZIP
  -> 404 durumunda günlük ZIP
  -> CHECKSUM + SHA-256 + akış halinde .part indirme
  -> CSV şeması ve timestamp birimi doğrulama
  -> PostgreSQL batch insert; içerik çelişkisinde dur
  -> boşluk taraması ve en fazla 7 günlük REST onarımı
  -> yalnız eksiksiz alt mumlardan 15m / 1h / 4h / 1d
  -> PostgreSQL'den aylık decimal Parquet
```

Manifest `planned -> downloading -> downloaded -> checksum_verified -> imported
-> validated` geçişlerini izler. Fallback önce `fallback_pending` olur ve yalnız
tam UTC gün/ay kapsamı PostgreSQL'de doğrulanınca `fallback_complete` durumuna
geçer. `invocation_count` iş akışı girişini, `attempt_count` ise yalnız gerçek ZIP
HTTP denemelerini sayar; checksum ve geçerli cache kullanımı deneme sayılmaz.

Tekillik anahtarı `venue + market_type + symbol + interval + open_time` değeridir.
Aynı anahtarda farklı piyasa içeriği sessizce güncellenmez.

Timestamp birimi yalnız dosya adına göre seçilmez. Milisaniye ve mikrosaniye adayları
dosyanın beklenen UTC dönemiyle karşılaştırılır; güvenilir tek aday yoksa işlem durur.

Parquet bölümleri:

```text
data/parquet/
  venue=binance/market_type=spot/symbol=BTCUSDT/
  interval=1m/year=YYYY/month=MM/candles.parquet
```

Üst zaman diliminde bir alt mum eksikse grup kanonik tabloya hiç eklenmez.

## CLI

Alt komutlar: `plan`, `download`, `import`, `validate`, `repair`, `aggregate`,
`export-parquet`, `verify-parquet`, `compare-binance`, `run`, `status`. `run` aşamaları güvenli
sırada çalıştırır. `--download-concurrency` 1-16 arasında ayarlanabilir ve
varsayılanı 4'tür. `compare-binance`, UTC gün sınırları içindeki kanonik 15m, 1h,
4h ve 1d mumları Binance'ın yayımladığı mumlarla birebir karşılaştırır.
`verify-parquet`, seçilen aylardaki beş zaman diliminin Parquet şemasını, bölüm
envanterini ve ihraç edilen 17 PostgreSQL alanını 4.096 satırlık akışlarla birebir
karşılaştırır; JSON raporu üretir ve herhangi bir farkta başarısız olur.
