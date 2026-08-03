# Drive, Git ve GitHub çalışma düzeni

## Google Drive klasörleri

| Klasör | İşlev |
|---|---|
| `00_KONTROL_MERKEZI` | Başlangıç talimatı, klasör manifestosu, aktif durum |
| `01_CHATGPT_GELEN` | ChatGPT'nin Codex'e gönderdiği zarflar |
| `02_CODEX_GELEN` | Codex'in ChatGPT'ye gönderdiği zarflar |
| `03_KARARLAR` | Kabul edilmiş karar kayıtları |
| `04_TEKNIK_TASARIM` | Mimari ve veri sözleşmeleri |
| `05_RAPORLAR` | Araştırma, test ve operasyon raporları |
| `06_PAYLASILAN_CIKTILAR` | Dışarı verilecek paketler ve görseller |
| `90_ARSIV` | Tamamlanmış aktarım dosyaları |

## Git politikası

- Ana ve tek yerel kod deposu `/Users/scm/Projects/trading-os` konumundadır;
  standart `.git` metadata'sını kullanır ve özel GitHub deposuna
  `origin` adıyla bağlıdır. Normal, etkileşimsiz Git komutları kullanılır.
- Eski `/Users/scm/Drive'ım/Trading OS/07_KOD/trading-os` kopyası çalışma alanı
  olarak kullanılmaz; taşıma doğrulandıktan sonra kalıntı bırakmadan kaldırılır.
- Ana dal: `main`.
- İş dalları: `agent/<kısa-konu>` veya `feature/<kısa-konu>`.
- Küçük, tek amaçlı kayıtlar yapılır.
- `sources/` aynalanmış referanstır; yerelde değiştirilmez.
- Veritabanı, günlük, anahtar ve ham özel veri Git'e eklenmez.

Örnek:

```bash
git status
git log --oneline
```

## GitHub politikası

- Depo: <https://github.com/Gebetto571/trading-os>
- Depo varsayılan olarak **private** oluşturulur.
- `main` doğrudan günlük geliştirme için kullanılmaz; değişiklikler dal ve inceleme üzerinden birleşir.
- GitHub kodun ve teknik belgelerin uzak, sürümlü kopyasıdır.
- Drive kod deposu veya `.git` taşımaz. Yalnız sohbet iletişimi, karar kaynağı,
  rapor ve paylaşılacak çıktılar için kullanılır.
- Anahtarlar daha sonra GitHub Secrets içinde tutulur, dosyaya yazılmaz.

## Yedekleme

- Kod ve teknik belgeler: `/Users/scm/Projects/trading-os` + özel GitHub deposu.
- SQLite: uygulama kapalıyken tarih damgalı şifreli yedek; GitHub'a gönderilmez.
- Drive karar/raporları: gerektiğinde Git deposundaki Markdown karşılığıyla eşleştirilir.

## İki ayrı arşiv

- İletişim zarfları: `/Users/scm/Drive'ım/Trading OS/90_ARSIV`
- Geçersizleşmiş karar ve yönetilen Markdown belgeleri:
  `/Users/scm/Drive'ım/Trading OS/03_KARARLAR/90_ARSIV`

Bu klasörler birbirinin yerine kullanılmaz. Bir karar belgesi mesaj arşivine, bir
JSON iletişim zarfı karar arşivine taşınmaz.

## Talimatlı Drive eşitlemesi

Drive işlemleri periyodik değildir. Kök dizin çalışma anında
`TRADING_OS_DRIVE_ROOT` ortam değişkeninden alınır. `sync-pull` ve `sync-push`
yalnız kullanıcı açıkça istediğinde çalışır; eksik veya beklenmeyen kök değerinde
işlem güvenli biçimde durur.
