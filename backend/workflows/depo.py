"""Akış deposu — kaydedilmiş iş dizileri.

Bir akış, başarıyla biten bir turun **dünyayı değiştiren** adımlarının
sırası. Ekran görüntüsü, dosya okuma, pencere ağacı okuma kaydedilmiyor:
onlar modelin karar vermesi içindi ve oynatmada karar veren yok. Kaydın
küçük olması yan etki değil, amaç — otuz adımlık bir tur oynatılırken
yirmi ekran görüntüsü almak, hem yavaş hem anlamsız olurdu.

## Düğme değil, yetenek değil

Üçü de "bir işi tekrar yaptırmak" diyor ama farklı şeyler:

- **Düğme** hazır bir talimat: ajan işi baştan düşünüyor, para harcıyor,
  ekran değişmişse uyum sağlıyor.
- **Yetenek** ajanın yazdığı Python kodu: hızlı ama ajanın o kodu doğru
  yazmasına bağlı.
- **Akış** kaydedilmiş tıklama dizisi: modele hiç uğramıyor, yani sıfır
  token, ve kendini UIA imzasından onarıyor.

## Depolama düz JSON

`~/.ajan/akislar/<ad>.json`. Bir veritabanı gereksiz ve dosyalar elle
okunabilir olmalı: bir akışın ne yapacağını görmek için onu çalıştırmak
gerekmemeli. Okuma hiçbir durumda istisna fırlatmıyor — bozuk bir akış
dosyası yüzünden uygulamanın açılmaması kabul edilemez.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..agent import kuru as kuru_mod
from ..skills.shortcuts import STATE_DIR
from .imza import Imza

DIZIN = STATE_DIR / "akislar"

AD_KURALI = re.compile(r"^[a-z][a-z0-9_]{1,40}$")

#: Bir akışın alabileceği en fazla adım. Bunu aşan bir tur zaten
#: tekrarlanabilir bir iş değil.
EN_COK_ADIM = 200

MAX_ETIKET = 40

#: Kaydedilmeyen araçlar. Kuru koşunun serbest listesiyle neredeyse aynı
#: soruyu soruyor — "bu araç dünyayı değiştiriyor mu" — ama bir istisna
#: var: `wait`.
#:
#: `wait` hiçbir şeyi değiştirmiyor, o yüzden kuru koşuda serbest. Ama
#: oynatmada **anlamlı**: ajan bir diyaloğun açılmasını beklemek için
#: koyduysa, o beklemeyi atlamak tıklamayı diyalog gelmeden yapmak
#: demek. Kayıt listesi bu yüzden ayrı bir isim taşıyor; ikisini tek
#: küme yapmak, birini değiştirirken diğerini sessizce bozardı.
KAYDEDILMEYEN = frozenset(kuru_mod.SALT_OKUNUR) - {"wait"} | {
    # Ekran kaydı dünyayı değiştiriyor — dosya yazıyor — ama bir akışa
    # ait değil. Oynatılan bir akışın sessizce ffmpeg başlatması ve
    # kimsenin istemediği bir video bırakması, kaydın kendisinden daha
    # şaşırtıcı olurdu.
    "record_start", "record_stop",
}


def kaydedilir(arac: str) -> bool:
    """Bu araç bir akışa kaydedilir mi."""
    if not arac or arac.startswith("workflow_"):
        return False
    return arac not in KAYDEDILMEYEN


class AkisHatasi(RuntimeError):
    pass


@dataclass
class Adim:
    """Kaydedilmiş tek bir eylem."""

    arac: str
    girdi: dict[str, Any] = field(default_factory=dict)
    #: Tıklama adımlarında tıklanan denetimin kimliği. Yoksa oynatma
    #: kayıtlı koordinatı kullanıyor.
    imza: Imza | None = None

    def as_dict(self) -> dict[str, Any]:
        cikti: dict[str, Any] = {"arac": self.arac, "girdi": self.girdi}
        if self.imza is not None:
            cikti["imza"] = self.imza.as_dict()
        return cikti

    @classmethod
    def from_dict(cls, ham: Any) -> Adim | None:
        if not isinstance(ham, dict) or not ham.get("arac"):
            return None
        girdi = ham.get("girdi")
        return cls(
            arac=str(ham["arac"]),
            girdi=dict(girdi) if isinstance(girdi, dict) else {},
            imza=Imza.from_dict(ham.get("imza")),
        )


@dataclass
class Akis:
    ad: str
    etiket: str
    talimat: str = ""
    adimlar: list[Adim] = field(default_factory=list)
    olusturuldu: float = 0.0

    @property
    def adim_sayisi(self) -> int:
        return len(self.adimlar)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ad": self.ad,
            "etiket": self.etiket,
            "talimat": self.talimat,
            "olusturuldu": self.olusturuldu,
            "adimlar": [a.as_dict() for a in self.adimlar],
        }

    @classmethod
    def from_dict(cls, ham: Any) -> Akis | None:
        if not isinstance(ham, dict) or not ham.get("ad"):
            return None
        adimlar = [
            adim for adim in (Adim.from_dict(a)
                              for a in (ham.get("adimlar") or []))
            if adim is not None
        ]
        return cls(
            ad=str(ham["ad"]),
            etiket=str(ham.get("etiket") or ham["ad"]),
            talimat=str(ham.get("talimat") or ""),
            adimlar=adimlar,
            olusturuldu=float(ham.get("olusturuldu") or 0.0),
        )


def dogrula_ad(ad: str) -> str:
    ad = (ad or "").strip().lower()
    if not AD_KURALI.match(ad):
        raise AkisHatasi(
            f"{ad!r} is not a usable name. Use lower case letters, digits "
            f"and underscores, 2-41 characters, starting with a letter."
        )
    return ad


class AkisDeposu:
    def __init__(self, dizin: Path | None = None) -> None:
        self.dizin = dizin or DIZIN

    def _yol(self, ad: str) -> Path:
        return self.dizin / f"{ad}.json"

    # --- okuma ------------------------------------------------------------

    def hepsi(self) -> list[Akis]:
        """Kayıtlı akışlar, yeniden eskiye. Bozuk dosyalar atlanıyor."""
        if not self.dizin.is_dir():
            return []
        cikti: list[Akis] = []
        for yol in sorted(self.dizin.glob("*.json")):
            akis = self._oku(yol)
            if akis is not None:
                cikti.append(akis)
        cikti.sort(key=lambda a: a.olusturuldu, reverse=True)
        return cikti

    def _oku(self, yol: Path) -> Akis | None:
        try:
            return Akis.from_dict(json.loads(yol.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return None

    def al(self, ad: str) -> Akis | None:
        return self._oku(self._yol(ad.strip().lower()))

    # --- yazma ------------------------------------------------------------

    def kaydet(self, akis: Akis) -> Akis:
        akis.ad = dogrula_ad(akis.ad)
        akis.etiket = (akis.etiket or akis.ad).strip()[:MAX_ETIKET]
        if not akis.adimlar:
            raise AkisHatasi(
                "There is nothing to save: the last turn did not do "
                "anything that changes the machine."
            )
        if len(akis.adimlar) > EN_COK_ADIM:
            raise AkisHatasi(
                f"{len(akis.adimlar)} steps is too many to replay "
                f"reliably (the limit is {EN_COK_ADIM})."
            )
        akis.olusturuldu = akis.olusturuldu or time.time()
        try:
            self.dizin.mkdir(parents=True, exist_ok=True)
            self._yol(akis.ad).write_text(
                json.dumps(akis.as_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as hata:
            raise AkisHatasi(f"could not write the workflow: {hata}") from None
        return akis

    def sil(self, ad: str) -> bool:
        try:
            self._yol(dogrula_ad(ad)).unlink()
            return True
        except (OSError, AkisHatasi):
            return False
