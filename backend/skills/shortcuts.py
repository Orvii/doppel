"""Düğmeler — tek tıkla çalışan hazır talimatlar.

Yetenek ajanın kullandığı bir araç. Düğme Berkay'ın kullandığı bir kısayol:
çubukta duruyor, tıklanınca hazır bir talimat gidiyor. İkisini de ajan
kurabiliyor, ikincisini Berkay Python yazmadan da kurabiliyor.

Ayrı bir dosyada tutuluyorlar çünkü ömürleri farklı: yetenek kod, düğme
tercih. Bir yeteneği silmek onu çağıran düğmeyi de silmemeli — düğme kalıyor
ve tıklandığında ajan yeteneğin olmadığını görüp ya yeniden yazıyor ya da
söylüyor.

Depolama düz JSON. Bir veritabanı gereksiz ve düğme listesi elle
düzeltilebilir olmalı: bozuk bir düğme yüzünden uygulamanın açılmaması
kabul edilemez, o yüzden okuma hiçbir durumda istisna fırlatmıyor.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

#: Kullanıcının veri klasörü: düğmeler, yetenekler, akışlar, MCP ayarı.
#: Ürün 2026-10-07'de Yan Masa'dan Doppel'e geçti ama bu yol **taşınmadı**:
#: kurulu bir makinede yetenekler ve düğmeler burada duruyor ve yolu
#: değiştirmek onları sahipsiz bırakırdı. Ad zaten ürünün adı değil,
#: "ajan"dan geliyor; eski adı da taşımıyordu. Taşımak isteyen
#: `AJAN_STATE_DIR` ile taşır.
STATE_DIR = Path(os.environ.get("AJAN_STATE_DIR") or (Path.home() / ".ajan"))
BUTTON_FILE = STATE_DIR / "dugmeler.json"

NAME_RULE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")

#: Etiket düğmenin üstünde duruyor ve çubuk dar; uzun etiket taşıyor.
MAX_LABEL = 22


class ShortcutError(RuntimeError):
    pass


@dataclass
class Shortcut:
    name: str
    label: str
    instruction: str
    glyph: str = "yetenek"
    #: Yetenek dosyasından gelen düğmeler burada düzenlenemiyor; kaynağı kod.
    from_skill: bool = False

    def as_dict(self) -> dict:
        return {
            "ad": self.name,
            "etiket": self.label,
            "talimat": self.instruction,
            "cizim": self.glyph,
        }


class ShortcutStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or BUTTON_FILE

    # --- okuma ------------------------------------------------------------

    def all(self) -> list[Shortcut]:
        """Kayıtlı düğmeler. Dosya bozuksa boş liste — açılışı engellemiyor."""
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(raw, list):
            return []
        out = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                out.append(
                    Shortcut(
                        name=str(item["ad"]),
                        label=str(item["etiket"]),
                        instruction=str(item["talimat"]),
                        glyph=str(item.get("cizim") or "yetenek"),
                    )
                )
            except KeyError:
                continue
        return out

    def get(self, name: str) -> Shortcut | None:
        for item in self.all():
            if item.name == name:
                return item
        return None

    # --- yazma ------------------------------------------------------------

    def save(self, shortcut: Shortcut) -> Shortcut:
        """Ekler ya da aynı adlıyı değiştirir."""
        if not NAME_RULE.match(shortcut.name):
            raise ShortcutError(
                f"{shortcut.name!r} is not a valid name — lower case, digits and underscore"
            )
        if not shortcut.label.strip():
            raise ShortcutError("The label cannot be empty")
        if len(shortcut.label) > MAX_LABEL:
            raise ShortcutError(f"Etiket en fazla {MAX_LABEL} karakter")
        if not shortcut.instruction.strip():
            raise ShortcutError("The instruction cannot be empty — what should the click send?")

        items = [s for s in self.all() if s.name != shortcut.name]
        items.append(shortcut)
        self._write(items)
        return shortcut

    def remove(self, name: str) -> None:
        items = self.all()
        kalan = [s for s in items if s.name != name]
        if len(kalan) == len(items):
            raise ShortcutError(f"there is no button called {name}")
        self._write(kalan)

    def reorder(self, names: list[str]) -> None:
        """Sürükleyerek sıralama. Listede olmayan düğmeler sona kalıyor."""
        by_name = {s.name: s for s in self.all()}
        ordered = [by_name.pop(n) for n in names if n in by_name]
        self._write(ordered + list(by_name.values()))

    def _write(self, items: list[Shortcut]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps([s.as_dict() for s in items], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
