"""X11 ekran envanteri — `xrandr` çıktısının saf ayrıştırıcıları.

Monitör listesi X sunucusunun cevabıdır ve iki biçimde gelir: modern
sunucularda `xrandr --listmonitors`, kâğıt üstünde tek doğru kaynak ama
NVIDIA'nın bazı sürücüleri desteklemiyor; onda `xrandr --query` var.
İkisi de burada ayrıştırılıyor, sırayla deneniyor.

Ayrıştırma saf fonksiyonlara ayrıldı (`xrandr_monitorleri_coz`,
`xrandr_sorgusunu_coz`) çünkü gerçek X sunucusu olmadan test edilebilen
tek parça bu — alt süreç katmanı sahtelenir, metin ayrıştırma gerçek
kalır. Biçim sürprizleri (negatif ofset, `+*` ön eki) tam burada
sabitlenmiştir.

`set_dpi_awareness` Linux'ta bilinçli olarak **no-op**: süreç başına DPI
ölçeklemesi Windows'a özgü bir sorun; X11'de koordinatlar zaten
sunucunun piksel uzayında ve yakaladığımız kare aynı uzaydan geliyor.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from . import komut
from .displays import Display, DisplayMap

#: `--listmonitors` satırı: ` 0: +*DP-1 1920/527x1080/296+0+0  DP-1`
_LISTE_KALIBI = re.compile(
    r"^\s*(\d+):\s+([+*]*)(\S+)\s+(\d+)/\d+x(\d+)/\d+([+-]-?\d+)([+-]-?\d+)"
)

#: `--query` satırı: `DP-1 connected primary 1920x1080+0+0 (normal ...) 527mm x 296mm`
_SORGU_KALIBI = re.compile(
    r"^(\S+)\s+connected\s+(primary\s+)?(\d+)x(\d+)([+-]-?\d+)([+-]-?\d+)"
)


def _sayi(deger: str) -> int:
    """`+1920` / `-1920` / `+-1920` biçimlerini int'e çevirir."""
    return int(deger.replace("+", ""))


def xrandr_monitorleri_coz(cikti: str) -> list[Display]:
    """`xrandr --listmonitors` çıktısını Display listesine çevirir.

    Birincil monitör `+*` ön ekiyle işaretli; sıralama Windows tarafıyla
    aynı: birincil önce, sonra soldan sağa, yukarıdan aşağı.
    """
    bulunan: list[tuple[int, int, int, int, bool]] = []
    for satir in cikti.splitlines():
        eslesme = _LISTE_KALIBI.match(satir)
        if not eslesme:
            continue
        _indeks, bayrak, _ad, genislik, yukseklik, sol, ust = eslesme.groups()
        bulunan.append(
            (
                _sayi(sol),
                _sayi(ust),
                int(genislik),
                int(yukseklik),
                "*" in bayrak,
            )
        )
    return _displaylere(bulunan)


def xrandr_sorgusunu_coz(cikti: str) -> list[Display]:
    """`xrandr --query` çıktısını Display listesine çevirir.

    Yalnızca `connected` satırları alınır; `disconnected` ve `unknown`
    monitörler atlanır. `primary` kelimesi birincil işareti.
    """
    bulunan: list[tuple[int, int, int, int, bool]] = []
    for satir in cikti.splitlines():
        eslesme = _SORGU_KALIBI.match(satir)
        if not eslesme:
            continue
        _ad, birincil, genislik, yukseklik, sol, ust = eslesme.groups()
        bulunan.append(
            (
                _sayi(sol),
                _sayi(ust),
                int(genislik),
                int(yukseklik),
                bool(birincil),
            )
        )
    return _displaylere(bulunan)


def _displaylere(bulunan: list[tuple[int, int, int, int, bool]]) -> list[Display]:
    """Ortak sıralama: birincil önce, sonra soldan sağa."""
    bulunan.sort(key=lambda oge: (not oge[4], oge[0], oge[1]))
    return [
        Display(
            index=i,
            left=sol,
            top=ust,
            width=genislik,
            height=yukseklik,
            primary=birincil,
        )
        for i, (sol, ust, genislik, yukseklik, birincil) in enumerate(bulunan)
    ]


def monitorler(env: Mapping[str, str] | None = None) -> DisplayMap:
    """Bağlı monitörleri X sunucusundan okur.

    `--listmonitors` denenir; çıktı işe yaramazsa `--query`'ye düşülür.
    İkisi de başarısızsa hata stderr'i taşır — "monitör yok" ile "xrandr
    konuşamadı" karışmasın.
    """
    try:
        sonuc = komut.calistir(
            ["xrandr", "--listmonitors"], env_ek=dict(env or {}), zaman_asimi=5.0
        )
    except komut.KomutYokHatasi as hata:
        raise RuntimeError(f"xrandr is not installed: {hata}") from None
    if sonuc.donus == 0:
        monitorlar = xrandr_monitorleri_coz(sonuc.cikti)
        if monitorlar:
            return DisplayMap(monitorlar)

    sonuc = komut.calistir(["xrandr", "--query"], env_ek=dict(env or {}), zaman_asimi=5.0)
    if sonuc.donus == 0:
        monitorlar = xrandr_sorgusunu_coz(sonuc.cikti)
        if monitorlar:
            return DisplayMap(monitorlar)

    ayrinti = (sonuc.hata or sonuc.cikti).strip() or "no monitors reported"
    raise RuntimeError(f"xrandr could not list monitors: {ayrinti}")


def sanal_dikdortgen(monitorlar: list[Display]) -> tuple[int, int, int, int]:
    """Monitör listesinin kapsadığı (left, top, width, height) dikdörtgen.

    X11'de bu genelde `xdotool`/`mss` için gerekmez — ikisi de sanal
    masaüstünü kendi bilir — ama sözleşme aynı kalsın diye saf ve doğru.
    """
    if not monitorlar:
        raise ValueError("At least one monitor is required")
    sol = min(m.left for m in monitorlar)
    ust = min(m.top for m in monitorlar)
    sag = max(m.left + m.width for m in monitorlar)
    alt = max(m.top + m.height for m in monitorlar)
    return sol, ust, sag - sol, alt - ust