"""Indeks folder video: urutkan berdasarkan jam rekam dan laporkan celah.

Rekaman Hikvision berekstensi .mp4 tetapi berisi MPEG-PS dengan kepala `IMKH`.
Jam mulai tersimpan di descriptor `40 0E 'HK'` pada Program Stream Map.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import cv2

VIDEO_EXT = {".mp4", ".avi", ".mkv", ".mov", ".ts", ".ps", ".dav"}


def read_hikvision_start(path: str | Path) -> datetime | None:
    """Jam mulai rekaman dari kepala file Hikvision; None jika bukan format itu."""
    with open(path, "rb") as fh:
        head = fh.read(4096)
    if head[:4] != b"IMKH":
        return None
    for i in range(len(head) - 12):
        if head[i] == 0x40 and head[i + 2 : i + 4] == b"HK":
            b = head[i + 2 :]
            try:
                return datetime(
                    2000 + b[4],
                    b[5] >> 4,
                    ((b[5] << 1) | (b[6] >> 7)) & 0x1F,
                    (b[6] >> 2) & 0x1F,
                    ((b[6] & 3) << 4) | (b[7] >> 4),
                    ((b[7] & 0xF) << 2) | (b[8] >> 6),
                )
            except ValueError:
                return None
    return None


@dataclass
class VideoFile:
    path: Path
    start: datetime | None
    fps: float
    frames: int
    width: int
    height: int

    @property
    def duration(self) -> timedelta:
        return timedelta(seconds=self.frames / self.fps) if self.fps else timedelta(0)

    @property
    def end(self) -> datetime | None:
        return self.start + self.duration if self.start else None


def probe(path: str | Path) -> VideoFile:
    path = Path(path)
    cap = cv2.VideoCapture(str(path))
    info = VideoFile(
        path=path,
        start=read_hikvision_start(path),
        fps=cap.get(cv2.CAP_PROP_FPS) or 0.0,
        frames=int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0),
        width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0),
        height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0),
    )
    cap.release()
    return info


def index_folder(folder: str | Path) -> list[VideoFile]:
    """Semua video di folder, diurutkan menurut jam mulai (nama file tidak berurutan)."""
    files = [probe(p) for p in Path(folder).iterdir() if p.suffix.lower() in VIDEO_EXT]
    files.sort(key=lambda v: (v.start or datetime.max, len(v.path.name), v.path.name))
    unique, seen = [], set()
    for v in files:  # salinan ganda, mis. "nama(1).mp4": jam mulai dan jumlah frame sama
        key = (v.start, v.frames, v.path.stat().st_size)
        if v.start and key in seen:
            continue
        seen.add(key)
        unique.append(v)
    return unique


def find_gaps(files: list[VideoFile], tolerance_s: float = 5.0) -> list[tuple[datetime, datetime]]:
    """Rentang waktu tanpa rekaman di antara file yang berurutan."""
    gaps = []
    for a, b in zip(files, files[1:]):
        if a.end and b.start and (b.start - a.end).total_seconds() > tolerance_s:
            gaps.append((a.end, b.start))
    return gaps


def describe(folder: str | Path) -> str:
    files = index_folder(folder)
    lines = [f"{len(files)} file di {folder}"]
    for v in files:
        start = v.start.strftime("%Y-%m-%d %H:%M:%S") if v.start else "jam tidak terbaca"
        lines.append(f"  {start}  {v.duration.total_seconds() / 60:6.1f} mnt  {v.width}x{v.height}@{v.fps:.0f}  {v.path.name}")
    gaps = find_gaps(files)
    lines.append(f"celah rekaman: {len(gaps)}")
    for a, b in gaps:
        lines.append(f"  {a:%Y-%m-%d %H:%M:%S} -> {b:%H:%M:%S}  ({(b - a).total_seconds():.0f} dtk)")
    return "\n".join(lines)
