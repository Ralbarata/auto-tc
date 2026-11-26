"""Alat pelabelan kelas PKJI: kisi potongan gambar kendaraan, satu gambar per lintasan.

Pilih kelas ("kuas") dengan tombol 1-6 atau 0 untuk buang, lalu klik gambar yang kelasnya itu.
Spasi = terima tebakan awal untuk semua yang belum dilabeli di halaman ini, lalu lanjut.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from .labels import CLASSES, DISCARD, load_items, load_labels, save_labels

COLORS = {"SM": "#4363d8", "MP": "#3cb44b", "KS": "#f58231", "BB": "#911eb4", "TB": "#e6194b", "KTB": "#00a3a3",
          DISCARD: "#808080"}
HINTS = {
    "SM": "motor, roda tiga", "MP": "sedan, jip, minibus, pikap, truk kecil", "KS": "bus sedang, truk 2 sumbu",
    "BB": "bus besar", "TB": "truk 3 sumbu, gandeng, tempel", "KTB": "sepeda, becak, gerobak",
    DISCARD: "bukan kendaraan / tidak jelas",
}
COLS, ROWS, THUMB = 8, 4, 150


class Thumb(QWidget):
    clicked = Signal(int)

    def __init__(self, index: int):
        super().__init__()
        self.index, self.pix, self.label, self.guess = index, None, "", ""
        self.setFixedSize(THUMB + 8, THUMB + 8)

    def set(self, pix: QPixmap | None, label: str, guess: str):
        self.pix, self.label, self.guess = pix, label, guess
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.pix is not None:
            self.clicked.emit(self.index)

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#1c1c1c"))
        if self.pix is None:
            return
        s = self.pix.scaled(THUMB, THUMB, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        p.drawPixmap(4 + (THUMB - s.width()) // 2, 4 + (THUMB - s.height()) // 2, s)
        f = QFont()
        f.setBold(True)
        if self.label:
            c = QColor(COLORS[self.label])
            p.setPen(QPen(c, 5))
            p.drawRect(2, 2, self.width() - 5, self.height() - 5)
            f.setPointSize(13)
            p.setFont(f)
            p.fillRect(4, 4, 14 + 12 * len(self.label), 24, c)
            p.setPen(QColor("white"))
            p.drawText(8, 22, self.label)
        else:
            p.setPen(QPen(QColor("#666666"), 1, Qt.DashLine))
            p.drawRect(1, 1, self.width() - 3, self.height() - 3)
            f.setPointSize(9)
            p.setFont(f)
            p.setPen(QColor("#dddddd"))
            p.drawText(6, 18, f"tebakan: {self.guess or '?'}")


class LabelTool(QWidget):
    def __init__(self, data_dir: str | Path):
        super().__init__()
        self.setWindowTitle("AUTO TC - Label kelas PKJI")
        self.data_dir = Path(data_dir)
        self.label_path = self.data_dir / "label.csv"
        self.items = load_items(self.data_dir)
        self.labels = load_labels(self.label_path)
        self.view: list[dict] = []
        self.page = 0
        self.brush = "SM"

        top = QHBoxLayout()
        self.group = QButtonGroup(self)
        for i, name in enumerate(CLASSES + [DISCARD]):
            key = 0 if name == DISCARD else i + 1
            b = QPushButton(f"{key}  {name}")
            b.setCheckable(True)
            b.setToolTip(HINTS[name])
            b.setStyleSheet(f"QPushButton:checked {{ background: {COLORS[name]}; color: white; font-weight: bold; }}")
            b.clicked.connect(lambda _=False, n=name: self.set_brush(n))
            self.group.addButton(b)
            top.addWidget(b)
            if name == self.brush:
                b.setChecked(True)
        self.hint = QLabel()
        top.addWidget(self.hint, 1)
        self.filter = QComboBox()
        self.filter.addItem("Belum dilabeli: semua", ("todo", None))
        for c in CLASSES:
            self.filter.addItem(f"Belum dilabeli: tebakan {c}", ("todo", c))
        self.filter.addItem("Belum dilabeli: malam saja", ("todo-malam", None))
        for c in CLASSES + [DISCARD]:
            self.filter.addItem(f"Sudah dilabeli: {c}", ("done", c))
        self.filter.currentIndexChanged.connect(self.apply_filter)
        top.addWidget(self.filter)

        grid = QGridLayout()
        grid.setSpacing(4)
        self.thumbs = []
        for i in range(COLS * ROWS):
            t = Thumb(i)
            t.clicked.connect(self.click)
            grid.addWidget(t, i // COLS, i % COLS)
            self.thumbs.append(t)

        bottom = QHBoxLayout()
        prev_b, next_b = QPushButton("< Sebelumnya"), QPushButton("Berikutnya >")
        accept = QPushButton("Terima tebakan untuk yang belum dilabeli di halaman ini, lalu lanjut  (Spasi)")
        prev_b.clicked.connect(lambda: self.go(-1))
        next_b.clicked.connect(lambda: self.go(1))
        accept.clicked.connect(self.accept_page)
        self.progress = QLabel()
        bottom.addWidget(prev_b)
        bottom.addWidget(accept, 1)
        bottom.addWidget(next_b)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addLayout(grid)
        lay.addLayout(bottom)
        lay.addWidget(self.progress)
        for w in self.findChildren(QPushButton) + [self.filter]:
            w.setFocusPolicy(Qt.NoFocus)  # supaya Spasi dan angka selalu sampai ke jendela, bukan ke tombol
        self.setFocusPolicy(Qt.StrongFocus)
        self.set_brush(self.brush)
        self.apply_filter()

    # --- tampilan
    def set_brush(self, name: str):
        self.brush = name
        for b in self.group.buttons():
            b.setChecked(b.text().split()[-1] == name)
        self.hint.setText(f"  Kuas: <b>{name}</b> ({HINTS[name]}). Klik gambar untuk memberi label ini.")

    def apply_filter(self):
        kind, cls = self.filter.currentData()
        if kind == "todo":
            self.view = [it for it in self.items if it["kunci"] not in self.labels and cls in (None, it["awal"])]
        elif kind == "todo-malam":
            self.view = [it for it in self.items if it["kunci"] not in self.labels and it["mode"] == "malam"]
        else:
            self.view = [it for it in self.items if self.labels.get(it["kunci"]) == cls]
        self.page = 0
        self.show_page()

    def page_items(self) -> list[dict]:
        n = COLS * ROWS
        return self.view[self.page * n:(self.page + 1) * n]

    def show_page(self):
        items = self.page_items()
        for i, t in enumerate(self.thumbs):
            if i < len(items):
                it = items[i]
                t.set(QPixmap(str(self.data_dir / it["berkas"])), self.labels.get(it["kunci"], ""), it["awal"])
            else:
                t.set(None, "", "")
        done = Counter(self.labels.values())
        pages = max((len(self.view) + COLS * ROWS - 1) // (COLS * ROWS), 1)
        self.progress.setText(
            f"Halaman {self.page + 1} dari {pages}  |  dilabeli {len(self.labels)} dari {len(self.items)} kendaraan  |  "
            + "  ".join(f"{c}: {done[c]}" for c in CLASSES + [DISCARD]))

    # --- aksi
    def click(self, i: int):
        items = self.page_items()
        if i >= len(items):
            return
        key = items[i]["kunci"]
        if self.labels.get(key) == self.brush:
            del self.labels[key]      # klik lagi dengan kuas yang sama = batalkan
        else:
            self.labels[key] = self.brush
        save_labels(self.label_path, self.labels)
        self.show_page()

    def accept_page(self):
        for it in self.page_items():
            if it["kunci"] not in self.labels and it["awal"] in CLASSES:
                self.labels[it["kunci"]] = it["awal"]
        save_labels(self.label_path, self.labels)
        self.go(1)

    def go(self, step: int):
        pages = max((len(self.view) + COLS * ROWS - 1) // (COLS * ROWS), 1)
        self.page = min(max(self.page + step, 0), pages - 1)
        self.show_page()

    def keyPressEvent(self, e):
        k = e.key()
        if Qt.Key_1 <= k < Qt.Key_1 + len(CLASSES):
            self.set_brush(CLASSES[k - Qt.Key_1])
        elif k == Qt.Key_0:
            self.set_brush(DISCARD)
        elif k == Qt.Key_Space:
            self.accept_page()
        elif k in (Qt.Key_Right, Qt.Key_PageDown):
            self.go(1)
        elif k in (Qt.Key_Left, Qt.Key_PageUp):
            self.go(-1)


def run(data_dir):
    app = QApplication.instance() or QApplication(sys.argv)
    w = LabelTool(data_dir)
    w.show()
    return app.exec()
