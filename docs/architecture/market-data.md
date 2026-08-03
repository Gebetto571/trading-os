# BTCUSDT veri katmanı

## Sorumluluk sınırı

Mesajlaşma ve karar izleri mevcut SQLite veritabanında kalır. Yüksek hacimli piyasa
verisi ayrı PostgreSQL servisinde tutulur. PostgreSQL doğrulanmış kanonik kaynaktır;
ZIP dosyaları tekrar kullanılabilir ham önbellek, Parquet ise türetilmiş arşivdir.

## Akış

```text
deterministik plan
  -> tamamlanmış ay için aylık ZIP
  -> 404 durumunda günlük ZIP
  -> CHECKSUM + SHA-256 + akış halinde .part indirme
  -> CSV şeması ve timestamp birimi doğrulama
  -> PostgreSQL batch insert; içerik çelişkisinde dur
  -> boşluk taraması ve en fazla 7 günlük REST onarımı
  -> yalnız eksiksiz alt mumlardan 15m / 1h / 4h / 1d
  -> PostgreSQL'den aylık decimal Parquet
```

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
`export-parquet`, `run`, `status`. `run` aşamaları güvenli sırada çalıştırır.
