"""Video beranotasi untuk memeriksa hitungan secara manual."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

import cv2
import numpy as np

from .movements import UNKNOWN, Gates, _palette, track_class


def render(tracks, meta: dict, project: dict, out_path: str | Path, seconds: float = 180, out_width: int = 1280):
    """Tulis video: gerbang, kotak tiap kendaraan berlabel gerakan + kelas, dan hitungan berjalan.

    Hitungan sebuah kendaraan bertambah saat lintasannya berakhir.
    """
    fps, stride = meta["fps"], meta["stride"]
    scale = out_width / meta["width"]
    size = (out_width, int(meta["height"] * scale) // 2 * 2)
    gates = Gates(project, meta["width"], meta["height"])

    def valid(t):
        return UNKNOWN not in (t.origin, t.dest) and t.origin != t.dest

    colors = _palette(sorted({t.movement for t in tracks if valid(t)}))
    per_frame = defaultdict(list)
    ends = defaultdict(list)
    for t in tracks:
        kelas = track_class(t, meta, project)
        label = f"{t.origin[:3]}>{t.dest[:3]} {kelas}"
        color = colors[t.movement] if valid(t) else (170, 170, 170)
        for f, b in zip(t.frames, t.boxes):
            per_frame[int(f)].append((b, label, color))
        if valid(t):
            ends[int(t.frames[-1])].append(t.movement)

    cap = cv2.VideoCapture(meta["video"])
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(out_path), cv2.VideoWriter_fourcc(*"mp4v"), fps / stride, size)
    counts = Counter()
    for f in range(int(seconds * fps)):
        ok, img = cap.read()
        if not ok:
            break
        for mv in ends.get(f, []):
            counts[mv] += 1
        if f % stride:
            continue
        img = cv2.resize(img, size)
        for name, poly in zip(gates.names, gates.polys):
            p = (poly * scale).astype(np.int32)
            cv2.polylines(img, [p], True, (255, 255, 255), 1)
            cv2.putText(img, name, (int(p[:, 0].min()) + 4, int(p[:, 1].min()) + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        for b, label, color in per_frame.get(f, []):
            x1, y1, x2, y2 = (b * scale).astype(int)
            cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
            cv2.putText(img, label, (x1, max(y1 - 4, 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 3)
            cv2.putText(img, label, (x1, max(y1 - 4, 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
        panel_h = 26 + 18 * len(colors)
        cv2.rectangle(img, (size[0] - 250, 0), (size[0], panel_h), (0, 0, 0), -1)
        clock = (meta["start"] + timedelta(seconds=f / fps)).strftime("%H:%M:%S") if meta["start"] else f"{f / fps:.0f}s"
        cv2.putText(img, f"{clock}  total {sum(counts.values())}", (size[0] - 244, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        for i, mv in enumerate(sorted(colors)):
            cv2.putText(img, f"{mv}: {counts[mv]}", (size[0] - 244, 38 + 18 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.45, colors[mv], 1)
        writer.write(img)
    writer.release()
    cap.release()
    return dict(counts)
