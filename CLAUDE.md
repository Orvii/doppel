# Doppel — çalışma kuralları

Bu depoda çalışan her ajan bunu okur. Kurallar tercih değil; her biri bir
kez bozulduğu için yazıldı.

## Ortam

- Python: `C:\Users\berkaycik\ajan\.venv\Scripts\python.exe`.
  **Kendi worktree'nde `.venv` yok** (gitignore'da) ve kurmana gerek yok —
  yukarıdaki mutlak yolu kullan.
- Test: `C:\Users\berkaycik\ajan\.venv\Scripts\python.exe -m pytest -q`
  Depo kökünden çalıştır. Bitirmeden önce **bütün** takım geçmeli.
- Uygulamayı sen başlatma. `pythonw.exe` süreçlerini öldürme — venv'deki
  `pythonw.exe` bir başlatıcı kabuğu, gerçek süreci o doğuruyor; iki tane
  görmen kopya olduğu anlamına gelmiyor.

## Dil

- Kod içindeki her şey **Türkçe**: modül/sınıf/fonksiyon/değişken adları,
  yorumlar, docstring'ler. `hedef`, `kosulari_derle`, `not_metni`.
- Kullanıcının gördüğü arayüz metinleri **İngilizce**.
- `README.md` İngilizce, `README.tr.md` Türkçe ve daha uzun olan o.

## Docstring'ler

Her modülün başında, ne yaptığını değil **neden böyle olduğunu** anlatan
bir docstring var. Ölçtüğün sayı varsa oraya yaz (`ControlFromPoint ~6 ms`,
`129. testten sonra çöküyor`). Yeni modül yazıyorsan aynısını yap; var olan
bir modülü değiştiriyorsan docstring'i gerçeğe uydur.

## Dürüstlük kuralları — bunlar pazarlık dışı

- Kuru koşu (`backend/agent/kuru.py`) **izin listesi** kullanıyor, kara
  liste değil. Yeni bir araç eklersen kuru koşuda varsayılan olarak engelli
  kalır; oraya eklemek ayrı ve bilinçli bir karar.
- Workflow oynatma imza tutmazsa **durur**; bayat koordinata tıklamaz.
- MCP araç tanımları engellenmez, işaretlenir ve **birebir** gösterilir.
- Onay kancası bağlanmamışsa varsayılan **reddet**.
- Esc ×3 acil durdurma her koşulda çalışmalı.
- API anahtarı asla depoya girmez. `backend/config.py` `os.environ`'a
  dokunan tek modül. `pre-commit` kancası anahtar kalıplarını engelliyor.
- MCP `env` değerleri arayüzde asla gösterilmez — yalnızca hangi anahtarın
  dolu olduğu.

## Test

- Yeni her davranışın testi olacak. Testler Windows API'sine, ağa ve
  `npx`e dokunmuyor; saf mantık test ediliyor.
- Qt testleri `tests/conftest.py`'deki tek `QApplication`'ı kullanır ve
  kurduğu widget'ı yok eder.
- Testi geçirmek için üretim kodunu gevşetme (`getattr` varsayılanı gibi).
  Sahte nesne eksikse **sahteyi** düzelt.

## Bitirirken

- Değişikliği anlatan tek satırlık Türkçe commit mesajı yaz.
- Tam takımı koştur ve sonucu **olduğu gibi** bildir. Bir test kırıksa
  kırık olduğunu söyle; "geçti" deme.
- Yaptığın işi abartma. Yapmadığın şeyi yapmış gibi anlatma.
