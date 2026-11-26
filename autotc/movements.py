"""Dari lintasan mentah ke hitungan per gerakan (gerbang masuk -> gerbang keluar).

Langkah: muat lintasan -> buang yang diam -> sambung potongan yang putus
-> tentukan gerbang awal dan akhir -> hitung per interval, gerakan, kelas.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import numpy as np

from .labels import DEFAULT_CLASS_MAP, TWO_WHEELERS

UNKNOWN = "?"


@dataclass
class Track:
    ids: list[int]
    frames: np.ndarray          # indeks frame video asli
    boxes: np.ndarray           # (N, 4) xyxy piksel
    cls: np.ndarray
    conf: np.ndarray
    origin: str = UNKNOWN
    dest: str = UNKNOWN
    stitched: int = 0           # jumlah sambungan
    origin_est: bool = False    # gerbang asal hasil perkiraan arah
    dest_est: bool = False
    route: bool = False         # gerakan ditetapkan lewat pencocokan jalur
    s0: float = 0.0             # posisi awal dan akhir di sepanjang jalur (0-1), hanya untuk route
    s1: float = 0.0
    foot: np.ndarray = field(init=False)

    def __post_init__(self):
        self.foot = np.column_stack([(self.boxes[:, 0] + self.boxes[:, 2]) / 2, self.boxes[:, 3]])

    @property
    def label(self) -> int:
        """Kelas mayoritas, dibobot keyakinan dan luas kotak (frame saat terlihat utuh lebih dipercaya)."""
        area = (self.boxes[:, 2] - self.boxes[:, 0]) * (self.boxes[:, 3] - self.boxes[:, 1])
        votes = defaultdict(float)
        for c, w in zip(self.cls, self.conf * np.sqrt(area)):
            votes[int(c)] += float(w)
        return max(votes, key=votes.get)

    @property
    def extent(self) -> float:
        return float(np.linalg.norm(self.foot.max(0) - self.foot.min(0)))

    @property
    def movement(self) -> str:
        return f"{self.origin}->{self.dest}"


def load_tracks(npz_path: str | Path) -> tuple[dict, list[Track]]:
    z = np.load(npz_path, allow_pickle=False)
    d = z["data"]
    start = str(z["start"])
    meta = {
        "fps": float(z["fps"]), "stride": int(z["stride"]), "width": int(z["width"]), "height": int(z["height"]),
        "start": datetime.fromisoformat(start) if start else None, "video": str(z["video"]),
        "names": [str(n) for n in z["names"]],
        "mode": str(z["mode"]) if "mode" in z else "",
    }
    # durasi video yang diproses; berkas lama tidak menyimpannya, pakai frame terakhir yang ada deteksinya
    frames = float(z["frames_done"]) if "frames_done" in z else (float(d[:, 0].max()) + meta["stride"] if len(d) else 0.0)
    meta["seconds"] = frames / meta["fps"] if meta["fps"] else 0.0
    # kelas PKJI dari pengklasifikasi, bila berkas pendampingnya sudah dibuat (lihat classify.classify_npz)
    side = Path(npz_path).with_suffix(".kelas.npz")
    meta["kelas"] = None
    if side.exists():
        k = np.load(side, allow_pickle=False)
        meta["kelas"] = ([str(n) for n in k["names"]], {int(i): p for i, p in zip(k["ids"], k["probs"])})
    tracks = []
    order = np.lexsort((d[:, 0], d[:, 1]))
    d = d[order]
    for tid in np.unique(d[:, 1]):
        r = d[d[:, 1] == tid]
        tracks.append(Track([int(tid)], r[:, 0].astype(int), r[:, 4:8], r[:, 2].astype(int), r[:, 3]))
    return meta, tracks


class Gates:
    """Gerbang = poligon (koordinat 0-1) tempat kendaraan muncul atau hilang dari gambar."""

    def __init__(self, project: dict, width: int, height: int):
        self.names = [g["nama"] for g in project["gerbang"]]
        self.polys = [
            (np.array(g["poligon"], dtype=np.float32) * [width, height]).astype(np.float32) for g in project["gerbang"]
        ]

    def at(self, pt) -> str | None:
        for name, poly in zip(self.names, self.polys):
            if cv2.pointPolygonTest(poly, (float(pt[0]), float(pt[1])), False) >= 0:
                return name
        return None

    def along(self, start, direction, reach: float, exclude: str | None = None) -> str:
        """Gerbang pertama yang dikenai sinar dari `start` searah `direction`, sejauh `reach` piksel."""
        n = float(np.linalg.norm(direction))
        if n < 2.0:
            return UNKNOWN
        step = direction / n * 8.0
        p = np.array(start, dtype=float)
        for _ in range(int(reach / 8)):
            p = p + step
            g = self.at(p)
            if g and g != exclude:
                return g
        return UNKNOWN

    def of_points(self, pts) -> str:
        hits = Counter(g for g in (self.at(p) for p in pts) if g)
        return hits.most_common(1)[0][0] if hits else UNKNOWN


def _same_group(a: int, b: int, names: list[str]) -> bool:
    """Roda dua (motor, sepeda) hanya disambung dengan roda dua; roda empat boleh berganti label
    (mobil/truk/bus)."""
    return (names[a] in TWO_WHEELERS) == (names[b] in TWO_WHEELERS)


def _direction(t: Track, fps: float, at_end: bool, window_s: float = 0.8) -> np.ndarray:
    k = t.frames >= t.frames[-1] - window_s * fps if at_end else t.frames <= t.frames[0] + window_s * fps
    pts = t.foot[k]
    return pts[-1] - pts[0] if len(pts) >= 2 else np.zeros(2)


def assign_gates(tracks: list[Track], gates: Gates, fps: float, window_s: float = 1.0):
    """Gerbang awal/akhir dibaca langsung dari posisi lintasan pada detik pertama dan terakhirnya."""
    w = window_s * fps
    for t in tracks:
        t.origin = gates.of_points(t.foot[t.frames <= t.frames[0] + w])
        t.dest = gates.of_points(t.foot[t.frames >= t.frames[-1] - w])
        t.origin_est = t.dest_est = t.route = False


def extrapolate(tracks: list[Track], gates: Gates, fps: float, reach: float):
    """Cadangan untuk yang belum lengkap: perpanjang arah gerak di ujung lintasan sejauh `reach` piksel
    sampai mengenai sebuah gerbang."""
    for t in tracks:
        if t.route or (UNKNOWN not in (t.origin, t.dest) and t.origin != t.dest):
            continue
        same = t.origin == t.dest != UNKNOWN  # muncul dan hilang di gerbang yang sama: coba perpanjang keduanya
        if t.dest == UNKNOWN or same:
            g = gates.along(t.foot[-1], _direction(t, fps, True), reach, exclude=t.origin)
            if g != UNKNOWN:
                t.dest, t.dest_est, same = g, True, False
        if t.origin == UNKNOWN or same:
            g = gates.along(t.foot[0], -_direction(t, fps, False), reach, exclude=t.dest)
            if g != UNKNOWN:
                t.origin, t.origin_est = g, True


def stitch(tracks: list[Track], gates: Gates, meta: dict, max_gap_s: float = 6.0) -> list[Track]:
    """Sambung potongan yang berakhir di tengah gambar dengan potongan yang mulai di tengah gambar."""
    fps, names = meta["fps"], meta["names"]
    assign_gates(tracks, gates, fps)
    # potongan = ujungnya tidak di gerbang, atau seluruhnya berada di satu gerbang saja
    def is_tail(t):
        return t.dest == UNKNOWN or t.dest == t.origin

    def is_head(t):
        return t.origin == UNKNOWN or t.dest == t.origin

    def single(t):
        return t.origin == t.dest != UNKNOWN

    def may_join(ta, tb):
        """Selain potongan dengan potongan: potongan yang seluruhnya di dalam satu gerbang boleh disambung
        ke lintasan lengkap yang berawal (atau berakhir) di gerbang itu. Gerbang yang luas membuat satu
        kendaraan yang lintasannya putus di dalam gerbang terhitung dua kali bila tidak disambung."""
        return ((is_tail(ta) and is_head(tb)) or (single(ta) and tb.origin == ta.origin)
                or (single(tb) and ta.dest == tb.origin))

    by_start = sorted(range(len(tracks)), key=lambda i: tracks[i].frames[0])
    starts = np.array([tracks[i].frames[0] for i in by_start])
    cands = []
    for a in range(len(tracks)):
        ta = tracks[a]
        lo, hi = np.searchsorted(starts, [ta.frames[-1] + 1, ta.frames[-1] + max_gap_s * fps + 1])
        heads = [b for b in by_start[lo:hi] if may_join(ta, tracks[b])]
        if not heads:
            continue
        k = ta.frames >= ta.frames[-1] - 0.8 * fps
        if k.sum() >= 2 and ta.frames[k][-1] > ta.frames[k][0]:
            vel = (ta.foot[k][-1] - ta.foot[k][0]) / (ta.frames[k][-1] - ta.frames[k][0])
        else:
            vel = np.zeros(2)
        size = float(np.hypot(*(ta.boxes[-1, 2:] - ta.boxes[-1, :2])))
        for b in heads:
            tb = tracks[b]
            gap = tb.frames[0] - ta.frames[-1]
            if a == b or gap <= 0 or gap > max_gap_s * fps or not _same_group(ta.label, tb.label, names):
                continue
            db = _direction(tb, fps, False)
            if np.linalg.norm(vel) > 0.5 and np.linalg.norm(db) > 2 and float(np.dot(vel, db)) <= 0:
                continue  # arah berlawanan: bukan kendaraan yang sama
            pred = ta.foot[-1] + vel * gap
            dist = float(np.linalg.norm(pred - tb.foot[0])) / max(size, 1.0)
            if dist <= 0.6 + 0.5 * gap / fps:
                cands.append((dist + 0.1 * gap / fps, a, b))
    nxt, used_b = {}, set()
    for _, a, b in sorted(cands):
        if a in nxt or b in used_b:
            continue
        nxt[a] = b
        used_b.add(b)
    out = []
    for i, t in enumerate(tracks):
        if i in used_b:
            continue
        chain = [t]
        j = i
        while j in nxt:
            j = nxt[j]
            chain.append(tracks[j])
        if len(chain) == 1:
            out.append(t)
        else:
            out.append(Track(
                sum((c.ids for c in chain), []), np.concatenate([c.frames for c in chain]),
                np.concatenate([c.boxes for c in chain]), np.concatenate([c.cls for c in chain]),
                np.concatenate([c.conf for c in chain]), stitched=len(chain) - 1,
            ))
    assign_gates(out, gates, fps)
    return out


def moving_tracks(raw: list[Track], meta: dict, min_obs: int = 5, min_move: float = 0.05,
                  min_seconds: float = 0.4) -> list[Track]:
    """Buang lintasan yang terlalu pendek dan kendaraan parkir (kotaknya bergetar tetapi posisi awal
    dan akhirnya hampir sama)."""
    return [
        t for t in raw
        if len(t.frames) >= min_obs and (t.frames[-1] - t.frames[0]) >= min_seconds * meta["fps"]
        and t.extent >= min_move * meta["width"]
        and np.linalg.norm(t.foot[-1] - t.foot[0]) >= 0.6 * min_move * meta["width"]
    ]


def analyze(npz_path: str | Path, project: dict, min_obs: int = 5, min_move: float = 0.05, do_stitch: bool = True,
            reach: float = 0.2, use_routes: bool = True, min_seconds: float = 0.4):
    """Kembalikan (meta, lintasan bergerak, ringkasan)."""
    from . import routes as R
    meta, raw = load_tracks(npz_path)
    gates = Gates(project, meta["width"], meta["height"])
    moving = moving_tracks(raw, meta, min_obs, min_move, min_seconds)
    assign_gates(moving, gates, meta["fps"])
    before = Counter("lengkap" if UNKNOWN not in (t.origin, t.dest) else "putus" for t in moving)
    tracks = stitch(moving, gates, meta) if do_stitch else moving
    assign_gates(tracks, gates, meta["fps"])
    n_direct = sum(R.is_complete(t) for t in tracks)
    n_merged = n_absorbed = 0
    route_set = R.build_routes(tracks) if use_routes else {}
    if route_set:
        R.route_match(tracks, meta, routes=route_set)
        tracks, n_merged = R.merge_fragments(tracks, meta)
        tracks, n_absorbed = R.absorb_leftovers(tracks, meta, route_set)
    else:
        # belum ada contoh jalur (data terlalu sedikit): pakai perpanjangan arah lurus, yang pada uji
        # potong-lintasan menetapkan lebih sedikit dan lebih sering salah daripada pencocokan jalur
        extrapolate(tracks, gates, meta["fps"], reach * meta["width"])
    summary = {
        "lintasan_mentah": len(raw),
        "diam_atau_terlalu_pendek": len(raw) - len(moving),
        "bergerak_sebelum_sambung": len(moving),
        "lengkap_sebelum_sambung": before["lengkap"],
        "bergerak_setelah_sambung": len(tracks),
        "lengkap_setelah_sambung": sum(UNKNOWN not in (t.origin, t.dest) and t.origin != t.dest for t in tracks),
        "gerbang_terbaca_langsung": n_direct,
        "lewat_pencocokan_jalur": sum(t.route for t in tracks),
        "di_antaranya_memakai_perkiraan_arah": sum(
            (t.origin_est or t.dest_est) and UNKNOWN not in (t.origin, t.dest) and t.origin != t.dest for t in tracks),
        "potongan_digabung_ke_kendaraan_lain": n_merged + n_absorbed,
        "asal_sama_dengan_tujuan": sum(t.origin == t.dest != UNKNOWN for t in tracks),
        "asal_tidak_terbaca": sum(t.origin == UNKNOWN and t.dest != UNKNOWN for t in tracks),
        "tujuan_tidak_terbaca": sum(t.origin != UNKNOWN and t.dest == UNKNOWN for t in tracks),
        "keduanya_tidak_terbaca": sum(t.origin == UNKNOWN and t.dest == UNKNOWN for t in tracks),
    }
    return meta, tracks, summary


def track_class(t: Track, meta: dict, project: dict) -> str:
    """Kelas PKJI satu kendaraan: dari pengklasifikasi bila ada (jumlah peluang semua potongannya),
    selain itu dari kelas bawaan detektor lewat `peta_kelas` proyek."""
    if meta.get("kelas"):
        names, probs = meta["kelas"]
        total = sum((probs[i] for i in t.ids if i in probs), np.zeros(len(names)))
        if total.sum() > 0:
            return names[int(total.argmax())]
    coco = meta["names"][t.label]
    return project.get("peta_kelas", {}).get(coco, DEFAULT_CLASS_MAP.get(coco, coco))


def count_table(tracks: list[Track], meta: dict, project: dict, interval_min: int = 5) -> dict:
    """{(mulai_interval, gerakan, kelas): jumlah}. Waktu = saat kendaraan pertama terlihat."""
    start = meta["start"] or datetime(2000, 1, 1)
    out = Counter()
    for t in tracks:
        ts = start + timedelta(seconds=float(t.frames[0]) / meta["fps"])
        bucket = ts.replace(minute=ts.minute - ts.minute % interval_min, second=0, microsecond=0)
        out[(bucket, t.movement, track_class(t, meta, project))] += 1
    return dict(out)


def movement_matrix(tracks: list[Track], meta: dict, project: dict) -> dict:
    out = defaultdict(Counter)
    for t in tracks:
        out[t.movement][track_class(t, meta, project)] += 1
    return out


def _palette(keys: list[str]) -> dict[str, tuple[int, int, int]]:
    """Satu warna berbeda per gerakan."""
    out = {}
    for i, k in enumerate(sorted(keys)):
        hue = int(180 * i / max(len(keys), 1))
        out[k] = tuple(int(v) for v in cv2.cvtColor(np.uint8([[[hue, 230, 255]]]), cv2.COLOR_HSV2BGR)[0, 0])
    return out


def audit_image(tracks: list[Track], meta: dict, project: dict, out_path: str | Path):
    """Gambar semua lintasan di atas frame pertama; warna = gerakan, abu-abu = tidak teridentifikasi."""
    cap = cv2.VideoCapture(meta["video"])
    ok, bg = cap.read()
    cap.release()
    canvas = (bg * 0.4).astype(np.uint8)
    gates = Gates(project, meta["width"], meta["height"])
    th = max(2, meta["width"] // 900)
    for name, poly in zip(gates.names, gates.polys):
        cv2.polylines(canvas, [poly.astype(np.int32)], True, (255, 255, 255), th)
        x, y = poly.astype(int).min(0)
        cv2.putText(canvas, name, (x + 6, y + 14 * th), cv2.FONT_HERSHEY_SIMPLEX, 0.5 * th, (255, 255, 255), th)
    def valid(t):
        return UNKNOWN not in (t.origin, t.dest) and t.origin != t.dest

    seen = Counter(t.movement for t in tracks if valid(t))
    colors = _palette(list(seen))
    for t in tracks:
        ok_mv = valid(t)
        color = colors[t.movement] if ok_mv else (150, 150, 150)
        cv2.polylines(canvas, [t.foot.astype(np.int32)], False, color, th if ok_mv else 1, cv2.LINE_AA)
    y = 60 * th
    for mv, n in seen.most_common():
        cv2.putText(canvas, f"{mv}: {n}", (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5 * th, colors[mv], th)
        y += 18 * th
    cv2.putText(canvas, f"tidak teridentifikasi (abu-abu): {len(tracks) - sum(seen.values())}", (20, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5 * th, (190, 190, 190), th)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), canvas)


def load_project(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))  # -sig: berkas yang disimpan Notepad punya BOM
