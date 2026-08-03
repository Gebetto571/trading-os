# ChatGPT ↔ Codex iletişim protokolü

## Amaç

Bulut sohbetlerinin ve yerel Codex çalışmalarının bağlam kaybetmeden görev, yanıt, karar ve artefakt paylaşmasını sağlar. Drive bir posta kutusudur; mesajın kalıcı işlem durumu SQLite'ta tutulur.

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

## Durum makinesi

```text
queued -> received -> processing -> completed
                    \-> failed
```

Aynı `id` ikinci kez gelirse yeni kayıt yaratılmaz. Böylece yeniden denemeler güvenlidir.

## Çalışma kuralları

1. Gönderen kendi gelen kutusuna değil, karşı tarafın gelen klasörüne yazar.
2. Bir yanıt ilk görevin `correlation_id` değerini taşır.
3. Büyük dosyalar mesaja gömülmez; `artifacts` listesinde Drive/GitHub yolu ve SHA-256 özeti verilir.
4. Bir karar ancak açıkça `decision` türüyle, gerekçesiyle ve yetkili kapsamda
   yayınlandığında bağlayıcıdır. Mevcut yaşayan karar belgesi varsa aynı belge
   güncellenir; sırf mesaj geldi diye yeni Markdown açılmaz.
5. Sohbet metni API anahtarı, özel anahtar veya canlı borsa kimlik bilgisi içeremez.
6. UTC sistem zamanıdır; kullanıcıya gösterimde Europe/Istanbul kullanılabilir.

## ChatGPT için kısa kullanım talimatı

Drive'daki `Trading OS/00_KONTROL_MERKEZI` belgesini oku. Codex'e görev verirken
protokole uygun JSON üretip `01_CHATGPT_GELEN` klasörüne koy. Codex yanıtlarını
`02_CODEX_GELEN` klasöründen oku. Kabul edilen kalıcı kararı ilgili sohbetin
mevcut yaşayan kaydına işle. Ayrı bir Markdown gerçekten zorunluysa TOS-DEC-004
istisnasını belgele ve merkezi fihristi dosyayla aynı işlemde güncelle.

Codex gelen kutusunu yalnız kullanıcının açık talimatıyla kontrol eder. Kullanıcı “Trading OS gelen kutusunu kontrol et” dediğinde yeni mesajlar alınır; UUID değeri daha önce işlendiyse görev tekrarlanmaz.

## Markdown sınırı

- Görev, yanıt, durum, uyarı ve teyit için iletişim zarfı kullanılır.
- Sohbetin mevcut Markdown kaydı varsa yaşayan kayıt tarihli bölümle güncellenir.
- Ayrı Markdown varsayılan değil, TOS-DEC-004'te tanımlanan denetlenebilir bir
  istisnadır.
- Yeni yönetilen Markdown, merkezi fihrist kaydı olmadan tamamlanmış sayılmaz.
