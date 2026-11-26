"""Pengklasifikasi kelas PKJI atas potongan gambar kendaraan: susun data, latih, pakai.

Detektor tetap mencari dan melacak kendaraan; model kecil ini hanya menentukan kelasnya.
Kelas satu kendaraan = jumlah peluang dari beberapa potongan gambar terbaiknya.
"""
from __future__ import annotations

import csv
import hashlib
import shutil
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from .labels import CLASSES, DISCARD, load_items, load_labels

ROOT = Path(__file__).resolve().parent.parent
WEIGHTS = ROOT / "model" / "kelas_pkji.pt"


def build_dataset(data_dir: str | Path, out_dir: str | Path, val_frac: float = 0.2) -> dict:
    """Susun folder train/val per kelas. Semua potongan satu kendaraan masuk ke sisi yang sama,
    supaya model tidak diuji dengan kendaraan yang sudah dilihatnya saat dilatih."""
    data_dir, out_dir = Path(data_dir), Path(out_dir)
    labels = load_labels(data_dir / "label.csv")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    stats = defaultdict(Counter)
    for it in load_items(data_dir):
        lab = labels.get(it["kunci"])
        if lab is None or lab == DISCARD:
            continue
        h = int(hashlib.md5(it["kunci"].encode()).hexdigest(), 16) % 1000
        split = "val" if h < val_frac * 1000 else "train"
        for rel in it["semua"]:
            dst = out_dir / split / lab / rel.replace("/", "__")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(data_dir / rel, dst)
            stats[split][lab] += 1
    for split in ("train", "val"):       # pustaka pelatihan butuh folder untuk setiap kelas di kedua sisi
        for c in CLASSES:
            (out_dir / split / c).mkdir(parents=True, exist_ok=True)
    return {k: dict(v) for k, v in stats.items()}


def train(dataset_dir: str | Path, epochs: int = 40, imgsz: int = 224, base: str = "yolo26s-cls.pt",
          out: str | Path = WEIGHTS) -> dict:
    from ultralytics import YOLO
    run_dir = ROOT / "hasil" / "pelatihan"
    model = YOLO(base)
    model.train(data=str(dataset_dir), epochs=epochs, imgsz=imgsz, project=str(run_dir), name="kelas_pkji",
                exist_ok=True, verbose=False, plots=False, workers=0)
    best = run_dir / "kelas_pkji" / "weights" / "best.pt"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(best, out)
    return evaluate(dataset_dir, out)


def evaluate(dataset_dir: str | Path, weights: str | Path = WEIGHTS) -> dict:
    """Tabel tertukar pada data val: baris = kelas sebenarnya, kolom = tebakan model."""
    from ultralytics import YOLO
    model = YOLO(str(weights))
    names = [model.names[i] for i in sorted(model.names)]
    table = {c: Counter() for c in CLASSES}
    for c in CLASSES:
        files = sorted((Path(dataset_dir) / "val" / c).glob("*.jpg"))
        for i in range(0, len(files), 64):
            for r in model.predict([str(f) for f in files[i:i + 64]], imgsz=224, verbose=False):
                table[c][names[int(r.probs.top1)]] += 1
    total = sum(sum(v.values()) for v in table.values())
    right = sum(table[c][c] for c in CLASSES)
    return {"tepat": right, "jumlah": total, "akurasi": round(right / total, 3) if total else None,
            "tabel": {c: dict(table[c]) for c in CLASSES}}


def classify_npz(npz_path: str | Path, weights: str | Path = WEIGHTS, k: int = 3) -> Path:
    """Klasifikasi semua lintasan bergerak di satu berkas lintasan; hasil disimpan di samping berkasnya
    sebagai <nama>.kelas.npz (peluang per kelas untuk tiap id lintasan)."""
    from ultralytics import YOLO

    from .crops import iter_crops
    model = YOLO(str(weights))
    names = [model.names[i] for i in sorted(model.names)]
    probs = defaultdict(lambda: np.zeros(len(names)))
    batch, owners = [], []

    def flush():
        if batch:
            for tid, r in zip(owners, model.predict(batch, imgsz=224, verbose=False)):
                probs[tid] += r.probs.data.cpu().numpy()
            batch.clear()
            owners.clear()

    for _, t, _, img in iter_crops(npz_path, k):
        batch.append(img)
        owners.append(t.ids[0])
        if len(batch) == 64:
            flush()
    flush()
    out = Path(npz_path).with_suffix(".kelas.npz")
    ids = sorted(probs)
    np.savez_compressed(out, ids=np.array(ids), probs=np.array([probs[i] for i in ids]), names=np.array(names))
    return out


def label_summary(data_dir: str | Path) -> dict:
    data_dir = Path(data_dir)
    labels = load_labels(data_dir / "label.csv")
    with open(data_dir / "manifest.csv", newline="", encoding="utf-8") as fh:
        n = len({f"{r['simpang']}/{r['video']}/{r['lintasan']}" for r in csv.DictReader(fh)})
    return {"kendaraan": n, "dilabeli": len(labels), "per_kelas": dict(Counter(labels.values()))}
