"""Pencocokan potongan lintasan ke jalur khas tiap gerakan.

Lintasan yang lengkap (gerbang asal dan tujuan terbaca langsung) menjadi contoh jalur.
Potongan yang tidak lengkap ditetapkan ke gerakan yang jalurnya paling mirip, asalkan
jelas lebih mirip daripada gerakan lain. Potongan yang hanya melewati bagian jalur yang
dipakai bersama beberapa gerakan sengaja dibiarkan tidak teridentifikasi.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np

from .labels import TWO_WHEELERS
from .movements import UNKNOWN, Track, _same_group

K_ROUTE, K_FRAG = 40, 12


def resample(pts: np.ndarray, k: int) -> np.ndarray:
    """k titik berjarak sama di sepanjang lintasan."""
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    if s[-1] <= 0:
        return np.repeat(pts[:1], k, axis=0)
    u = np.linspace(0, s[-1], k)
    return np.column_stack([np.interp(u, s, pts[:, 0]), np.interp(u, s, pts[:, 1])])


def car_scale(t: Track, names: list[str]) -> float:
    """Perkiraan ukuran satu mobil (piksel) di posisi lintasan ini, sebagai satuan jarak yang ikut perspektif."""
    diag = float(np.median(np.hypot(t.boxes[:, 2] - t.boxes[:, 0], t.boxes[:, 3] - t.boxes[:, 1])))
    name = names[t.label]
    return max(diag * (1.8 if name in TWO_WHEELERS else 0.75 if name in ("truck", "bus") else 1.0), 1.0)


def is_complete(t: Track) -> bool:
    return UNKNOWN not in (t.origin, t.dest) and t.origin != t.dest


def build_routes(tracks: list[Track], max_per: int = 25, min_obs: int = 10) -> dict[str, np.ndarray]:
    """{gerakan: (n, K_ROUTE, 2)} dari lintasan yang gerbangnya terbaca langsung."""
    groups = defaultdict(list)
    for t in tracks:
        if is_complete(t) and not t.route and not (t.origin_est or t.dest_est) and len(t.frames) >= min_obs:
            groups[t.movement].append(t)
    routes = {}
    for mv, ts in groups.items():
        pick = ts if len(ts) <= max_per else [ts[i] for i in np.linspace(0, len(ts) - 1, max_per).astype(int)]
        routes[mv] = np.stack([resample(t.foot, K_ROUTE) for t in pick])
    return routes


def route_distance(frag: np.ndarray, scale: float, exemplars: np.ndarray) -> tuple[float, float, float]:
    """(jarak, posisi awal, posisi akhir) potongan terhadap satu gerakan; posisi 0-1 di sepanjang jalur.

    Jarak = rata-rata jarak titik potongan ke jalur, dalam satuan ukuran mobil, diambil dari 3 contoh terdekat.
    Contoh jalur yang arahnya berlawanan dengan potongan tidak dipakai.
    """
    d = np.linalg.norm(frag[None, :, None, :] - exemplars[:, None, :, :], axis=3)  # (n, K_FRAG, K_ROUTE)
    idx = d.argmin(axis=2)
    dist = d.min(axis=2).mean(axis=1) / scale
    i0, i1 = idx[:, 0], idx[:, -1]
    dist[i1 <= i0] = np.inf
    order = np.argsort(dist)[:3]
    good = order[np.isfinite(dist[order])]
    if not len(good):
        return np.inf, 0.0, 0.0
    return float(dist[good].mean()), i0[good[0]] / (K_ROUTE - 1), i1[good[0]] / (K_ROUTE - 1)


def best_movement(t: Track, routes: dict, names: list[str], allowed=None) -> tuple[str | None, float, float, float, float]:
    """(gerakan terbaik, jarak terbaik, jarak terbaik kedua, s0, s1)."""
    frag, scale = resample(t.foot, K_FRAG), car_scale(t, names)
    scored = []
    for mv, ex in routes.items():
        if allowed is None or mv in allowed:
            dist, s0, s1 = route_distance(frag, scale, ex)
            scored.append((dist, mv, s0, s1))
    scored.sort()
    if not scored or not np.isfinite(scored[0][0]):
        return None, np.inf, np.inf, 0.0, 0.0
    second = scored[1][0] if len(scored) > 1 else np.inf
    return scored[0][1], scored[0][0], second, scored[0][2], scored[0][3]


def _allowed(t: Track, routes: dict) -> set[str]:
    """Gerakan yang masih mungkin, mengingat ujung yang gerbangnya sudah terbaca langsung."""
    out = set()
    for mv in routes:
        o, d = mv.split("->")
        if t.origin == t.dest != UNKNOWN:      # seluruhnya di dalam satu gerbang: gerbang itu asal ATAU tujuannya
            if t.origin in (o, d):
                out.add(mv)
        elif (t.origin in (UNKNOWN, o)) and (t.dest in (UNKNOWN, d)):
            out.add(mv)
    return out


def route_match(tracks: list[Track], meta: dict, accept: float = 0.6, ratio: float = 0.6, min_obs: int = 8,
                routes: dict | None = None, min_cover_in_gate: float = 0.3) -> int:
    """Tetapkan gerakan untuk potongan yang tidak lengkap. Mengembalikan jumlah yang berhasil ditetapkan."""
    routes = routes if routes is not None else build_routes(tracks)
    n = 0
    for t in tracks:
        if is_complete(t) or len(t.frames) < min_obs:
            continue
        mv, d1, d2, s0, s1 = best_movement(t, routes, meta["names"], _allowed(t, routes))
        # potongan yang seluruhnya di dalam satu gerbang biasanya sisa pendek dari kendaraan yang lintasan
        # utamanya sudah terhitung; hanya diterima jika menempuh bagian jalur yang cukup panjang
        if t.origin == t.dest != UNKNOWN and s1 - s0 < min_cover_in_gate:
            continue
        if mv and d1 <= accept and d1 <= ratio * d2:
            t.origin, t.dest = mv.split("->")
            t.route, t.s0, t.s1 = True, s0, s1
            n += 1
    return n


def _follows(a: Track, b: Track, b_s0: float, fps: float, names: list[str], max_gap_s: float) -> bool:
    """Apakah b masuk akal sebagai lanjutan a di jalur yang sama (posisi lebih maju, waktu tempuh wajar)."""
    gap = (b.frames[0] - a.frames[-1]) / fps
    if gap <= 0 or gap > max_gap_s or b_s0 < a.s1 - 0.05 or not _same_group(a.label, b.label, names):
        return False
    dur = (a.frames[-1] - a.frames[0]) / fps
    speed = (a.s1 - a.s0) / dur if dur > 0 else 0.0
    if speed <= 0:
        return gap <= 3.0
    expected = max(b_s0 - a.s1, 0.0) / speed
    return 0.4 * expected - 1.0 <= gap <= 2.5 * expected + 2.0


def _join(a: Track, b: Track) -> Track:
    t = Track(a.ids + b.ids, np.concatenate([a.frames, b.frames]), np.concatenate([a.boxes, b.boxes]),
              np.concatenate([a.cls, b.cls]), np.concatenate([a.conf, b.conf]),
              origin=a.origin, dest=a.dest, stitched=a.stitched + b.stitched + 1)
    t.route, t.s0, t.s1 = True, a.s0, b.s1
    return t


def merge_fragments(tracks: list[Track], meta: dict, max_gap_s: float = 12.0) -> tuple[list[Track], int]:
    """Gabungkan potongan-potongan satu kendaraan yang ditetapkan ke gerakan yang sama, supaya tidak terhitung dua kali."""
    fps, names = meta["fps"], meta["names"]
    order = sorted(range(len(tracks)), key=lambda i: tracks[i].frames[0])
    used, out, merged = set(), [], 0
    for i in order:
        if i in used:
            continue
        cur = tracks[i]
        if cur.route:
            while True:
                nxt = next((j for j in order if j not in used and j != i and tracks[j].route
                            and tracks[j].movement == cur.movement
                            and _follows(cur, tracks[j], tracks[j].s0, fps, names, max_gap_s)), None)
                if nxt is None:
                    break
                cur = _join(cur, tracks[nxt])
                used.add(nxt)
                merged += 1
        used.add(i)
        out.append(cur)
    return out, merged


def absorb_leftovers(tracks: list[Track], meta: dict, routes: dict, accept: float = 0.6,
                     max_gap_s: float = 12.0) -> tuple[list[Track], int]:
    """Potongan yang gerakannya ambigu tetapi cocok sebagai awal/akhir kendaraan yang sudah ditetapkan
    lewat jalur: gabungkan ke kendaraan itu (bukan kendaraan tersendiri)."""
    fps, names = meta["fps"], meta["names"]
    counted = [t for t in tracks if t.route]
    gone, absorbed = set(), 0
    for u in tracks:
        if is_complete(u) or u.origin == u.dest != UNKNOWN or len(u.frames) < 5:
            continue
        frag, scale = resample(u.foot, K_FRAG), car_scale(u, names)
        for k, c in enumerate(counted):
            if id(c) in gone or c.movement not in routes:
                continue
            if u.origin not in (UNKNOWN, c.origin) or u.dest not in (UNKNOWN, c.dest):
                continue
            dist, s0, s1 = route_distance(frag, scale, routes[c.movement])
            if dist > accept:
                continue
            u.s0, u.s1 = s0, s1
            if _follows(u, c, c.s0, fps, names, max_gap_s):        # u adalah bagian awal c
                u.origin, u.dest = c.origin, c.dest
                new = _join(u, c)
            elif _follows(c, u, s0, fps, names, max_gap_s):        # u adalah bagian akhir c
                new = _join(c, u)
            else:
                continue
            gone.update((id(u), id(c)))
            counted[k] = new
            tracks = [new if t is c else t for t in tracks]
            absorbed += 1
            break
    return [t for t in tracks if id(t) not in gone], absorbed
