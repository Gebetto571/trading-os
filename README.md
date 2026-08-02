# Trading OS

Trading OS; araştırma, risk, yürütme ve yapay zekâ destekli denetim bileşenlerini sade ve izlenebilir bir çalışma düzeninde birleştirir.

Bu depo üç katmanlıdır:

- **Yerel çalışma alanı:** Kod, testler, SQLite kayıtları ve hızlı geliştirme.
- **Google Drive:** ChatGPT bulut sohbetleri ile Codex arasında kontrollü mesaj ve belge aktarımı.
- **GitHub:** Kodun ve kalıcı teknik belgelerin sürüm geçmişi ve uzak yedeği.

Private GitHub deposu: <https://github.com/Gebetto571/trading-os>

## Hızlı başlangıç

Python 3.11 veya daha yeni bir sürüm yeterlidir; harici paket gerekmez.

```bash
python3 -m trading_os_bridge init
python3 -m trading_os_bridge send --to chatgpt --subject "İlk görev" --body "Mimariyi değerlendir"
python3 -m trading_os_bridge list
```

Üretilen aktarım dosyaları `var/outbox/` altında oluşur. Drive'a gelen dosyalar `var/inbox/` içine konup şu komutla kayda alınır:

```bash
python3 -m trading_os_bridge ingest var/inbox
```

## Temel belgeler

- [Sistem mimarisi](docs/architecture.md)
- [ChatGPT ↔ Codex iletişim protokolü](docs/communication-protocol.md)
- [Veritabanı tasarımı](docs/database.md)
- [Drive, Git ve GitHub çalışma düzeni](docs/operations.md)
- [Güvenlik politikası](docs/security.md)

`sources/` klasörü ChatGPT projesinden eşlenen salt okunur kaynaktır; değiştirilmez.
