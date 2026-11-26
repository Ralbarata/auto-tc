"""Deteksi + pelacakan satu file video; lintasan disimpan ke berkas .npz.

Lintasan disimpan mentah supaya gerbang bisa diubah dan dihitung ulang
tanpa memproses video lagi.
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timedelta
from datetime import time as dtime
from pathlib import Path

import numpy as np
from ultralytics import YOLO

from .video_index import probe

COCO_VEHICLES = [1, 2, 3, 5, 7]  # bicycle, car, motorcycle, bus, truck
ROOT = Path(__file__).resolve().parent.parent


# Pengaturan per mode. Malam: ambang lebih rendah supaya kendaraan yang samar tetap terdeteksi.
MODES = {
    "siang": {"conf": 0.20, "tracker": ROOT / "konfig" / "pelacak.yaml"},
    "malam": {"conf": 0.08, "tracker": ROOT / "konfig" / "pelacak_malam.yaml",
              "model": ROOT / "model" / "deteksi_malam.pt"},
}
DEFAULT_MODEL = ROOT / "model" / "yolo26m.pt"
NIGHT_HOURS = (dtime(17, 30), dtime(5, 30))  # malam = dari jam pertama sampai jam kedua keesokan harinya


FAST_REID = True    # potongan ReID diambil sekaligus di GPU (lihat reid_fast.py)
AGNOSTIC_NMS = True   # buang kotak bertumpuk walau kelasnya berbeda (satu kendaraan terbaca dua kelas)
USE_ENGINE = True   # pakai mesin TensorRT (.engine) bila sudah dibuat untuk ukuran gambar video ini


def input_shape(width: int, height: int, imgsz: int = 1280) -> tuple[int, int]:
    """(tinggi, lebar) masukan model: sisi panjang = imgsz, sisi pendek dibulatkan naik ke kelipatan 32.
    Sama dengan ukuran yang dipakai model .pt, sehingga hasil keduanya sebanding."""
    long, short = max(width, height), min(width, height)
    s = math.ceil(short * imgsz / long / 32) * 32
    return (s, imgsz) if width >= height else (imgsz, s)


def engine_path(weights: str | Path, shape: tuple[int, int]) -> Path:
    w = Path(weights)
    return w.with_name(f"{w.stem}_{shape[0]}x{shape[1]}.engine")


def build_engine(weights: str | Path, shape: tuple[int, int], device: int | str = 0) -> Path:
    """Ubah bobot .pt menjadi mesin TensorRT FP16 untuk satu ukuran gambar (beberapa menit, sekali saja).
    Mesin hanya berlaku di kartu grafis dan versi driver tempat ia dibuat."""
    out = engine_path(weights, shape)
    made = Path(YOLO(str(weights)).export(format="engine", imgsz=list(shape), half=True, device=device, batch=1, verbose=False))
    made.replace(out)
    for extra in Path(weights).parent.glob(Path(weights).stem + "*.onnx"):
        extra.unlink(missing_ok=True)
    return out


def prepare_engine(weights: str | Path, shape: tuple[int, int], notice=print) -> Path | None:
    """Mesin TensorRT untuk bobot dan ukuran ini; dibuat dulu bila belum ada (sekali saja, beberapa menit).
    None bila TensorRT tidak tersedia atau sedang dibuat proses lain: pemanggil memakai bobot .pt."""
    eng = engine_path(weights, shape)
    if eng.exists():
        return eng
    try:
        import tensorrt  # noqa: F401
    except ImportError:
        return None
    lock = eng.with_suffix(".sedang_dibuat")
    if lock.exists() and time.time() - lock.stat().st_mtime < 3600:
        return None   # proses lain sedang membuatnya; video ini memakai model biasa
    lock.write_text("")
    try:
        if notice:
            notice(f"Menyiapkan TensorRT untuk {Path(weights).name} (sekali saja, beberapa menit)...")
        return build_engine(weights, shape)
    except Exception as exc:   # kartu grafis/driver tidak mendukung: tetap jalan dengan model biasa
        if notice:
            notice(f"TensorRT gagal disiapkan ({exc.__class__.__name__}); memakai model biasa.")
        return None
    finally:
        lock.unlink(missing_ok=True)


def pick_mode(start: datetime | None, seconds: float, night_hours=NIGHT_HOURS) -> str:
    """Siang atau malam menurut jam di tengah rentang yang diproses. Kecerahan gambar tidak dipakai
    karena kamera menaikkan penguatan saat gelap, sehingga malam bisa tampak seterang siang."""
    if start is None:
        return "siang"
    t = (start + timedelta(seconds=seconds / 2)).time()
    return "malam" if t >= night_hours[0] or t < night_hours[1] else "siang"


def track_video(
    video: str | Path,
    out_npz: str | Path,
    model_path: str | Path | None = None,
    tracker: str | Path | None = None,
    imgsz: int = 1280,
    stride: int = 1,
    conf: float | None = None,
    max_seconds: float | None = None,
    classes: list[int] | None = None,
    device: int | str = 0,
    mode: str = "auto",
    night_hours=NIGHT_HOURS,
    progress=None,
    notice=print,
    engine: bool | None = None,
    fast_reid: bool | None = None,
    agnostic: bool | None = None,
) -> dict:
    """`mode`: "siang", "malam", atau "auto" (dipilih dari jam rekaman). `conf` dan `tracker` yang
    diisi langsung mengalahkan pengaturan mode."""
    info = probe(video)
    max_frames = int(max_seconds * info.fps) if max_seconds else info.frames
    if mode == "auto":
        mode = pick_mode(info.start, max_frames / info.fps if info.fps else 0.0, night_hours)
    if model_path is None:
        # malam: detektor yang dilatih ulang dengan frame malam, bila sudah ada
        special = MODES[mode].get("model")
        model_path = special if special and Path(special).exists() else DEFAULT_MODEL
    if (USE_ENGINE if engine is None else engine) and Path(model_path).suffix == ".pt":
        shape = input_shape(info.width, info.height, imgsz)
        eng = prepare_engine(model_path, shape, notice)
        if eng:
            model_path, imgsz = eng, list(shape)
    if fast_reid if fast_reid is not None else FAST_REID:
        from . import reid_fast
        if (USE_ENGINE if engine is None else engine) and not reid_fast.ENGINE.exists():
            try:
                import tensorrt  # noqa: F401
                if notice:
                    notice("Menyiapkan TensorRT untuk ReID (sekali saja, sekitar satu menit)...")
                reid_fast.build_engine()
            except Exception:
                pass   # ReID tetap jalan dengan PyTorch
        reid_fast.install()
    else:
        from ultralytics.trackers import bot_sort
        from ultralytics.trackers.utils.reid import build_encoder
        bot_sort.build_encoder = build_encoder
        import autotc.reid_fast as rf
        rf._installed = False
    model = YOLO(str(model_path), task="detect")
    if classes is None and len(model.names) == 80:
        classes = COCO_VEHICLES   # model umum: ambil kelas kendaraan saja; model latih ulang hanya berisi kendaraan
    conf = MODES[mode]["conf"] if conf is None else conf
    tracker = MODES[mode]["tracker"] if tracker is None else tracker
    rows = []
    speed = np.zeros(3)
    n = 0
    t0 = time.time()
    results = model.track(
        source=str(video), stream=True, vid_stride=stride, imgsz=imgsz, conf=conf,
        classes=classes, tracker=str(tracker), device=device, verbose=False,
        agnostic_nms=AGNOSTIC_NMS if agnostic is None else agnostic,
    )
    for i, r in enumerate(results):
        frame = i * stride
        if frame >= max_frames:
            break
        n += 1
        if progress and n % 50 == 0:
            progress(frame, max_frames)
        speed += [r.speed["preprocess"], r.speed["inference"], r.speed["postprocess"]]
        if r.boxes.id is None:
            continue
        b = r.boxes
        m = len(b)
        rows.append(np.column_stack([
            np.full(m, frame), b.id.cpu().numpy(), b.cls.cpu().numpy(), b.conf.cpu().numpy(), b.xyxy.cpu().numpy(),
        ]))
    wall = time.time() - t0
    data = np.concatenate(rows) if rows else np.zeros((0, 8))
    out_npz = Path(out_npz)
    out_npz.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out_npz,
        data=data.astype(np.float32),
        columns=np.array(["frame", "id", "cls", "conf", "x1", "y1", "x2", "y2"]),
        fps=info.fps, stride=stride, frames_done=n * stride, mode=mode, conf=conf, width=info.width, height=info.height,
        start=info.start.isoformat() if info.start else "",
        video=str(video), names=np.array([model.names[i] for i in sorted(model.names)]),
    )
    return {
        "mode": mode, "conf": conf, "model": Path(model_path).name, "reid_cepat": bool(FAST_REID if fast_reid is None else fast_reid),
        "frames_processed": n,
        "video_seconds": n * stride / info.fps,
        "wall_seconds": wall,
        "x_realtime": (n * stride / info.fps) / wall if wall else 0,
        "ms_pre_inf_post": (speed / max(n, 1)).round(1).tolist(),
        "detections": int(len(data)),
        "tracks": int(len(np.unique(data[:, 1]))) if len(data) else 0,
    }
