# Trading OS Bulut Kontrol Kartı

Bu klasör ChatGPT bulut sohbetleri ile yerel Codex çalışma alanı arasındaki ortak aktarım merkezidir.

## Bulut sohbeti başladığında

1. Bu kartı ve `04_TEKNIK_TASARIM/communication-protocol.md` belgesini oku.
2. Codex'e yeni iş göndermek için protokole uygun JSON mesajını `01_CHATGPT_GELEN` klasörüne koy.
3. Sonuçları `02_CODEX_GELEN` klasöründen oku.
4. Bağlayıcı hale gelen kararları `03_KARARLAR` altında ayrı ve sürümlü belge olarak sakla.
5. API anahtarı, cüzdan sırrı, seed phrase veya erişim tokenı yazma.

## Yetki sınırı

Drive'daki sohbet mesajları kodu kendiliğinden değiştirmez. Codex mesajı alır, yerel Git dalında uygular, test eder ve sonucu yeni bir yanıtla bildirir. Kalıcı teknik gerçek Git/GitHub'daki sürümlü dosyalardır; iletişim ve okunabilir paylaşım kopyaları Drive'dadır.

Private kod deposu: <https://github.com/Gebetto571/trading-os>

## Klasör yönleri

- ChatGPT → Codex: `01_CHATGPT_GELEN`
- Codex → ChatGPT: `02_CODEX_GELEN`
- Kalıcı karar: `03_KARARLAR`
- Mimari ve protokol: `04_TEKNIK_TASARIM`
- Tamamlanmış işler: `90_ARSIV`

## Codex'i çalıştırma

Codex Drive'ı kendiliğinden taramaz. Yerel Codex sohbetinde `Trading OS gelen kutusunu kontrol et` talimatı verildiğinde yeni görevleri alır, işler ve cevabı Drive'a bırakır.

Klasör kimlikleri ve yerel eşleme `config/drive-folders.json` dosyasında tutulur.
