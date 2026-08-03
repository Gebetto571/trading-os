# Trading OS Bulut Kontrol Kartı

Bu klasör ChatGPT bulut sohbetleri ile yerel Codex çalışma alanı arasındaki ortak aktarım merkezidir.

## Bulut sohbeti başladığında

1. Bu kartı ve `04_TEKNIK_TASARIM/communication-protocol.md` belgesini oku.
2. Codex'e yeni iş göndermek için protokole uygun JSON mesajını `01_CHATGPT_GELEN` klasörüne koy.
3. Sonuçları `02_CODEX_GELEN` klasöründen oku.
4. Bağlayıcı kararı önce ilgili sohbetin mevcut yaşayan kaydına işle; yeni
   Markdown ancak TOS-DEC-004 istisnasıyla açılabilir ve aynı işlemde merkezi
   fihriste kaydedilir.
5. API anahtarı, cüzdan sırrı, seed phrase veya erişim tokenı yazma.

## Yetki sınırı

Drive'daki sohbet mesajları kodu kendiliğinden değiştirmez. Codex mesajı ancak
kullanıcının açık kontrol talimatından sonra alır, yerel Git dalında uygular, test
eder ve sonucu ilişkili JSON yanıt zarfıyla bildirir. Kalıcı teknik gerçek
Git/GitHub'daki sürümlü dosyalardır; iletişim, karar kaynağı ve paylaşım kopyaları
Drive'dadır.

Private kod deposu: <https://github.com/Gebetto571/trading-os>

## Klasör yönleri

- ChatGPT → Codex: `01_CHATGPT_GELEN`
- Codex → ChatGPT: `02_CODEX_GELEN`
- Yaşayan kararlar ve merkezi Markdown fihristi: `03_KARARLAR`
- Mimari ve protokol: `04_TEKNIK_TASARIM`
- Tamamlanmış işler: `90_ARSIV`

## Codex'i çalıştırma

Codex Drive'ı kendiliğinden taramaz. Yerel Codex sohbetinde `Trading OS gelen kutusunu kontrol et` talimatı verildiğinde yeni görevleri alır, işler ve cevabı Drive'a bırakır.

Yeni `.md` açma, yeniden adlandırma, taşıma ve arşivleme kararlarında
`03_KARARLAR/00_SISTEM_KURALLARI` altındaki TOS-DEC-004 uygulanır. Rutin görev,
yanıt, durum ve teyitler Markdown değildir; JSON zarfı ve yerel veritabanıyla
izlenir.

Klasör kimlikleri ve yerel eşleme `config/drive-folders.json` dosyasında tutulur.
