"""Kelas PKJI dan baca-tulis label (tanpa ketergantungan tampilan)."""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

CLASSES = ["SM", "MP", "KS", "BB", "TB", "KTB"]   # KTB = kendaraan tak bermotor (sepeda, becak, gerobak)
MOTORIZED = CLASSES[:5]                              # lima kelas yang ada di form PKJI
DISCARD = "buang"
# kelas bawaan detektor -> tebakan awal kelas PKJI (sebelum ada pengklasifikasi)
DEFAULT_CLASS_MAP = {"motorcycle": "SM", "car": "MP", "truck": "KS", "bus": "BB", "bicycle": "KTB"}
TWO_WHEELERS = {"motorcycle", "bicycle"}


def load_items(data_dir: Path) -> list[dict]:
    """Satu butir per lintasan: gambar wakil = potongan terbesarnya."""
    groups = defaultdict(list)
    with open(Path(data_dir) / "manifest.csv", newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            groups[f"{r['simpang']}/{r['video']}/{r['lintasan']}"].append(r)
    items = []
    for key, rows in groups.items():
        best = max(rows, key=lambda r: int(r["lebar"]) * int(r["tinggi"]))
        items.append({"kunci": key, "berkas": best["berkas"], "awal": best["awal"], "mode": best["mode"],
                      "semua": [r["berkas"] for r in rows]})
    return items


def load_labels(path: Path) -> dict[str, str]:
    path = Path(path)
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as fh:
        return {r["kunci"]: r["label"] for r in csv.DictReader(fh)}


def save_labels(path: Path, labels: dict[str, str]):
    path = Path(path)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["kunci", "label"])
        w.writerows(sorted(labels.items()))
    tmp.replace(path)
