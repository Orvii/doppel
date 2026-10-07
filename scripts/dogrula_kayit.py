"""Elle doğrulama: kayıt gerçekten YAN masayı mı çekiyor.

Bu bir test değil, bir ölçüm. Testler ffmpeg çalıştırmıyor — Windows
API'sine ve dış süreçlere dokunmuyorlar. Bu betik bir kez elle
koşturulup sonucu `backend/computer/kayit.py`'nin docstring'ine yazılsın
diye burada; ölçümü tekrarlamak isteyen aynı komutu koşturuyor.

    python scripts/dogrula_kayit.py

Yan masaüstünde `charmap.exe` açıyor, `-i desktop` ve `-i hwnd=` ile
ayrı ayrı kayıt deniyor, sonuçları basıyor ve çalışanın ilk karesini
`runs/dogrulama/` altına PNG olarak koyuyor. Karenin içinde charmap
görünüyorsa kayıt yan masadan geliyor: charmap ana masaüstünde açık
değil.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.computer import kayit as kayit_mod  # noqa: E402
from backend.computer.kayit import EkranKaydi, KayitHatasi  # noqa: E402
from backend.computer.masaustu import Calisma  # noqa: E402

CIKTI = Path(__file__).resolve().parent.parent / "runs" / "dogrulama"


def main() -> int:
    CIKTI.mkdir(parents=True, exist_ok=True)
    calisma = Calisma()
    calisma.ac()
    calisma.baslat(r"C:\Windows\System32\charmap.exe")
    time.sleep(2.5)
    pencereler = calisma.pencereler()
    print("yan masadaki pencereler:", [p.baslik for p in pencereler])
    if not pencereler:
        print("charmap açılmadı; ölçüm yapılamıyor")
        calisma.kapat()
        return 1
    hwnd = pencereler[0].hwnd

    # 1) Bütün masaüstü — çalışmıyor, ve neden çalışmadığı görünsün.
    komut = kayit_mod.ffmpeg_komutu(CIKTI / "desktop.mp4", 0).replace(
        "-i hwnd=0", "-i desktop")
    surec = kayit_mod.dogur(komut, calisma.ad)
    if surec.bekle(3.0):
        print("-i desktop  -> ÖLDÜ:", surec.gunluk.splitlines()[0])
    else:
        print("-i desktop  -> yaşadı (beklenmiyordu)")
        surec.dur_iste()
        surec.bekle(8)
    surec.kapat()

    # 2) Tek pencere — kullandığımız yol.
    kayit = EkranKaydi(calisma.ad)
    try:
        hedef = kayit.basla(CIKTI / "yan.mp4", hwnd=hwnd)
    except KayitHatasi as hata:
        print("-i hwnd=    -> BAŞLAYAMADI:", hata)
        calisma.kapat()
        return 1
    time.sleep(4)
    kayit.durdur()
    print(f"-i hwnd=    -> {hedef.stat().st_size} bayt, "
          f"{kayit.sure:.1f} sn")

    kare = CIKTI / "yan.png"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-i", str(hedef), "-frames:v", "1", str(kare)],
        check=True,
    )
    print("ilk kare:", kare)
    calisma.kapat()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
