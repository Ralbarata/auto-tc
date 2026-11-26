"""Potong gambar kendaraan dari video untuk dilabeli dan untuk mengklasifikasi kelas PKJI.

Untuk tiap lintasan bergerak diambil beberapa frame terbaik: kotaknya besar dan tidak terpotong tepi gambar.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

import cv2
import numpy as np

from .movements import Track, load_tracks, moving_tracks

from .labels import DEFAULT_CLASS_MAP as DEFAULT_MAP

FIELDS = ["berkas", "simpang", "video", "lintasan", "frame", "waktu", "mode", "coco", "awal", "lebar", "tinggi"]


def best_frames(t: Track, width: int, height: int, fps: float, k: int = 3, min_gap_s: float = 0.5) -> list[int]:
    """Indeks pengamatan terbaik: luas kotak terbesar, tidak menyentuh tepi gambar, berjarak waktu."""
    w, h = t.boxes[:, 2] - t.boxes[:, 0], t.boxes[:, 3] - t.boxes[:, 1]
    inside = (t.boxes[:, 0] > 4) & (t.boxes[:, 1] > 4) & (t.boxes[:, 2] < width - 4) & (t.boxes[:, 3] < height - 4)
    score = w * h * np.where(inside, 1.0, 0.25) * t.conf
    picked = []
    for i in np.argsort(-score):
        if all(abs(t.frames[i] - t.frames[j]) >= min_gap_s * fps for j in picked):
            picked.append(int(i))
            if len(picked) == k:
                break
    return picked


def crop(img: np.ndarray, box, pad: float = 0.10, max_side: int = 256) -> np.ndarray | None:
    x1, y1, x2, y2 = box
    p = pad * max(x2 - x1, y2 - y1)
    x1, y1 = int(max(x1 - p, 0)), int(max(y1 - p, 0))
    x2, y2 = int(min(x2 + p, img.shape[1])), int(min(y2 + p, img.shape[0]))
    c = img[y1:y2, x1:x2]
    if c.size == 0 or min(c.shape[:2]) < 12:
        return None
    s = max_side / max(c.shape[:2])
    return cv2.resize(c, (max(int(c.shape[1] * s), 1), max(int(c.shape[0] * s), 1))) if s < 1 else c


def iter_crops(npz_path: str | Path, k: int = 3, min_size: int = 24):
    """Hasilkan (lintasan, indeks_pengamatan, gambar_potongan) dengan satu kali baca video dari awal.

    Video dibaca berurutan karena rekaman HEVC tidak bisa dilompati dengan benar.
    """
    meta, raw = load_tracks(npz_path)
    tracks = moving_tracks(raw, meta)
    want = defaultdict(list)
    for ti, t in enumerate(tracks):
        for i in best_frames(t, meta["width"], meta["height"], meta["fps"], k):
            b = t.boxes[i]
            if min(b[2] - b[0], b[3] - b[1]) >= min_size:
                want[int(t.frames[i])].append((ti, i))
    if not want:
        return
    cap = cv2.VideoCapture(meta["video"])
    last = max(want)
    for f in range(last + 1):
        ok = cap.grab()
        if not ok:
            break
        if f in want:
            ok, img = cap.retrieve()
            if not ok:
                continue
            for ti, i in want[f]:
                c = crop(img, tracks[ti].boxes[i])
                if c is not None:
                    yield meta, tracks[ti], i, c
    cap.release()


def extract(npz_path: str | Path, simpang: str, out_dir: str | Path, k: int = 3, tag: str = "") -> int:
    """Simpan potongan ke out_dir/<simpang>/<video><tag>/ dan tambahkan ke out_dir/manifest.csv.

    `tag` membedakan hasil pelacakan lain atas video yang sama (nomor lintasannya tidak sama),
    supaya label yang sudah dibuat untuk pelacakan sebelumnya tidak tertimpa."""
    out_dir = Path(out_dir)
    manifest = out_dir / "manifest.csv"
    seen = set()
    if manifest.exists():
        with open(manifest, newline="", encoding="utf-8") as fh:
            seen = {r["berkas"] for r in csv.DictReader(fh)}
    rows = []
    for meta, t, i, img in iter_crops(npz_path, k):
        video = Path(meta["video"]).stem + tag
        rel = f"{simpang}/{video}/{t.ids[0]:06d}_{int(t.frames[i]):07d}.jpg"
        if rel in seen:
            continue
        path = out_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 90])
        coco = meta["names"][t.label]
        when = (meta["start"] + timedelta(seconds=float(t.frames[i]) / meta["fps"])).isoformat() if meta["start"] else ""
        rows.append({
            "berkas": rel, "simpang": simpang, "video": video, "lintasan": t.ids[0], "frame": int(t.frames[i]),
            "waktu": when, "mode": meta.get("mode", ""), "coco": coco, "awal": DEFAULT_MAP.get(coco, ""),
            "lebar": int(t.boxes[i][2] - t.boxes[i][0]), "tinggi": int(t.boxes[i][3] - t.boxes[i][1]),
        })
    new_file = not manifest.exists()
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(manifest, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        if new_file:
            w.writeheader()
        w.writerows(rows)
    return len(rows)
