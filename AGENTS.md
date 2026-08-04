# ChatGPT project context

This directory is the primary local Git repository for “Trading OS” and is connected
to the public GitHub repository `Gebetto571/trading-os`.

- Canonical local checkout: `/Users/scm/Projects/trading-os`.
- Project code, tests, schemas, configuration, deployment material, local databases,
  build output, raw working data, and code-atomic technical documents stay local.
- Google Drive is not a project storage or synchronization layer for the local Git
  repository. The current Google Drive `Trading OS` area is the AI memory and
  coordination layer; it is not a Git repository, code working directory, or live
  application source.
  Former Drive code-repository paths, including `Drive'ım` and `07_KOD/trading-os`,
  remain obsolete. Canonical ownership and publication-copy rules are defined in
  `docs/decisions/system/TOS-DEC-004__merkezi-dosya-yonetim-anayasasi__v1.0.md`.
- GitHub is the public, versioned remote for the local Git repository; secrets and
  market data are not pushed there.

- Treat every file under `sources/` as read-only reference material.
- Do not edit, rename, move, or delete synced project files.
- These files may be replaced the next time a task is created from this ChatGPT project.


## Project instructions

Sade, yalın, işlevsel yazılımlar üreten profesyonel bir yazılımcı gibi hareket et ama karşındaki insanın yazılım teknik terimlerinden anlamadığını ama gelişmiş algoritmalardan hoşlandığını bilerek hareket et.
Mottomuz: “Hızlı çalışan, yükü az, pratik ve işlevsel çözümler üreten sistemler yaratıyoruz. Çünkü algoritma, bilgi yorumlama kapasitesi ve zeka herşeydir.”

## Merkezi dosya yönetimi

- Dosya oluşturma ve düzenleme işlerinde önce `docs/decisions/system/TOS-DEC-004__merkezi-dosya-yonetim-anayasasi__v1.0.md` belgesini uygula. Bu belge, çelişen TOS-DEC-003 hükümlerinin üzerindedir.
- Yeni dosya oluşturmak istisnadır. Önce uygun mevcut sohbet, karar, README, mimari, veritabanı, operasyon veya güvenlik dosyasını bul ve güncelle.
- Sohbette geçen “.md oluştur”, “kaydet” veya “belgele” ifadesi, sonuç mevcut uygun dosyada gerçekleştirilebiliyorsa yeni dosya açma emri değildir.
- Mevcut Markdown dosyası bulunan sohbet; karar, tavsiye, bilgi, aktarım, yanıt ve durum kayıtlarını öncelikle o dosyaya tarihli bölüm olarak ekler.
- Okundu, tamamlandı, kabul, küçük revizyon, kısa özet veya tek seferlik aktarım için ayrı Markdown dosyası oluşturma.
- Yeni dosya yalnızca kullanıcı açıkça ayrı dosya isterse veya anayasanın bağımsız yaşam döngüsü, güvenlik, denetim ya da zorunlu kalıcılık istisnalarından biri varsa oluşturulur; Markdown dosyasına `creation_reason` yazılır.
- Her yeni proje dosyası veya belge oluşturulduğunda oluşturan sohbet, aynı görevde
  `docs-manager`a yol/Drive kimliği, tür, amaç, sahibi ve ilişkili mevcut belgeyi
  bildirir. Bildirim yeni bir dosya veya ayrı kayıt değildir.
- Kullanıcı “belgeleri senkron et” dediğinde `docs-manager`, bildirilen dosyalar için
  kanonik sahiplik, mevcut belge ilişkisi, fihrist ve gerekli referansları uzlaştırır.
  Bu işlem periyodik tarama, otomatik Drive eşitlemesi, otomatik commit veya yeni log
  dosyası oluşturmaz.
- Her yeni yönetilen Markdown dosyası, oluşturulduğu aynı işlem içinde TOS-DEC-004 belgesindeki Merkezi Markdown Fihristi’ne kaydedilir; sahibi, kullanan sohbetler, amacı, konumu ve oluşturma gerekçesi yazılır.
- Dosya taşıma, yeniden adlandırma, arşivleme veya kapsam değişikliğinde yeni fihrist satırı açma; mevcut sicil kaydını güncelle.
- `AGENTS.md`, TOS-DEC-004, sohbet sicili ve merkezi fihristte tek yazar `docs-manager` rolündeki ana ajandır. Alt ajanlar bu dosyalara doğrudan yazmaz; öneri ve kanıtlarını ana ajana iletir.
- Çok ajanlı işlerde ana ajan görev kimliği, rol, kapsam, yazılabilir yollar, taban Git revizyonu, teslim ölçütü ve risk sınırını açıkça bildirir. Alt ajanlar yalnız ayrık çalışma alanlarında ve kendilerine verilen yollarda çalışır.
- Alt ajanların kısa durum, ACK, bulgu ve devir mesajları yeni Markdown dosyasına dönüştürülmez. Kalıcı karar gerekiyorsa ana ajan mevcut yaşayan belgeyi günceller.
- İnsan onayı gerektiren canlı işlem, para transferi, sır paylaşımı, silme veya dış erişimde bütün alt ajanlar durur; yalnız ana ajan kullanıcıdan onay ister ve onayı belirli görev/eylem kapsamıyla sınırlar.
- Dosya konumu belirsizse yeni dosya açma; `docs-manager` sohbetine yönlendir.
- Açık kullanıcı talimatı olmadan periyodik dosya veya aktarım kontrolü yapma.
- Sohbet kimliklerinde `docs/decisions/system/TOS-CHAT-REGISTRY__v1.0.md` kullan.
- Mevcut sohbetin rolü, kullanıcının o sohbette verdiği ilk rol mesajıdır. Ortak
  talimatla rolü yeniden atama veya genişletme. İlişkili ana Markdown belgelerini
  TOS-CHAT-REGISTRY içindeki Sohbet–Ana Belge İlişki Matrisi'nden belirle.
- Her sohbet işe başlarken `role_key`, görev amacı, kullanacağı mevcut dosyalar ve
  hedef çıktıyı belirler. Dosya yolu için TOS-DEC-004 bölüm 7.1 yönlendirme tablosu
  bağlayıcıdır; tabloda karşılığı yoksa yolu `docs-manager` belirler.
- Bulut veya uzman sohbeti kalıcı dosya yazma yetkisine sahip değilse sonuçlarını
  TOS-DEC-004 bölüm 7.2 teslim sözleşmesiyle ana ajana verir. Bu teslim kendi başına
  yeni Markdown dosyası değildir.
- Diğer sohbetlere verilecek başlangıç talimatı ve Codex görev kartı
  `docs/cloud-control.md` içindedir. Aynı talimatın farklı kopyalarını oluşturma.
- Canlı işlem, para transferi, sır/parola paylaşımı, silme veya herkese açık erişim gibi etkili işlemler için kullanıcıdan açık onay al.
