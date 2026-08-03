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

## Sade çalışma modeli

Her görev, mevcut görev metninde aşağıdaki üç düzeyden biriyle sınıflandırılır;
ayrı form, dosya veya kayıt tablosu açılmaz:

- **FAST:** Tek veya birkaç mevcut belgede geri alınabilir yerel düzenleme. Varsayılan
  danışman sayısı `0`dır; yalnız hedef dosyalar ve ilgili bağlayıcı kural okunur,
  hedefli doğrulama yapılır.
- **STANDARD:** Birden fazla kanonik belgeyi veya sohbet alanını etkileyen düzenleme.
  Kısa etki haritası ve çelişki kontrolü yapılır. Gerçek ihtiyaç varsa tek görevlik,
  salt okunur danışman kullanılabilir.
- **STRICT:** Ürün veya test kodu, API/veri sözleşmesi, şema, migration,
  konfigürasyon, deployment, çalışan servis, güvenlik, Risk Guardian, execution ya
  da canlı işlem etkisi. Belge sohbeti uygulama yapmaz; Chief Engineer için görev
  kartı hazırlar ve kullanıcı devrini bekler.

Yerel düzenleme hattı mevcut belgeleri, karar kayıtlarını, sohbet–belge ilişkilerini,
görev kartlarını, dosya sahipliği ve yaşam döngüsü kayıtlarını doğrudan düzenleyebilir.
Kaynak veya test koduna; konfigürasyon, şema, migration ve deployment dosyalarına;
çalışan süreçlere veya canlı işlem yetkisine dokunamaz. Chief Engineer sürekli bir
belge kapısı değil, yalnız yazılım uygulama hattıdır.

Bağlam minimum tutulur: `AGENTS.md`, ilgili bağlayıcı karar veya sözleşme, hedef
dosyalar ve mevcut diff. İhtiyaç kanıtlanmadan proje tarihi veya ilgisiz sohbetler
taranmaz. Önce hedefli doğrulama yapılır; tam test yalnız ortak sözleşme, risk,
şema/migration, çapraz alan veya sürüm etkisinde Chief Engineer tarafından çalıştırılır.

Geçici danışmanlar dosya değiştiremez, bağlayıcı karar veremez ve raporları için
ayrı dosya açılmaz. Ana sohbet yalnız kabul ettiği bulguları sonuç özetine alır;
FAST işlerde danışman kullanılmaz ve aynı konu için kalıcı danışman rolü kurulmaz.

## Bulut sohbeti başladığında

1. Bu kartı ve `docs/communication-protocol.md` belgesini oku.
2. İşi FAST, STANDARD veya STRICT olarak sınıflandır. FAST ve STANDARD belge işini
   yetki sınırında doğrudan yürüt; STRICT işte Chief Engineer görev kartı hazırla.
3. STRICT işte veya yerel dosyaya erişim yoksa kullanıcıdan kartı ChatGPT proje
   kaynağına eklemesini ya da GitHub issue/commit/PR bağlantısıyla Chief Engineer'a
   devretmesini iste.
4. Bağlayıcı kararı önce ilgili sohbetin mevcut yaşayan kaydına işle; yeni
   Markdown ancak TOS-DEC-004 istisnasıyla açılabilir ve aynı işlemde merkezi
   fihriste kaydedilir.
5. API anahtarı, cüzdan sırrı, seed phrase veya erişim tokenı yazma.

## Yetki sınırı

Proje kaynağındaki sohbet mesajları kodu kendiliğinden değiştirmez. Chief Engineer
görevi ancak kullanıcının açık talimatından sonra alır, yerel Git alanında uygular
ve doğrular. Commit, push, PR veya merge ayrıca açıkça yetkilendirilmedikçe yapılmaz.
Kalıcı teknik gerçek yerel Git ve GitHub'daki sürümlü dosyalardır.

Drive'ın AI hafızası, görev/sonuç koordinasyonu ve katmanlar arası tek kanonik
sahip kuralları TOS-DEC-004 bölüm 7'de bağlayıcıdır. Eski Drive kod deposu yolları
geçersizdir; güncel `Trading OS` Drive hafıza alanı bu yasak kapsamında değildir.

Public kod deposu: <https://github.com/Gebetto571/trading-os>

## Devir yönleri

- ChatGPT → Chief Engineer: Drive `01_CHATGPT_GELEN` içindeki onaylı JSON görev zarfı
- Chief Engineer → ChatGPT: Drive `02_CODEX_GELEN` içindeki korelasyonlu sonuç zarfı
- Alternatif teknik referans: GitHub issue/commit/PR bağlantısı
- AI hafızası ve koordinasyon: güncel Drive `Trading OS` alanı
- Kalıcı kod ve Git-kanonik teknik belge: `/Users/scm/Projects/trading-os`
- Sürüm ve uzak yedek: public GitHub `Gebetto571/trading-os`

## Codex'i çalıştırma

Codex hiçbir kaynağı kendiliğinden taramaz. Kullanıcı “Kodlama emrini işleme koy”,
“Trading OS gelen kutusunu kontrol et” veya ilgili GitHub bağlantısını içeren
eşdeğer talimatı verdiğinde yalnız ilgili Drive görev zarfını ya da teknik referansı
kontrol eder. Periyodik kontrol yapılmaz.

Yeni `.md` açma, yeniden adlandırma, taşıma ve arşivleme kararlarında TOS-DEC-004
uygulanır. Mevcut köprü kullanılıyorsa görev, yanıt, durum ve teyitler yeni Markdown
yerine korelasyonlu JSON zarfla taşınır; sonuç geri okunmadan görev tamamlanmaz.

## Codex'e verilecek görev kartı

Bulut sohbetinin çıktısı aşağıdaki kısa kartla Codex'e devredilir:

```text
Trading OS için aşağıdaki görevi uygula.

Gönderen rol: <role_key>
Değişiklik modu: <FAST | STANDARD | STRICT>
Amaç: <tek cümle>
Kapsam: <dahil olanlar>
Kapsam dışı: <dokunulmayacaklar>
Kaynaklar: <Drive görev/araştırma kimliği veya GitHub bağlantıları>
Hedef yollar / aktif yazar: <yollar ve tek yazar>
Karar etkisi: <yok | mevcut TOS-DEC kimliği | docs-manager incelemesi>
Ajan politikası: <0 | gerekçeli geçici salt-okunur danışman>
Bağlam bütçesi: <okunacak asgari belgeler ve diff>
Kabul ölçütleri: <ölçülebilir maddeler>
Test kapsamı: <hedefli kontroller; gerekiyorsa tam test gerekçesi>
Risk/onay sınırı: <silme, dış erişim, canlı işlem vb.>
Durma koşulu: <çakışma, yetki veya kapsam aşımı>
Commit/push/merge yetkisi: <yok | açık kapsam>

TOS-DEC-004 dosya mimarisini uygula. Gereksiz yeni Markdown oluşturma.
Önce mevcut durumu doğrula; güvenli kapsamda uygula ve hedefli kanıtı bildir.
Periyodik kontrol başlatma.
```
