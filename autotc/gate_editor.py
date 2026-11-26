"""Editor gerbang: gambar poligon gerbang di atas satu frame video, simpan ke berkas proyek.

Klik kiri = tambah titik, klik ganda / Enter = selesai, klik kanan = hapus titik terakhir, Esc = batal.
Titik gerbang yang sudah ada bisa digeser.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QMessageBox, QPushButton, QTextBrowser, QVBoxLayout, QWidget,
)

DEFAULT_PROJECT = {
    "nama": "",
    "interval_menit": 5,
    "peta_kelas": {"motorcycle": "SM", "car": "MP", "truck": "KS", "bus": "BB"},
    "catatan_kelas": "Sementara: memakai kelas bawaan model. TB belum bisa dibedakan dari KS sebelum model dilatih ulang.",
    "gerbang": [],
}
COLORS = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#42d4f4", "#f032e6", "#bfef45"]


def grab_frame(video: str | Path, second: float = 60.0) -> np.ndarray | None:
    cap = cv2.VideoCapture(str(video))
    cap.set(cv2.CAP_PROP_POS_MSEC, second * 1000)
    ok, frame = cap.read()
    if not ok:  # video lebih pendek dari yang diminta
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        ok, frame = cap.read()
    cap.release()
    return frame if ok else None


def to_pixmap(bgr: np.ndarray) -> QPixmap:
    rgb = np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    h, w = rgb.shape[:2]
    return QPixmap.fromImage(QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy())


def trajectory_overlay(npz: str | Path, width: int = 1344) -> QPixmap:
    """Semua lintasan bergerak sebagai garis tipis; membantu melihat di mana kendaraan muncul dan hilang."""
    from .movements import load_tracks
    meta, tracks = load_tracks(npz)
    s = width / meta["width"]
    img = np.zeros((int(meta["height"] * s), width, 4), np.uint8)
    for t in tracks:
        if len(t.frames) >= 5 and t.extent >= 0.05 * meta["width"]:
            cv2.polylines(img, [(t.foot * s).astype(np.int32)], False, (255, 230, 0, 55), 1, cv2.LINE_AA)
    return QPixmap.fromImage(QImage(img.data, img.shape[1], img.shape[0], 4 * img.shape[1], QImage.Format_RGBA8888).copy())


def movement_overlay(tracks, meta: dict, width: int = 1344) -> tuple[QPixmap, dict[str, str]]:
    """Lintasan berwarna per gerakan (abu-abu = tidak teridentifikasi) dan warna tiap gerakan (#rrggbb)."""
    from .movements import UNKNOWN, _palette

    def valid(t):
        return UNKNOWN not in (t.origin, t.dest) and t.origin != t.dest

    bgr = _palette(sorted({t.movement for t in tracks if valid(t)}))
    s = width / meta["width"]
    img = np.zeros((int(meta["height"] * s), width, 4), np.uint8)
    for t in sorted(tracks, key=valid):  # yang teridentifikasi digambar paling atas
        b, g, r = bgr[t.movement] if valid(t) else (170, 170, 170)
        cv2.polylines(img, [(t.foot * s).astype(np.int32)], False, (r, g, b, 200 if valid(t) else 110), 1, cv2.LINE_AA)
    pix = QPixmap.fromImage(QImage(img.data, img.shape[1], img.shape[0], 4 * img.shape[1], QImage.Format_RGBA8888).copy())
    return pix, {mv: "#{:02x}{:02x}{:02x}".format(c[2], c[1], c[0]) for mv, c in bgr.items()}


class Canvas(QWidget):
    changed = Signal()
    polygon_closed = Signal()

    def __init__(self):
        super().__init__()
        self.setMinimumSize(640, 360)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.frame: QPixmap | None = None
        self.overlay: QPixmap | None = None
        self.show_overlay = True
        self.gates: list[dict] = []
        self.draft: list[list[float]] = []
        self.selected = -1
        self._drag: tuple[int, int] | None = None
        self._cursor: QPointF | None = None

    # --- koordinat: poligon disimpan 0-1 supaya tidak bergantung resolusi video
    def image_rect(self) -> QRectF:
        if not self.frame:
            return QRectF(self.rect())
        s = min(self.width() / self.frame.width(), self.height() / self.frame.height())
        w, h = self.frame.width() * s, self.frame.height() * s
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def to_widget(self, p) -> QPointF:
        r = self.image_rect()
        return QPointF(r.x() + p[0] * r.width(), r.y() + p[1] * r.height())

    def to_norm(self, pos) -> list[float]:
        r = self.image_rect()
        return [round(min(max((pos.x() - r.x()) / r.width(), 0.0), 1.0), 4),
                round(min(max((pos.y() - r.y()) / r.height(), 0.0), 1.0), 4)]

    def _vertex_at(self, pos) -> tuple[int, int] | None:
        for gi, g in enumerate(self.gates):
            for vi, p in enumerate(g["poligon"]):
                q = self.to_widget(p)
                if abs(q.x() - pos.x()) + abs(q.y() - pos.y()) < 12:
                    return gi, vi
        return None

    # --- interaksi
    def mousePressEvent(self, e):
        pos = e.position()
        if e.button() == Qt.RightButton:
            if self.draft:
                self.draft.pop()
                self.update()
            return
        if e.button() != Qt.LeftButton:
            return
        if not self.draft:
            hit = self._vertex_at(pos)
            if hit:
                self._drag, self.selected = hit, hit[0]
                self.changed.emit()
                return
        self.draft.append(self.to_norm(pos))
        self.update()

    def mouseMoveEvent(self, e):
        self._cursor = e.position()
        if self._drag:
            gi, vi = self._drag
            self.gates[gi]["poligon"][vi] = self.to_norm(e.position())
        self.update()

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._drag = None
            self.changed.emit()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton and self.draft:
            self.draft.pop()  # klik kedua dari klik ganda menambah titik kembar
            self.close_polygon()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.close_polygon()
        elif e.key() == Qt.Key_Escape:
            self.draft = []
            self.update()

    def close_polygon(self):
        if len(self.draft) >= 3:
            self.polygon_closed.emit()

    def add_gate(self, name: str):
        self.gates.append({"nama": name, "poligon": self.draft})
        self.draft = []
        self.selected = len(self.gates) - 1
        self.changed.emit()
        self.update()

    # --- gambar
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#202020"))
        r = self.image_rect()
        if self.frame:
            p.drawPixmap(r, self.frame, QRectF(self.frame.rect()))
        if self.overlay and self.show_overlay:
            p.drawPixmap(r, self.overlay, QRectF(self.overlay.rect()))
        for i, g in enumerate(self.gates):
            c = QColor(COLORS[i % len(COLORS)])
            poly = QPolygonF([self.to_widget(q) for q in g["poligon"]])
            fill = QColor(c)
            fill.setAlpha(110 if i == self.selected else 60)
            p.setPen(QPen(c, 3 if i == self.selected else 2))
            p.setBrush(fill)
            p.drawPolygon(poly)
            p.setBrush(c)
            for q in poly:
                p.drawEllipse(q, 4, 4)
            p.setPen(QColor("white"))
            f = p.font()
            f.setBold(True)
            f.setPointSize(11)
            p.setFont(f)
            p.drawText(poly.boundingRect().topLeft() + QPointF(6, 18), g["nama"])
        if self.draft:
            pts = [self.to_widget(q) for q in self.draft]
            p.setPen(QPen(QColor("white"), 2, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawPolyline(QPolygonF(pts + ([self._cursor] if self._cursor else [])))
            p.setBrush(QColor("white"))
            for q in pts:
                p.drawEllipse(q, 4, 4)
        p.end()


class GateEditor(QWidget):
    """Layar pengaturan simpang: nama, frame acuan, daftar gerbang."""

    def __init__(self, project_path: str | Path | None = None, video: str | Path | None = None,
                 tracks: str | Path | None = None):
        super().__init__()
        self.setWindowTitle("AUTO TC - Gerbang simpang")
        self.project_path = Path(project_path) if project_path else None
        self.project = json.loads(json.dumps(DEFAULT_PROJECT))
        if self.project_path and self.project_path.exists():
            self.project.update(json.loads(self.project_path.read_text(encoding="utf-8")))
        self.video = str(video) if video else self.project.get("video_acuan", "")
        self.tracks_path = ""
        self._result_html = ""

        self.canvas = Canvas()
        self.canvas.gates = self.project["gerbang"]
        self.name = QLineEdit(self.project.get("nama", ""))
        self.name.setPlaceholderText("mis. Rajekwesi")
        self.second = QDoubleSpinBox()
        self.second.setRange(0, 86400)
        self.second.setValue(60)
        self.second.setSuffix(" dtk")
        self.list = QListWidget()
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.show_tracks = QCheckBox("Tampilkan lintasan kendaraan")
        self.show_tracks.setChecked(True)

        def button(text, slot):
            b = QPushButton(text)
            b.clicked.connect(slot)
            return b

        side = QVBoxLayout()
        form = QFormLayout()
        form.addRow("Nama simpang", self.name)
        form.addRow("Frame pada", self.second)
        side.addLayout(form)
        side.addWidget(button("Pilih video acuan...", self.pick_video))
        side.addWidget(button("Muat lintasan (.npz)...", self.pick_tracks))
        side.addWidget(self.show_tracks)
        side.addWidget(QLabel("<b>Gerbang</b>"))
        self.list.setMaximumHeight(130)
        side.addWidget(self.list)
        row = QHBoxLayout()
        row.addWidget(button("Ganti nama", self.rename_gate))
        row.addWidget(button("Hapus", self.delete_gate))
        side.addLayout(row)
        help_text = QLabel(
            "Klik kiri: tambah titik. Klik ganda / Enter: selesai. Klik kanan: hapus titik terakhir. Esc: batal. "
            "Geser titik untuk mengubah gerbang.<br>"
            "Gambar gerbang di tempat lintasan <b>berakhir</b>, satu per lengan.")
        help_text.setWordWrap(True)
        side.addWidget(help_text)
        side.addWidget(button("Hitung ulang dengan gerbang ini", self.recount))
        self.result = QTextBrowser()
        self.result.setPlaceholderText("Muat lintasan, lalu tekan Hitung ulang untuk melihat hasil gerbang ini.")
        side.addWidget(self.result, 1)
        side.addWidget(self.status)
        side.addWidget(button("Simpan proyek", self.save))
        panel = QWidget()
        panel.setLayout(side)
        panel.setFixedWidth(280)
        lay = QHBoxLayout(self)
        lay.addWidget(self.canvas, 1)
        lay.addWidget(panel)

        self.canvas.changed.connect(self.refresh)
        self.canvas.polygon_closed.connect(self.ask_name)
        self.list.currentRowChanged.connect(self.select)
        self.second.editingFinished.connect(self.load_frame)
        self.show_tracks.toggled.connect(self.toggle_tracks)
        self.load_frame()
        tracks = tracks or self.project.get("lintasan_acuan")
        if tracks and Path(tracks).exists():
            self.load_tracks(tracks)
        self.refresh()
        self.resize(1400, 760)

    # --- data
    def load_frame(self):
        if not self.video:
            self.status.setText("Belum ada video acuan.")
            return
        frame = grab_frame(self.video, self.second.value())
        if frame is None:
            self.status.setText(f"Video tidak bisa dibuka: {self.video}")
            return
        self.canvas.frame = to_pixmap(frame)
        self.canvas.update()

    def load_tracks(self, npz):
        try:
            self.canvas.overlay = trajectory_overlay(npz)
            self.tracks_path = str(npz)
        except Exception as exc:  # berkas rusak atau bukan lintasan
            self.status.setText(f"Lintasan tidak bisa dimuat: {exc}")
        self.canvas.update()

    def recount(self):
        """Hitung gerakan dengan gerbang yang sedang digambar; tampilkan lintasan berwarna dan ringkasannya."""
        if not self.tracks_path:
            self.result.setHtml("Muat berkas lintasan (.npz) dulu.")
            return
        if len(self.canvas.gates) < 2:
            self.result.setHtml("Butuh minimal dua gerbang.")
            return
        from .movements import analyze, movement_matrix
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            project = {**self.project, "gerbang": self.canvas.gates}
            meta, tracks, s = analyze(self.tracks_path, project)
            self.canvas.overlay, colors = movement_overlay(tracks, meta)
            mm = movement_matrix(tracks, meta, project)
        finally:
            QApplication.restoreOverrideCursor()
        total, ok = s["bergerak_setelah_sambung"], s["lengkap_setelah_sambung"]
        rows = [f"<b>{ok} dari {total} kendaraan teridentifikasi ({100 * ok / max(total, 1):.0f}%)</b>",
                f"{s['gerbang_terbaca_langsung']} gerbangnya terbaca langsung, "
                f"{s['lewat_pencocokan_jalur']} lewat pencocokan jalur"]
        for mv in sorted(colors, key=lambda m: -sum(mm[m].values())):
            rows.append(f"<span style='color:{colors[mv]}'>&#9632;</span> {mv.replace('->', ' ke ')}: {sum(mm[mv].values())}")
        rows.append(f"<span style='color:#aaaaaa'>&#9632;</span> tidak teridentifikasi: {total - ok} "
                    f"(asal tidak terbaca {s['asal_tidak_terbaca']}, tujuan tidak terbaca {s['tujuan_tidak_terbaca']}, "
                    f"asal = tujuan {s['asal_sama_dengan_tujuan']}, keduanya {s['keduanya_tidak_terbaca']})")
        self._result_html = "<br>".join(rows)
        self.result.setHtml(self._result_html)
        self.show_tracks.setChecked(True)
        self.canvas.update()

    def pick_video(self):
        path, _ = QFileDialog.getOpenFileName(self, "Pilih video acuan", "", "Video (*.mp4 *.avi *.mkv *.mov *.ts *.dav)")
        if path:
            self.video = path
            self.load_frame()

    def pick_tracks(self):
        path, _ = QFileDialog.getOpenFileName(self, "Pilih berkas lintasan", "", "Lintasan (*.npz)")
        if path:
            self.load_tracks(path)

    def toggle_tracks(self, on):
        self.canvas.show_overlay = on
        self.canvas.update()

    # --- gerbang
    def refresh(self):
        self.list.blockSignals(True)
        self.list.clear()
        self.list.addItems([g["nama"] for g in self.canvas.gates])
        self.list.setCurrentRow(self.canvas.selected)
        self.list.blockSignals(False)
        n = len(self.canvas.gates)
        self.status.setText(f"{n} gerbang, {n * (n - 1)} gerakan (asal ke tujuan).")
        if self._result_html:  # hasil di bawah dihitung dengan gerbang sebelum perubahan ini
            self.result.setHtml("<i>Gerbang berubah. Tekan Hitung ulang.</i><br>" + self._result_html)

    def select(self, row):
        self.canvas.selected = row
        self.canvas.update()

    def ask_name(self):
        name, ok = QInputDialog.getText(self, "Nama gerbang", "Nama lengan (mis. Utara, Jl. Untung Suropati):")
        self.finish_polygon(name if ok else "")

    def finish_polygon(self, name: str):
        name = name.strip()
        if not name:
            return  # poligon tetap sebagai draf; Esc untuk membatalkan
        if name in [g["nama"] for g in self.canvas.gates]:
            QMessageBox.warning(self, "Nama sudah dipakai", f"Sudah ada gerbang bernama {name}.")
            return
        self.canvas.add_gate(name)

    def rename_gate(self):
        i = self.list.currentRow()
        if i < 0:
            return
        name, ok = QInputDialog.getText(self, "Ganti nama", "Nama baru:", text=self.canvas.gates[i]["nama"])
        if ok and name.strip():
            self.canvas.gates[i]["nama"] = name.strip()
            self.refresh()
            self.canvas.update()

    def delete_gate(self):
        i = self.list.currentRow()
        if i >= 0:
            del self.canvas.gates[i]
            self.canvas.selected = -1
            self.refresh()
            self.canvas.update()

    def save(self, _=False, path: str | Path | None = None):
        self.project["nama"] = self.name.text().strip()
        self.project["video_acuan"] = self.video
        if self.tracks_path:
            self.project["lintasan_acuan"] = self.tracks_path
        if not self.project["nama"]:
            QMessageBox.warning(self, "Nama kosong", "Isi nama simpang dulu.")
            return False
        path = path or self.project_path
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "Simpan proyek", f"{self.project['nama'].lower()}.json", "Proyek (*.json)")
            if not path:
                return False
        self.project_path = Path(path)
        self.project_path.parent.mkdir(parents=True, exist_ok=True)
        self.project_path.write_text(json.dumps(self.project, indent=2, ensure_ascii=False), encoding="utf-8")
        self.status.setText(f"Tersimpan: {self.project_path.name}")
        return True


def run(project=None, video=None, tracks=None):
    app = QApplication.instance() or QApplication(sys.argv)
    w = GateEditor(project, video, tracks)
    w.show()
    return app.exec()
