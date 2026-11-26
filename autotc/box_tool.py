"""Alat label kotak: lengkapi kotak kendaraan pada frame untuk melatih ulang detektor.

Kotak yang sudah dikenali model terisi otomatis; pengguna menambah kendaraan yang terlewat dan
menghapus kotak yang salah.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QVBoxLayout,
                               QWidget)

from . import boxes as B

COLORS = {"motorcycle": "#35d0ff", "car": "#6dff6d", "truck": "#ffb347", "bus": "#ff6df0", "bicycle": "#ffffff"}
FAR = (0.28, 0.12, 0.95, 0.62)   # bagian gambar yang diperbesar dengan tombol F (sisi jauh simpang)
MIN_SIDE = 6                     # piksel gambar; kotak lebih kecil dari ini dianggap salah klik


class Canvas(QWidget):
    def __init__(self, tool):
        super().__init__()
        self.tool = tool
        self.pix = None
        self.scale, self.off = 1.0, QPointF(0, 0)
        self.drag0 = self.drag1 = None      # kotak baru yang sedang ditarik (koordinat gambar)
        self.pan0 = None
        self.setMouseTracking(True)
        self.setMinimumSize(900, 520)
        self.setCursor(Qt.CrossCursor)

    # --- pandangan ---
    def set_image(self, pix: QPixmap, keep_view: bool):
        self.pix = pix
        if not keep_view:
            self.fit()
        self.update()

    def fit(self, region=None):
        if self.pix is None:
            return
        w, h = self.pix.width(), self.pix.height()
        x0, y0, x1, y1 = region or (0, 0, 1, 1)
        rw, rh = (x1 - x0) * w, (y1 - y0) * h
        self.scale = min(self.width() / rw, self.height() / rh)
        self.off = QPointF((self.width() - rw * self.scale) / 2 - x0 * w * self.scale,
                           (self.height() - rh * self.scale) / 2 - y0 * h * self.scale)
        self.update()

    def to_img(self, p) -> QPointF:
        return QPointF((p.x() - self.off.x()) / self.scale, (p.y() - self.off.y()) / self.scale)

    def wheelEvent(self, e):
        f = 1.25 if e.angleDelta().y() > 0 else 0.8
        new = min(max(self.scale * f, 0.1), 12.0)
        p = e.position()
        img = self.to_img(p)
        self.scale = new
        self.off = QPointF(p.x() - img.x() * new, p.y() - img.y() * new)
        self.update()

    # --- tetikus ---
    def mousePressEvent(self, e):
        if self.pix is None:
            return
        if e.button() == Qt.LeftButton:
            self.drag0 = self.drag1 = self.to_img(e.position())
        elif e.button() in (Qt.RightButton, Qt.MiddleButton):
            self.pan0 = (e.position(), QPointF(self.off))

    def mouseMoveEvent(self, e):
        if self.drag0 is not None:
            self.drag1 = self.to_img(e.position())
            self.update()
        elif self.pan0 is not None:
            self.off = self.pan0[1] + (e.position() - self.pan0[0])
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.drag0 is not None:
            a, b = self.drag0, self.to_img(e.position())
            self.drag0 = self.drag1 = None
            if abs(a.x() - b.x()) >= MIN_SIDE and abs(a.y() - b.y()) >= MIN_SIDE:
                self.tool.add_box(a.x(), a.y(), b.x(), b.y())
            else:
                self.tool.select_at(b.x(), b.y())
        elif e.button() in (Qt.RightButton, Qt.MiddleButton):
            self.pan0 = None
        self.update()

    # --- gambar ---
    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#202020"))
        if self.pix is None:
            return
        p.setRenderHint(QPainter.SmoothPixmapTransform, self.scale < 1)
        p.translate(self.off)
        p.scale(self.scale, self.scale)
        p.drawPixmap(0, 0, self.pix)
        p.setFont(QFont("Segoe UI", max(int(11 / self.scale), 1)))
        for i, (x1, y1, x2, y2, kind, src) in enumerate(self.tool.boxes):
            sel = i == self.tool.selected
            pen = QPen(QColor("#ff3030" if sel else COLORS.get(kind, "#ffffff")), (3 if sel else 1.6) / self.scale)
            if src == "manual" and not sel:
                pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.drawRect(QRectF(x1, y1, x2 - x1, y2 - y1))
            p.drawText(QPointF(x1, y1 - 3 / self.scale), B.KIND_LABEL.get(kind, kind))
        if self.drag0 is not None:
            p.setPen(QPen(QColor("#ffff00"), 2 / self.scale))
            p.drawRect(QRectF(self.drag0, self.drag1).normalized())


class BoxTool(QMainWindow):
    def __init__(self, folder: str | Path):
        super().__init__()
        self.folder = Path(folder)
        self.images = sorted(self.folder.glob("*.jpg"))
        self.data = [B.load(p) for p in self.images]
        self.idx, self.selected, self.kind = 0, -1, B.KINDS[0]
        self.undo_stack: list = []
        self.far = False
        self.setWindowTitle(f"Label kotak kendaraan - {self.folder.name}")

        self.canvas = Canvas(self)
        self.head = QLabel()
        self.head.setStyleSheet("font-size: 15px; font-weight: bold;")
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.kind_lbl = QLabel()
        self.kind_lbl.setStyleSheet("font-size: 14px;")
        guide = QLabel(
            "<b>Cara pakai</b><br>"
            "Tarik tombol kiri: kotak baru untuk kendaraan yang belum berkotak<br>"
            "Klik kotak lalu <b>Delete</b>: hapus kotak yang salah<br>"
            "<b>1</b> motor &nbsp; <b>2</b> mobil &nbsp; <b>3</b> truk &nbsp; <b>4</b> bus &nbsp; <b>5</b> sepeda<br>"
            "(mengubah kotak terpilih, dan jenis kotak baru berikutnya)<br>"
            "Roda tetikus: perbesar &nbsp; Tarik tombol kanan: geser<br>"
            "<b>F</b>: perbesar sisi jauh / seluruh gambar<br>"
            "<b>Ctrl+Z</b>: batalkan<br>"
            "<b>Enter</b> atau <b>Spasi</b>: gambar ini selesai, lanjut<br>"
            "<b>&larr; &rarr;</b>: gambar sebelumnya / berikutnya<br><br>"
            "<b>Yang ditandai</b><br>"
            "Semua kendaraan di jalan yang masih bisa Anda kenali, termasuk yang silau lampunya "
            "dan yang jauh di mulut jembatan. Kotak mengelilingi badan kendaraan beserta pengendaranya, "
            "bukan pantulan lampunya di aspal. Gambar tanpa kendaraan cukup ditekan Enter.")
        guide.setWordWrap(True)
        guide.setTextFormat(Qt.RichText)
        side = QVBoxLayout()
        for w in (self.head, self.info, self.kind_lbl, guide):
            side.addWidget(w)
        side.addStretch(1)
        for text, fn in (("Selesai, lanjut (Enter)", self.done_next), ("Lompat ke yang belum selesai", self.goto_undone)):
            b = QPushButton(text)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(fn)
            side.addWidget(b)
        panel = QWidget()
        panel.setLayout(side)
        panel.setFixedWidth(330)
        row = QHBoxLayout()
        row.addWidget(self.canvas, 1)
        row.addWidget(panel)
        central = QWidget()
        central.setLayout(row)
        self.setCentralWidget(central)
        self.resize(1500, 820)
        if self.images:
            self.goto_undone(first=True)

    # --- data gambar aktif ---
    @property
    def boxes(self) -> list:
        return self.data[self.idx]["kotak"] if self.images else []

    def _changed(self):
        B.save(self.images[self.idx], self.data[self.idx])
        self.refresh()

    def _remember(self):
        self.undo_stack.append((self.idx, [list(b) for b in self.boxes], self.data[self.idx].get("selesai", False)))
        del self.undo_stack[:-50]

    def add_box(self, x1, y1, x2, y2):
        pix = self.canvas.pix
        w, h = (pix.width(), pix.height()) if pix else (1e9, 1e9)
        x1, x2 = sorted((min(max(x1, 0), w), min(max(x2, 0), w)))
        y1, y2 = sorted((min(max(y1, 0), h), min(max(y2, 0), h)))
        if x2 - x1 < MIN_SIDE or y2 - y1 < MIN_SIDE:
            return
        self._remember()
        self.boxes.append([round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1), self.kind, "manual"])
        self.selected = len(self.boxes) - 1
        self._changed()

    def select_at(self, x, y):
        hits = [(( b[2] - b[0]) * (b[3] - b[1]), i) for i, b in enumerate(self.boxes)
                if b[0] <= x <= b[2] and b[1] <= y <= b[3]]
        self.selected = min(hits)[1] if hits else -1   # kotak terkecil di bawah kursor
        self.refresh()

    def delete_selected(self):
        if 0 <= self.selected < len(self.boxes):
            self._remember()
            del self.boxes[self.selected]
            self.selected = -1
            self._changed()

    def set_kind(self, kind: str):
        self.kind = kind
        if 0 <= self.selected < len(self.boxes) and self.boxes[self.selected][4] != kind:
            self._remember()
            self.boxes[self.selected][4] = kind
            self.boxes[self.selected][5] = "manual"
            self._changed()
        else:
            self.refresh()

    def undo(self):
        if not self.undo_stack:
            return
        idx, saved, done = self.undo_stack.pop()
        if idx != self.idx:
            self.show_image(idx)
        self.data[idx]["kotak"], self.data[idx]["selesai"] = saved, done
        self.selected = -1
        self._changed()

    # --- pindah gambar ---
    def show_image(self, idx: int):
        if not self.images:
            return
        first = self.canvas.pix is None
        self.idx, self.selected = max(0, min(idx, len(self.images) - 1)), -1
        self.canvas.set_image(QPixmap(str(self.images[self.idx])), keep_view=not first)
        self.refresh()

    def done_next(self):
        if not self.images:
            return
        self._remember()
        self.data[self.idx]["selesai"] = True
        B.save(self.images[self.idx], self.data[self.idx])
        if all(d.get("selesai") for d in self.data):
            self.refresh()
            QMessageBox.information(self, "Selesai", "Semua gambar sudah selesai dilabeli.")
            return
        self.goto_undone()

    def goto_undone(self, first: bool = False):
        n = len(self.images)
        order = range(n) if first else [(self.idx + k) % n for k in range(1, n + 1)]
        self.show_image(next((i for i in order if not self.data[i].get("selesai")), self.idx))

    def toggle_far(self):
        self.far = not self.far
        self.canvas.fit(FAR if self.far else None)

    def refresh(self):
        if not self.images:
            self.head.setText("Tidak ada gambar di folder ini.")
            return
        d = self.data[self.idx]
        done = sum(x.get("selesai", False) for x in self.data)
        self.head.setText(f"Gambar {self.idx + 1} dari {len(self.images)}" + ("  (selesai)" if d.get("selesai") else ""))
        manual = sum(b[5] == "manual" for b in d["kotak"])
        self.info.setText(f"{self.images[self.idx].name}\nSelesai: {done} dari {len(self.images)} gambar\n"
                          f"Kotak di gambar ini: {len(d['kotak'])} ({manual} dari Anda)")
        self.kind_lbl.setText(f"Jenis kotak baru: <b>{B.KIND_LABEL[self.kind]}</b>")
        self.canvas.update()

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.done_next()
        elif k in (Qt.Key_Delete, Qt.Key_Backspace):
            self.delete_selected()
        elif Qt.Key_1 <= k <= Qt.Key_5:
            self.set_kind(B.KINDS[k - Qt.Key_1])
        elif k == Qt.Key_Z and e.modifiers() & Qt.ControlModifier:
            self.undo()
        elif k == Qt.Key_F:
            self.toggle_far()
        elif k in (Qt.Key_Right, Qt.Key_PageDown):
            self.show_image(self.idx + 1)
        elif k in (Qt.Key_Left, Qt.Key_PageUp):
            self.show_image(self.idx - 1)
        elif k == Qt.Key_Escape:
            self.selected = -1
            self.refresh()
        else:
            super().keyPressEvent(e)


def run(folder: str | Path | None = None) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    w = BoxTool(folder or B.DATA / "rajekwesi")
    w.showMaximized()
    return app.exec()
