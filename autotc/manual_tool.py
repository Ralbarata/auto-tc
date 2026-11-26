"""Alat hitung manual: putar video, tekan satu tombol per kendaraan, hasil langsung menjadi form validasi.

Cara kerja: pilih satu lengan ASAL, putar video, dan untuk setiap kendaraan yang datang dari lengan itu
tekan satu tombol. Baris tombol menentukan TUJUAN, kolom menentukan KELAS:

    tujuan ke-1:  Q W E R T Y      (SM MP KS BB TB KTB)
    tujuan ke-2:  A S D F G H
    tujuan ke-3:  Z X C V B N
    tujuan ke-4:  1 2 3 4 5 6

Setiap tekanan dicatat bersama waktu videonya, jadi pembagian per 15 menit dilakukan otomatis.
Ulangi video untuk tiap lengan asal. Catatan tersimpan otomatis dan bisa dilanjutkan kapan saja.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import openpyxl
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QMessageBox,
    QProgressDialog, QPushButton, QSlider, QVBoxLayout, QWidget,
)

from .gate_editor import COLORS, to_pixmap
from .labels import CLASSES
from .movements import load_project
from .validate import FIRST_COL, FIRST_ROW, make_form, movements_of
from .video_index import probe, read_hikvision_start

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "manual"
KEY_ROWS = ["QWERTY", "ASDFGH", "ZXCVBN", "123456"]
SPEEDS = [0.5, 1.0, 1.5, 2.0, 3.0, 4.0]
INTERVAL = 15  # menit per sheet form


def find_ffmpeg() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    hits = glob.glob(os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*\*\bin\ffmpeg.exe"))
    return hits[0] if hits else None


def video_tag(video: str | Path) -> str:
    v = Path(video)
    return f"{v.parent.name}_{v.stem}".replace(" ", "_")


def make_proxy(video: str | Path, out: Path, progress=None) -> Path:
    """Salinan ringan (lebar 1280, H.264, satu keyframe per detik) supaya video bisa dimaju-mundurkan dengan
    lancar. Rekaman asli (terutama HEVC) tidak bisa dilompati dengan andal. Jumlah frame dipertahankan."""
    if out.exists():
        return out
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("FFmpeg tidak ditemukan.")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".sebagian.mp4")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    for codec in (["-c:v", "h264_nvenc", "-preset", "p4", "-b:v", "3M"], ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "26"]):
        cmd = [ffmpeg, "-y", "-v", "error", "-i", str(video), "-an", "-vf", "scale=1280:-2", "-fps_mode", "passthrough",
               *codec, "-g", "25", "-progress", "pipe:1", "-nostats", str(tmp)]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, creationflags=flags)
        for line in proc.stdout:
            if line.startswith("out_time_us=") and progress:
                try:
                    if progress(int(line.split("=")[1]) / 1e6) is False:
                        proc.kill()
                        proc.wait()
                        tmp.unlink(missing_ok=True)
                        raise KeyboardInterrupt
                except ValueError:
                    pass
        if proc.wait() == 0 and tmp.exists():
            tmp.replace(out)
            return out
        tmp.unlink(missing_ok=True)
    raise RuntimeError(f"Gagal menyiapkan video: {video}")


class Session:
    """Catatan hitung manual satu video: kejadian (detik video, asal, tujuan, kelas) + seberapa jauh ditonton."""

    def __init__(self, project: dict, video: str | Path, start: datetime, duration: float, path: Path | None = None):
        self.project, self.video, self.start, self.duration = project, str(video), start, float(duration)
        self.path = path or DATA / project["nama"].lower() / f"{video_tag(video)}.json"
        self.events: list[list] = []
        self.watched: dict[str, float] = {}
        self.position = 0.0
        self.t0, self.t1 = 0.0, self.duration      # rentang hitung, dalam detik video
        self.has_window = False
        if self.path.exists():
            d = json.loads(self.path.read_text(encoding="utf-8"))
            self.events, self.watched, self.position = d["kejadian"], d["ditonton"], d.get("posisi", 0.0)
            if d.get("rentang"):
                self.set_window(*d["rentang"])

    def set_window(self, t0: float, t1: float):
        """Rentang yang dihitung (mis. 19:00-19:30). Hanya kejadian di dalamnya yang dipakai."""
        self.t0, self.t1 = max(float(t0), 0.0), min(float(t1), self.duration)
        self.has_window = True

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"video": self.video, "mulai": self.start.isoformat(), "durasi": self.duration,
                                   "posisi": round(self.position, 2), "ditonton": self.watched,
                                   "rentang": [self.t0, self.t1] if self.has_window else None,
                                   "kejadian": self.events}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def add(self, t: float, origin: str, dest: str, kelas: str):
        self.events.append([round(t, 2), origin, dest, kelas])

    def undo(self):
        return self.events.pop() if self.events else None

    def mark_watched(self, origin: str, t0: float, t1: float):
        """Hanya pemutaran bersambung yang dihitung sebagai sudah ditonton (melompat ke depan tidak)."""
        w = self.seen(origin)
        if t0 <= w + 1.0 and t1 > w:
            self.watched[origin] = round(min(t1, self.t1), 2)

    def seen(self, origin: str) -> float:
        """Sampai detik video ke berapa lengan ini sudah ditonton bersambung sejak awal rentang."""
        return min(max(self.watched.get(origin, self.t0), self.t0), self.t1)

    def counts(self, origin: str | None = None, t0: float | None = None, t1: float | None = None) -> Counter:
        t0 = self.t0 if t0 is None else t0
        t1 = self.t1 if t1 is None else t1
        c = Counter()
        for t, o, d, k in self.events:
            if (origin is None or o == origin) and t0 <= t < t1:
                c[(o, d, k)] += 1
        return c

    def windows(self) -> list[dict]:
        """Rentang 15 menit: mulai (detik video), panjang (menit), dan apakah semua lengan asal sudah ditonton."""
        origins = sorted({o for o, _ in movements_of(self.project)})
        done = min((self.seen(o) for o in origins), default=self.t0)
        total = int((self.t1 - self.t0 + 0.5) // 60)
        out, t = [], 0
        while t < total:
            n = min(INTERVAL, total - t)
            out.append({"mulai": self.t0 + t * 60.0, "menit": n,
                        "selesai": done >= min(self.t0 + (t + n) * 60.0, self.t1) - 1.5})
            t += INTERVAL
        return out

    def export(self, out_path: str | Path) -> dict:
        """Tulis form manual (format `autotc validasi`); hanya rentang yang selesai ditonton yang diisi."""
        wins = self.windows()
        if not wins:
            raise SystemExit("Rentang hitung lebih pendek dari satu menit.")
        total = sum(w["menit"] for w in wins)
        begin = (self.start + timedelta(seconds=self.t0 + 0.5)).replace(microsecond=0)
        form = make_form(self.project, out_path, begin, total, Path(self.video).name,
                         INTERVAL if total > INTERVAL else None)
        wb = openpyxl.load_workbook(form)
        mvs, filled, n = movements_of(self.project), 0, 0
        for ws, w in zip(wb.worksheets, wins):
            if not w["selesai"]:
                continue
            c = self.counts(None, w["mulai"], w["mulai"] + w["menit"] * 60.0)
            for i, (o, d) in enumerate(mvs):
                for j, k in enumerate(CLASSES):
                    ws.cell(FIRST_ROW + i, FIRST_COL + j, c[(o, d, k)])
                    n += c[(o, d, k)]
            ws["B5"] = "alat hitung manual"
            filled += 1
        try:
            wb.save(form)
        except PermissionError:
            raise SystemExit(f"Tidak bisa menulis {form}: tutup dulu file itu di Excel, lalu ulangi.") from None
        return {"berkas": str(form), "rentang_terisi": filled, "rentang": len(wins), "kendaraan": n}


def _mmss(s: float) -> str:
    s = int(max(s, 0))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


class View(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(640, 360)
        self.frame: QPixmap | None = None
        self.gates: list[dict] = []
        self.origin = ""
        self.dest_keys: dict[str, str] = {}
        self.clock = ""
        self.flash = ""
        self.show_gates = True

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#101010"))
        if not self.frame:
            p.setPen(QColor("#bbbbbb"))
            p.drawText(self.rect(), Qt.AlignCenter, "Belum ada video. Tekan \"Buka video...\"")
            p.end()
            return
        s = min(self.width() / self.frame.width(), self.height() / self.frame.height())
        w, h = self.frame.width() * s, self.frame.height() * s
        r = QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)
        p.drawPixmap(r, self.frame, QRectF(self.frame.rect()))
        f = QFont(p.font())
        f.setBold(True)
        if self.show_gates:
            for i, g in enumerate(self.gates):
                c = QColor(COLORS[i % len(COLORS)])
                poly = QPolygonF([QPointF(r.x() + x * r.width(), r.y() + y * r.height()) for x, y in g["poligon"]])
                is_origin = g["nama"] == self.origin
                fill = QColor(c)
                fill.setAlpha(70 if is_origin else 0)
                p.setPen(QPen(c, 4 if is_origin else 2, Qt.SolidLine if is_origin else Qt.DashLine))
                p.setBrush(fill)
                p.drawPolygon(poly)
                text = f"ASAL: {g['nama']}" if is_origin else f"{g['nama']}  [{self.dest_keys.get(g['nama'], '-')}]"
                f.setPointSize(12)
                p.setFont(f)
                box = p.fontMetrics().boundingRect(text).adjusted(-6, -3, 6, 3)
                box.moveTopLeft(poly.boundingRect().topLeft().toPoint())
                p.fillRect(box, QColor(0, 0, 0, 170))
                p.setPen(QColor("white"))
                p.drawText(box, Qt.AlignCenter, text)
        f.setPointSize(14)
        p.setFont(f)
        if self.clock:
            box = p.fontMetrics().boundingRect(self.clock).adjusted(-8, -4, 8, 4)
            box.moveBottomLeft(r.bottomLeft().toPoint())
            p.fillRect(box, QColor(0, 0, 0, 170))
            p.setPen(QColor("white"))
            p.drawText(box, Qt.AlignCenter, self.clock)
        if self.flash:
            f.setPointSize(20)
            p.setFont(f)
            box = p.fontMetrics().boundingRect(self.flash).adjusted(-12, -6, 12, 6)
            box.moveCenter(QPointF(r.center().x(), r.bottom() - 40).toPoint())
            p.fillRect(box, QColor(0, 110, 40, 210))
            p.setPen(QColor("white"))
            p.drawText(box, Qt.AlignCenter, self.flash)
        p.end()


class ManualTool(QWidget):
    def __init__(self, project_path: str | Path, video: str | Path | None = None, session_dir: Path | None = None,
                 proxy_dir: Path | None = None):
        super().__init__()
        self.project_path = Path(project_path)
        self.project = load_project(self.project_path)
        self.session_dir = session_dir or DATA / self.project["nama"].lower()
        self.proxy_dir = proxy_dir or DATA / "proxy"
        self.project.setdefault("gerbang", [])
        self.movements = movements_of(self.project)
        self.origins = list(dict.fromkeys(o for o, _ in self.movements))
        self.setWindowTitle(f"AUTO TC - Hitung manual - {self.project['nama']}")
        self.setFocusPolicy(Qt.StrongFocus)
        self.session: Session | None = None
        self.cap = None
        self.fps, self.nframes, self.frame_no = 25.0, 0, 0
        self.playing, self.speed_i, self.origin = False, 1, self.origins[0] if self.origins else ""
        self._dirty, self._skip, self._f0, self._w0, self._next = False, 0, 0, 0.0, 0

        self.view = View()
        self.view.gates = self.project["gerbang"]
        self.slider = QSlider(Qt.Horizontal)
        self.time = QLabel("00:00 / 00:00")
        self.speed = QComboBox()
        self.speed.addItems([f"{s:g}x" for s in SPEEDS])
        self.speed.setCurrentIndex(self.speed_i)
        self.play_btn = QPushButton("Putar (Spasi)")
        self.origin_box = QComboBox()
        self.origin_box.addItems(self.origins)
        self.grid = QGridLayout()
        self.grid.setSpacing(3)
        self.progress = QLabel()
        self.recent = QLabel()
        self.status = QLabel()
        for lab in (self.progress, self.recent, self.status):
            lab.setWordWrap(True)
            lab.setTextFormat(Qt.RichText)

        def button(text, slot):
            b = QPushButton(text)
            b.clicked.connect(slot)
            return b

        side = QVBoxLayout()
        side.addWidget(button("Buka video...", self.pick_video))
        self.win_start, self.win_len = QComboBox(), QComboBox()
        self.win_len.addItems([f"{m} menit" for m in (15, 30, 45, 60)])
        self.win_len.setCurrentIndex(1)
        row = QHBoxLayout()
        row.addWidget(QLabel("<b>Rentang hitung</b> mulai jam"))
        row.addWidget(self.win_start, 1)
        row.addWidget(QLabel("selama"))
        row.addWidget(self.win_len)
        side.addLayout(row)
        side.addWidget(QLabel("<b>Lengan asal yang sedang dihitung</b> (Tab = ganti)"))
        side.addWidget(self.origin_box)
        side.addWidget(QLabel("<b>Tombol</b>: baris = tujuan, kolom = kelas. Angka kecil = jumlah."))
        side.addLayout(self.grid)
        side.addWidget(QLabel("<b>Tekanan terakhir</b> (Backspace = batalkan)"))
        side.addWidget(self.recent)
        side.addWidget(QLabel("<b>Kemajuan</b>"))
        side.addWidget(self.progress)
        side.addStretch(1)
        hint = QLabel("Spasi putar/jeda · ← → mundur/maju 5 dtk · ↑ ↓ kecepatan · G tampilkan/sembunyikan gerbang")
        hint.setWordWrap(True)
        side.addWidget(hint)
        side.addWidget(self.status)
        side.addWidget(button("Ekspor ke form manual (Excel)", self.export))
        panel = QWidget()
        panel.setLayout(side)
        panel.setFixedWidth(400)
        bar = QHBoxLayout()
        bar.addWidget(self.play_btn)
        bar.addWidget(self.slider, 1)
        bar.addWidget(self.time)
        bar.addWidget(self.speed)
        left = QVBoxLayout()
        left.addWidget(self.view, 1)
        left.addLayout(bar)
        lay = QHBoxLayout(self)
        lay.addLayout(left, 1)
        lay.addWidget(panel)
        for w in self.findChildren(QWidget):  # semua tombol keyboard menuju jendela, bukan ke tombol/kotak pilihan
            if w is not self:
                w.setFocusPolicy(Qt.NoFocus)
        for box in (self.win_start, self.win_len, self.origin_box, self.speed):
            box.installEventFilter(self)   # roda mouse yang tak sengaja tidak boleh mengganti rentang/lengan

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.saver = QTimer(self)
        self.saver.timeout.connect(self.autosave)
        self.saver.start(3000)
        self.flash_timer = QTimer(self)
        self.flash_timer.setSingleShot(True)
        self.flash_timer.timeout.connect(self.clear_flash)
        self.play_btn.clicked.connect(self.toggle)
        self.slider.sliderMoved.connect(lambda v: self.seek(v / self.fps))
        self.speed.currentIndexChanged.connect(self.set_speed)
        self.origin_box.currentTextChanged.connect(self.set_origin)
        self.win_start.activated.connect(self.apply_window)
        self.win_len.activated.connect(self.apply_window)
        self.set_origin(self.origin)
        self.resize(1500, 800)
        if video:
            self.open_video(video)

    # --- video
    def pick_video(self):
        path, _ = QFileDialog.getOpenFileName(self, "Pilih video yang akan dihitung", "", "Video (*.mp4 *.avi *.mkv *.mov *.ts *.dav)")
        if path:
            self.open_video(path)

    def open_video(self, video: str | Path, start: datetime | None = None) -> bool:
        self.pause()
        self.autosave()
        start = start or read_hikvision_start(video)
        if start is None:
            text, ok = QInputDialog.getText(self, "Jam mulai video", "Jam mulai tidak terbaca dari rekaman.\n"
                                            "Isi jam mulai (TTTT-BB-HH JJ:MM:DD):", text="2026-01-01 00:00:00")
            if not ok:
                return False
            try:
                start = datetime.strptime(text.strip(), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                QMessageBox.warning(self, "Format salah", "Contoh: 2026-10-21 16:00:00")
                return False
        proxy = self.proxy_dir / f"{video_tag(video)}.mp4"
        if not proxy.exists():
            info = probe(video)
            total = info.frames / info.fps if info.fps and info.frames > 0 else 0
            dlg = QProgressDialog("Menyiapkan video supaya bisa dimaju-mundurkan (sekali saja per video)...", "Batal", 0, 1000, self)
            dlg.setWindowModality(Qt.WindowModal)
            dlg.setMinimumDuration(0)

            def on_progress(sec):
                dlg.setValue(min(int(1000 * sec / total), 999) if total else 0)
                dlg.setLabelText(f"Menyiapkan video (sekali saja per video)... {_mmss(sec)}" + (f" / {_mmss(total)}" if total else ""))
                QApplication.processEvents()
                return not dlg.wasCanceled()
            try:
                make_proxy(video, proxy, on_progress)
            except KeyboardInterrupt:
                return False
            except RuntimeError as exc:
                dlg.close()
                QMessageBox.warning(self, "Video", str(exc))
                return False
            dlg.close()
        cap = cv2.VideoCapture(str(proxy))
        if not cap.isOpened():
            QMessageBox.warning(self, "Video", f"Tidak bisa dibuka: {proxy}")
            return False
        self.cap = cap
        self.fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        self.nframes = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.session = Session(self.project, video, start, self.nframes / self.fps,
                               self.session_dir / f"{video_tag(video)}.json")
        self.fill_window_choices()
        self.apply_window(resume=True)
        self.status.setText(f"{Path(video).name}: rekaman {start:%d-%m-%Y %H:%M:%S} s.d. "
                            f"{start + timedelta(seconds=self.session.duration):%H:%M:%S}")
        return True

    # --- rentang hitung: jam bulat (kelipatan 15 menit) yang ada di dalam video
    def fill_window_choices(self):
        s = self.session
        t = s.start.replace(minute=s.start.minute - s.start.minute % INTERVAL, second=0, microsecond=0)
        if t < s.start:
            t += timedelta(minutes=INTERVAL)
        self.win_start.blockSignals(True)
        self.win_start.clear()
        while (t - s.start).total_seconds() + INTERVAL * 60 <= s.duration + 1:
            self.win_start.addItem(f"{t:%H:%M}", (t - s.start).total_seconds())
            t += timedelta(minutes=INTERVAL)
        if not self.win_start.count():      # video lebih pendek dari 15 menit: hitung seluruhnya
            self.win_start.addItem(f"{s.start:%H:%M:%S}", 0.0)
        if s.has_window:                     # sesi lama: pakai rentang yang tersimpan
            i = min(range(self.win_start.count()), key=lambda k: abs(self.win_start.itemData(k) - s.t0))
            self.win_start.setCurrentIndex(i)
            self.win_len.setCurrentIndex(min(max(round((s.t1 - s.t0) / 60 / INTERVAL) - 1, 0), 3))
        self.win_start.blockSignals(False)

    def apply_window(self, _=None, resume: bool = False):
        if not self.session:
            return
        self.pause()
        s = self.session
        t0 = float(self.win_start.currentData())
        want = (self.win_len.currentIndex() + 1) * INTERVAL * 60.0
        fit = max(int((s.duration + 1 - t0) // (INTERVAL * 60)), 1) * INTERVAL * 60.0   # yang muat di video ini
        if want > fit:
            want = fit
            self.win_len.setCurrentIndex(int(fit // (INTERVAL * 60)) - 1)
            self.set_flash(f"video ini hanya cukup untuk {int(fit // 60)} menit dari jam itu")
        s.set_window(t0, t0 + want)
        self._dirty = True
        self.slider.setRange(int(s.t0 * self.fps), int(s.t1 * self.fps))
        self.seek(s.position if resume and s.t0 <= s.position <= s.t1 else s.seen(self.origin))
        self.refresh()

    def now(self) -> float:
        return self.frame_no / self.fps

    def show_frame(self) -> bool:
        ok, frame = self.cap.read()
        if not ok:
            return False
        self.frame_no = self._next      # dihitung sendiri; posisi yang dilaporkan pembaca video tidak selalu stabil
        self._next += 1
        self.view.frame = to_pixmap(frame)
        clock = self.session.start + timedelta(seconds=self.now())
        self.view.clock = f"{clock:%H:%M:%S}   {self.speed.currentText()}"
        self.slider.blockSignals(True)
        self.slider.setValue(self.frame_no)
        self.slider.blockSignals(False)
        s = self.session
        self.time.setText(f"{_mmss(self.now() - s.t0)} / {_mmss(s.t1 - s.t0)}")
        self.view.update()
        return True

    def seek(self, seconds: float):
        if not self.cap:
            return
        seconds = min(max(seconds, self.session.t0), self.session.t1)     # tidak keluar dari rentang hitung
        n = int(min(max(seconds, 0.0) * self.fps, max(self.nframes - 1, 0)))
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, n)
        self._next = n
        self.show_frame()
        self._sync()
        self.session.position = self.now()
        self._dirty = True

    def tick(self):
        if not self.cap:
            return
        # ikuti jam dinding: kalau menampilkan gambar lebih lambat dari kecepatan yang diminta, lewati frame
        target = self._f0 + (time.perf_counter() - self._w0) * self.fps * SPEEDS[self.speed_i]
        if target < self.frame_no + 1:
            return
        t0 = self.now()
        self._skip = int(min(target - self.frame_no - 1, 15))
        for _ in range(self._skip):
            self._next += bool(self.cap.grab())
        if not self.show_frame() or self.now() >= self.session.t1:
            self.pause()
            self.session.mark_watched(self.origin, t0, self.session.t1)
            self._dirty = True
            self.set_flash(f"rentang selesai untuk lengan {self.origin}")
            self.refresh()
            return
        self.session.mark_watched(self.origin, t0, self.now())
        self.session.position = self.now()
        self._dirty = True
        if self.frame_no % int(self.fps) < self._skip + 1:
            self.refresh_progress()

    def set_speed(self, i: int):
        self.speed_i = i
        self._sync()
        self.timer.setInterval(max(int(500 / self.fps), 5))
        if self.speed.currentIndex() != i:
            self.speed.setCurrentIndex(i)

    def _sync(self):
        self._f0, self._w0 = self.frame_no, time.perf_counter()

    def toggle(self):
        self.pause() if self.playing else self.play()

    def play(self):
        if self.cap:
            self.set_speed(self.speed_i)
            self.playing = True
            self.timer.start()
            self.play_btn.setText("Jeda (Spasi)")

    def pause(self):
        self.playing = False
        self.timer.stop()
        self.play_btn.setText("Putar (Spasi)")

    # --- hitungan
    def dests(self) -> list[str]:
        return [d for o, d in self.movements if o == self.origin]

    def set_origin(self, name: str):
        if not name:
            return
        self.origin = name
        if self.origin_box.currentText() != name:
            self.origin_box.setCurrentText(name)
        self.view.origin = name
        self.view.dest_keys = {d: KEY_ROWS[i] for i, d in enumerate(self.dests()[:len(KEY_ROWS)])}
        while self.grid.count():
            old = self.grid.takeAt(0).widget()
            old.setParent(None)      # langsung hilang; deleteLater saja masih tergambar sampai giliran berikutnya
            old.deleteLater()
        self.cells = {}
        for j, k in enumerate(CLASSES):
            self.grid.addWidget(QLabel(f"<b>{k}</b>", alignment=Qt.AlignCenter), 0, j + 1)
        for i, d in enumerate(self.dests()[:len(KEY_ROWS)]):
            self.grid.addWidget(QLabel(f"ke <b>{d}</b>"), i + 1, 0)
            for j, k in enumerate(CLASSES):
                cell = QLabel(alignment=Qt.AlignCenter)
                cell.setStyleSheet("border:1px solid #888; border-radius:4px; padding:3px;")
                cell.setTextFormat(Qt.RichText)
                self.grid.addWidget(cell, i + 1, j + 1)
                self.cells[(d, k)] = (cell, KEY_ROWS[i][j])
        if self.session and self.cap:     # lanjutkan lengan ini dari tempat terakhir ditonton
            self.pause()
            self.seek(self.session.seen(name))
        self.refresh()

    def count_key(self, ch: str) -> bool:
        if not self.session:
            return False
        for i, d in enumerate(self.dests()[:len(KEY_ROWS)]):
            j = KEY_ROWS[i].find(ch)
            if j >= 0:
                self.session.add(self.now(), self.origin, d, CLASSES[j])
                self._dirty = True
                self.set_flash(f"{CLASSES[j]}  →  {d}")
                self.refresh()
                return True
        return False

    def undo(self):
        if self.session:
            ev = self.session.undo()
            if ev:
                self._dirty = True
                self.set_flash(f"dibatalkan: {ev[3]} {ev[1]} → {ev[2]}")
                self.refresh()

    def set_flash(self, text: str):
        self.view.flash = text
        self.view.update()
        self.flash_timer.start(700)

    def clear_flash(self):
        self.view.flash = ""
        self.view.update()

    def refresh(self):
        c = self.session.counts(self.origin) if self.session else Counter()
        for (d, k), (cell, key) in self.cells.items():
            cell.setText(f"<span style='font-size:15pt'><b>{key}</b></span><br>{c[(self.origin, d, k)]}")
        if self.session:
            last = self.session.events[-5:][::-1]
            self.recent.setText("<br>".join(f"{_mmss(t)}  {k}  {o} → {d}" for t, o, d, k in last) or "-")
        self.refresh_progress()

    def refresh_progress(self):
        if not self.session:
            self.progress.setText("-")
            return
        s = self.session
        rows = []
        for o in self.origins:
            n = sum(s.counts(o).values())
            w = s.seen(o)
            mark = "✔" if w >= s.t1 - 1.5 else ""
            rows.append(f"{'<b>' if o == self.origin else ''}{o}: ditonton {_mmss(w - s.t0)} / {_mmss(s.t1 - s.t0)}, "
                        f"{n} kendaraan {mark}{'</b>' if o == self.origin else ''}")
        wins = s.windows()
        rows.append(f"Rentang 15 menit yang selesai untuk semua lengan: <b>{sum(w['selesai'] for w in wins)} dari {len(wins)}</b>")
        self.progress.setText("<br>".join(rows))

    def autosave(self):
        if self.session and self._dirty:
            self.session.save()
            self._dirty = False

    def export(self):
        if not self.session:
            return
        self.pause()
        self.autosave()
        wins = self.session.windows()
        if not any(w["selesai"] for w in wins):
            QMessageBox.information(self, "Belum ada rentang selesai",
                                    "Belum ada rentang 15 menit yang selesai ditonton untuk SEMUA lengan asal.\n"
                                    "Lihat bagian Kemajuan: tiap lengan harus ditonton bersambung dari awal.")
            return
        begin = self.session.start + timedelta(seconds=self.session.t0 + 0.5)
        default = ROOT / "hasil" / "validasi" / f"Manual {self.project['nama']} {begin:%Y-%m-%d %H%M}.xlsx"
        default.parent.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(self, "Simpan form manual", str(default), "Excel (*.xlsx)")
        if not path:
            return
        try:
            res = self.session.export(path)
        except SystemExit as exc:
            QMessageBox.warning(self, "Ekspor", str(exc))
            return
        self.status.setText(f"Form tersimpan: {res['rentang_terisi']} dari {res['rentang']} rentang terisi, "
                            f"{res['kendaraan']} kendaraan.<br>{res['berkas']}")

    # --- keyboard
    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key_Space:
            self.toggle()
        elif k in (Qt.Key_Left, Qt.Key_Right):
            self.seek(self.now() + (5 if k == Qt.Key_Right else -5) * (6 if e.modifiers() & Qt.ShiftModifier else 1))
        elif k in (Qt.Key_Up, Qt.Key_Down):
            self.set_speed(min(max(self.speed_i + (1 if k == Qt.Key_Up else -1), 0), len(SPEEDS) - 1))
        elif k == Qt.Key_Backspace:
            self.undo()
        elif k == Qt.Key_Tab and self.origins:
            self.set_origin(self.origins[(self.origins.index(self.origin) + 1) % len(self.origins)])
        elif k == Qt.Key_G:
            self.view.show_gates = not self.view.show_gates
            self.view.update()
        elif not e.isAutoRepeat() and e.text() and self.count_key(e.text().upper()):
            pass
        else:
            super().keyPressEvent(e)

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Wheel and isinstance(obj, QComboBox):
            e.ignore()
            return True
        return super().eventFilter(obj, e)

    def focusNextPrevChild(self, _next):  # Tab dipakai untuk ganti lengan, bukan pindah fokus
        return False

    def closeEvent(self, e):
        self.pause()
        self.autosave()
        super().closeEvent(e)


def run(project=None, video=None):
    app = QApplication.instance() or QApplication(sys.argv)
    if not project:
        project, _ = QFileDialog.getOpenFileName(None, "Pilih berkas proyek simpang", str(ROOT / "proyek"), "Proyek (*.json)")
        if not project:
            return 0
    p = load_project(project)
    if len(p.get("gerbang", [])) < 2 and len(p.get("lengan", [])) < 2:
        # hitung manual tidak butuh gerbang, cukup nama lengan; disimpan di proyek supaya form konsisten
        text, ok = QInputDialog.getText(None, "Nama lengan simpang", "Simpang ini belum punya gerbang. Untuk hitung manual "
                                        "cukup nama lengannya.\nTulis nama lengan, dipisah koma (mis. Utara, Timur, Selatan, Barat):")
        names = list(dict.fromkeys(n.strip() for n in text.split(",") if n.strip())) if ok else []
        if len(names) < 2:
            return 1
        raw = json.loads(Path(project).read_text(encoding="utf-8-sig"))
        raw["lengan"] = names
        Path(project).write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
        p = load_project(project)
    if max(Counter(o for o, _ in movements_of(p)).values()) > len(KEY_ROWS):
        QMessageBox.warning(None, "Terlalu banyak tujuan", "Alat ini mendukung paling banyak 4 tujuan per lengan asal.")
        return 1
    w = ManualTool(project, video)
    w.show()
    return app.exec()
