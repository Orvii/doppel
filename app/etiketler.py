"""Araç adlarının insan diline karşılığı.

Bu tablo iki yerden okunuyor: canlı koşuda önizleme karesi ve komut
çubuğu, geçmiş sayfasında ise diskteki kayıt. Aynı çağrının iki yerde
iki farklı adla görünmesi — "run_shell" ile "Running a command" — aynı
şeyin iki ayrı iş olduğunu düşündürürdü. Tek kaynak burası.
"""

from __future__ import annotations

#: Önizleme karesinde hedef olarak gösterilecek alan, araç bazında.
TARGET_KEYS = ("path", "name", "target", "ref", "command", "text", "coordinate")

TOOL_LABEL = {
    "screenshot": "Looking at the screen",
    "zoom": "Zooming in",
    "left_click": "Clicking",
    "double_click": "Double-clicking",
    "type": "Typing",
    "key": "Pressing a key",
    "scroll": "Scrolling",
    "read_ui_tree": "Reading the window",
    "launch_app": "Launching an app",
    "run_shell": "Running a command",
    "write_file": "Writing a file",
    "read_file": "Reading a file",
    "edit_file": "Editing a file",
    "list_dir": "Listing a folder",
    "terminal_open": "Opening a terminal",
    "terminal_send": "Typing in the terminal",
    "terminal_read": "Reading the terminal",
    "office_open": "Opening a document",
    "office_read": "Reading the document",
    "office_edit": "Editing the document",
    "office_save": "Saving the document",
    "office_history": "Reviewing the changes",
    "office_close": "Closing the document",
    "cursor_position": "Locating the cursor",
    "right_click": "Right-clicking",
    "middle_click": "Middle-clicking",
    "triple_click": "Triple-clicking",
    "mouse_move": "Moving the cursor",
    "left_mouse_down": "Holding the button",
    "left_mouse_up": "Releasing",
    "left_click_drag": "Dragging",
    "hold_key": "Holding a key",
    "wait": "Waiting",
    "switch_display": "Switching display",
    "list_apps": "Listing apps",
    "write_files": "Writing files",
    "terminal_close": "Closing the terminal",
    "skill_list": "Listing skills",
    "skill_write": "Writing a skill",
    "skill_remove": "Removing a skill",
    "button_write": "Adding a button",
    "button_remove": "Removing a button",
    "remote_connect": "Connecting to the server",
    "remote_list": "Listing the server",
    "remote_read": "Reading from the server",
    "remote_write": "Writing to the server",
    "remote_run": "Running on the server",
    "side_launch": "Launching in the side desk",
    "side_windows": "Listing the side desk",
    "side_capture": "Looking at the side desk",
    "side_act": "Working in the side desk",
    "side_close": "Closing the side desk",
    "record_start": "Starting the recording",
    "record_stop": "Stopping the recording",
    "heads_up": "A note",
    "workflow_save": "Saving a workflow",
    "workflow_list": "Listing workflows",
    "workflow_run": "Replaying a workflow",
    "workflow_remove": "Removing a workflow",
}




def tool_label(name: str) -> str:
    """Araç adının okunur hâli. Bilinmeyen araç — yetenekler — kendi adıyla
    görünüyor: uydurulmuş bir etiket, adını bilmediğin bir işi anlatmaz."""
    if name.startswith("mcp__"):
        # `mcp__playwright__browser_click` -> "playwright · browser_click".
        # Ham ad okunmuyor ve hangi sunucudan geldiği tam da bakan kişinin
        # sorduğu şey.
        parcalar = name.split("__", 2)
        if len(parcalar) == 3:
            return f"{parcalar[1]} · {parcalar[2]}"
    return TOOL_LABEL.get(name, name)


def hedef(payload: dict, sinir: int = 46) -> str:
    """Çağrının üstünde çalıştığı şey: yol, ad, komut ya da koordinat.

    Bilinen alanlardan hiçbiri yoksa ilk kısa değere düşülüyor. Sebebi
    yetenekler: girdi adlarını ajan kendi seçiyor ve hiçbiri bu listede
    olmuyor. Boş bırakıldığında dökümde arka arkaya dört tane aynı satır
    çıkıyordu — hangisinin ne yaptığı okunmuyordu.
    """
    for key in TARGET_KEYS:
        if payload.get(key) is not None:
            return _kisalt(str(payload[key]), sinir)
    for anahtar, deger in payload.items():
        if anahtar == "why" or deger is None:
            continue
        metin = str(deger)
        # Uzun bir gövde hedef değil içerik: satıra sığmaz ve zaten
        # anlatmaz.
        if 0 < len(metin) <= sinir * 2:
            return _kisalt(f"{anahtar}={metin}", sinir)
    return ""


def _kisalt(metin: str, sinir: int) -> str:
    return metin if len(metin) <= sinir else metin[:sinir - 3] + "…"
