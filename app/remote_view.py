"""Uzak makine paneli — sunucuyu kendi bilgisayarın gibi gez.

Bir sunucuya bağlanmanın alışılmış yolu terminal: `ls`, `cd`, `cat`. Çalışır
ama nerede olduğunu aklında tutmak zorundasın ve bir dizinde ne olduğunu
görmek için her seferinde komut yazıyorsun. Burada klasörler bir listede,
yol bir kırıntı çubuğunda, dosyalar boyutu ve tarihiyle duruyor — Dosya
Gezgini'nde ne bekliyorsan o.

Dosya Gezgini taklidi değil, aynı görsel dil: aynı Fluent renkleri, aynı
çizimler. Uzak makine ayrı bir dünya gibi değil, aynı uygulamanın bir
sekmesi gibi görünüyor. Zaten amaç bu.

**Bu panel salt okunur değil ama silme yok.** Dosya okunuyor, yazılıyor,
gezinliyor; silme ve taşıma buradan yapılamıyor. Yanlış klasörde yapılan
bir sağ tık > sil, sunucuda geri alınamaz.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import isletim
from .fluent import RADIUS_CONTROL, Tokens
from .glyphs import glyph_icon


def _varsayilan(alan: str) -> str:
    """Bağlantı alanının `.env`'den gelen ön dolgusu.

    Depoda gerçek bir sunucu adresi durmuyor: bir IP, kullanıcı adı ve
    SSH portu tek başına parola değil ama açık bir depoda "şu adreste
    root, şu portta" demek, kaba kuvvet denemesi için hazır bir hedef
    vermek demek. Kendi sunucun `.env`'de.

    Ayar okunamıyorsa boş dönüyor — bu panel bir kolaylık, ve eksik bir
    `.env` yüzünden uygulamanın açılmaması saçma olurdu.
    """
    try:
        from backend.config import Config

        return str(getattr(Config.load(), alan, "") or "")
    except Exception:
        return ""

#: Uzantıya göre çizim. Bir sunucuda en çok bunlar aranıyor.
BY_SUFFIX = {
    ".sh": "kabuk", ".bash": "kabuk", ".zsh": "kabuk",
    ".py": "kabuk", ".js": "kabuk", ".ts": "kabuk", ".go": "kabuk",
    ".service": "pencere", ".socket": "pencere", ".timer": "bekle",
    ".conf": "sayfa", ".cfg": "sayfa", ".ini": "sayfa", ".toml": "sayfa",
    ".yml": "sayfa", ".yaml": "sayfa", ".json": "sayfa", ".env": "sayfa",
    ".log": "defter",
    ".csv": "tablo", ".xlsx": "tablo", ".db": "tablo", ".sqlite": "tablo",
    ".md": "yazi", ".txt": "yazi", ".docx": "yazi",
}


def _glyph_for(entry) -> str:
    if entry.is_dir:
        return "klasor"
    name = entry.name.lower()
    for suffix, key in BY_SUFFIX.items():
        if name.endswith(suffix):
            return key
    # Çalıştırılabilir olduğunu izinlerden anlıyoruz; uzantısız komut
    # dosyaları bir sunucuda kuraldır, istisna değil.
    return "kabuk" if "x" in entry.mode[1:4] else "sayfa"


class ConnectDialog(QDialog):
    """SSH bilgileri.

    Takma ad alanı en üstte ve öncelikli: `~/.ssh/config` içinde tanımlı bir
    ad varsa geri kalanını doldurmak gereksiz, üstelik oradaki ayarı ezmek
    çalışan bir bağlantıyı bozar.
    """

    def __init__(self, t: Tokens, parent=None) -> None:
        super().__init__(parent)
        self.t = t
        self.setWindowTitle("Connect to a server")
        self.setMinimumWidth(420)
        self.setStyleSheet(
            f"QDialog {{ background: {t.background}; }}"
            f"QLabel {{ color: {t.text_secondary}; font-size: 12px; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(10)

        self.alias = QLineEdit(_varsayilan("ssh_alias"))
        self.alias.setPlaceholderText("sunucum")
        self.alias.setStyleSheet(self._field(t))
        form.addRow("Takma ad", self.alias)

        hint = QLabel(
            "If the name is defined in ~/.ssh/config, fill in only that; "
            "leave the rest empty."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {t.text_tertiary}; font-size: 11px;")
        form.addRow("", hint)

        self.host = QLineEdit(_varsayilan("ssh_host"))
        # Yer tutucu RFC 5737'nin belgeleme aralığından: gerçek bir
        # makineye çözülemez, yani depoda kimsenin sunucusu durmuyor.
        self.host.setPlaceholderText("203.0.113.10")
        self.host.setStyleSheet(self._field(t))
        form.addRow("Sunucu", self.host)

        self.user = QLineEdit(_varsayilan("ssh_user") or "root")
        self.user.setStyleSheet(self._field(t))
        form.addRow("User", self.user)

        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(int(_varsayilan("ssh_port") or 22))
        self.port.setStyleSheet(self._field(t))
        form.addRow("Port", self.port)

        self.key = QLineEdit()
        # Yer tutucu platformun kendi yol biçimi; Linux'ta `C:\Users\...`
        # yanlış bir yol gösterirdi.
        self.key.setPlaceholderText(isletim.anahtar_ipucu())
        self.key.setStyleSheet(self._field(t))
        form.addRow("Anahtar", self.key)
        layout.addLayout(form)

        # Parolayı desteklemediğimizi gizlemek, parola alanını arayan
        # kullanıcıyı boşuna aratırdı.
        note = QLabel(
            "Password login is not supported — the password would have to "
            "be stored somewhere. Add your key to the server instead."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {t.text_tertiary}; font-size: 11px;")
        layout.addWidget(note)

        self._error = QLabel()
        self._error.setWordWrap(True)
        self._error.setStyleSheet(f"color: {t.critical}; font-size: 12px;")
        self._error.setVisible(False)
        layout.addWidget(self._error)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Connect")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancel")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _field(self, t: Tokens) -> str:
        return (
            f"QLineEdit, QSpinBox {{ background: {t.control};"
            f" border: 1px solid {t.control_stroke};"
            f" border-radius: {RADIUS_CONTROL}px; padding: 6px 8px;"
            f" color: {t.text}; font-size: 13px;"
            f" selection-background-color: {t.accent};"
            f" selection-color: {t.on_accent}; }}"
        )

    def _accept(self) -> None:
        if not self.alias.text().strip() and not self.host.text().strip():
            self._error.setText("Takma ad ya da sunucu adresi gerekli.")
            self._error.setVisible(True)
            return
        self.accept()

    def result_host(self):
        from backend.remote.ssh import SshHost

        return SshHost(
            alias=self.alias.text().strip(),
            host=self.host.text().strip(),
            user=self.user.text().strip() or "root",
            port=self.port.value(),
            key=self.key.text().strip(),
        )


class Breadcrumb(QWidget):
    """Yol, tıklanabilir parçalar hâlinde."""

    jumped = Signal(str)

    def __init__(self, t: Tokens) -> None:
        super().__init__()
        self.t = t
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)

    def set_path(self, path: str) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        parts = [p for p in path.split("/") if p]
        walked = ""
        for index, part in enumerate([""] + parts):
            walked = walked + "/" + part if part else "/"
            chip = QPushButton(part or "/")
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setFixedHeight(24)
            son = index == len(parts)
            chip.setStyleSheet(
                f"QPushButton {{ background: transparent; border: none;"
                f" padding: 0 6px; border-radius: {RADIUS_CONTROL}px;"
                f" color: {self.t.text if son else self.t.text_secondary};"
                f" font-size: 12px; font-weight: {600 if son else 400}; }}"
                f"QPushButton:hover {{ background: {self.t.subtle_hover};"
                f" color: {self.t.text}; }}"
            )
            chip.clicked.connect(lambda _=False, p=walked: self.jumped.emit(p))
            self._layout.addWidget(chip)
            if not son:
                sep = QLabel("›")
                sep.setStyleSheet(
                    f"color: {self.t.text_tertiary}; font-size: 12px;"
                )
                self._layout.addWidget(sep)
        self._layout.addStretch(1)


class RemoteView(QWidget):
    """Uzak makinenin dosya tarayıcısı."""

    #: Ajana gönderilecek talimat — bir dosyaya sağ tıklayıp "ajana sor".
    ask_agent = Signal(str)

    def __init__(self, t: Tokens, session) -> None:
        super().__init__()
        self.t = t
        self.session = session
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._toolbar(t))

        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["Name", "Size", "Modified", "Permissions"])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setIconSize(QSize(18, 18))
        self.tree.setAlternatingRowColors(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.itemActivated.connect(self._open)
        self.tree.setStyleSheet(
            f"QTreeWidget {{ background: {t.background}; border: none;"
            f" color: {t.text}; font-size: 13px; outline: none; }}"
            f"QTreeWidget::item {{ height: 28px; border: none; }}"
            f"QTreeWidget::item:hover {{ background: {t.subtle_hover}; }}"
            f"QTreeWidget::item:selected {{ background: {t.accent};"
            f" color: {t.on_accent}; }}"
            f"QHeaderView::section {{ background: {t.background};"
            f" border: none; border-bottom: 1px solid {t.divider};"
            f" padding: 6px 8px; color: {t.text_secondary};"
            f" font-size: 12px; font-weight: 600; }}"
        )
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.tree, 1)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet(
            f"color: {t.text_secondary}; font-size: 12px;"
            f" border-top: 1px solid {t.divider}; padding: 7px 12px;"
        )
        layout.addWidget(self.status)

    def _toolbar(self, t: Tokens) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(40)
        bar.setStyleSheet(
            f"background: {t.background}; border-bottom: 1px solid {t.divider};"
        )
        row = QHBoxLayout(bar)
        row.setContentsMargins(8, 6, 10, 6)
        row.setSpacing(6)

        self._up = self._tool_button(t, "Parent folder", "yukari")
        self._up.clicked.connect(self.go_up)
        row.addWidget(self._up)

        self._refresh = self._tool_button(t, "Yenile", "yenile")
        self._refresh.clicked.connect(lambda: self.show_path(self.session.cwd, True))
        row.addWidget(self._refresh)

        self.crumbs = Breadcrumb(t)
        self.crumbs.jumped.connect(lambda p: self.show_path(p))
        row.addWidget(self.crumbs, 1)

        self._host = QLabel(self.session.host.label)
        self._host.setStyleSheet(
            f"color: {t.text_tertiary}; font-size: 11px;"
            f" font-family: '{t.font_mono}';"
        )
        row.addWidget(self._host)
        return bar

    def _tool_button(self, t: Tokens, tip: str, glyph: str) -> QPushButton:
        """Unicode karakter değil, kendi çizimimiz. Bir yazı tipindeki
        oka güvenmek, o glifi taşımayan bir sistemde boş kare demek."""
        button = QPushButton()
        button.setIcon(glyph_icon(glyph, 18, t.text_secondary, t.text_tertiary))
        button.setIconSize(QSize(18, 18))
        button.setToolTip(tip)
        button.setFixedSize(28, 28)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none;"
            f" border-radius: {RADIUS_CONTROL}px; }}"
            f"QPushButton:hover {{ background: {t.subtle_hover}; }}"
            f"QPushButton:disabled {{ opacity: 0.4; }}"
        )
        return button

    # --- gezinme ----------------------------------------------------------

    def show_path(self, path: str, refresh: bool = False) -> None:
        from backend.remote.ssh import RemoteError

        try:
            entries = self.session.listdir(path, refresh=refresh)
        except RemoteError as exc:
            # Hata gizlenmiyor ve liste de silinmiyor: izin verilmeyen bir
            # klasöre girmeye çalışmak, bulunduğun yeri kaybettirmemeli.
            self.status.setText(str(exc))
            self.status.setStyleSheet(
                f"color: {self.t.critical}; font-size: 12px;"
                f" border-top: 1px solid {self.t.divider}; padding: 7px 12px;"
            )
            return

        self.session.cwd = path
        self.tree.clear()
        for entry in entries:
            item = QTreeWidgetItem([
                entry.name, entry.size_label, entry.modified, entry.mode
            ])
            item.setIcon(0, glyph_icon(
                _glyph_for(entry), 18,
                self.t.accent if entry.is_dir else self.t.text_secondary,
                self.t.text_tertiary,
            ))
            item.setData(0, Qt.ItemDataRole.UserRole, entry)
            self.tree.addTopLevelItem(item)

        self.crumbs.set_path(path)
        self._up.setEnabled(path != "/")
        klasor = sum(1 for e in entries if e.is_dir)
        self.status.setText(
            f"{klasor} folders, {len(entries) - klasor} files"
            if entries else "This folder is empty."
        )
        self.status.setStyleSheet(
            f"color: {self.t.text_secondary}; font-size: 12px;"
            f" border-top: 1px solid {self.t.divider}; padding: 7px 12px;"
        )

    def go_up(self) -> None:
        from pathlib import PurePosixPath

        self.show_path(str(PurePosixPath(self.session.cwd).parent))

    def _open(self, item: QTreeWidgetItem, _column: int) -> None:
        entry = item.data(0, Qt.ItemDataRole.UserRole)
        if entry is None:
            return
        if entry.is_dir:
            self.show_path(entry.path)
            return
        self._preview(entry)

    def _preview(self, entry) -> None:
        from backend.remote.ssh import RemoteError

        try:
            text = self.session.read(entry.path)
        except RemoteError as exc:
            self.status.setText(str(exc))
            return
        FilePreview(self.t, entry.path, text, self).exec()


class FilePreview(QDialog):
    """Uzak dosyanın içeriği. Salt okunur — buradan yazmak, hangi sunucuda
    olduğunu unutmuş birinin yapabileceği en pahalı hata."""

    def __init__(self, t: Tokens, path: str, text: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(path)
        self.resize(860, 600)
        self.setStyleSheet(f"QDialog {{ background: {t.background}; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        head = QLabel(f"{path}  ·  {len(text.splitlines())} lines")
        head.setStyleSheet(f"color: {t.text_secondary}; font-size: 12px;")
        layout.addWidget(head)

        body = QPlainTextEdit(text)
        body.setReadOnly(True)
        body.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        body.setStyleSheet(
            f"QPlainTextEdit {{ background: {t.background_secondary};"
            f" border: 1px solid {t.stroke};"
            f" border-radius: {RADIUS_CONTROL}px; padding: 8px;"
            f" color: {t.text}; font-family: '{t.font_mono}'; font-size: 12px;"
            f" selection-background-color: {t.accent};"
            f" selection-color: {t.on_accent}; }}"
        )
        layout.addWidget(body, 1)
