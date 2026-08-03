# Trading OS Bulut Kontrol Kartı

Bu belge ChatGPT bulut sohbetleri ile yerel Codex çalışma alanı arasındaki
kullanıcı denetimli devir kartıdır.

## Bulut sohbeti başladığında

1. Bu kartı ve `docs/communication-protocol.md` belgesini oku.
2. Codex'e yeni iş göndermek için amaç, kapsam, kabul kriterleri ve kaynakları
   içeren görev kartını hazırla.
3. Kullanıcıdan kartı ChatGPT proje kaynağına eklemesini veya GitHub issue/commit/PR
   bağlantısıyla Codex'e devretmesini iste.
4. Bağlayıcı kararı önce ilgili sohbetin mevcut yaşayan kaydına işle; yeni
   Markdown ancak TOS-DEC-004 istisnasıyla açılabilir ve aynı işlemde merkezi
   fihriste kaydedilir.
5. API anahtarı, cüzdan sırrı, seed phrase veya erişim tokenı yazma.

## Yetki sınırı

Proje kaynağındaki sohbet mesajları kodu kendiliğinden değiştirmez. Codex görevi
ancak kullanıcının açık talimatından sonra alır, yerel Git dalında uygular, test
eder ve sonucu commit/PR bağlantısı ile bildirir. Kalıcı teknik gerçek yerel Git
ve GitHub'daki sürümlü dosyalardır.

Private kod deposu: <https://github.com/Gebetto571/trading-os>

## Devir yönleri

- ChatGPT → Codex: kullanıcı tarafından eklenen proje kaynağı veya GitHub görev bağlantısı
- Codex → ChatGPT: kullanıcı aracılığıyla verilen commit/PR ve sonuç özeti
- Kalıcı kod ve belge: `/Users/scm/Projects/trading-os`
- Sürüm ve uzak yedek: private GitHub `Gebetto571/trading-os`

## Codex'i çalıştırma

Codex hiçbir kaynağı kendiliğinden taramaz. Kullanıcı “Trading OS proje kaynağındaki
görevi incele” veya ilgili GitHub bağlantısını içeren eşdeğer talimatı verdiğinde
görevi alır, işler ve sonucu kullanıcıya teslim eder.

Yeni `.md` açma, yeniden adlandırma, taşıma ve arşivleme kararlarında
TOS-DEC-004 uygulanır. Rutin görev,
yanıt, durum ve teyitler Markdown değildir; JSON zarfı ve yerel veritabanıyla
izlenir.
