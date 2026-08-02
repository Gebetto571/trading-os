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

- Bu Codex proje aynasında uygulama `.git` yolunu koruduğu için Git metadata'sı `.local-git/` altında tutulur. Normal Git komutlarının yerine `bin/tos-git` kullanılır.
- Ana dal: `main`.
- İş dalları: `agent/<kısa-konu>` veya `feature/<kısa-konu>`.
- Küçük, tek amaçlı kayıtlar yapılır.
- `sources/` aynalanmış referanstır; yerelde değiştirilmez.
- Veritabanı, günlük, anahtar ve ham özel veri Git'e eklenmez.

Örnek:

```bash
bin/tos-git status
bin/tos-git log --oneline
```

## GitHub politikası

- Depo varsayılan olarak **private** oluşturulur.
- `main` doğrudan günlük geliştirme için kullanılmaz; değişiklikler dal ve inceleme üzerinden birleşir.
- GitHub uzak yedektir ama Drive'ın yerine geçmez.
- Belgelerin kalıcı ve teknik sürümü GitHub'dadır; sohbet aktarım kopyası Drive'dadır.
- Anahtarlar daha sonra GitHub Secrets içinde tutulur, dosyaya yazılmaz.

## Yedekleme

- Kod ve belgeler: yerel Git + özel GitHub deposu.
- SQLite: uygulama kapalıyken tarih damgalı şifreli yedek; GitHub'a gönderilmez.
- Drive karar/raporları: gerektiğinde Git deposundaki Markdown karşılığıyla eşleştirilir.
