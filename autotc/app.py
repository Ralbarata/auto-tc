"""Aplikasi pencacahan satu simpang: pilih video -> proses -> lihat hasil -> buat Excel.

Sementara dipakai untuk Simpang Rajekwesi (gerbang sudah ada di berkas proyeknya). Pemrosesan video
berjalan di proses terpisah supaya jendela tetap responsif dan bisa dihentikan.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from collections import Counter
from datetime import timedelta
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, Qt, QTimer
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QMessageBox, QProgressBar, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .labels import CLASSES
from .manual_tool import video_tag
from .movements import UNKNOWN, analyze, audit_image, count_table, load_project, movement_matrix
from .tracking import pick_mode
from .validate import movements_of
from .video_index import index_folder, probe

ROOT = Path(__file__).resolve().parent.parent
VIDEO_FILTER = "Video (*.mp4 *.avi *.mkv *.mov *.ts *.dav)"
COLS = ["Mulai rekaman", "Durasi", "Kondisi", "Status"]


NEW_PROJECT = {"interval_menit": 5, "peta_kelas": {"motorcycle": "SM", "car": "MP", "truck": "KS", "bus": "BB"}, "gerbang": []}


ERROR_LOG = ROOT / "hasil" / "autotc_galat.log"
STALL_MINUTES = 30      # tanpa keluaran selama ini: proses dianggap macet, dihentikan, video ditandai Gagal
RETRIES = 1             # video yang gagal diulang sekali di akhir antrean


def keep_awake(on: bool):
    """Cegah Windows tidur selama pemrosesan (tidur di tengah proses bisa membuat GPU/proses mati)."""
    try:
        import ctypes
        flags = 0x80000000 | (0x00000001 if on else 0)    # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
    except Exception:
        pass


def log_error(text: str):
    try:
        ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
        with ERROR_LOG.open("a", encoding="utf-8") as f:
            f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}]\n{text}\n")
    except OSError:
        pass


def project_files() -> list[Path]:
    """Berkas proyek simpang; salinan cadangan (nama berkurung) tidak ikut."""
    return sorted(f for f in (ROOT / "proyek").glob("*.json") if "(" not in f.name)


def _dur(s: float) -> str:
    s = int(max(s, 0))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


class App(QWidget):
    def __init__(self, project_path: str | Path, out_dir: Path | None = None):
        super().__init__()
        self.fixed_out_dir = out_dir
        self.xproc: QProcess | None = None   # proses pembuat Excel
        self.failed: list[str] = []
        self.log_dir = None
        self.set_project(project_path)
        self.videos: list[dict] = []       # {"info": VideoFile, "npz": Path, "status": str}
        self.cache: dict[Path, tuple] = {}  # npz -> (meta, tracks, ringkasan)
        self.proc: QProcess | None = None
        self.current = -1
        self.queue: list[int] = []
        self.t_start = 0.0
        self.last_excel: Path | None = None

        def button(text, slot):
            b = QPushButton(text)
            b.clicked.connect(slot)
            return b

        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.show_selected)
        self.limit = QSpinBox()
        self.limit.setRange(0, 600)
        self.limit.setSuffix(" menit")
        self.limit.setSpecialValueText("seluruh video")
        self.limit.valueChanged.connect(self.refresh_status)
        self.start_btn = button("Mulai proses", self.start)
        self.stop_btn = button("Berhenti", self.stop)
        self.stop_btn.setEnabled(False)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.progress = QLabel("Tambahkan video, lalu tekan Mulai proses.")
        self.progress.setWordWrap(True)

        left = QVBoxLayout()
        self.combo = QComboBox()
        self.fill_combo()
        self.combo.currentIndexChanged.connect(self.project_chosen)
        self.gate_btn = button("Atur gerbang...", self.edit_gates)
        row = QHBoxLayout()
        row.addWidget(QLabel("<b>Simpang:</b>"))
        row.addWidget(self.combo, 1)
        row.addWidget(button("Simpang baru...", self.new_project))
        row.addWidget(self.gate_btn)
        left.addLayout(row)
        self.arms = QLabel()
        self.arms.setWordWrap(True)
        left.addWidget(self.arms)
        row = QHBoxLayout()
        row.addWidget(button("Tambah video...", self.add_files))
        row.addWidget(button("Tambah folder...", self.add_folder))
        row.addWidget(button("Hapus dari daftar", self.remove_selected))
        left.addLayout(row)
        left.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel("Proses hanya awal video:"))
        row.addWidget(self.limit)
        row.addStretch(1)
        row.addWidget(self.start_btn)
        row.addWidget(self.stop_btn)
        left.addLayout(row)
        left.addWidget(self.bar)
        left.addWidget(self.progress)
        lw = QWidget()
        lw.setLayout(left)
        lw.setFixedWidth(520)

        self.image = QLabel("Pilih video yang sudah selesai untuk melihat lintasannya.")
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setMinimumSize(480, 270)
        self.image.setStyleSheet("background:#202020; color:#bbbbbb;")
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.RichText)
        self.result = QTableWidget(0, len(CLASSES) + 2)
        self.result.setHorizontalHeaderLabels(["Gerakan", *CLASSES, "Total"])
        self.result.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.result.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.result.verticalHeader().setVisible(False)
        right = QVBoxLayout()
        right.addWidget(self.image, 3)
        right.addWidget(self.summary)
        right.addWidget(self.result, 2)
        self.one_file = QCheckBox("Semua hari dalam satu berkas Excel (sheet berbeda)")
        self.one_file.setChecked(True)
        self.one_file.setToolTip("Dicentang: satu berkas per simpang, tiap hari punya sheet sendiri.\n"
                                 "Tidak dicentang: satu berkas Excel per tanggal.")
        right.addWidget(self.one_file)
        self.spread = QCheckBox("Sebarkan kendaraan tak teridentifikasi ke gerakan (kekekalan arus: masuk = keluar)")
        self.spread.setChecked(True)
        self.spread.setToolTip("Kendaraan yang asal/tujuannya tidak terbaca dibagi ke gerakan yang sah sesuai proporsi\n"
                               "gerakan kelas PKJI yang sama pada jam yang sama. Lintasan yang hanya menyentuh satu gerbang\n"
                               "dibuang (dianggap potongan kendaraan yang sudah terhitung). Matikan untuk melihat angka mentah.")
        right.addWidget(self.spread)
        row = QHBoxLayout()
        self.export_btn = button("Buat Excel rekap (TC per 5 menit + LHR + jam puncak)", self.export)
        row.addWidget(self.export_btn)
        self.open_btn = button("Buka Excel", self.open_excel)
        self.open_btn.setEnabled(False)
        row.addWidget(self.open_btn)
        right.addLayout(row)
        lay = QHBoxLayout(self)
        lay.addWidget(lw)
        lay.addLayout(right, 1)
        self.resize(1500, 850)
        self._pix: QPixmap | None = None
        self.show_arms()
        self.watch = QTimer(self)
        self.watch.timeout.connect(self.check_job)
        self.watch.start(20000)
        self.last_output = time.time()
        self.tries: dict[int, int] = {}

    # --- simpang
    def set_project(self, path):
        self.project_path = Path(path)
        self.project = load_project(self.project_path)
        self.name = self.project["nama"]
        self.out_dir = self.fixed_out_dir or ROOT / "hasil" / self.name.lower()
        self.setWindowTitle(f"AUTO TC - Simpang {self.name}")
        self.cache = {}

    def fill_combo(self):
        self.combo.blockSignals(True)
        self.combo.clear()
        files = project_files()
        if self.project_path.resolve() not in [f.resolve() for f in files]:
            files.append(self.project_path)
        for f in files:
            try:
                self.combo.addItem(load_project(f).get("nama", f.stem), str(f))
            except ValueError:
                continue
        paths = [Path(self.combo.itemData(k)).resolve() for k in range(self.combo.count())]
        if self.project_path.resolve() in paths:
            self.combo.setCurrentIndex(paths.index(self.project_path.resolve()))
        self.combo.blockSignals(False)

    def show_arms(self):
        gates = [g["nama"] for g in self.project.get("gerbang", [])]
        self.arms.setText("Lengan: " + ", ".join(gates) if gates else
                          "<span style='color:#c0392b'>Simpang ini belum punya gerbang. Tambahkan satu video, lalu tekan "
                          "<b>Atur gerbang...</b>; video tetap bisa diproses lebih dulu.</span>")

    def busy(self) -> bool:
        return bool(self.proc or self.xproc)

    def project_chosen(self, _i):
        path = self.combo.currentData()
        if not path or Path(path).resolve() == self.project_path.resolve():
            return
        if self.busy():
            QMessageBox.information(self, "Sedang bekerja", "Tunggu proses selesai atau hentikan dulu sebelum ganti simpang.")
            self.fill_combo()
            return
        self.set_project(path)
        self.videos = []
        self.show_arms()
        self.refresh_status()
        self.progress.setText("Tambahkan video, lalu tekan Mulai proses.")

    def new_project(self):
        name, ok = QInputDialog.getText(self, "Simpang baru", "Nama simpang atau titik survei:")
        name = name.strip()
        if not ok or not name:
            return
        path = ROOT / "proyek" / (name.lower().replace(" ", "_") + ".json")
        if path.exists():
            QMessageBox.information(self, "Sudah ada", f"Simpang dengan nama berkas {path.name} sudah ada; pilih dari daftar.")
        else:
            path.write_text(json.dumps({"nama": name, **NEW_PROJECT}, indent=2, ensure_ascii=False), encoding="utf-8")
        self.fill_combo()
        self.combo.setCurrentIndex([Path(self.combo.itemData(k)).resolve() for k in range(self.combo.count())]
                                   .index(path.resolve()))

    def edit_gates(self):
        """Buka editor gerbang di jendela terpisah; proyek dibaca ulang setelah editor ditutup."""
        if self.busy():
            QMessageBox.information(self, "Sedang bekerja", "Tunggu proses selesai sebelum mengubah gerbang.")
            return
        r = self.table.currentRow()
        v = self.videos[r] if 0 <= r < len(self.videos) else (self.videos[0] if self.videos else None)
        video = str(v["info"].path) if v else self.project.get("video_acuan")
        if not video or not Path(video).exists():
            QMessageBox.information(self, "Perlu video", "Tambahkan satu video simpang ini dulu, untuk gambar latar gerbang.")
            return
        args = ["-m", "autotc", "gerbang", str(self.project_path), "--video", video]
        if v and v["status"] == "Selesai":
            args += ["--lintasan", str(v["npz"])]
        ed = QProcess(self)
        ed.setWorkingDirectory(str(ROOT))
        ed.finished.connect(lambda *_: self.gates_edited())
        self.gate_btn.setEnabled(False)
        ed.start(sys.executable, args)

    def gates_edited(self):
        self.gate_btn.setEnabled(True)
        self.set_project(self.project_path)
        self.show_arms()
        self.show_selected()

    # --- daftar video
    def npz_for(self, info) -> Path:
        tag = video_tag(info.path) + (f"_{self.limit.value()}mnt" if self.limit.value() else "")
        return self.out_dir / f"{tag}.npz"

    def result_for(self, info) -> Path:
        """Berkas lintasan video ini: milik aplikasi, atau hasil proses harian (hasil\\<simpang>_*\\<nama video>.npz)."""
        own = self.npz_for(info)
        if own.exists() or self.limit.value():
            return own
        for f in sorted((ROOT / "hasil").glob(f"{self.name.lower()}_*/{info.path.stem}.npz")):
            return f
        return own

    def seconds_of(self, info) -> float:
        full = info.frames / info.fps if info.fps else 0.0
        return min(full, self.limit.value() * 60.0) if self.limit.value() else full

    def add_videos(self, infos):
        known = {v["info"].path for v in self.videos}
        for info in infos:
            if info.path not in known:
                self.videos.append({"info": info, "npz": None, "status": ""})
        self.videos.sort(key=lambda v: (v["info"].start is None, v["info"].start, str(v["info"].path)))
        self.refresh_status()

    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Pilih video", "", VIDEO_FILTER)
        if paths:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                self.add_videos([probe(p) for p in paths])
            finally:
                QApplication.restoreOverrideCursor()

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Pilih folder video satu hari")
        if folder:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                self.add_videos(index_folder(folder))
            finally:
                QApplication.restoreOverrideCursor()

    def remove_selected(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        if self.proc and (self.current in rows or any(q in rows for q in self.queue)):
            QMessageBox.information(self, "Sedang diproses", "Hentikan proses dulu sebelum menghapus video dari daftar.")
            return
        for r in rows:
            del self.videos[r]
        self.refresh_status()

    def refresh_status(self):
        if self.proc:   # daftar tidak berubah selama proses berjalan; hanya teks status
            self.fill_table()
            return
        for v in self.videos:
            v["npz"] = self.result_for(v["info"])
            v["status"] = "Selesai" if v["npz"].exists() else "Belum diproses"
        self.fill_table()
        self.show_selected()

    def fill_table(self):
        self.table.blockSignals(True)
        sel = self.table.currentRow()
        self.table.setRowCount(len(self.videos))
        for r, v in enumerate(self.videos):
            info, secs = v["info"], self.seconds_of(v["info"])
            cells = [f"{info.start:%d-%m-%Y %H:%M:%S}" if info.start else info.path.name, _dur(secs),
                     pick_mode(info.start, secs) if info.start else "siang", v["status"]]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(str(info.path))
                if c == 3 and text == "Selesai":
                    item.setForeground(QColor("#2e9e4f"))
                self.table.setItem(r, c, item)
        if 0 <= sel < len(self.videos):
            self.table.selectRow(sel)
        self.table.blockSignals(False)

    # --- pemrosesan
    def start(self):
        self.queue = [i for i, v in enumerate(self.videos) if v["status"] != "Selesai"]
        if not self.queue:
            self.progress.setText("Tidak ada video yang perlu diproses." if self.videos else "Tambahkan video dulu.")
            return
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.limit.setEnabled(False)
        self.total_jobs = len(self.queue)
        self.tries = {}
        self.failed: list[str] = []
        keep_awake(True)
        self.next_job()

    def next_job(self):
        if not self.queue:
            if self.failed:
                self.finish_all(f"Selesai, tetapi {len(self.failed)} video gagal: " + ", ".join(self.failed[:5])
                                + f". Rincian di {self.log_dir}.")
            else:
                self.finish_all("Semua video selesai diproses.")
            return
        self.current = self.queue.pop(0)
        v = self.videos[self.current]
        v["status"] = "Memproses 0%"
        self.fill_table()
        self.out_dir.mkdir(parents=True, exist_ok=True)
        exe = Path(sys.executable).with_name("python.exe")
        args = ["-u", "-m", "autotc", "proses", str(v["info"].path), str(v["npz"])]
        if self.project.get("gerbang"):
            args += ["--proyek", str(self.project_path)]
        if self.limit.value():
            args += ["--detik", str(self.limit.value() * 60)]
        self.proc = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        self.proc.setProcessEnvironment(env)
        self.proc.setWorkingDirectory(str(ROOT))
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self.read_output)
        proc = self.proc
        proc.finished.connect(lambda code, _st, proc=proc: self.job_finished(code, proc))
        self.log = ""
        self.t_start = self.last_output = time.time()
        self.log_dir = self.out_dir / "log"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / (v["npz"].stem + ".log")
        with self.log_file.open("a", encoding="utf-8") as f:
            f.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} mulai {v['info'].path}\n")
        self.bar.setValue(0)
        self.progress.setText("Memuat model...")
        self.proc.start(str(exe if exe.exists() else sys.executable), args)

    def read_output(self):
        if not self.proc or self.current < 0:
            return
        text = bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace")
        self.log = (self.log + text)[-4000:]
        self.last_output = time.time()
        try:
            with self.log_file.open("a", encoding="utf-8") as f:
                f.write("".join(ln + "\n" for ln in text.splitlines() if not ln.startswith("PROGRES")))
        except OSError:
            pass
        v = self.videos[self.current]
        for line in text.splitlines():
            if line.startswith("PROGRES"):
                _, n, total = line.split()
                frac = int(n) / max(int(total), 1)
                el = time.time() - self.t_start
                left = el * (1 - frac) / frac if frac > 0.01 else 0
                v["status"] = f"Memproses {100 * frac:.0f}%"
                self.bar.setValue(int(1000 * frac))
                done = self.total_jobs - len(self.queue)
                self.progress.setText(f"Video {done} dari {self.total_jobs}: {100 * frac:.0f}%"
                                      + (f", sisa sekitar {_dur(left)}" if left else "")
                                      + (f" (kecepatan {frac * self.seconds_of(v['info']) / el:.1f}x waktu nyata)" if el > 5 else ""))
            elif line.startswith("PESAN "):
                self.progress.setText(line[6:])
            elif line.startswith("TAHAP kelas"):
                v["status"] = "Menentukan kelas..."
                self.progress.setText("Menentukan kelas PKJI tiap kendaraan...")
            elif line.startswith("TAHAP hitung"):
                v["status"] = "Menghitung gerakan..."
                self.progress.setText("Menghitung gerakan tiap kendaraan...")
        self.fill_table()

    def job_finished(self, code=None, proc=None):
        if self.current < 0 or (proc is not None and proc is not self.proc):
            return      # sinyal terlambat dari proses yang sudah ditangani pengawas
        if self.proc and self.proc.bytesAvailable():
            self.read_output()
        v = self.videos[self.current]
        ok = code == 0 and v["npz"].exists()
        stopped = self.proc is None or getattr(self, "_stopping", False)
        self.proc = None
        v["status"] = "Selesai" if ok else ("Belum diproses" if stopped else "Gagal")
        self.fill_table()
        if stopped:
            self._stopping = False
            self.finish_all("Dihentikan. Video yang belum selesai akan diulang dari awal saat diproses lagi.")
            return
        if not ok:
            tail = [ln for ln in self.log.splitlines() if ln and not ln.startswith("PROGRES")][-3:]
            log_error(f"Video gagal (kode {code}): {v['info'].path}\n" + "\n".join(tail))
            n = self.tries.get(self.current, 0)
            if n < RETRIES:          # coba lagi di akhir antrean; video lain tetap jalan
                self.tries[self.current] = n + 1
                self.queue.append(self.current)
                self.total_jobs += 1
            else:
                self.failed.append(v["info"].path.name)
            self.next_job()
            return
        self.table.selectRow(self.current)
        self.next_job()

    def check_job(self):
        """Pengawas: proses yang sudah mati tanpa sinyal, atau macet tanpa keluaran, tidak boleh membuat antrean menggantung."""
        if not self.proc or self.current < 0:
            return
        if self.proc.state() == QProcess.NotRunning:
            log_error(f"Proses berhenti tanpa sinyal selesai: {self.videos[self.current]['info'].path}")
            self.job_finished(self.proc.exitCode() if self.proc.exitStatus() == QProcess.NormalExit else -1)
        elif time.time() - self.last_output > STALL_MINUTES * 60:
            log_error(f"Tidak ada keluaran {STALL_MINUTES} menit, proses dihentikan: {self.videos[self.current]['info'].path}")
            self.log += f"\nmacet: tidak ada keluaran {STALL_MINUTES} menit"
            proc = self.proc
            proc.kill()
            proc.waitForFinished(5000)
            if self.proc is proc:       # sinyal selesai belum datang
                self.job_finished(-1, proc)

    def stop(self):
        if self.proc:
            self._stopping = True
            self.queue = []
            self.proc.kill()

    def finish_all(self, text: str):
        keep_awake(False)
        self.proc, self.current = None, -1
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.limit.setEnabled(True)
        self.bar.setValue(0)
        self.progress.setText(text)
        for f in self.out_dir.glob("*.sebagian*.npz"):
            f.unlink(missing_ok=True)
        self.show_selected()

    # --- hasil
    def analyzed(self, npz: Path):
        if npz not in self.cache:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                self.cache[npz] = analyze(npz, self.project)
            finally:
                QApplication.restoreOverrideCursor()
        return self.cache[npz]

    def show_selected(self):
        r = self.table.currentRow()
        if not (0 <= r < len(self.videos)) or self.videos[r]["status"] != "Selesai" or not self.project.get("gerbang"):
            self.result.setRowCount(0)
            self.summary.setText("")
            self._pix = None
            self.image.setPixmap(QPixmap())
            self.image.setText("Pilih video yang sudah selesai untuk melihat lintasannya.")
            return
        npz = self.videos[r]["npz"]
        meta, tracks, s = self.analyzed(npz)
        mm = movement_matrix(tracks, meta, self.project)
        valid = [f"{o}->{d}" for o, d in movements_of(self.project)]
        self.result.setRowCount(len(valid) + 1)
        tot = Counter()
        for i, mv in enumerate(valid):
            row = [mv.replace("->", " ke "), *[mm[mv][c] for c in CLASSES], sum(mm[mv][c] for c in CLASSES)]
            tot.update({c: mm[mv][c] for c in CLASSES})
            for c, val in enumerate(row):
                self.result.setItem(i, c, self._cell(val))
        for c, val in enumerate(["TOTAL", *[tot[c] for c in CLASSES], sum(tot.values())]):
            self.result.setItem(len(valid), c, self._cell(val, bold=True))
        total, ok = s["bergerak_setelah_sambung"], s["lengkap_setelah_sambung"]
        end = meta["start"] + timedelta(seconds=meta["seconds"]) if meta["start"] else None
        kelas = "pengklasifikasi PKJI" if meta.get("kelas") else "kelas bawaan detektor (belum PKJI)"
        self.summary.setText(
            (f"<b>{meta['start']:%d-%m-%Y %H:%M:%S} s.d. {end:%H:%M:%S}</b> (mode {meta.get('mode', '?')})<br>" if end else "")
            + f"{total} kendaraan bergerak; <b>{ok} ({100 * ok / max(total, 1):.0f}%)</b> terbaca gerakannya, "
            f"{total - ok} tidak teridentifikasi. Kelas dari {kelas}.")
        png = npz.with_suffix(".jpg")
        if not png.exists():
            try:
                audit_image(tracks, meta, self.project, png)
            except Exception:  # video sumber sudah dipindah: tabel tetap tampil tanpa gambar
                pass
        self._pix = QPixmap(str(png)) if png.exists() else None
        self.image.setText("" if self._pix else "Gambar lintasan tidak tersedia (video sumber tidak ditemukan).")
        self.fit_image()

    @staticmethod
    def _cell(val, bold=False):
        item = QTableWidgetItem(str(val))
        if not isinstance(val, str):
            item.setTextAlignment(Qt.AlignCenter)
        if bold:
            f = item.font()
            f.setBold(True)
            item.setFont(f)
        return item

    def fit_image(self):
        if self._pix:
            self.image.setPixmap(self._pix.scaled(self.image.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fit_image()

    def export(self, _=False, path: str | Path | None = None):
        """Buat Excel rekap di proses terpisah (jendela tetap responsif). Semua video berstatus Selesai ikut."""
        if self.xproc:
            return
        done = [v for v in self.videos if v["status"] == "Selesai"]
        if not done:
            QMessageBox.information(self, "Belum ada hasil", "Belum ada video yang selesai diproses.")
            return
        if not self.project.get("gerbang"):
            QMessageBox.information(self, "Belum ada gerbang", "Gambar gerbang simpang ini dulu lewat tombol Atur gerbang.")
            return
        if not path:
            path, _f = QFileDialog.getSaveFileName(self, "Simpan Excel rekap", str(self.out_dir / f"TC {self.name}.xlsx"),
                                                   "Excel (*.xlsx)")
            if not path:
                return
        lst = Path(tempfile.gettempdir()) / f"autotc_rekap_{os.getpid()}.txt"
        lst.write_text("\n".join(str(v["npz"]) for v in done), encoding="utf-8")
        args = ["-u", "-m", "autotc", "rekap", str(self.project_path), str(path), "@" + str(lst)]
        if not self.one_file.isChecked():
            args.append("--per-hari")
        if not self.spread.isChecked():
            args.append("--tanpa-sebar")
        self.xlog = ""
        self.xproc = QProcess(self)
        self.xproc.setWorkingDirectory(str(ROOT))
        self.xproc.setProcessChannelMode(QProcess.MergedChannels)
        self.xproc.readyReadStandardOutput.connect(self.export_output)
        self.xproc.finished.connect(self.export_finished)
        self.export_btn.setEnabled(False)
        self.progress.setText(f"Membuat Excel dari {len(done)} video...")
        exe = Path(sys.executable).with_name("python.exe")
        self.xproc.start(str(exe if exe.exists() else sys.executable), args)

    def export_output(self):
        text = bytes(self.xproc.readAllStandardOutput()).decode("utf-8", "replace")
        self.xlog = (self.xlog + text)[-20000:]
        for line in text.splitlines():
            if line.startswith("PROGRES"):
                _, n, total = line.split()
                self.progress.setText(f"Membuat Excel: menghitung gerakan video {n} dari {total}"
                                      + (" (video yang baru pertama kali direkap butuh waktu)" if n != total else
                                         "; menulis sheet..."))

    def export_finished(self, code, _status):
        self.xproc = None
        self.export_btn.setEnabled(True)
        line = next((ln for ln in reversed(self.xlog.splitlines()) if ln.startswith("SELESAI ")), None)
        if code != 0 or not line:
            tail = [ln for ln in self.xlog.splitlines() if ln and not ln.startswith("PROGRES")][-2:]
            self.progress.setText("Excel gagal dibuat: " + " | ".join(tail))
            QMessageBox.warning(self, "Excel", "Excel gagal dibuat.\n" + "\n".join(tail))
            return
        res = json.loads(line[8:])
        self.last_excel = Path(res["berkas"][0])
        self.open_btn.setEnabled(True)
        self.progress.setText(
            f"Excel tersimpan ({res['hari']} hari, {res['video']} video): {res['kendaraan_terisi']} kendaraan terisi, "
            f"{res['ktb_di_rekap']} KTB di rekap, "
            + (f"{res['disebar']} kendaraan tak teridentifikasi disebar ke gerakan.\n" if res.get("disebar")
               else f"{res['tidak_teridentifikasi']} tidak teridentifikasi.\n")
            + "\n".join(res["berkas"][:3]) + (f"\n... dan {len(res['berkas']) - 3} berkas lain" if len(res["berkas"]) > 3 else ""))
        self.last_result = res

    def open_excel(self):
        if self.last_excel and self.last_excel.exists():
            os.startfile(str(self.last_excel))

    def closeEvent(self, e):
        if self.busy():
            if QMessageBox.question(self, "Sedang memproses", "Proses masih berjalan. Hentikan dan tutup?") != QMessageBox.Yes:
                e.ignore()
                return
            if self.xproc:
                self.xproc.kill()
                self.xproc.waitForFinished(3000)
            self.stop()
            self.proc and self.proc.waitForFinished(3000)
        super().closeEvent(e)


def run(project=None):
    app = QApplication.instance() or QApplication(sys.argv)

    def hook(kind, exc, tb):   # galat tak terduga: catat ke berkas dan tampilkan, jangan diam-diam
        import traceback
        text = "".join(traceback.format_exception(kind, exc, tb))
        log_error(text)
        try:
            QMessageBox.warning(None, "AUTO TC - galat", f"{exc}\n\nRincian tersimpan di {ERROR_LOG}")
        except Exception:
            pass
    sys.excepthook = hook
    files = project_files()
    w = App(project or (ROOT / "proyek" / "rajekwesi.json" if (ROOT / "proyek" / "rajekwesi.json").exists() else files[0]))
    w.show()
    return app.exec()
