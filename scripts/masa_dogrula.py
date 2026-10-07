"""Ajanın masasını uçtan uca doğrular ve bir kare yazar.

Gizli masaüstünde gerçek uygulamalar açıyor, ajanın imlecini oynatıyor ve
canlı görüntüyü olduğu gibi `varliklar/onizleme/masa.png` dosyasına
çiziyor. Ekran yakalanmıyor — pencere `QImage`'a render ediliyor, yani
kare Berkay'ın masaüstünde ne varsa onu yayımlamıyor.

    .venv/Scripts/python.exe scripts/masa_dogrula.py

Ölçtüğü şey: pencereler doğru yerde mi, istemci alanı kırpması iki başlık
çubuğunu teke indiriyor mu, imleç masaüstü koordinatında mı duruyor.
"""

from __future__ import annotations

import base64
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.masa import MasaPenceresi  # noqa: E402
from backend.computer.canli import masayi_oku  # noqa: E402
from backend.computer.masaustu import Calisma  # noqa: E402
from backend.computer.mesaj import Girdi  # noqa: E402

KROM = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
SAYFA = (
    "<html><head><meta charset='utf-8'></head>"
    "<body style='margin:0;background:#f4f4f4;font:16px system-ui'>"
    "<div style='background:#2b6b3f;color:#fff;padding:14px 18px;"
    "font-size:20px'>Doppel</div>"
    "<div style='padding:18px'>Bu sayfa ajanın kendi masaüstünde açık. "
    "Berkay'ın ekranında görünmüyor, faresi ve odağı yerinde.</div>"
    "</body></html>"
)


def main() -> int:
    app = QApplication(sys.argv)

    with Calisma("ajan-masa-dogrula") as c:
        girdi = Girdi()
        c.baslat("charmap.exe")
        if os.path.exists(KROM):
            url = "data:text/html;base64," + base64.b64encode(
                SAYFA.encode()).decode()
            profil = os.path.join(os.environ["TEMP"], "ajan-masa-dogrula")
            c.baslat(f'"{KROM}" --user-data-dir="{profil}" --no-first-run '
                     f'--window-size=980,660 --window-position=520,190 '
                     f'--new-window "{url}"')
        else:
            print("Chrome yok, yalnızca charmap ile bakılıyor")

        for _ in range(40):
            time.sleep(0.3)
            if len(c.pencereler()) >= (2 if os.path.exists(KROM) else 1):
                break
        pencereler = c.pencereler()
        print(f"{len(pencereler)} pencere:")
        for p in pencereler:
            print(f"  {p.hwnd}  {p.en}x{p.boy} @ ({p.x},{p.y})  {p.baslik[:38]!r}")
        if not pencereler:
            print("BAŞARISIZ: hiç pencere açılmadı")
            return 1

        # Ajanın imlecini bir yere koy ve arkasında iz bıraksın.
        hedef = pencereler[0]
        for i in range(8):
            girdi.imlec.tasi(hedef.x + 60 + i * 26, hedef.y + 90 + i * 12)
            girdi.iz.append((girdi.imlec.x, girdi.imlec.y))
        girdi.son_tik = True

        kare = masayi_oku(c, girdi, alan=(1920, 1080), etkin=hedef.hwnd)
        print(f"yakalanan: {len(kare.pencereler)} pencere, "
              f"imleç {kare.imlec}, iz {len(kare.iz)}")
        for pk in kare.pencereler:
            print(f"  istemci {pk.en}x{pk.boy} @ ({pk.x},{pk.y}) "
                  f"{len(pk.ham)} bayt")

        pencere = MasaPenceresi(lambda: kare)
        pencere.resize(1180, 740)
        pencere._kare = kare
        pencere.show()
        app.processEvents()

        gorsel = QImage(pencere.size(), QImage.Format_ARGB32)
        gorsel.fill(QColor("#000000"))
        pencere.render(gorsel)
        hedef_yol = Path("varliklar/onizleme/masa.png")
        hedef_yol.parent.mkdir(parents=True, exist_ok=True)
        gorsel.save(str(hedef_yol))
        print(f"kare -> {hedef_yol} ({gorsel.width()}x{gorsel.height()})")
        pencere._akis.dur()
        pencere.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
