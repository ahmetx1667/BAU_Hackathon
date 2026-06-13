# BAU_Hackathon
Repository for Bahcesehir University's Hackathon 2026

# StudyMate
StudyMate, universite ogrencilerinin konu, seviye, zaman ve semte gore calisma arkadasi bulmasi icin hazirlanmis web tabanli bir MVP'dir. Backend Python standart kutuphanesiyle yazildi; veriler SQLite'ta tutulur.

## Ozellikler

- Kayit ve giris
- Turkiye universite listesiyle edu mail domain zorunlulugu
- Profil, ilgi alanlari ve telefon bilgisi
- Calisma ilani olusturma
- Konum, konu, seviye ve calisma tipine gore filtreleme
- Anahtar kelime tabanli AI Match Score benzeri uygunluk puani
- Istek gonderme, kabul, red ve eslesme akisi
- Telefon bilgisini sadece kabul edilmis eslesmelerde gosterme
- Public place onerisi ve kullanici raporlama
- CSRF, session token hash, parola hash ve temel spam korumasi

## Lokal Calistirma

Python 3.11+ onerilir. Proje harici paket gerektirmez.

```bash
python app.py
```

Varsayilan adres:

```text
http://127.0.0.1:8000
```

Ilk calistirmada `instance/studymate.sqlite3` ve `instance/secret.key` olusur. Bu dosyalar public repoya girmemelidir.

## Ortam Degiskenleri

`.env.example` dosyasi referans olarak eklidir. Kopyasini `.env` olarak olusturup degerleri duzenleyebilirsin; uygulama proje kokundeki `.env` dosyasini otomatik okur. Shell, systemd veya hosting panelinden verilen ortam degiskenleri `.env` degerlerinin onune gecer.

| Degisken | Varsayilan | Aciklama |
| --- | --- | --- |
| `HOST` | `127.0.0.1` | Dinlenecek IP. Sunucuda ters proxy yoksa `0.0.0.0` kullanilabilir. |
| `PORT` | `8000` | HTTP portu. |
| `STUDYMATE_SECRET_KEY` | Yok | Production'da mutlaka ver. Session imzalama icin kullanilir. |
| `STUDYMATE_DB_PATH` | `instance/studymate.sqlite3` | SQLite dosya yolu. |
| `STUDYMATE_SECRET_PATH` | `instance/secret.key` | Lokal secret dosya yolu. |
| `STUDYMATE_COOKIE_SECURE` | `0` | HTTPS arkasinda `1` yap. |

Secret uretmek:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```