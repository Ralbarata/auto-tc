"""Data kotak kendaraan untuk melatih ulang detektor: ambil frame, isi kotak awal, baca-tulis label.

Susunan: data/kotak/<simpang>/<nama>.jpg dan <nama>.json di sampingnya:
{"kotak": [[x1, y1, x2, y2, kelas, sumber], ...], "selesai": bool}; koordinat piksel gambar,
kelas = nama kelas detektor (KINDS), sumber = "model" atau "manual".
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "kotak"
KINDS = ["motorcycle", "car", "truck", "bus", "bicycle"]          # urutan tombol 1-5
KIND_LABEL = {"motorcycle": "motor", "car": "mobil", "truck": "truk", "bus": "bus", "bicycle": "sepeda"}


def extract_frames(video: str | Path, out_dir: str | Path, tag: str, every_s: float = 42.0, fps: float = 25.0) -> int:
    """Satu frame tiap `every_s` detik dari seluruh video (dibaca berurutan: HEVC tidak bisa dilompati)."""
    from .manual_tool import find_ffmpeg
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    step = max(int(round(every_s * fps)), 1)
    cmd = [find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(video), "-an",
           "-vf", f"select=not(mod(n\\,{step}))", "-fps_mode", "vfr", "-q:v", "2", str(out_dir / f"{tag}_%04d.jpg")]
    subprocess.run(cmd, check=True)
    return len(list(out_dir.glob(f"{tag}_*.jpg")))


def label_path(image: Path) -> Path:
    return Path(image).with_suffix(".json")


def load(image: Path) -> dict:
    p = label_path(image)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"kotak": [], "selesai": False}


def save(image: Path, data: dict):
    p = label_path(image)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(p)


def prefill(folder: str | Path, model_path: str | Path | None = None, conf: float = 0.25, imgsz: int = 1280) -> int:
    """Kotak awal dari model untuk gambar yang belum punya berkas label."""
    from ultralytics import YOLO
    todo = [p for p in sorted(Path(folder).glob("*.jpg")) if not label_path(p).exists()]
    if not todo:
        return 0
    model = YOLO(str(model_path or ROOT / "model" / "yolo26m.pt"))
    ids = [i for i, n in model.names.items() if n in KINDS]
    for p in todo:
        r = model.predict(str(p), imgsz=imgsz, conf=conf, classes=ids, verbose=False)[0]
        boxes = [[round(float(v), 1) for v in xyxy] + [model.names[int(c)], "model"]
                 for xyxy, c in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.cls.cpu().numpy())]
        save(p, {"kotak": boxes, "selesai": False})
    return len(todo)


def build_dataset(folders: list, out_dir: str | Path, val_every: int = 7) -> dict:
    """Dataset deteksi format YOLO dari gambar yang sudah ditandai selesai. Gambar tanpa kotak ikut
    sebagai contoh latar. Satu dari `val_every` gambar disisihkan untuk validasi."""
    import shutil

    import cv2
    out_dir = Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    n = {"train": 0, "val": 0, "kotak": 0}
    k = 0
    for folder in folders:
        for img in sorted(Path(folder).glob("*.jpg")):
            d = load(img)
            if not d.get("selesai"):
                continue
            split = "val" if k % val_every == val_every - 1 else "train"
            k += 1
            h, w = cv2.imread(str(img)).shape[:2]
            (out_dir / "images" / split).mkdir(parents=True, exist_ok=True)
            (out_dir / "labels" / split).mkdir(parents=True, exist_ok=True)
            name = f"{Path(folder).name}_{img.stem}"
            shutil.copy(img, out_dir / "images" / split / f"{name}.jpg")
            lines = [f"{KINDS.index(b[4])} {(b[0] + b[2]) / 2 / w:.6f} {(b[1] + b[3]) / 2 / h:.6f} "
                     f"{(b[2] - b[0]) / w:.6f} {(b[3] - b[1]) / h:.6f}" for b in d["kotak"] if b[4] in KINDS]
            (out_dir / "labels" / split / f"{name}.txt").write_text("\n".join(lines), encoding="utf-8")
            n[split] += 1
            n["kotak"] += len(lines)
    names = "\n".join(f"  {i}: {k_}" for i, k_ in enumerate(KINDS))
    (out_dir / "data.yaml").write_text(
        f"path: {out_dir.as_posix()}\ntrain: images/train\nval: images/val\nnames:\n{names}\n", encoding="utf-8")
    return n


NIGHT_WEIGHTS = ROOT / "model" / "deteksi_malam.pt"


def train(dataset: str | Path, epochs: int = 60, imgsz: int = 1280, batch: int = 4, out: Path = NIGHT_WEIGHTS) -> dict:
    """Latih ulang detektor umum dengan frame malam berlabel; bobot terbaik disalin ke `out`."""
    import shutil

    from ultralytics import YOLO
    model = YOLO(str(ROOT / "model" / "yolo26m.pt"))
    res = model.train(data=str(Path(dataset) / "data.yaml"), epochs=epochs, imgsz=imgsz, batch=batch, workers=2,
                      project=str(ROOT / "hasil" / "pelatihan"), name="deteksi_malam", exist_ok=True, verbose=False)
    best = Path(res.save_dir) / "weights" / "best.pt"
    shutil.copy(best, out)
    return {"bobot": str(out), "mAP50": round(float(res.box.map50), 3), "mAP50_95": round(float(res.box.map), 3),
            "recall": round(float(res.box.mr), 3), "presisi": round(float(res.box.mp), 3)}


def summary(folder: str | Path) -> dict:
    imgs = sorted(Path(folder).glob("*.jpg"))
    data = [load(p) for p in imgs]
    done = [d for d in data if d.get("selesai")]
    return {"gambar": len(imgs), "selesai": len(done),
            "kotak_model": sum(b[5] == "model" for d in done for b in d["kotak"]),
            "kotak_manual": sum(b[5] == "manual" for d in done for b in d["kotak"])}
