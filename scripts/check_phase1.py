"""Faz 1 elle doğrulama: yakalama ve girdi gerçekten çalışıyor mu.

    python scripts/check_phase1.py            # yalnızca yakalama, ekrana dokunmaz
    python scripts/check_phase1.py --input    # Notepad açıp Türkçe metin yazar

Girdi testi ekranı gerçekten sürdüğü için varsayılan olarak kapalı.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.computer import input as kb  # noqa: E402
from backend.computer.capture import ScreenCapture  # noqa: E402
from backend.computer import windows as win  # noqa: E402
from backend.computer.displays import (  # noqa: E402
    enumerate_displays,
    model_kare_boyutu,
    set_dpi_awareness,
)

TURKCE = "Ajan iskeleti ayakta. ğüşıöç ĞÜŞİÖÇ — 1234 %&/ → tamam."


def check_capture(out_dir: Path) -> None:
    displays = enumerate_displays()
    print(f"{len(displays)} ekran bulundu:")
    print(displays.describe())

    out_dir.mkdir(parents=True, exist_ok=True)
    with ScreenCapture(displays) as capture:
        for display in displays:
            start = time.perf_counter()
            frame = capture.grab(display)
            png = frame.to_png()
            elapsed = (time.perf_counter() - start) * 1000

            path = out_dir / f"display{display.index}.png"
            path.write_bytes(png)
            kare_en, kare_boy = model_kare_boyutu(display.width, display.height)
            model_notu = (
                f" → modele {kare_en}x{kare_boy}"
                if (kare_en, kare_boy) != (display.width, display.height)
                else ""
            )
            print(
                f"  ekran {display.index}: {display.width}x{display.height}{model_notu}, "
                f"{len(png) / 1024:.0f} KB, {elapsed:.0f} ms -> {path}"
            )

        # zoom yolu: kırpma kaynak kareden geliyor, yeniden yakalamadan.
        frame = capture.grab(0)
        region = (frame.width // 4, frame.height // 4, frame.width // 2, frame.height // 2)
        crop = frame.crop(region)
        print(f"  zoom crop {region} -> {crop.width}x{crop.height}")


def check_input() -> None:
    print("\nOpening Notepad — do not touch the keyboard.")
    subprocess.Popen(["notepad.exe"])

    # Odak kilidi: Notepad öne gelmezse hiçbir tuş gönderilmez. Bu kontrol
    # olmadan metin o an odakta olan pencereye gider — ilk denemede tam olarak
    # bu oldu ve yazı bir tarayıcı sekmesine düştü.
    if not win.wait_for_foreground(process="notepad.exe", timeout=8.0):
        print(
            f"  FAILED: Notepad did not come forward. In the foreground: "
            f"{win.foreground_process()} / {win.foreground_title()!r} var. "
            f"No key was sent."
        )
        return
    time.sleep(0.4)
    win.assert_foreground(process="notepad.exe")

    kb.type_text(TURKCE)
    time.sleep(0.3)
    win.assert_foreground(process="notepad.exe")
    kb.press("Return")
    kb.type_text("Second line. If you can read this in Notepad, the input layer works.")

    x, y = kb.cursor_position()
    print(f"  cursor position: ({x}, {y})")
    print(f"  the text typed:\n    {TURKCE}")
    print("\n  If the text in Notepad matches the above exactly, phase 1 passed.")
    print("  If the Turkish characters are mangled, the KEYEVENTF_UNICODE path is broken.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="store_true", help="also run the keyboard test")
    parser.add_argument("--out", type=Path, default=Path("runs/phase1"))
    args = parser.parse_args()

    set_dpi_awareness()
    check_capture(args.out)
    if args.input:
        check_input()
    else:
        print("\nKeyboard/mouse test skipped. To run it: --input")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
