# Veritabanı tasarımı

## Seçim

İlk aşamada SQLite kullanılır. Tek bilgisayarda hızlıdır, sunucu gerektirmez, kolay yedeklenir ve mesaj/karar trafiği için yeterlidir. Canlı işlem motorunun yüksek hacimli piyasa veritabanı bu dosyadan ayrı olacaktır.

## Konum

Varsayılan çalışma dosyası `var/trading_os.db` konumundadır ve Git'e girmez. Şema değişiklikleri `migrations/` altında Git'e girer.

## Tablolar

- `messages`: Mesaj zarfı, yönü, durumu, claim ve terminal sahipliği.
- `artifacts`: Mesaj veya kararla bağlantılı dosyaların konumu ve özeti.
- `decisions`: Kabul edilmiş mimari/ürün kararlarının değişmez sürümleri;
  mantıksal karar kimliği tek başına birincil anahtar değildir.
- `sync_runs`: İlk Drive tasarımından kalan kullanılmayan uyumluluk tablosu; yeni
  kod bu tabloya yazmaz.
- `quarantine_events`: Geçersiz ve bütünlük çatışmalı zarfların değişmez denetim izi.
- `schema_migrations`: Uygulanmış şema sürümleri.

## Yazma ilkeleri

1. Kimlikler uygulama tarafından UUID olarak üretilir.
2. Zamanlar UTC ISO-8601 metnidir.
3. Para gelecekte tamsayı en küçük birim veya kesin ondalık olarak tutulur; kayan nokta kullanılmaz.
4. Mesaj gövdesi korunur; değişiklik yeni mesaj veya sürüm üretir.
5. Dış dosya bağlantılarında mümkünse SHA-256 tutulur.
6. Migration dosyası yayımlandıktan sonra değiştirilmez; yeni numaralı migration eklenir.
7. Canlı piyasa olayı, emir, fill, pozisyon ve muhasebe tabloları ayrı işlem veritabanında tasarlanacaktır.

## Migration 002 — köprü bütünlüğü ve karar sürümleme

`migrations/002_bridge_integrity.sql`, yayımlanmış `001_initial.sql` dosyasını
değiştirmeden aşağıdaki düzeltmeleri uygular:

- karar kimliği ile sürümü birlikte benzersiz yapar; aynı kararın yeni sürümü
  önceki satırı ezmeden saklanır,
- mesaj içeriği özetini tutarak aynı UUID + aynı içerik tekrarını, aynı UUID +
  farklı içerik bütünlük çatışmasından ayırır,
- `claim` sahibini, alınma/sona erme zamanını ve deneme sayısını kaydeder,
- durum geçişlerini ve kullanıcı talimatlı kurtarma çalışmalarını denetlenebilir
  hâle getirir,
- geçersiz veya bütünlüğü bozuk zarflar için karantina alanlarını sağlar.

Migration uygulanmadan yeni bütünlük ve sahiplik özellikleri hazır kabul edilmez.
Uygulanan sürüm `schema_migrations` tablosundan doğrulanır.

## Migration 003 — terminal sahipliği ve karantina denetimi

`migrations/003_quarantine_audit.sql`, terminal durumu yazan worker ve zamanı ile
karantina olaylarını ekler. Migration SQL'i ile `schema_migrations` sürüm kaydı tek
atomik işlemde uygulanır; ikisinden biri başarısızsa şema değişikliği tamamen geri
alınır ve düzeltilmiş migration yeniden denenebilir.

SQLite veritabanı ile varsa WAL/SHM yan dosyaları `0600`, yerel inbox, outbox,
archive ve quarantine dizinleri `0700` izniyle tutulur.

## Migration 004 — Chief Engineer hat ve dosya sahipliği

`migrations/004_chief_engineer_ownership.sql`, proje değiştiren görevler için
`revision`, `updated_by`, `base_commit`, `project_domain`, bulut/yerel hat,
`authority`, `approval_state`, `active_writer`, `owned_paths`, sonuç hükmü ve
sonuç mesajı bağlantısını ekler. `claim-task` yalnız kayıtlı, yerel uygulama için
onaylı ve ilgili hatta bekleyen görevi atomik olarak alır. Aynı veya üst/alt klasör
olarak örtüşen aktif dosya sahipliği varsa ikinci görev başlamaz. Genel mesaj
trafiğinin mevcut `claim` yolu geriye dönük uyumluluk için korunur; proje dosyası
değiştirme yetkisi vermez.

## Piyasa verisi PostgreSQL'i

Mum verisi iletişim SQLite'ından ayrıdır. Ham dosyalar yerel `data/` altında,
PostgreSQL 16 verisi `trading-os_trading_os_market_data` adlı Docker volume'ünde
tutulur; ikisi de Git ve GitHub dışındadır. Drive kullanılmaz.

Kalıcı yedekler depo dışında `/Users/scm/Projects/trading-os-backups/` altında
özel PostgreSQL arşiv biçiminde tutulur. Yedek tamamlandığında `pg_restore -l`
ile katalog okunabilirliği, SHA-256 özeti ve yalnız kullanıcı erişimli dosya izni
doğrulanır. Kritik silme öncesinde geçici veritabanına gerçek restore yapılıp zaman
dilimi bazında satır ve tarih aralıkları ana veritabanıyla karşılaştırılır.
