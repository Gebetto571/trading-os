---
id: TOS-CHATDEC-20260803-002
record_type: decision
created_at: 2026-08-03T01:20:34Z
sender_chat: codex-dev
recipient_chats:
  - all-chats
subject: BTCUSDT tarihsel veri katmanının ayrı PostgreSQL bileşeni olması
status: accepted
correlation_id: null
decision_refs:
  - TOS-DEC-003
document_refs:
  - docs/architecture/market-data.md
  - docs/reports/2026-08-03-btcusdt-data-integrity.md
requires_action: false
---

# Karar

## Karar cümlesi

BTCUSDT tarihsel piyasa verisi, mesajlaşma SQLite veritabanından ayrılarak
`crates/market-data` Rust bileşeni ve ayrı PostgreSQL servisi içinde tutulacaktır.

## Gerekçe

Dakikalık piyasa verisinin hacmi ve batch/decimal gereksinimleri mesajlaşma SQLite
veritabanının sorumluluğundan farklıdır. Ayrım mevcut `docs/database.md` kararını
uygular ve kanonik piyasa verisini çelişki kontrollü tutar.

## Etki

Kök Rust workspace, `crates/market-data`, ayrı migration, yerel PostgreSQL Compose
servisi, mimari belge ve bütünlük raporu eklenir. Mevcut Python köprüsü değişmez.

## Uygulama

Arşiv planlama, checksum doğrulama, CSV/timestamp normalizasyonu, PostgreSQL batch
import, REST boşluk onarımı, Parquet ve üst zaman dilimi üretimi tek CLI altında
sunulur. Büyük aktarım küçük gerçek veri ve kalite kapıları geçmeden başlatılmaz.
