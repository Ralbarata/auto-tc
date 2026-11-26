"""Rekap LHR (volume sehari) dan jam puncak dari berkas lintasan satu simpang.

Volume lengan = kendaraan yang MASUK simpang dari lengan itu. Kendaraan yang asalnya terbaca tetapi
tujuannya tidak tetap dihitung di lengan asalnya; yang asalnya tidak terbaca dilaporkan terpisah.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .labels import CLASSES, MOTORIZED
from .movements import UNKNOWN, analyze, track_class

BIN = 15  # menit


def vehicles(npz_paths: list, project: dict) -> tuple[list[dict], list[tuple[datetime, datetime]]]:
    """Daftar kendaraan [{waktu, asal, tujuan, kelas}] dan rentang waktu yang tercakup tiap berkas."""
    out, coverage = [], []
    for npz in npz_paths:
        meta, tracks, _ = analyze(npz, project)
        if not meta["start"]:
            raise SystemExit(f"Jam mulai tidak terbaca untuk {npz}.")
        coverage.append((meta["start"], meta["start"] + timedelta(seconds=meta["seconds"])))
        for t in tracks:
            if t.origin == t.dest:
                continue   # putar balik atau potongan di dalam satu gerbang; juga asal dan tujuan sama-sama tak terbaca
            out.append({"waktu": meta["start"] + timedelta(seconds=float(t.frames[0]) / meta["fps"]),
                        "asal": t.origin, "tujuan": t.dest, "kelas": track_class(t, meta, project)})
    return out, sorted(coverage)


def _bin(ts: datetime) -> datetime:
    return ts.replace(minute=ts.minute - ts.minute % BIN, second=0, microsecond=0)


def _covered_minutes(coverage, start: datetime, minutes: int) -> float:
    end = start + timedelta(minutes=minutes)
    return sum(max((min(end, b) - max(start, a)).total_seconds(), 0.0) for a, b in coverage) / 60


def summarize(veh: list[dict], coverage: list, project: dict) -> dict:
    arms = [g["nama"] for g in project["gerbang"]]
    known = [v for v in veh if v["asal"] != UNKNOWN]
    t0, t1 = _bin(coverage[0][0]), coverage[-1][1]
    bins = []
    b = t0
    while b < t1:
        bins.append(b)
        b += timedelta(minutes=BIN)
    per_bin = Counter((_bin(v["waktu"]), v["asal"], v["kelas"]) for v in known)

    def vol(start, n_bins, arm=None, cls=None, motor_only=True):
        keys = [start + timedelta(minutes=BIN * i) for i in range(n_bins)]
        return sum(n for (bb, a, c), n in per_bin.items()
                   if bb in keys and (arm is None or a == arm) and (cls is None or c == cls)
                   and (not motor_only or c in MOTORIZED))

    # jam puncak: 4 selang 15 menit berurutan dengan volume bermotor tertinggi, hanya jam yang videonya utuh
    def peak(arm=None, lo=None, hi=None):
        best = None
        for b in bins:
            if lo is not None and not (lo <= b.hour and b.hour + b.minute / 60 + 1 <= hi):
                continue
            if _covered_minutes(coverage, b, 60) < 59:
                continue
            v = vol(b, 4, arm)
            if best is None or v > best["volume"]:
                q = [vol(b + timedelta(minutes=BIN * i), 1, arm) for i in range(4)]
                best = {"mulai": b, "volume": v, "per_15": q, "phf": round(v / (4 * max(q)), 3) if max(q) else None,
                        "kelas": {c: vol(b, 4, arm, c, False) for c in CLASSES}}
        return best

    hours = sorted({b.replace(minute=0) for b in bins})
    return {
        "arms": arms, "bins": bins, "hours": hours, "coverage": coverage,
        "menit_tercakup": round(sum((b - a).total_seconds() for a, b in coverage) / 60, 1),
        "lhr": {a: {c: sum(1 for v in known if v["asal"] == a and v["kelas"] == c) for c in CLASSES} for a in arms},
        "keluar": {a: {c: sum(1 for v in veh if v["tujuan"] == a and v["kelas"] == c) for c in CLASSES} for a in arms},
        "per_jam": {h: {a: {c: vol(h, 4, a, c, False) for c in CLASSES} for a in arms} for h in hours},
        "tercakup_per_jam": {h: round(_covered_minutes(coverage, h, 60), 1) for h in hours},
        "puncak": {"simpang": peak(), "pagi": peak(lo=5, hi=11), "siang": peak(lo=11, hi=15), "sore": peak(lo=15, hi=21),
                   **{f"lengan {a}": peak(a) for a in arms}},
        "gerakan": Counter((f"{v['asal']}->{v['tujuan']}", v["kelas"]) for v in known if v["tujuan"] != UNKNOWN),
        "tanpa_tujuan": sum(v["tujuan"] == UNKNOWN for v in known),
        "tanpa_asal": sum(v["asal"] == UNKNOWN for v in veh),
        "total": len(known),
    }


HEAD = PatternFill("solid", fgColor="DDEBF7")


def _table(ws, row: int, header: list, rows: list) -> int:
    for j, h in enumerate(header, 1):
        c = ws.cell(row, j, h)
        c.font, c.fill, c.alignment = Font(bold=True), HEAD, Alignment(horizontal="center", wrap_text=True)
    for i, r in enumerate(rows, 1):
        for j, v in enumerate(r, 1):
            ws.cell(row + i, j, v)
    return row + len(rows) + 2


def add_sheets(wb, s: dict, project: dict, prefix: str = "", index: int | None = None) -> int:
    """Tambahkan sheet LHR, JAM PUNCAK, PER JAM, GERAKAN ke `wb` (mulai di posisi `index`).
    Mengembalikan posisi sesudah sheet terakhir."""
    made = []

    def sheet(name):
        ws = wb.create_sheet((prefix + name)[:31], None if index is None else index + len(made))
        made.append(ws)
        return ws

    ws = sheet("LHR")
    c0, c1 = s["coverage"][0][0], s["coverage"][-1][1]
    ws["A1"] = f"Rekap volume lalu lintas - Simpang {project.get('nama', '')}"
    ws["A1"].font = Font(bold=True, size=13)
    ws["A2"] = f"Rentang rekaman: {c0:%d-%m-%Y %H:%M} s.d. {c1:%d-%m-%Y %H:%M} ({s['menit_tercakup'] / 60:.1f} jam video)"
    ws["A3"] = ("Volume lengan = kendaraan yang masuk simpang dari lengan itu, hasil hitungan program (belum dikoreksi). "
                f"Tidak termasuk {s['tanpa_asal']} kendaraan yang lengan asalnya tidak terbaca.")
    row = _table(ws, 5, ["Lengan (masuk)", *CLASSES, "Total bermotor", "Total"], [
        [a, *[s["lhr"][a][c] for c in CLASSES], sum(s["lhr"][a][c] for c in MOTORIZED), sum(s["lhr"][a].values())]
        for a in s["arms"]] + [["SIMPANG", *[sum(s["lhr"][a][c] for a in s["arms"]) for c in CLASSES],
                                sum(s["lhr"][a][c] for a in s["arms"] for c in MOTORIZED),
                                sum(sum(s["lhr"][a].values()) for a in s["arms"])]])
    row = _table(ws, row, ["Lengan (keluar)", *CLASSES, "Total bermotor", "Total"], [
        [a, *[s["keluar"][a][c] for c in CLASSES], sum(s["keluar"][a][c] for c in MOTORIZED), sum(s["keluar"][a].values())]
        for a in s["arms"]])
    ws.cell(row, 1, f"Kendaraan dengan lengan asal terbaca tetapi tujuan tidak terbaca: {s['tanpa_tujuan']} "
                    "(dihitung di lengan masuk, tidak di lengan keluar maupun gerakan).")

    ws = sheet("JAM PUNCAK")
    rows = []
    for name, p in s["puncak"].items():
        if p:
            rows.append([name, f"{p['mulai']:%d-%m %H:%M} - {p['mulai'] + timedelta(hours=1):%H:%M}", p["volume"],
                         *p["per_15"], p["phf"], *[p["kelas"][c] for c in CLASSES]])
    _table(ws, 1, ["Cakupan", "Jam puncak", "Volume bermotor (kend/jam)", "15' ke-1", "15' ke-2", "15' ke-3", "15' ke-4",
                   "PHF", *CLASSES], rows)
    ws.cell(len(rows) + 3, 1, "Jam puncak = 60 menit berurutan (langkah 15 menit) dengan volume kendaraan bermotor masuk "
                              "tertinggi; pagi 05-11, siang 11-15, sore 15-21. Hanya jam yang rekamannya utuh.")

    ws = sheet("PER JAM")
    header = ["Jam", "Menit video", *[f"{a} {c}" for a in s["arms"] for c in MOTORIZED], *[f"Total {a}" for a in s["arms"]],
              "Total simpang (bermotor)"]
    rows = []
    for h in s["hours"]:
        d = s["per_jam"][h]
        tot = [sum(d[a][c] for c in MOTORIZED) for a in s["arms"]]
        rows.append([f"{h:%d-%m %H:%M}", s["tercakup_per_jam"][h], *[d[a][c] for a in s["arms"] for c in MOTORIZED], *tot, sum(tot)])
    _table(ws, 1, header, rows)

    ws = sheet("GERAKAN")
    mvs = [f"{a}->{b}" for a in s["arms"] for b in s["arms"] if a != b]
    _table(ws, 1, ["Gerakan", *CLASSES, "Total"], [
        [mv, *[s["gerakan"][(mv, c)] for c in CLASSES], sum(s["gerakan"][(mv, c)] for c in CLASSES)] for mv in mvs])
    for ws in made:
        ws.column_dimensions["A"].width = 26
        for j in range(2, ws.max_column + 1):
            ws.column_dimensions[get_column_letter(j)].width = 13
    return (len(wb.sheetnames) if index is None else index + len(made))


def write_excel(s: dict, project: dict, out_path: str | Path) -> str:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    add_sheets(wb, s, project)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    return str(out_path)


def format_summary(s: dict) -> str:
    lines = [f"video tercakup {s['menit_tercakup'] / 60:.1f} jam | kendaraan masuk {s['total']} | "
             f"tanpa tujuan {s['tanpa_tujuan']} | tanpa asal {s['tanpa_asal']}"]
    for a in s["arms"]:
        lines.append(f"  {a:<10} " + " ".join(f"{c} {s['lhr'][a][c]:>6}" for c in CLASSES))
    for name, p in s["puncak"].items():
        if p:
            lines.append(f"  puncak {name:<16} {p['mulai']:%d-%m %H:%M}  {p['volume']} kend/jam  PHF {p['phf']}")
    return "\n".join(lines)
