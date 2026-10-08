"""Alt süreç kapısı — Linux sürücülerinin tek komut noktası.

Kabuk yok, argv listesi var. `shell=True` olsaydı modelden gelen ya da
panoya kopyalanan bir metin bir gün kabuk yorumuna dönüşürdü; argv'de
öyle bir yüzey yok — metin hep tek argüman olarak gidiyor.

Bütün alt süreç çağrıları (xdotool, ydotool, xrandr) buradan geçiyor ki
testler tek noktadan sahteleyebilsin: Linux'ta gerçek X sunucusuna
dokunan bir test, doğrulamadığı şey hakkında güven üretirdi.

`FILE_NOT_FOUND` ayrı bir hata türü: "araç kurulu değil" ile "araç
kurulu ama hata verdi" karışırsa erişim katmanı yanlış adaya geçer.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class KomutSonuc:
    """Çalıştırılan bir komutun sonucu. `donus` exit kodu."""

    donus: int
    cikti: str
    hata: str


class KomutYokHatasi(RuntimeError):
    """Araç PATH'te değil — eksik kurulumun anlaşılır hâli."""


class KomutHatasi(RuntimeError):
    """Araç var ama komut başarısız bitti."""


def var_mi(ad: str) -> str | None:
    """PATH'te varsa tam yolunu döndürür, yoksa None."""
    return shutil.which(ad)


def calistir(
    argv: list[str],
    env_ek: dict[str, str] | None = None,
    zaman_asimi: float | None = 5.0,
) -> KomutSonuc:
    """argv'yi çalıştırır ve üçlü sonucu döndürür.

    `env_ek` mevcut ortamın üstüne yazılır — yan masa (port-ortam) kendi
    X ekranına `DISPLAY=:n` ile konuşacak ve o override buradan geçiyor.

    `zaman_asimi=None` uzun süren, girdi uzunluğuyla ölçeklenen işler için
    (ör. `xdotool type --delay 12` on bin karakterde dakikalar sürer);
    sabit bir sınır oraya konursa uzun yazma keyfî olarak kesilirdi.
    """
    env = None
    if env_ek:
        env = {**os.environ, **env_ek}
    try:
        sonuc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=zaman_asimi,
            env=env,
            check=False,
        )
    except FileNotFoundError:
        raise KomutYokHatasi(f"{argv[0]} not found on PATH") from None
    return KomutSonuc(sonuc.returncode, sonuc.stdout, sonuc.stderr)