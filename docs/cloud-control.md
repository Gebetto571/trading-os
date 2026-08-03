# Trading OS Bulut Kontrol Kartı

Bu belge ChatGPT bulut sohbetleri ile yerel Codex çalışma alanı arasındaki
kullanıcı denetimli devir kartıdır.

## Yeni sohbetlere verilecek ana talimat

Mevcut sohbetlerin kullanıcı tarafından verilmiş ilk rol mesajları geçerlidir; bu
talimat mevcut sohbetlere yeniden rol vermek için kullanılmaz. Aşağıdaki tam talimat
yalnız yeni bir Trading OS sohbeti açılırken kullanılır. Köşeli alanlar göreve göre
doldurulur; diğer hükümler değiştirilmez.

```text
Trading OS projesinde çalışıyorsun.

Rolün: [cloud-planner / codex-dev / tanımlı uzman rolü]
Görevin: [tek cümlelik amaç]

Önce proje kaynağındaki AGENTS.md, Merkezi Dosya Yönetim Anayasası
(TOS-DEC-004), Sohbet Kimlik Defteri ve docs/cloud-control.md kurallarını uygula.

Dosya kuralları:
1. Yeni Markdown dosyası oluşturma. Önce uygun mevcut dosyayı belirle.
2. Merkezi kural, fihrist, sohbet sicili ve yaşayan sohbet kayıtlarına doğrudan
   yazma; güncelleme önerisini docs-manager rolündeki ana ajana teslim et.
3. Kodun hedef klasörünü TOS-DEC-004 yönlendirme tablosundan seç. Emin değilsen
   klasör tahmin etme.
4. Görev, yanıt, kısa durum ve teyidi Markdown dosyasına dönüştürme.
5. Ham veri, veritabanı, sır, token ve çalışma çıktısını GitHub'a gönderme.
6. Periyodik kontrol yapma; yalnız benim açık talimatımla kontrol et.

Çalışmanın sonunda şunları bildir:
- rolün ve yaptığın iş,
- kullanılan veya güncellenmesi önerilen mevcut dosyalar,
- kod hedefi,
- doğrulama kanıtı,
- risk veya engel,
- Codex'e ya da docs-manager'a devredilecek sonraki eylem.

Yerel dosyaya veya Codex'e doğrudan erişimin yoksa erişiyormuş gibi davranma.
Codex için uygulanabilir bir görev kartı hazırla ve kullanıcı devrini bekle.
```

Bu ana talimat yeni sohbet başına bir kez verilir. Mevcut sohbetlere tekrar
gönderilmez. Mevcut sohbetin ilişkili ana belgeleri
`docs/decisions/system/TOS-CHAT-REGISTRY__v1.0.md` içindeki ilişki matrisinden
okunur. Kullanıcı rolü açıkça değiştirmedikçe yalnız yeni görev verilir; ortak dosya
talimatı rol değişikliği sayılmaz.

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

Public kod deposu: <https://github.com/Gebetto571/trading-os>

## Devir yönleri

- ChatGPT → Codex: kullanıcı tarafından eklenen proje kaynağı veya GitHub görev bağlantısı
- Codex → ChatGPT: kullanıcı aracılığıyla verilen commit/PR ve sonuç özeti
- Kalıcı kod ve belge: `/Users/scm/Projects/trading-os`
- Sürüm ve uzak yedek: public GitHub `Gebetto571/trading-os`

## Codex'i çalıştırma

Codex hiçbir kaynağı kendiliğinden taramaz. Kullanıcı “Trading OS proje kaynağındaki
görevi incele” veya ilgili GitHub bağlantısını içeren eşdeğer talimatı verdiğinde
görevi alır, işler ve sonucu kullanıcıya teslim eder.

Yeni `.md` açma, yeniden adlandırma, taşıma ve arşivleme kararlarında
TOS-DEC-004 uygulanır. Rutin görev,
yanıt, durum ve teyitler Markdown değildir; JSON zarfı ve yerel veritabanıyla
izlenir.

## Codex'e verilecek görev kartı

Bulut sohbetinin çıktısı aşağıdaki kısa kartla Codex'e devredilir:

```text
Trading OS için aşağıdaki görevi uygula.

Gönderen rol: <role_key>
Amaç: <tek cümle>
Kapsam: <dahil olanlar>
Kapsam dışı: <dokunulmayacaklar>
Kaynaklar: <proje kaynağı veya GitHub bağlantıları>
Önerilen mevcut dosyalar: <yollar>
Kod hedefi: <yol veya docs-manager kararı gerekli>
Kabul ölçütleri: <ölçülebilir maddeler>
Risk/onay sınırı: <silme, dış erişim, canlı işlem vb.>

TOS-DEC-004 dosya mimarisini uygula. Gereksiz yeni Markdown oluşturma.
Önce mevcut durumu doğrula; güvenli kapsamda uygula, test et ve sonucu commit/PR
ile bildir. Periyodik kontrol başlatma.
```
