"""Penyebaran kendaraan yang gerakannya tidak teridentifikasi, supaya arus kekal:
jumlah kendaraan masuk simpang = jumlah kendaraan keluar simpang.

Setiap kendaraan tetap memakai kelas PKJI hasil klasifikasinya. Yang disebar hanya gerakannya, sesuai
proporsi gerakan kendaraan yang teridentifikasi pada kelas yang sama:

- asal terbaca, tujuan tidak (A -> ?)    : ke gerakan dari A
- asal tidak, tujuan terbaca (? -> B)    : ke gerakan menuju B
- satu gerbang saja (A -> A)             : ke gerakan dari atau menuju A
- keduanya tidak terbaca (? -> ?)        : ke semua gerakan

Proporsi diambil dari jam yang sama pada hari yang sama. Kalau pada jam itu tidak ada kendaraan kelas
tersebut, dipakai proporsi kelas tersebut sepanjang hari; kalau tetap tidak ada, proporsi semua kelas
pada jam itu, lalu sepanjang hari, dan terakhir dibagi rata.

Hasilnya bilangan bulat per selang 5 menit. Pembulatan memakai selisih kumulatif sepanjang hari, jadi
jumlah kendaraan selalu tepat dan pembagian tidak condong ke gerakan terbesar.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta

from .movements import UNKNOWN
from .validate import movements_of

KINDS = {"asal": "asal terbaca, tujuan tidak", "tujuan": "tujuan terbaca, asal tidak",
         "satu": "hanya satu gerbang terbaca", "semua": "asal dan tujuan tidak terbaca"}


# Lintasan yang hanya menyentuh satu gerbang dibuang, tidak disebar (keputusan pengguna 2026-11-18): pada
# validasi malam Rajekwesi sebagian besar adalah potongan kendaraan yang sudah terhitung di dekat kamera.
# Menyebar semua jenis: +6,7% dan GEH<5 4/12; tanpa satu-gerbang: -4,1% dan 6/12. Ubah per simpang lewat
# "sebar_jenis" di berkas proyek.
DEFAULT_KINDS = ["asal", "tujuan", "semua"]


def _bin5(t: datetime) -> datetime:
    return t.replace(minute=t.minute - t.minute % 5, second=0, microsecond=0)


def classify(a: str, b: str, valid: set[str]) -> tuple[str, str | None]:
    """('dikenal', None) untuk gerakan sah; selain itu jenis ketidakpastian dan gerbang yang terbaca."""
    if a != UNKNOWN and b != UNKNOWN and a != b:
        return ("dikenal", None) if f"{a}->{b}" in valid else ("semua", None)
    if a != UNKNOWN and b == UNKNOWN:
        return "asal", a
    if a == UNKNOWN and b != UNKNOWN:
        return "tujuan", b
    if a == b != UNKNOWN:
        return "satu", a
    return "semua", None


def candidates(kind: str, gate: str | None, mvs: list[str]) -> list[str]:
    if kind == "asal":
        c = [m for m in mvs if m.split("->")[0] == gate]
    elif kind == "tujuan":
        c = [m for m in mvs if m.split("->")[1] == gate]
    elif kind == "satu":
        c = [m for m in mvs if gate in m.split("->")]
    else:
        c = list(mvs)
    return c or list(mvs)


def distribute(veh: list[tuple], project: dict, kinds=None) -> tuple[Counter, dict]:
    """veh: [(waktu, asal, tujuan, kelas)]. Mengembalikan ({(selang_5_menit, gerakan, kelas): jumlah}, ringkasan).
    `kinds`: jenis yang disebar (bawaan: `sebar_jenis` di proyek, atau semua jenis). Jenis lain dibuang (tidak
    dihitung sama sekali), sehingga arus tetap kekal."""
    kinds = set(kinds if kinds is not None else project.get("sebar_jenis", DEFAULT_KINDS))
    mvs = [f"{o}->{d}" for o, d in movements_of(project)]
    valid = set(mvs)
    counts = Counter()
    by_hour_k, by_day_k, by_hour, by_day = Counter(), Counter(), Counter(), Counter()
    pending = defaultdict(Counter)        # (tanggal, jenis, gerbang, kelas) -> {selang: n}
    stats = Counter()
    for t, a, b, k in veh:
        kind, gate = classify(a, b, valid)
        if kind != "dikenal" and kind not in kinds:
            stats["dibuang_" + kind] += 1
            continue
        stats[kind] += 1
        if kind == "dikenal":
            mv = f"{a}->{b}"
            counts[(_bin5(t), mv, k)] += 1
            h = t.replace(minute=0, second=0, microsecond=0)
            by_hour_k[(h, mv, k)] += 1
            by_day_k[(t.date(), mv, k)] += 1
            by_hour[(h, mv)] += 1
            by_day[(t.date(), mv)] += 1
        else:
            pending[(t.date(), kind, gate, k)][_bin5(t)] += 1

    def shares(cands, hour, day, k):
        for table, key in ((by_hour_k, lambda m: (hour, m, k)), (by_day_k, lambda m: (day, m, k)),
                           (by_hour, lambda m: (hour, m)), (by_day, lambda m: (day, m))):
            w = [table[key(m)] for m in cands]
            if sum(w):
                s = sum(w)
                return [x / s for x in w]
        return [1 / len(cands)] * len(cands)

    added = Counter()
    for (day, kind, gate, k), bins in pending.items():
        cands = candidates(kind, gate, mvs)
        target = [0.0] * len(cands)       # jumlah seharusnya (pecahan), kumulatif sepanjang hari
        given = [0] * len(cands)
        for b in sorted(bins):
            p = shares(cands, b.replace(minute=0), day, k)
            n = bins[b]
            target = [x + n * q for x, q in zip(target, p)]
            for _ in range(n):            # satu per satu ke gerakan yang paling "berutang"
                i = max(range(len(cands)), key=lambda j: (target[j] - given[j], p[j]))
                given[i] += 1
                counts[(b, cands[i], k)] += 1
                added[(day, kind)] += 1
    summary = {
        "dikenal": stats["dikenal"],
        "disebar": {kind: stats[kind] for kind in KINDS if stats[kind]},
        "dibuang": {kind: stats["dibuang_" + kind] for kind in KINDS if stats["dibuang_" + kind]},
        "total": sum(v for key, v in stats.items() if not key.startswith("dibuang_")),
        "per_hari": {d: {kind: added[(d, kind)] for kind in KINDS if added[(d, kind)]} for d in sorted({d for d, _ in added})},
    }
    return counts, summary


def as_vehicles(counts: Counter) -> list[dict]:
    """Bentuk daftar kendaraan untuk rekap LHR/jam puncak (waktu = awal selang 5 menit)."""
    out = []
    for (b, mv, k), n in counts.items():
        a, d = mv.split("->")
        out += [{"waktu": b, "asal": a, "tujuan": d, "kelas": k}] * n
    return out
