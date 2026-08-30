"""Özel araç tanımları.

Computer araç seti fare ve klavye veriyor; bunlar onun yapamadığı ya da çok
pahalı yaptığı şeyler.

`launch_app` tek başına en büyük hız kazancı. Ajana Notepad'i Başlat
menüsünden açtırmak dört-beş tur sürüyor: ekran görüntüsü al, Başlat'a tıkla,
görüntü al, yaz, görüntü al, Enter, görüntü al. Her tur bir model çağrısı ve
~1500 token görsel. `launch_app("notepad")` bunu bir tura indiriyor.
"""

from __future__ import annotations

from typing import Any

# Hiçbir araçta `strict: True` yok ve bu bilinçli. Katı şemalar kısıtlı bir
# gramere derleniyor ve tüm araçların toplam gramer boyutunun bir sınırı var;
# 18 aracın hepsi katı olduğunda API isteği "Schema is too complex" ile 400
# dönüyor. Ölçüldü: 12 katı + 6 gevşek geçiyor, 18 katı geçmiyor.
#
# Kaybı küçük: her aracın girdisi zaten `dispatch.py` içinde doğrulanıyor ve
# eksik alan modele "Bu islem icin eksik alan: ref, values" gibi düzeltmesi
# kolay bir hata olarak dönüyor. Yeni araç eklerken katılığa geri dönme —
# sınır araç sayısıyla değil şema boyutuyla ilgili ve sessizce geri gelir.

SWITCH_DISPLAY = {
    "name": "switch_display",
    "description": (
        "Changes which display you work on. From then on, screenshots and "
        "coordinates belong to that display."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"index": {"type": "integer", "description": "Display index"}},
        "required": ["index"],
        "additionalProperties": False,
    },
}

READ_UI_TREE = {
    "name": "read_ui_tree",
    "description": (
        "Returns the foreground window's controls as text, each with its "
        "click point. Far cheaper than a screenshot, and the coordinates "
        "are measured rather than guessed. If you are looking for a button, "
        "a menu item or a text box, try this FIRST. If the result comes "
        "back empty or shallow (canvas, game, video, some web pages), fall "
        "back to a screenshot."
    ),
    "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
}

LAUNCH_APP = {
    "name": "launch_app",
    "description": (
        "Launches an app directly and waits for it to come to the front. "
        "Much faster than clicking through the Start menu — always use this "
        "when you need to open an app. You can open any installed app by "
        "name ('Discord', 'Spotify', 'Calculator'); an executable name, a "
        "full path or a URL also works. A name that does not match comes "
        "back with close candidates; `list_apps` shows what is installed."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "App name, full path or URL",
            },
            "arguments": {
                "type": "string",
                "description": "Optional command-line arguments",
            },
        },
        "required": ["target"],
        "additionalProperties": False,
    },
}

RUN_SHELL = {
    "name": "run_shell",
    "description": (
        "Runs a PowerShell command and returns its output. Use it for bulk "
        "file work, queries, and anything that would take dozens of clicks "
        "in a GUI. Irreversible commands (deleting, shutting down, the "
        "registry, overwriting) ask the user for approval — without it the "
        "command does not run. Do not run interactive commands; one that "
        "waits for input will time out."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The PowerShell command"},
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds, default 30",
            },
        },
        "required": ["command"],
        "additionalProperties": False,
    },
}

WRITE_FILE = {
    "name": "write_file",
    "description": (
        "Writes UTF-8 text to a file. Missing folders are created. "
        "Overwriting an existing file asks the user for approval; if you "
        "are changing part of it, use edit_file instead of write_file — "
        "that does not ask."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path"},
            "content": {"type": "string", "description": "The content to write"},
            "append": {
                "type": "boolean",
                "description": "Append instead of overwriting",
            },
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    },
}

READ_FILE = {
    "name": "read_file",
    "description": "Reads a file as UTF-8. Long files are truncated.",
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
        "additionalProperties": False,
    },
}

EDIT_FILE = {
    "name": "edit_file",
    "description": (
        "Replaces exact text in a file. `old` must appear in the file "
        "exactly once; on zero or more than one match nothing is written "
        "and an error is returned. Read the file before editing it."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old": {"type": "string", "description": "The exact text to replace"},
            "new": {"type": "string", "description": "The replacement text"},
        },
        "required": ["path", "old", "new"],
        "additionalProperties": False,
    },
}

LIST_DIR = {
    "name": "list_dir",
    "description": "Lists the contents of a folder.",
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
        "additionalProperties": False,
    },
}

TERMINAL_OPEN = {
    "name": "terminal_open",
    "description": (
        "Opens a persistent terminal session and returns its screen. Unlike "
        "`run_shell` the session stays open, so interactive programs work: "
        "Claude Code, opencode, REPLs, `git rebase -i`, servers. Use this "
        "for anything long-running or waiting for input."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "The name you give the session"},
            "command": {
                "type": "string",
                "description": "The command to run; empty opens PowerShell",
            },
            "cwd": {"type": "string", "description": "Working directory"},
        },
        "required": ["name"],
        "additionalProperties": False,
    },
}

TERMINAL_SEND = {
    "name": "terminal_send",
    "description": (
        "Sends text or a key to an open terminal and returns the screen "
        "once it settles. `text` is the text to type; `key` is a special "
        "key (enter, tab, escape, up, down, left, right, ctrl+c, ctrl+d, "
        "page_up, page_down, backspace, shift+tab). To run a command, give "
        "text and leave submit true. Use key to navigate a TUI."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "text": {"type": "string"},
            "key": {"type": "string"},
            "submit": {
                "type": "boolean",
                "description": "Send Enter after the text, default true",
            },
            "wait": {
                "type": "number",
                "description": "How many seconds to wait for the screen to "
                               "settle, default 15",
            },
        },
        "required": ["name"],
        "additionalProperties": False,
    },
}

TERMINAL_READ = {
    "name": "terminal_read",
    "description": (
        "Returns a terminal's current screen. Use it to follow the progress "
        "of a long job — it only reads, it sends nothing."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "wait": {
                "type": "number",
                "description": "Wait for the screen to settle before "
                               "reading, in seconds",
            },
        },
        "required": ["name"],
        "additionalProperties": False,
    },
}

TERMINAL_CLOSE = {
    "name": "terminal_close",
    "description": "Closes a terminal session and terminates the process "
                   "inside it.",
    "input_schema": {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
        "additionalProperties": False,
    },
}


# --- Ofis ---------------------------------------------------------------
#
# `why` her düzenleme aracında **zorunlu**. İsteğe bağlı olsaydı model çoğu
# zaman atlardı ve gerekçe defteri yarı dolu kalırdı; yarı dolu bir defter
# hiç olmamasından kötüdür, çünkü güvenilir sanılır.

OFFICE_OPEN = {
    "name": "office_open",
    "description": (
        "Opens a sheet (.xlsx) or a text document (.docx), creating the "
        "file if it does not exist. Microsoft Office is not required; the "
        "files are in the real Office format and open in Excel or Word. You "
        "refer to the document by the name you give it."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "The name you give the document"},
            "path": {"type": "string", "description": "File path (.xlsx or .docx)"},
        },
        "required": ["name", "path"],
        "additionalProperties": False,
    },
}

OFFICE_READ = {
    "name": "office_read",
    "description": (
        "Reads an open document. In a sheet, `ref` is a cell range (A1, "
        "B2:D20) and `sheet` a sheet name; in a text document `start` is a "
        "paragraph number. Always read before editing — paragraph numbers "
        "and cell contents may have changed."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "ref": {"type": "string", "description": "Cell range, for a sheet"},
            "sheet": {"type": "string", "description": "Sheet name, for a sheet"},
            "start": {"type": "integer", "description": "Starting paragraph, for a text "
                                                        "document"},
        },
        "required": ["name"],
        "additionalProperties": False,
    },
}

OFFICE_EDIT = {
    "name": "office_edit",
    "description": (
        "Edits the document. `why` is required — every change carries its "
        "reason and that record is shown to the user. Sheet operations: "
        "`write` (ref + values, values being a list of rows; you can write "
        "formulas like '=SUM(B2:B4)'), `add_sheet` (sheet). Text "
        "operations: `append` (text, optional style: Title, Heading 1, "
        "Heading 2, List Bullet, Quote), `replace` (index + text), "
        "`add_table` (values)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "operation": {
                "type": "string",
                "enum": ["write", "add_sheet", "append", "replace", "add_table"],
            },
            "why": {
                "type": "string",
                "description": "Why this change is being made; where the "
                               "value comes from",
            },
            "ref": {"type": "string"},
            "sheet": {"type": "string"},
            "values": {
                "type": "array",
                "description": "A list of rows; each row a list of cells",
                "items": {"type": "array", "items": {}},
            },
            "text": {"type": "string"},
            "style": {"type": "string"},
            "index": {"type": "integer"},
        },
        "required": ["name", "operation", "why"],
        "additionalProperties": False,
    },
}

OFFICE_SAVE = {
    "name": "office_save",
    "description": "Saves the document to disk. Give `path` to save it "
                   "elsewhere.",
    "input_schema": {
        "type": "object",
        "properties": {"name": {"type": "string"}, "path": {"type": "string"}},
        "required": ["name"],
        "additionalProperties": False,
    },
}

OFFICE_HISTORY = {
    "name": "office_history",
    "description": (
        "Returns the document's changes with their reasons. Give `undo` to "
        "revert that many recent changes."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "undo": {"type": "integer", "description": "How many changes to revert"},
        },
        "required": ["name"],
        "additionalProperties": False,
    },
}

OFFICE_CLOSE = {
    "name": "office_close",
    "description": (
        "Closes the document. Refuses if there are unsaved changes; pass "
        "discard=true if you are deliberately throwing them away."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "discard": {"type": "boolean"},
        },
        "required": ["name"],
        "additionalProperties": False,
    },
}

SKILL_LIST = {
    "name": "skill_list",
    "description": (
        "Lists the skills that have been written, including broken files "
        "that failed to load. Give name to see a skill's code."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "The name of the skill whose code you want "
                               "to read",
            }
        },
        "required": [],
        "additionalProperties": False,
    },
}

SKILL_WRITE = {
    "name": "skill_write",
    "description": (
        "Writes yourself a new skill or fixes an existing one. A skill is a "
        "Python file: an ARAC dict plus a calistir(girdi, ortam) function. "
        "It loads the moment it is written and you can call it on the next "
        "step. You cannot reuse an existing tool's name. Every write asks "
        "the user for approval and the full code is shown to them."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "File and tool name: lower case, digits, "
                               "underscore",
            },
            "code": {"type": "string", "description": "The skill's complete Python "
                                                      "code"},
            "why": {
                "type": "string",
                "description": "Why you are writing this skill — the user "
                               "sees it on the approval screen",
            },
        },
        "required": ["name", "code", "why"],
        "additionalProperties": False,
    },
}

SKILL_REMOVE = {
    "name": "skill_remove",
    "description": "Deletes a skill.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "why": {"type": "string", "description": "Why it is being removed"},
        },
        "required": ["name", "why"],
        "additionalProperties": False,
    },
}

BUTTON_WRITE = {
    "name": "button_write",
    "description": (
        "Sets up or changes one of the buttons on the user's bar. Clicking "
        "the button sends the instruction you wrote to the agent. Offer one "
        "when you notice a repeating job: 'shall I make this a button?'. "
        "The user can edit and delete these buttons themselves."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Identifier: lower case, "
                                                      "digits, underscore"},
            "label": {"type": "string", "description": "The button label, 22 "
                                                       "characters at most"},
            "instruction": {
                "type": "string",
                "description": "The instruction sent to you when it is "
                               "clicked",
            },
            "glyph": {
                "type": "string",
                "description": (
                    "Icon: goz, mercek, imlec, surukle, klavye, tus, "
                    "kaydir, pencere, kabuk, agac, sayfa, klasor, tablo, "
                    "yazi, kaydet, defter, yetenek, bekle"
                ),
            },
            "why": {"type": "string", "description": "Why this button"},
        },
        "required": ["name", "label", "instruction", "why"],
        "additionalProperties": False,
    },
}

BUTTON_REMOVE = {
    "name": "button_remove",
    "description": "Removes a button.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "why": {"type": "string"},
        },
        "required": ["name", "why"],
        "additionalProperties": False,
    },
}

REMOTE_CONNECT = {
    "name": "remote_connect",
    "description": (
        "Connects to a server over SSH. With `alias`, the entry in "
        "~/.ssh/config is used (the user's own server: brky). Once "
        "connected, remote_list, remote_read, remote_write and remote_run "
        "work, and the server's folders open in the interface."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "alias": {"type": "string", "description": "An alias from ~/.ssh/config"},
            "host": {"type": "string"},
            "user": {"type": "string"},
            "port": {"type": "integer"},
        },
        "required": [],
        "additionalProperties": False,
    },
}

REMOTE_LIST = {
    "name": "remote_list",
    "description": "Lists a folder on the server. Leave it empty for the "
                   "current one.",
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": [],
        "additionalProperties": False,
    },
}

REMOTE_READ = {
    "name": "remote_read",
    "description": "Reads a file on the server.",
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
        "additionalProperties": False,
    },
}

REMOTE_WRITE = {
    "name": "remote_write",
    "description": (
        "Writes a file on the server, overwriting it if it exists. Always "
        "asks for approval. Read the current state with remote_read first."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
            "why": {"type": "string", "description": "Why this change"},
        },
        "required": ["path", "content", "why"],
        "additionalProperties": False,
    },
}

REMOTE_RUN = {
    "name": "remote_run",
    "description": (
        "Runs a shell command on the server. Read-only commands (ls, cat, "
        "df, systemctl status, journalctl) run directly; every command that "
        "changes something is put to the user."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "timeout": {"type": "integer", "description": "Seconds, default 60"},
        },
        "required": ["command"],
        "additionalProperties": False,
    },
}

LIST_APPS = {
    "name": "list_apps",
    "description": (
        "Lists the installed apps. If you are unsure of an app's name, "
        "check here first; much cheaper than hunting through the Start menu "
        "with screenshots."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search text. Leave it empty to list "
                               "everything.",
            }
        },
        "required": [],
        "additionalProperties": False,
    },
}

WRITE_FILES = {
    "name": "write_files",
    "description": (
        "Writes several files in ONE call. Use it when you are setting up a "
        "project or a script: one call per file means one model turn per "
        "file, which makes the job several times slower. Missing folders "
        "are created. Overwriting an existing file asks for approval; a new "
        "file does not."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "files": {
                "type": "array",
                "description": "The files to write",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
            },
            "why": {"type": "string", "description": "What is being set up"},
        },
        "required": ["files"],
        "additionalProperties": False,
    },
}

# --- yan çalışma alanı ------------------------------------------------------
#
# Bunlar `computer` araç setinin karşılığı değil, **paraleli**. Computer
# araçları fiziksel fareyi sürüyor ve çalıştıkları sürece Berkay'ın
# bilgisayarını işgal ediyorlar. Yan alan görünmez bir masaüstünde duruyor;
# ajan orada çalışırken Berkay kendi işine devam edebiliyor.

SIDE_LAUNCH = {
    "name": "side_launch",
    "description": (
        "Launches an app IN THE SIDE WORKSPACE — on an invisible desktop. "
        "Nothing opens on the user's screen and their cursor and focus "
        "never move, so they can keep working while you do. Prefer it for "
        "long-running browser jobs. Limit: Microsoft Store apps (including "
        "Windows 11's Notepad) open no window here; classic .exe files and "
        "Chrome work."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": (
                    "The full command line. Quote the path, e.g. "
                    '"C:\\Program '
                    'Files\\Google\\Chrome\\Application\\chrome.exe" '
                    "https://example.com"
                ),
            }
        },
        "required": ["command"],
        "additionalProperties": False,
    },
}

SIDE_WINDOWS = {
    "name": "side_windows",
    "description": (
        "Lists the windows in the side workspace: hwnd, title, class and "
        "position. Get the hwnd from here before clicking or capturing."
    ),
    "input_schema": {
        "type": "object", "properties": {}, "additionalProperties": False,
    },
}

SIDE_CAPTURE = {
    "name": "side_capture",
    "description": (
        "Captures a window in the side workspace. Coordinates are relative "
        "to the window's top-left corner; side_act uses the same space."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"hwnd": {"type": "integer", "description": "Window handle"}},
        "required": ["hwnd"],
        "additionalProperties": False,
    },
}

SIDE_ACT = {
    "name": "side_act",
    "description": (
        "Clicks, types, presses a key or scrolls in the side workspace. The "
        "agent's own cursor is used; the user's mouse does not move. "
        "Modifier combinations (like Ctrl+S) DO NOT WORK HERE — click the "
        "menu instead."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "hwnd": {"type": "integer"},
            "action": {
                "type": "string",
                "enum": ["click", "right_click", "double_click", "type", "key", "scroll"],
            },
            "coordinate": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "[x, y], relative to the window's top-left "
                               "corner",
            },
            "text": {
                "type": "string",
                "description": "text for type, a key name for key (enter, "
                               "tab, escape, f5...)",
            },
            "amount": {"type": "integer", "description": "scroll amount; positive is up"},
        },
        "required": ["hwnd", "action"],
        "additionalProperties": False,
    },
}

SIDE_CLOSE = {
    "name": "side_close",
    "description": (
        "Closes the side workspace and terminates every app you launched "
        "there. Call it when you are done; otherwise the processes keep "
        "living invisibly in the background."
    ),
    "input_schema": {
        "type": "object", "properties": {}, "additionalProperties": False,
    },
}

RECORD_START = {
    "name": "record_start",
    "description": (
        "Starts recording a window in the side workspace to a video file. "
        "Use it when the user asks for a video or a recording of what you "
        "do, or wants something they can share afterwards — a screenshot "
        "shows where you ended up, a video shows how you got there. "
        "It records ONE window: the one you name, or the last one you "
        "touched. Windows only draws the desktop that has the keyboard, "
        "so the whole side desk cannot be captured — if the job moves to "
        "another window, stop and start again. "
        "Always call record_stop when you are done; a recording left "
        "running is stopped when the turn ends and the video ends there."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "hwnd": {
                "type": "integer",
                "description": "Window to record, from side_windows. "
                               "Defaults to the last window you acted on.",
            },
        },
        "additionalProperties": False,
    },
}

RECORD_STOP = {
    "name": "record_stop",
    "description": (
        "Stops the recording and returns the path of the video file and "
        "how long it is. Tell the user that path — the file is the whole "
        "point and they cannot find it otherwise."
    ),
    "input_schema": {
        "type": "object", "properties": {}, "additionalProperties": False,
    },
}

WORKFLOW_SAVE = {
    "name": "workflow_save",
    "description": (
        "Saves what you did in THIS turn as a replayable workflow. Only "
        "the actions that changed something are kept — screenshots, file "
        "reads and window reads are not. A saved workflow replays with no "
        "model call at all, so it is free and instant, and it re-finds "
        "moved controls by their accessibility identity. "
        "Save one when the user asks you to remember a job, or right after "
        "you finish a job they clearly do often. Do not save a job that "
        "went wrong or needed several attempts: you would be recording the "
        "attempts too."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Identifier: lower "
                     "case letters, digits and underscores"},
            "label": {"type": "string", "description": "Short human label, "
                      "up to 40 characters"},
        },
        "required": ["name", "label"],
        "additionalProperties": False,
    },
}

WORKFLOW_LIST = {
    "name": "workflow_list",
    "description": (
        "Lists saved workflows with their step counts. Check here before "
        "doing a job by hand: replaying costs nothing."
    ),
    "input_schema": {
        "type": "object", "properties": {}, "additionalProperties": False,
    },
}

WORKFLOW_RUN = {
    "name": "workflow_run",
    "description": (
        "Replays a saved workflow step by step. No screenshots and no "
        "thinking — the recorded actions run directly. It stops at the "
        "first step that fails or whose control cannot be found any more, "
        "and tells you which one. If it stops, carry on by hand from "
        "there."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
        "additionalProperties": False,
    },
}

WORKFLOW_REMOVE = {
    "name": "workflow_remove",
    "description": "Deletes a saved workflow.",
    "input_schema": {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
        "additionalProperties": False,
    },
}

HEADS_UP = {
    "name": "heads_up",
    "description": (
        "Writes a short note to the user about the thing you are about to "
        "do: what could go wrong, what you are being careful about, what "
        "you had to assume. It changes nothing on the machine and asks "
        "the user for nothing — it is a note, not a question, and it "
        "does not pause you. "
        "Use it right before you touch something inside an app where a "
        "mistake would be seen by other people or would be hard to undo: "
        "sending a message, posting, replying, deleting, renaming, "
        "paying, changing a setting, closing something unsaved. Also use "
        "it when the instruction left a choice open and you made it — "
        "say which way you went. "
        "One or two sentences, concrete. Name the thing, not the "
        "category: 'the reply goes to the #genel channel, not a DM' beats "
        "'be careful with messaging'. A note on every click is a note "
        "nobody reads."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "note": {
                "type": "string",
                "description": "What to watch out for, one or two sentences",
            },
            "about": {
                "type": "string",
                "description": "The operation it concerns, a few words",
            },
        },
        "required": ["note"],
        "additionalProperties": False,
    },
}

CUSTOM_TOOLS: list[dict[str, Any]] = [
    READ_UI_TREE,
    LAUNCH_APP,
    LIST_APPS,
    RUN_SHELL,
    SWITCH_DISPLAY,
    WRITE_FILE,
    WRITE_FILES,
    READ_FILE,
    EDIT_FILE,
    LIST_DIR,
    TERMINAL_OPEN,
    TERMINAL_SEND,
    TERMINAL_READ,
    TERMINAL_CLOSE,
    OFFICE_OPEN,
    OFFICE_READ,
    OFFICE_EDIT,
    OFFICE_SAVE,
    OFFICE_HISTORY,
    OFFICE_CLOSE,
    SKILL_LIST,
    SKILL_WRITE,
    SKILL_REMOVE,
    BUTTON_WRITE,
    BUTTON_REMOVE,
    REMOTE_CONNECT,
    REMOTE_LIST,
    REMOTE_READ,
    REMOTE_WRITE,
    REMOTE_RUN,
    SIDE_LAUNCH,
    SIDE_WINDOWS,
    SIDE_CAPTURE,
    SIDE_ACT,
    SIDE_CLOSE,
    RECORD_START,
    RECORD_STOP,
    HEADS_UP,
    WORKFLOW_SAVE,
    WORKFLOW_LIST,
    WORKFLOW_RUN,
    WORKFLOW_REMOVE,
]

CUSTOM_TOOL_NAMES = {tool["name"] for tool in CUSTOM_TOOLS}
