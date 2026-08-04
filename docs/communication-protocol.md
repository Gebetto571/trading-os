# ChatGPT ↔ Codex iletişim protokolü

## Amaç

Bulut sohbetlerinin ve yerel Codex çalışmalarının bağlam kaybetmeden görev, yanıt,
karar ve artefakt paylaşmasını sağlar. Google Drive güncel `Trading OS` alanı AI
hafızası ve ortak görev–sonuç posta kutusudur; yerel mesaj işlem durumu SQLite'ta
tutulabilir. Drive kod deposu veya canlı uygulama kaynağı değildir. Katman sahipliği
ve yayın kopyası kuralları TOS-DEC-004 bölüm 7'de bağlayıcıdır.

Eski Drive kod deposu, `Drive'ım` ve `07_KOD/trading-os` yolları kullanılmaz.
Doğrulanmış yönler:

- ChatGPT → Chief Engineer: `01_CHATGPT_GELEN`
- Chief Engineer → ChatGPT: `02_CODEX_GELEN`

## Mesaj zarfı

Her aktarım UTF-8 JSON dosyasıdır ve `schemas/message.schema.json` sözleşmesine uyar.

Dosya adı:

```text
YYYYMMDDTHHMMSSZ__<kısa-mesaj-kimliği>__<tür>.json
```

Zorunlu alanlar:

- `id`: Değişmez UUID.
- `created_at`: UTC ve ISO-8601 zaman damgası.
- `sender`, `recipient`: `chatgpt`, `codex` veya tanımlı servis adı.
- `type`: `task`, `response`, `decision`, `status` ya da `error`.
- `subject`, `body`: İnsan tarafından okunabilir içerik.
- `correlation_id`: Yanıtı ilk görevle bağlar.
- `schema_version`: Şimdilik `1`.

Chief Engineer görevlerinde `schemas/conversation-map.json`, `00`–`08` bulut
alanlarını tek otoritenin `chief-engineer/<alan>` hatlarına bağlar. Görev ayrıca
`authority=chief-engineer`, `approval_state=approved_for_local_implementation`,
değişiklik modu ve eksiksiz uygulama brifi taşır. Bu alanlardan biri eşleşmezse
görev proje dosyalarına dokunmadan reddedilir.

## Durum makinesi

```text
queued -> received -> processing -> completed
                    \-> failed
```

Aynı `id` ikinci kez gelirse yeni kayıt yaratılmaz. Böylece yeniden denemeler güvenlidir.

## Çalışma kuralları

1. ChatGPT görevi `01_CHATGPT_GELEN`, Chief Engineer sonucu `02_CODEX_GELEN`
   klasörüne yazar ve yazdığı zarfı geri okuyarak doğrular.
2. Bir yanıt ilk görevin `correlation_id` değerini; görevde bu alan boşsa görev
   UUID'sini korelasyon kimliği olarak taşır.
3. Büyük dosyalar mesaja gömülmez; `artifacts` listesinde Drive, yerel veya GitHub
   kimliği/yolu ve gerekiyorsa SHA-256 özeti verilir.
4. Bir karar ancak açıkça `decision` türüyle, gerekçesiyle ve yetkili kapsamda
   yayınlandığında bağlayıcıdır. Mevcut yaşayan karar belgesi varsa aynı belge
   güncellenir; sırf mesaj geldi diye yeni Markdown açılmaz.
5. Sohbet metni API anahtarı, özel anahtar veya canlı borsa kimlik bilgisi içeremez.
6. UTC sistem zamanıdır; kullanıcıya gösterimde Europe/Istanbul kullanılabilir.
7. Ürün kodu, test, şema, migration ve çalışan sistem değişikliklerinde tek aktif
   yazar `chief-engineer`; belge düzenleme hattında `docs-manager` olur. `base_commit`,
   `revision`, `updated_by`, `active_writer` ve repository-göreli `owned_paths`
   SQLite'ta kaydedilir; aktif görevlerin dosya yolları örtüşürse yeni görev
   fail-closed durur.
8. Sonuç zarfı değişen dosyaları, komut/exit code özetlerini, Git durumunu,
   atlanan kontrolleri, riskleri ve `ALIGNED`, `CONDITIONAL` veya `BLOCKED`
   hükmünü taşır. Bulut kabulü commit, push, merge, deployment veya canlı işlem
   yetkisi vermez.

## ChatGPT için kısa kullanım talimatı

Trading OS proje kurallarını oku. Codex'e görev verirken protokole uygun görev
kartı üret ve onaylı JSON zarfı `01_CHATGPT_GELEN` klasörüne yazıp geri oku.
Chief Engineer sonucu aynı `correlation_id` ile `02_CODEX_GELEN` klasörüne yazar;
sonuç geri okunmadan görev tamamlanmış sayılmaz. GitHub issue/commit/PR bağlantısı
teknik referans olarak kullanılabilir. Kabul edilen kalıcı kararın kanonik konumu
TOS-DEC-004 bölüm 7'ye göre belirlenir; aynı yaşayan içerik Drive ve Git'te bağımsız
düzenlenmez.

Codex Drive görev zarfını veya GitHub teknik referansını yalnız kullanıcının
talimatıyla kontrol eder. UUID daha önce işlendiyse görev tekrarlanmaz. Sonuç zarfı
geri okunup korelasyonu doğrulanmadan görev tamamlanmaz. Otomatik ya da periyodik
kontrol yapılmaz. Drive erişimi kullanıcı talimatıyla bağlayıcı üzerinden veya elle
yapılır; yerel köprü Drive'ı izlemez, taramaz veya otomatik eşitlemez.

## Markdown sınırı

- Görev, yanıt, durum, uyarı ve teyit için iletişim zarfı kullanılır.
- Sohbetin mevcut Markdown kaydı varsa yaşayan kayıt tarihli bölümle güncellenir.
- Ayrı Markdown varsayılan değil, TOS-DEC-004'te tanımlanan denetlenebilir bir
  istisnadır.
- Yeni yönetilen Markdown, merkezi fihrist kaydı olmadan tamamlanmış sayılmaz.
