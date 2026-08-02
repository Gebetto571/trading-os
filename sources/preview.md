---
id: TOS-DEC-001
title: Trading OS Bot Çalışma Sistemi ve Kârlılık Disiplini
status: accepted
version: 0.1
date: 2026-08-02
language: tr
scope:
  - trading-engine
  - strategy-lab
  - risk
  - execution
  - control-api
  - control-panel
  - platform-adapters
  - production-ops
  - ai-supervisor
  - tests
---

# Trading OS Bot Çalışma Sistemi ve Kârlılık Disiplini

> Bu kart proje kaynağına eklendiği anda bağlayıcıdır. Sohbet mesajları bu kartı değiştirmez. Değişiklik ancak gerekçeli yeni sürüm veya yeni karar kartıyla yapılır.

## 1. Tek cümlelik karar

Trading OS; yalnızca bütün maliyetlerden sonra ölçülebilir pozitif beklenti taşıyan fırsatları seçen, stratejiyi riskten ve emir yürütmeden ayıran, teknik gerçeklik belirsizleştiğinde yeni risk almayan ve canlı sermayeyi yalnız kanıt geldikçe büyüten ortak bir Rust işlem motoru olacaktır.

## 2. Gerçekçi hedef

Amaç en fazla işlemi yapmak, yüksek kazanma oranı göstermek veya brüt kâr üretmek değildir.

Amaç:

1. Ücret, kayma, ters seçilim, fonlama, hedge, settlement ve sermaye kilitlenmesi sonrasında pozitif net beklenti bulmak.
2. Sermayeyi aynı anda görülen fırsatlar içinde en iyi risk/getiri oranına sahip olanlara vermek.
3. Tek bir kötü olayın veya teknik arızanın sistemi kalıcı olarak yaralamasını engellemek.
4. Strateji avantajı zayıfladığında geçmiş kâra bağlanmadan küçülmek veya durmak.
5. Uzun vadeli bileşik sermaye büyümesini, önceden kabul edilmiş düşüş sınırları içinde artırmak.

Bu mimari kârı garanti etmez. Avantajı olmayan bir stratejiyi güvenli biçimde çalıştırmak yine para kaybettirir. Bu kartın ekonomik savunması şudur:

> Kanıtlanmış avantaj yoksa işlem yok; avantaj zayıfsa küçük işlem; canlı kanıt güçlendikçe kontrollü büyüme.

## 3. Kapsam ve kapsam dışı

Bu kart şunları bağlar:

- Botun ana karar ve emir akışı
- Çalışma durumları ve arıza davranışı
- İşlem kabulü, piyasa seçimi ve sermaye tahsisi
- Risk sınırları
- Backtest, paper ve canlıya geçiş kapıları
- Kontrol API’si, panel ve AI yetki sınırları
- Acil durdurma, restart ve mutabakat
- Performans ölçümü ve strateji bozunma kuralları

Bu kart şunları tek başına belirlemez:

- Her platformun güncel ücret, tick, lot, seans ve API ayrıntıları
- Her stratejinin adil değer modeli ve parametreleri
- Kullanıcının ayıracağı toplam gerçek sermaye
- Vergi ve hukuki yükümlülükler
- Her platformda native dead-man özelliğinin bulunup bulunmadığı

Bu ayrıntılar ilgili platform ve strateji kartlarında tanımlanır; bu karttaki güvenlik ve kârlılık kapılarını gevşetemez.

## 4. Bağlayıcı mimari

Canlı karar hattı:

    Piyasa verisi
        → Normalizasyon ve veri kalite kontrolü
        → Özellikler / adil değer
        → Strateji
        → TradeIntent
        → Ekonomik kapı ve Capital Allocator
        → Risk Authority
        → Execution
        → Platform adaptörü
        → Emir / fill / iptal / settlement
        → Mutabakat ve P&L

### 4.1. Tek otoriteler

- Strateji yalnız TradeIntent üretir; doğrudan emir gönderemez.
- Risk Authority normal işlem hattında yeni riske son izin veren tek otoritedir.
- Emergency-flatten normal işlem hattı değildir; yalnızca riski kesin olarak azaltan eylemlere izin verebilen ayrı ve küçük Flatten Guard’dan geçer.
- Execution yalnız geçerli risk izni ve rezervasyonu bulunan emri gönderebilir.
- Platform adaptörü platform dilini ortak çekirdeğe çevirir; ortak strateji veya risk kuralı yazamaz.
- Motorun mutabakat sonucu sistem gerçeğidir; paneldeki eski görüntü sistem gerçeği değildir.

### 4.2. Üç kod sınırı

| Sınır | Görev | Yasak |
|---|---|---|
| Rust işlem çekirdeği | Veri, strateji, risk, emir, portföy, mutabakat | React veya HTTP’ye bağımlı olmak |
| Axum kontrol adaptörü | Kimlik, yetki, sürümlü komut ve görünüm API’si | İkinci bir strateji/risk motoru olmak |
| React + TypeScript panel | İzleme ve komut talebi | Anahtar saklamak, platforma bağlanmak, doğrudan emir vermek |

İlk sürümde Rust çekirdeği ve Axum aynı süreçte çalışabilir. Bu, iş mantıklarının birleşmesi anlamına gelmez. Axum görevleri gözetimli, kaynakları sınırlı ve canlı emir hattından geri basınç açısından ayrılmış olmalıdır. API panic’i, yavaş istemci, dolu telemetri kanalı veya bağlantı seli bütün motor sürecini düşüremez ya da canlı hattı bloke edemez. Ölçülmüş ihtiyaç olmadan mikroservis, Kubernetes, Kafka, Redis veya benzeri yeni altyapı eklenmez.

### 4.3. Ortak çekirdek, farklı ürün kuralları

İlk adaptör Polymarket’tir. Ortak çekirdek daha sonra kripto spot, kripto perpetual ve BIST/hisse ürünlerini taşıyabilmelidir.

| Ürün | Adaptör/ürün kuralında kalacak fark |
|---|---|
| Tahmin piyasası | Sonuç kontratı, azami ödeme/kayıp, resolution ve settlement |
| Kripto spot | Base/quote rezervasyonu, 7/24 piyasa |
| Kripto perpetual | Marjin, kaldıraç, fonlama, tasfiye |
| BIST/hisse | Seans, lot/tick, fiyat sınırı, aracı kurum ve takas |

Bütün piyasalara tek bir emir, pozisyon veya risk modeli zorlanmaz. Ortak çekirdek yetenekleri sorar; ürün modülü en kötü durum kaybını ve geçerli eylemleri hesaplar.

## 5. Birbirinden ayrı üç çalışma ekseni

### 5.1. Deney/sermaye modu

| Mod | Gerçek emir | Amaç |
|---|---:|---|
| BACKTEST | Hayır | Tarihsel hipotez testi |
| REPLAY | Hayır | Gerçek olay sırası ve motor davranışı |
| PAPER | Hayır | Canlı veriyle uçtan uca prova |
| LIVE_CANARY | Evet, çok küçük | Gerçek dolum ve maliyet ölçümü |
| LIVE | Evet, onaylı sınırda | Kanıtlanmış tahsis |

Kodun güvenli varsayılanı PAPER’dır. LIVE ve LIVE_CANARY açık insan onayı, sermaye limiti ve onaylanmış strateji sürümü olmadan açılamaz.

### 5.2. Motor durumu

Durum her venue + account çalışma alanı için tutulur. Ortak risk gerçeği bozulursa global durum bütün alanları ezer.

| Durum | Yeni risk | İptal | Fill işleme | Mutabakat |
|---|---:|---:|---:|---:|
| NORMAL | İzinli | İzinli | Zorunlu | Sürekli |
| RECONCILING | Yasak | İzinli | Zorunlu | Zorunlu |
| HALTED | Yasak | İzinli | Zorunlu | Zorunlu |

### 5.3. Yönetim bağlantısı

Yönetim bağlantısı motor durumundan ayrıdır:

- CONNECTED: Kontrol API’si ulaşılabilir.
- UNATTENDED: Kontrol API’si/panel ulaşılamıyor.

UNATTENDED tek başına botu durdurmaz. Motor kritik sağlık kontrolleri geçiyorsa son atomik ve onaylanmış ayar sürümüyle çalışır.

## 6. Değişmez çalışma kuralları

1. Panel, Axum, AI veya raporlama canlı emir hattının zorunlu bağımlılığı değildir.
2. Panel/API kesilince son onaylanmış ayarlar devam eder; yeni ayar alınmaz ve alarm üretilir.
3. Eski fiyat, bozuk saat, bilinmeyen emir sonucu veya uyuşmayan pozisyonla yeni risk alınamaz.
4. Belirsiz emir reddedilmiş, iptal edilmiş veya risksiz kabul edilemez.
5. İptal isteğinin gönderilmesi, iptalin gerçekleştiği anlamına gelmez.
6. Cancel, fill işleme ve mutabakat hiçbir motor durumunda engellenmez.
7. Motor açılışta doğrudan NORMAL olamaz.
8. HALTED kendiliğinden kalkamaz.
9. Acil durdurma mevcut pozisyonları kendiliğinden kapatmaz.
10. AI canlı emir oluşturamaz, limit yükseltemez, strateji açamaz, sistemi unhalt edemez ve kod dağıtamaz.
11. Martingale ve kaybettikçe pozisyon büyütme yasaktır.
12. Backtest kârı tek başına canlı işlem yetkisi vermez.
13. Kazanma oranı tek başına başarı ölçüsü değildir.
14. Açık, iptali doğrulanmamış ve belirsiz emirler risk hesabına dahildir.
15. Kâr üreten fakat ölçülemeyen strateji büyütülmez.

## 7. Ana denetim algoritması

    HER OLAYDA VE DÜZENLİ SAĞLIK KONTROLÜNDE:

    1. Fill, execution report, iptal cevabı ve settlement olaylarını
       motor durumundan bağımsız olarak işle.

    2. Kalıcı halt kilidi varsa veya EMERGENCY_STOP alındıysa:
          HALTED uygula.
          Yeni intent, rezervasyon, submit ve retry işlemlerini reddet.
          İptal ve mutabakata devam et.
          İşlem üretme bölümünü atla.

    3. Risk Authority, ortak saat, global portföy gerçeği,
       yapılandırma bütünlüğü veya kritik kalıcı kayıt sağlıksızsa:
          GLOBAL HALTED uygula.

    4. Her venue + account alanı için:
          Piyasa verisi eskiyse,
          veri sırası bozuksa,
          platform emir kanalı belirsizse,
          submit/cancel sonucu bilinmiyorsa,
          veya emir, bakiye ve pozisyon kayıtları uyuşmuyorsa:

              Alanı RECONCILING yap.
              Yeni riski engelle.
              Risk artırabilecek açık emirleri iptal etmeye çalış.
              Rezervasyonları kesin sonuç alınana kadar koru.
              Platform gerçeğini yeniden sorgula.

          Alan RECONCILING ise ve bütün kritik sağlık kontrolleri ile
          mutabakat kesin olarak doğrulanmışsa:

              Alanı NORMAL yap.

    5. Kontrol API’si ulaşılamıyorsa:
          Yönetim durumunu UNATTENDED yap.
          Motor durumunu sırf bu nedenle değiştirme.
          Son onaylanmış ayar sürümünü koru.
          Yeni ayar kabul etme.
          Alarm üret.

    6. Yalnız NORMAL alanlarda ekonomik seçim ve strateji üretimine izin ver.

Sorun bağımsız biçimde sınırlandırılabiliyorsa yalnız ilgili venue/account karantinaya alınır. Ortak portföy, ortak risk motoru veya durumun kapsamı belirsizse global güvenli durum uygulanır.

## 8. Risk artıran eylemin ortak tanımı

Bir emir veya eylem, ürün modülünün hesapladığı makul kötü senaryolarda portföyün en kötü durum kaybını artırıyorsa risk artırandır.

    risk_artiriyor =
        emir_sonrasi_en_kotu_kayip
        > mevcut_en_kotu_kayip + hesap_toleransi

Bu tanım nominal emir büyüklüğünden üstündür. Örneğin hedge gibi görünen bir emir yanlış ürün, yetersiz miktar veya execution riski nedeniyle toplam kötü durum kaybını artırabilir.

RECONCILING ve HALTED durumlarında varsayılan olarak yalnız:

- Cancel
- Fill ve execution işleme
- Mutabakat
- Açıkça onaylanmış ayrı emergency-flatten akışı

çalışabilir.

## 9. Ekonomik işlem kapısı

Her TradeIntent için muhafazakâr net avantaj hesaplanır:

    Muhafazakâr Net Avantaj
      = Beklenen brüt kazanç
      - platform ücretleri
      - beklenen kayma ve market impact
      - ters seçilim maliyeti
      - fonlama / borrow / hedge maliyeti
      - settlement ve zincir maliyeti
      - sermayenin kilitli kalma maliyeti
      - model belirsizlik payı

İşlem ancak aşağıdaki koşulların tamamında aday olabilir:

1. Muhafazakâr Net Avantajın güven alt sınırı sıfırdan büyüktür.
2. Maliyetler stres senaryosunda büyütüldüğünde avantaj tamamen kaybolmaz.
3. En kötü durum kaybı güvenilir biçimde hesaplanabilir.
4. Veri güncel ve tutarlıdır.
5. Çıkış, vade veya settlement planı vardır.
6. Piyasa ve korelasyon limitleri uygundur.
7. Emir gerçek uygulanabilir fiyat ve derinlik üzerinden hesaplanmıştır.
8. İlgili alan NORMAL durumundadır.

Brüt sinyal, yüksek kazanma oranı veya teorik arbitraj tek başına yeterli değildir.

### 9.1. Fırsat sıralama

Risk kapısını geçen fırsatlar şu sırayla değerlendirilir:

1. En yüksek muhafazakâr net getiri / en kötü durum kaybı
2. Daha kısa ve güvenilir sermaye kilitlenme süresi
3. Mevcut portföyle daha düşük kötü-senaryo korelasyonu
4. Daha yüksek gerçek likidite ve daha düşük execution belirsizliği

Sermaye her pozitif sinyale dağıtılmaz. Risk bütçesi dolduğunda daha düşük skorlu fırsat elenir.

### 9.2. Piyasa eleme filtresi

Aşağıdakilerden biri varsa piyasa işleme kapatılır:

- Resolution/settlement şartı yorumlanamayacak kadar belirsizse
- Gerçek alış/satış fiyatında yeterli derinlik yoksa
- Fiyat, emir, fill veya settlement verisi güvenilir değilse
- Kötü durum kaybı hesaplanamıyorsa
- Mevcut portföyle aynı kötü senaryoda aşırı yoğunlaşma yaratıyorsa
- Çıkış veya vade sonuna kadar taşıma planı yoksa
- Beklenen sermaye getirisi, seçilmiş risksiz kıstas ve gerekli risk primini aşmıyorsa
- Platform/saklama riski kabul edilen sınırı aşıyorsa

Pilot varsayılanında tek emir büyüklüğü, görünen uygulanabilir derinliğin yüzde 10’unu ve uygun yakın dönem hacmin yüzde 5’ini aşamaz. Görünen derinlik dolum garantisi değildir; yalnız kapasite tavanıdır. Strateji kartı daha düşük sınır koyabilir; daha yüksek sınır için canlı execution kanıtı gerekir.

## 10. İlk ekonomik hipotez: seçici piyasa yapıcılık

v0.1’in ilk test edilecek Polymarket hipotezi, her piyasada sürekli emir vermek değil; yalnız temiz resolution şartı, yeterli likidite ve ölçülebilir net avantaj bulunan piyasalarda çalışan likidite-duyarlı piyasa yapıcılıktır.

### 10.1. Teklif üretimi

Her iki taraf ayrı değerlendirilir:

    Maker alış avantajı = adil değer - önerilen bid limit fiyatı
    Maker satış avantajı = önerilen ask limit fiyatı - adil değer

    Taker alış avantajı = adil değer - uygulanabilir ask fiyatı
    Taker satış avantajı = uygulanabilir bid fiyatı - adil değer

    Gerekli minimum avantaj
      = ücret
      + beklenen ters seçilim
      + volatilite tamponu
      + model belirsizliği
      + inventory maliyeti
      + hedef net kâr

Yalnız ilgili tarafın avantajı gerekli minimum avantajı geçiyorsa emir üretilebilir.

### 10.2. Davranış kuralları

- Volatilite ve model belirsizliği yükselince teklif aralığı genişler, miktar küçülür.
- Inventory bir yönde büyüyünce aynı yöndeki yeni emirler geri çekilir; azaltıcı taraf öncelik kazanır.
- Inventory limite yaklaşınca çift taraflı teklif yerine yalnız azaltıcı taraf kalabilir.
- Ani fiyat/veri şoku algılanınca risk artıran emirler iptal edilir ve soğuma + mutabakat tamamlanana kadar yeni emir üretilmez.
- Vade/sonuçlandırma yaklaştıkça resolution ve sermaye kilidi riski ayrıca fiyatlanır.
- Likidite alan taker emirleri yalnız pasif emre göre belirgin biçimde daha yüksek muhafazakâr avantaj varsa kullanılabilir.
- Teorik arbitrajda bütün bacaklar, hedge gecikmesi ve başarısız bacak senaryosu fiyatlanmadan işlem yapılmaz.
- Momentum, ortalamaya dönüş ve yeni arbitraj türleri ayrı strateji kartı ve kabul testi olmadan canlı sermaye alamaz.

Bu bölüm bir kârlılık garantisi değil, test edilecek ilk ekonomik hipotezdir. Test kapılarından geçmezse mimari korunur; strateji rafa kaldırılır.

## 11. TradeIntent ve emir gönderme kapısı

Her TradeIntent en az şunları taşır:

- Benzersiz intent ve strateji kimliği
- Strateji/model sürümü
- Venue, account ve ürün
- Yön, miktar, limit fiyat ve yaşam süresi
- Beklenen brüt ve muhafazakâr net avantaj
- Kullanılan maliyet varsayımları
- En kötü durum kaybı
- Adil değer zamanı ve veri tazeliği
- Yapılandırma sürümü
- Risk dönem/epoch numarası
- İdempotency anahtarı

Emir gönderme algoritması:

    TRADEINTENT GELDİĞİNDE:

    1. Alan NORMAL değilse reddet.
    2. Ekonomik işlem kapısı geçmediyse reddet.
    3. Risk Authority limit, korelasyon, bakiye, inventory,
       açık/belirsiz emir ve kötü durum kaybını kontrol etsin.
    4. Risk izni yoksa reddet; gerekirse miktarı küçült.
    5. Sermaye ve risk rezervasyonunu emirden önce yap.
    6. Güncel risk epoch numarasını emre ekle.
    7. Kritik kimlik, rezervasyon ve submit niyetini
       crash sonrasında okunabilir biçimde kalıcılaştır.
    8. Emri gönderim kuyruğuna al.
    9. Ağ gönderiminden hemen önce atomik olarak tekrar kontrol et:
          - Global veya hedefli halt yok
          - Alan hâlâ NORMAL
          - Risk epoch güncel
          - Rezervasyon geçerli
          - Veri ve kritik sağlık hâlâ geçerli
   10. Kontrollerden biri başarısızsa gönderme.
   11. Başarılıysa benzersiz client order/idempotency kimliğiyle gönder.
   12. Timeout veya belirsiz cevapta kör retry yapma;
       durumu UNKNOWN kabul et ve mutabakata geç.

Gönderim öncesi son kontrol ile emergency-stop aynı atomik sıralama kapısından geçmelidir. Böylece durdurmadan önce kuyrukta kalan emir dışarı kaçamaz.

## 12. Muhafazakâr başlangıç risk bütçesi

Yüzdeler kullanıcının Trading OS’a açıkça ayırdığı bot sermayesi üzerinden hesaplanır; kullanıcının toplam malvarlığı üzerinden değil.

| Risk | Pilot üst sınır |
|---|---:|
| Tek bağımsız işlem kararı | Bot sermayesinin yüzde 0,25’i en kötü kayıp |
| Tek piyasa/kontrat | Yüzde 1 en kötü toplam kayıp |
| Aynı kötü senaryoda kaybeden olay kümesi | Yüzde 2 |
| Yuvarlanan 24 saatlik gerçekleşmiş + muhafazakâr açık zarar | Yüzde 1 |
| Yuvarlanan yedi günlük zarar | Yüzde 2,5 |
| Zirveden toplam sermaye düşüşü | Yüzde 5 |
| Pilot dönemde serbest rezerv | En az yüzde 50 |

Uygulama:

- Her strateji kendi onaylı zarar bütçesini aşarsa o strateji yeni riske kapanır.
- Portföyün yuvarlanan 24 saatlik yüzde 1 limiti aşılırsa bütün yeni risk global durur.
- Portföyün yedi günlük limiti aşılırsa bütün yeni risk global durur ve yeniden yetkilendirme gerekir.
- Zirveden yüzde 5 düşüşte bütün yeni risk global olarak durur.
- Bir stratejinin olağan dalgalanması bu sınırları aşıyorsa limit yükseltilmez; pozisyon küçültülür.
- Kademeli alım yalnız toplam kötü durum kaybı baştan ayrılmışsa kullanılabilir.
- Kaldıraç v0.1’de kapalıdır. Perpetual ürünler ayrı marjin/tasfiye kartı onaylanmadan LIVE olamaz.
- Tek platformda tutulan fon için ayrıca platform/saklama tavanı belirlenmeden LIVE açılamaz.

Bu sayısal pilot sınırlar, kanıt sunan yeni bir risk karar kartıyla değiştirilebilir. Panel veya AI tarafından sessizce yükseltilemez.

## 13. Stratejinin canlıya kabul protokolü

Hiçbir strateji şu sırayı atlayamaz:

    Hipotez
      → Veri kalite testi
      → Backtest / walk-forward
      → Out-of-sample
      → Replay
      → Paper
      → LIVE_CANARY
      → Sınırlı LIVE
      → Kanıtlanmış tahsis

### 13.1. Backtest kabul şartları

- Gelecek verisi sızıntısı yoktur.
- Ücret, spread, kayma, gecikme, sıra önceliği, kısmi dolum ve gerçekleşmeyen iptal modellenmiştir.
- Parametre seçimi out-of-sample veriyi görmeden yapılmıştır.
- Denenen model ve parametre sayısı kaydedilmiş; çoklu deneme/data-snooping etkisi hesaba katılmıştır.
- En az üç ayrı zaman/olay/rejim diliminin çoğunda maliyet sonrası sonuç pozitiftir.
- Birleşik out-of-sample net beklentinin yüzde 95 güven alt sınırı sıfırın üzerindedir.
- Ücret, kayma ve gecikme iki kat streslendiğinde net beklenti negatif olmaz ve düşüş onaylı pilot risk bütçesini aşmaz.
- Sonuç tek piyasa, tek olay veya birkaç şanslı işlemden gelmez.
- Parametre komşuluklarında sonuç çökmez; tek sivri optimum kabul edilmez.
- Test düşüşü, kapasitesi ve sermaye kilitlenmesi raporlanır.

### 13.2. Paper gerçeği

Paper aşaması veri, karar, risk, panel ve kayıt zincirinin çalıştığını kanıtlar. Özellikle maker stratejisinde gerçek sıra önceliği ve dolum kalitesini kanıtlamaz. Bu nedenle paper’dan sonra mikro canlı zorunludur.

### 13.3. LIVE_CANARY ve ölçekleme

- Başlangıç canary tahsisi, hedef strateji tahsisinin en fazla yüzde 1–5’idir ve ayrıca kullanıcı tarafından mutlak para tavanı ile onaylanır.
- Varsayılan ölçekleme değerlendirmesi için en az 30 canlı gün ve 100 bağımsız karar kümesi gerekir.
- Canlı ücret ve execution maliyeti model tahmininden yüzde 25’ten fazla sapmamalıdır.
- Canlı maliyet sonrası beklenti pozitif kalmalıdır.
- Tek olay toplam canlı kârın yüzde 25’inden fazlasını oluşturmamalıdır.
- Tahsis tek adımda en fazla iki katına çıkabilir ve iki artış arasında en az yedi gün bulunur.
- Tam tahsis için varsayılan olarak en az 300 bağımsız canlı karar kümesi gerekir.

Düşük frekanslı stratejide gözlem sayısı istatistiksel olarak oluşmuyorsa strateji reddedilmek zorunda değildir; deneysel kalır ve büyütülmez. İstisna ancak ayrı deney kartıyla açıkça onaylanır.

## 14. Canlı bozunma ve otomatik küçülme

| Gözlenen durum | Zorunlu eylem |
|---|---|
| Canlı execution maliyeti modelden yüzde 25 yüksek | Yeni tahsisi yarıya indir, inceleme başlat |
| Maliyet farkı yüzde 50’yi aşar | Stratejiyi yeni riske kapat |
| Son 100 bağımsız kararda net beklenti negatif | Stratejiyi yeni riske kapat, neden analizi |
| Net beklentinin yüzde 95 güven aralığı üst sınırı dahi sıfır veya altı | Stratejiyi rafa kaldır |
| Canlı düşüş, stres backtest düşüşünün 1,5 katını aşar | Stratejiyi durdur |
| Tek olay toplam kârın yüzde 25’inden fazlasını oluşturur | Ölçekleme yasağı |
| Emir/pozisyon mutabakat farkı | İlgili alan RECONCILING |
| Risk motoru veya piyasa verisi güvenilmez | Yeni risk anında durur |

Limit ihlali sonrasında bot kendiliğinden büyümez veya normale dönmez. İnsan incelemesi, neden kaydı ve sürümlü yeniden yetkilendirme gerekir.

## 15. Acil durdurma

Emergency-stop’un amacı:

1. Yeni riskin motordan çıkmasını atomik olarak kesmek.
2. Açık ve belirsiz emirleri iptal etmeye çalışmak.
3. Geç fill’leri kaybetmeden gerçek durumu doğrulamak.
4. İnsan onayı olmadan yeniden başlamamaktır.

Algoritma:

    EMERGENCY_STOP ALINDIĞINDA:

    1. Tek atomik kritik bölümde:
          - submit kapısını kapat,
          - risk/emir epoch numarasını artır,
          - hedef alanı veya global sistemi bellekte HALTED yap.
    2. Yeni intent, rezervasyon, submit ve retry işlemlerini reddet.
    3. Kalıcı halt kilidini güvenli depoya yaz ve kalıcılığını doğrula.
    4. Kalıcı yazım başarısızsa bellekte HALTED kal,
       HALT_NOT_DURABLE alarmı üret ve “durable halt” cevabı verme.
    5. Stratejilerin yeni emir üretmesini durdur.
    6. Açık ve durumu belirsiz emirleri öncelikli kanaldan iptal etmeye çalış.
    7. Geç fill ve execution olaylarını işlemeye devam et.
    8. Emir, bakiye ve pozisyon mutabakatı yap.
    9. İptali doğrulanamayan emirleri ve kalan pozisyonları açıkça bildir.
   10. İnsan onayı olmadan halt kilidini kaldırma.

Tek bir “başarılı” mesajı kullanılamaz:

- HALT_ACCEPTED: Yeni risk motor içinde bloke edildi.
- HALT_DURABLE: Halt kilidi kalıcı depoda doğrulandı.
- HALT_NOT_DURABLE: Yeni risk bellekte bloke, fakat kalıcı kilit doğrulanamadı.
- CANCELING: Açık/belirsiz emir iptalleri sürüyor.
- CANCEL_VERIFIED: Platform iptalleri doğruladı.
- CANCEL_UNVERIFIED: Kesin platform doğrulaması alınamadı.
- RESIDUAL_POSITION: Mevcut pozisyon riski devam ediyor.

### 15.1. Erişim yolları

- Panelde emergency-stop düğmesi
- Yerel tradingctl emergency-stop komutu
- İşletim sistemi SIGTERM ile güvenli durdurma akışı
- Platform destekliyorsa native dead-man / cancel-on-disconnect
- Makine tamamen kaybolursa ayrı cihaz ve ağ üzerinden platformda manuel iptal ve API anahtarını devre dışı bırakma

Panel ile yerel komut iki farklı giriş olsa da aynı makine arıza alanındadır. Gerçek bağımsız savunma platform mekanizması veya ayrı cihaz/ağ müdahalesidir.

Makine platforma erişemiyorsa ve platform native koruma sunmuyorsa, yerel yazılım açık emirlerin iptalini garanti edemez.

### 15.2. Emergency-flatten

Emergency-stop açık pozisyonları otomatik satmaz. Pozisyon kapatma:

- Ayrı emergency-flatten komutudur.
- Yanlışlıkla çalıştırılması daha zor, iki aşamalı onay ister.
- Normal Risk Authority’den bağımsız küçük bir Flatten Guard kullanır.
- Flatten Guard yalnız bütün makul kötü senaryolarda toplam riski kesin olarak azaltan, miktar ve fiyat sınırı bulunan emirleri kabul eder.
- Riskin azaldığı güvenilir biçimde kanıtlanamıyorsa veya Flatten Guard sağlıksızsa otomatik emir göndermez; manuel platform müdahalesi gerekir.
- Piyasa etkisi ve limit fiyat koruması kullanır.
- Kısmi kapanma, hedge başarısızlığı ve platform kesintisini raporlar.
- Sonucun tüm riski kapattığı mutabakatla doğrulanmadan “flat” göstermez.

## 16. Restart ve güvenli kapanış

Motor açılırken:

    Eğer kalıcı halt kilidi varsa:
        HALTED başla.
    Eğer önceki kapanış temiz değilse, halt deposu doğrulanamıyorsa
    veya HALT_NOT_DURABLE ihtimali varsa:
        HALTED başla ve insan incelemesi iste.
    Aksi hâlde:
        RECONCILING başla.
        Açık/belirsiz emirleri, bakiyeleri, pozisyonları,
        config sürümünü ve risk rezervasyonlarını doğrula.
        Yalnız mutabakat tamamlanınca NORMAL ol.

HALTED durumundan devam:

    Yetkili insan devam onayı
        → halt kilidini kontrollü kaldır
        → RECONCILING
        → tam sağlık ve mutabakat
        → NORMAL

Doğrudan HALTED → NORMAL geçişi yasaktır.

SIGTERM yeni riski kesen, mümkünse açık emirleri iptal eden, mutabakat yapan ve durumu kalıcılaştıran güvenli kapanışı başlatır. SIGKILL yalnız son çaredir; güvenli durdurma sayılmaz.

## 17. Kontrol API’si ve ayar güvenliği

Her değiştirici komut şunları taşır:

- Benzersiz command_id
- İsteyen kullanıcı ve rol
- Zaman
- Beklenen mevcut config sürümü
- Yeni atomik config sürümü
- Gerekçe
- İdempotency anahtarı

Kurallar:

- Eski ekran, beklenen config sürümü uyuşmuyorsa yeni ayarı yazamaz.
- Aynı komut tekrar gelirse ikinci kez uygulanmaz.
- Limit azaltma tek onayla yapılabilir.
- Limit artırma, LIVE açma, unhalt ve emergency-flatten güçlü yeniden doğrulama ve açık onay ister.
- Bütün komutlar değiştirilemez audit kaydına yazılır.
- Kontrol API’si açık internete sunulmaz; özel ağ, şifreli bağlantı ve rol tabanlı yetki kullanır.
- API’ye özel sürümlenmiş görünüm modelleri kullanılır; Rust iç modelleri doğrudan JSON sözleşmesi yapılmaz.
- Frontend platform anahtarına, doğrudan order metoduna veya veritabanı yazma yetkisine sahip olamaz.

## 18. Veri ve kalıcılık

- Sıcak karar hattı bellek içinde çalışır; PostgreSQL, panel veya AI gecikmesi emri bloke edemez.
- Kritik emir kimliği, risk rezervasyonu, submit niyeti, fill, config sürümü ve halt kilidi crash sonrasında yeniden okunabilir biçimde kalıcı olmalıdır.
- PostgreSQL olayların, emirlerin, fill’lerin, pozisyonların, config’lerin, P&L ve audit kayıtlarının ortak kalıcı kaynağıdır; sıcak hattaki zorunlu senkron bağımlılık değildir.
- Analiz/replay için Parquet kullanılabilir.
- PostgreSQL geçici olarak kapalıyken kritik yerel kalıcı kayıt ve güvenli kuyruk sağlamsa motor yalnız açıkça yapılandırılmış max_offline_duration, max_buffer_events ve max_buffer_bytes sınırları içinde alarm vererek devam edebilir.
- Bu üç sınırın biri tanımsızsa PostgreSQL kaybında varsayılan davranış yeni risk almamaktır.
- Sınırların biri aşılırsa veya kritik kalıcı kayıt yapılamıyorsa yeni risk durur.
- Market data sıralama boşluğu, tekrar, zaman gerilemesi ve snapshot/delta uyumsuzluğu veri arızasıdır.
- Stale süresi evrensel sabit değildir; platform adaptörü heartbeat, mesaj sırası, beklenen veri ritmi ve strateji ufkuna göre belirler. Sessiz piyasa, sağlıklı heartbeat varsa otomatik olarak stale sayılmaz.

## 19. Gerçek performans hesabı

    Gerçek Net P&L
      = gerçekleşmiş kâr/zarar
      + açık pozisyonların orta fiyatla değil, uygulanabilir çıkış fiyatıyla muhafazakâr piyasa değeri
      - bütün ücretler
      - kayma ve market impact
      - fonlama / borrow
      - hedge
      - settlement ve zincir maliyetleri

Her emir ve strateji için en az şunlar tutulur:

- Sinyal anındaki adil değer ve beklenen avantaj
- Karar, config, strateji ve model sürümü
- İstenen ve gerçekleşen fiyat/miktar
- Dolum oranı ve dolum gecikmesi
- Dolumdan 1, 10 ve 60 saniye sonraki ters fiyat hareketi
- Ücret, rebate, kayma ve market impact
- Açık risk ve sermaye kullanım süresi
- Strateji, piyasa, olay kümesi, platform ve hesap bazında net P&L
- Reddedilen fırsatların gölge sonucu
- Backtest/paper tahmini ile canlı sonuç farkı

Execution kalitesi ile yönsel şans ayrı raporlanır. Piyasa yönü sayesinde kâr ederken kötü execution yapmak mümkündür.

Ana performans göstergeleri:

- Maliyet sonrası net beklenti
- En kötü ve ortalama düşüş
- Kâr faktörü
- Risk ayarlı getiri
- Sermaye kullanım verimi
- Fill kalitesi ve adverse selection
- Kapasite ve korelasyon
- Mutabakat farkı sayısı
- Sistem çalışma süresi ve kritik gecikme

## 20. AI Supervisor

AI canlı karar hattının dışında, salt-okunur denetçi ve öneri katmanıdır.

Program:

- Her 15 dakikada strateji gidişatı, açık risk ve olağandışı sapma değerlendirmesi
- Her saat yazılım, bağlantı, gecikme, veri kalitesi ve mutabakat sağlık kontrolü
- Her gün işlem/strateji bazında performans, toplam net P&L, execution farkı ve yazılım raporu

AI şunları yapabilir:

- Açıklama, uyarı, kök neden adayı ve deney önerisi
- Backtest/paper/live farklarını özetleme
- Geliştirme kartı taslağı hazırlama

AI şunları yapamaz:

- Emir veya TradeIntent üretmek
- Risk limitini veya sermaye tahsisini değiştirmek
- LIVE açmak, unhalt etmek veya flatten çalıştırmak
- Kodu, ayarı veya servisi insan onayı olmadan değiştirmek

AI veya raporlama kesilirse motor sağlıklıysa çalışmaya devam eder ve alarm üretir.

## 21. Bileşen sorumlulukları

| Bileşen | Tek sorumluluğu | Yapamayacağı |
|---|---|---|
| Market Data | Doğru, sıralı, zamanlı piyasa gerçeği | Strateji kararı vermek |
| Strategy | Test edilmiş TradeIntent üretmek | Emir göndermek, risk izni vermek |
| Capital Allocator | Onaylı fırsatları risk verimine göre sıralamak | Risk limitini aşmak |
| Risk Authority | Limit, rezervasyon ve son izin | Platforma doğrudan emir göndermek |
| Flatten Guard | Yalnız kanıtlanmış acil risk azaltma izni | Yeni risk, strateji veya normal emir üretmek |
| Runtime Supervisor | Durum makinesi, sağlık, halt ve restart | Kâr sinyali üretmek |
| Execution | İzinli emri idempotent yürütmek | Risk kontrolünü atlamak |
| Reconciler | Motor ile platform gerçeğini eşlemek | Belirsizliği yok saymak |
| Platform Adapter | Platform verisi, emirleri ve ürün kuralları | Ortak iş mantığını değiştirmek |
| Axum Control | Kimlik, yetki, komut sürümü ve audit | İkinci işlem motoru olmak |
| React Panel | Gerçeği göstermek, talep göndermek | Anahtar saklamak, doğrudan emir vermek |
| tradingctl / Linux | Yerel acil kontrol ve servis işletimi | Platform iptalini doğrulanmış saymak |
| AI Supervisor | Analiz, rapor ve öneri | Canlı sistemde karar uygulamak |

## 22. Uygulama ve test kabul kriterleri

Bu kart aşağıdaki otomatik testler geçmeden uygulanmış sayılmaz.

### 22.1. Mimari

- [ ] Aynı strateji karar kodu backtest, replay, paper ve live modlarında çalışabilir.
- [ ] Strateji doğrudan execution veya platform client çağıramaz.
- [ ] Frontend platform anahtarına, doğrudan order metoduna veya veri tabanı yazımına erişemez.
- [ ] Axum iş kurallarının ikinci kopyasını barındırmaz.
- [ ] Yavaş panel/telemetri istemcisi canlı emir hattını bloke edemez.
- [ ] Axum task panic’i, bağlantı seli ve kanal taşması motoru düşüremez veya emir hattını bloke edemez.

### 22.2. Ekonomik kapı

- [ ] Ücret, kayma ve belirsizlik sonrası avantaj sıfır veya altındaysa intent reddedilir.
- [ ] Bütün maliyet kalemleri strateji/model sürümüyle kayıt altındadır.
- [ ] Risk bütçesi doluyken daha düşük skorlu fırsat reddedilir.
- [ ] Resolution şartı veya kötü durum kaybı belirsiz ürün canlıya alınmaz.
- [ ] Backtest ve canlı P&L aynı net maliyet tanımını kullanır.

### 22.3. Kesinti ve mutabakat

- [ ] Kontrol API’si kapanınca sağlıklı motor son onaylanmış ayarlarla devam eder ve alarm üretir.
- [ ] API geri gelince panel motorun gerçek durumunu yeniden okur; eski ekran sistemi ezemez.
- [ ] Eski/bozuk piyasa verisinde yeni risk alınmaz ve risk artıran açık emirler için iptal başlatılır.
- [ ] Timeout alan emir reddedilmiş sayılmaz; rezervasyonu mutabakata kadar korunur.
- [ ] Platform, bakiye, emir veya pozisyon uyuşmazlığında ilgili alan RECONCILING olur.
- [ ] Ortak risk gerçeği belirsizse sistem global güvenli duruma geçer.

### 22.4. Emergency-stop ve restart

- [ ] Emergency-stop kabulünden sonra eski epoch’lu kuyruk ve retry emirleri gönderilemez.
- [ ] Emergency-stop’un atomik kapı kapatma, epoch artırma ve kalıcı yazım adımları arasındaki her crash noktası test edilir.
- [ ] Halt kilidi yazılamazsa sistem bellekte HALTED kalır ve HALT_NOT_DURABLE bildirir.
- [ ] HALTED iken fill, iptal cevabı ve mutabakat işlenmeye devam eder.
- [ ] Halt kilidi bulunan motor restart sonrası HALTED açılır.
- [ ] Temiz kapanış kanıtı veya halt deposu bütünlüğü yoksa motor restart sonrası HALTED açılır.
- [ ] Halt kilidi olmayan motor doğrudan NORMAL açılmaz.
- [ ] Yetkili devam sistemi önce RECONCILING durumuna geçirir.
- [ ] İptal doğrulanamazsa CANCEL_UNVERIFIED gösterilir.
- [ ] Mevcut pozisyon varsa RESIDUAL_POSITION gösterilir.
- [ ] Emergency-flatten iki aşamalı doğrulama olmadan çalışmaz.
- [ ] Flatten Guard yalnız kötü durum riskini kesin azaltan emre izin verir; belirsizlikte fail-closed çalışır.

### 22.5. Risk ve canlıya geçiş

- [ ] Açık ve belirsiz bütün emirlerin aynı anda dolması senaryosu risk testinde yer alır.
- [ ] Kısmi fill, cancel/fill yarışı, duplicate event ve out-of-order event test edilir.
- [ ] Yuvarlanan 24 saatlik, yedi günlük ve drawdown limitleri insan onayı olmadan kalkmaz.
- [ ] LIVE varsayılan olarak kapalıdır.
- [ ] Strateji onay kartı ve sermaye tavanı yoksa LIVE açılamaz.
- [ ] Canlı bozunma eşikleri küçültme/durdurma üretir.
- [ ] Risk Authority arızası bütün yeni riski durdurur.
- [ ] Persist-before-submit ve crash recovery sonrasında aynı emir ikinci kez gönderilmez.

## 23. Çalışma alanlarına aktarım

| Sohbet/alan | Bu karttan uygulanacak bölüm |
|---|---|
| 00 — Ana Kararlar ve Yol Haritası | Kartın bağlayıcılığı, sürümü ve istisnaları |
| 01 — Rust İşlem Motoru | Ana akış, durum makinesi, Risk Authority, epoch, execution ve reconciliation |
| 02 — Kontrol Paneli ve v0.1 | Axum sözleşmesi, roller, config sürümü, durum ve alarm göstergeleri |
| 03 — Strateji Laboratuvarı | Ekonomik kapı, piyasa filtresi, backtest/paper/canary ve strateji kartları |
| 04 — Test, Risk ve Güvenlik | Risk limitleri, yarışlar, kesintiler, restart, fuzz/property testleri |
| 05 — Linux ve Üretim | Kalıcı halt, tradingctl, SIGTERM, saat, kayıt ve servis işletimi |
| 06 — AI Supervisor | 15 dakikalık, saatlik ve günlük salt-okunur denetim |
| 07 — Platform Adaptörleri | Piyasa verisi, ücretler, product rules, reconciliation ve native dead-man |

## 24. Değişiklik protokolü

Bu karttaki bir kuralı değiştirmek için:

1. Değişecek madde açıkça belirtilir.
2. Ekonomik fayda ve yeni kötü senaryo yazılır.
3. Backtest/replay/paper veya arıza testiyle kanıt sunulur.
4. Etkilenen risk ve kabul testleri güncellenir.
5. Yeni kart sürümü onaylanır.

Bir sohbet, ajan, panel ayarı, AI önerisi veya platform kolaylığı bu adımları atlayamaz.

## 25. Nihai hüküm

Trading OS’un para kazanma yaklaşımı daha fazla tahminde bulunmak değil; yalnızca maliyet sonrası avantajı kanıtlanmış işlemleri seçmek, kötü fiyatlanan riski reddetmek, canlı gerçeğe göre hızla küçülmek ve teknik belirsizlikte yeni risk almamaktır.

Bu kart eklendiğinde:

- Mimari sınırlar bağlayıcıdır.
- Çalışma ve kesinti algoritması bağlayıcıdır.
- Pilot risk limitleri varsayılandır.
- İlk Polymarket piyasa yapıcılık yaklaşımı test hipotezidir; canlıya otomatik onay değildir.
- Platforma özel değerler ve strateji parametreleri ayrı kartlarla tamamlanacaktır.
