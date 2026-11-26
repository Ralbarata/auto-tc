"""Validasi: bandingkan hitungan program dengan hitung manual pada rentang waktu yang sama.

Alur: buat form manual (satu baris per gerakan, kolom per kelas) -> diisi penghitung ->
bandingkan dengan lintasan program untuk rentang waktu yang tertulis di form.
Rentang panjang (mis. satu jam) bisa dipecah menjadi beberapa sheet, mis. per 15 menit.
"""
from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .labels import CLASSES
from .movements import UNKNOWN, analyze, track_class

HEAD_ROW, FIRST_ROW = 7, 8
FIRST_COL = 3                           # kolom kelas pertama (C)
TOTAL_COL = FIRST_COL + len(CLASSES)
BOLD = Font(bold=True)


def movements_of(project: dict) -> list[tuple[str, str]]:
    # tanpa gerbang (hitung manual saja), nama lengan diambil dari daftar "lengan" di proyek
    gates = [g["nama"] for g in project.get("gerbang", [])] or list(project.get("lengan", []))
    skip = {tuple(m) for m in project.get("gerakan_tidak_ada", [])}
    return [(o, d) for o in gates for d in gates if o != d and (o, d) not in skip]


def _fill_sheet(ws, project: dict, start: datetime, minutes: int, video: str):
    ws["A1"] = f"HITUNG MANUAL - SIMPANG {project['nama'].upper()}"
    ws["A1"].font = Font(bold=True, size=14)
    for r, (k, v) in enumerate([("Mulai", start.strftime("%Y-%m-%d %H:%M:%S")), ("Durasi (menit)", minutes),
                                ("Video", video), ("Penghitung", "")], start=2):
        ws.cell(r, 1, k).font = BOLD
        ws.cell(r, 2, v)
    for c, h in enumerate(["Asal", "Tujuan", *CLASSES, "Total"], start=1):
        cell = ws.cell(HEAD_ROW, c, h)
        cell.font, cell.fill = BOLD, PatternFill("solid", fgColor="D9E1F2")
        cell.alignment = Alignment(horizontal="center")
    first, last = get_column_letter(FIRST_COL), get_column_letter(TOTAL_COL - 1)
    r = FIRST_ROW
    for o, d in movements_of(project):
        ws.cell(r, 1, o)
        ws.cell(r, 2, d)
        ws.cell(r, TOTAL_COL, f"=SUM({first}{r}:{last}{r})")
        r += 1
    ws.cell(r, 1, "TOTAL").font = BOLD
    for c in range(FIRST_COL, TOTAL_COL + 1):
        col = get_column_letter(c)
        ws.cell(r, c, f"=SUM({col}{FIRST_ROW}:{col}{r - 1})").font = BOLD
    ws.cell(r + 2, 1, "Isi jumlah kendaraan per gerakan dan kelas. Kendaraan dihitung pada rentang saat ia "
                      "pertama kali terlihat masuk simpang. Sel kosong dianggap 0. KTB = kendaraan tak bermotor.")
    ws.column_dimensions["A"].width = 18
    ws.column_dimensions["B"].width = 26


def make_form(project: dict, out_path: str | Path, start: datetime, minutes: int, video: str = "",
              interval: int | None = None) -> Path:
    """Satu sheet MANUAL, atau beberapa sheet "MANUAL 1", "MANUAL 2", ... jika `interval` (menit) diisi."""
    wb = openpyxl.Workbook()
    if not interval or interval >= minutes:
        ws = wb.active
        ws.title = "MANUAL"
        _fill_sheet(ws, project, start, minutes, video)
    else:
        wb.remove(wb.active)
        t, i = start, 1
        while t < start + timedelta(minutes=minutes):
            length = min(interval, int((start + timedelta(minutes=minutes) - t).total_seconds() // 60))
            _fill_sheet(wb.create_sheet(f"MANUAL {i}"), project, t, length, video)
            t += timedelta(minutes=interval)
            i += 1
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    return out_path


def read_form(path: str | Path) -> list[dict]:
    """Daftar rentang: {"sheet", "mulai", "menit", "manual": {(gerakan, kelas): n}, "terisi": bool}."""
    wb = openpyxl.load_workbook(path, data_only=True)
    out = []
    for name in wb.sheetnames:
        if not name.startswith("MANUAL"):
            continue
        ws = wb[name]
        start = ws["B2"].value
        start = start if isinstance(start, datetime) else datetime.strptime(str(start).strip(), "%Y-%m-%d %H:%M:%S")
        manual, filled = Counter(), False
        r = FIRST_ROW
        while ws.cell(r, 1).value and ws.cell(r, 1).value != "TOTAL":
            mv = f"{ws.cell(r, 1).value}->{ws.cell(r, 2).value}"
            for i, c in enumerate(CLASSES):
                v = ws.cell(r, FIRST_COL + i).value
                filled = filled or v not in (None, "")
                manual[(mv, c)] += int(v) if v not in (None, "") else 0
            r += 1
        out.append({"sheet": name, "mulai": start, "menit": int(ws["B3"].value), "manual": dict(manual), "terisi": filled})
    return out


def load_program(npz_paths: list, project: dict) -> list:
    loaded = []
    for npz in npz_paths:
        meta, tracks, _ = analyze(npz, project)
        if not meta["start"]:
            raise SystemExit(f"Jam mulai tidak terbaca untuk {npz}.")
        loaded.append((meta, tracks))
    return loaded


def program_counts(loaded: list, project: dict, start: datetime, minutes: int) -> tuple[dict, int, float]:
    """({(gerakan, kelas): jumlah}, tidak teridentifikasi, menit video yang tercakup di dalam rentang)."""
    end = start + timedelta(minutes=minutes)
    counts, unknown, covered = Counter(), 0, 0.0
    for meta, tracks in loaded:
        v0, v1 = meta["start"], meta["start"] + timedelta(seconds=meta["seconds"])
        covered += max((min(end, v1) - max(start, v0)).total_seconds(), 0.0) / 60
        for t in tracks:
            when = meta["start"] + timedelta(seconds=float(t.frames[0]) / meta["fps"])
            if not (start <= when < end):
                continue
            if UNKNOWN in (t.origin, t.dest) or t.origin == t.dest:
                unknown += 1
            else:
                counts[(t.movement, track_class(t, meta, project))] += 1
    return dict(counts), unknown, covered


def geh(m: float, c: float, minutes: float) -> float:
    """Statistik GEH pada volume setara per jam; di bawah 5 umumnya dianggap cocok untuk pemodelan."""
    if minutes <= 0:
        return 0.0
    m, c = m * 60 / minutes, c * 60 / minutes
    return math.sqrt(2 * (m - c) ** 2 / (m + c)) if m + c else 0.0


def _pct(p: int, m: int):
    return round(100 * (p - m) / m, 1) if m else None


def compare(project: dict, form_path: str | Path, npz_paths: list, out_path: str | Path | None = None) -> dict:
    """Bandingkan semua sheet MANUAL yang sudah diisi. Sheet yang masih kosong dilewati."""
    windows = [w for w in read_form(form_path) if w["terisi"]]
    if not windows:
        raise SystemExit("Form belum diisi: tidak ada angka di sheet MANUAL mana pun.")
    loaded = load_program(npz_paths, project)
    mvs = [f"{o}->{d}" for o, d in movements_of(project)]
    manual, program, unknown, covered, minutes, per_window = Counter(), Counter(), 0, 0.0, 0, []
    for w in windows:
        prog, unk, cov = program_counts(loaded, project, w["mulai"], w["menit"])
        tm, tp = sum(w["manual"].values()), sum(prog.values())
        per_window.append({"sheet": w["sheet"], "mulai": w["mulai"].strftime("%H:%M"), "menit": w["menit"],
                           "tercakup": round(cov, 1), "manual": tm, "program": tp, "persen": _pct(tp, tm)})
        manual.update(w["manual"])
        program.update(prog)
        unknown, covered, minutes = unknown + unk, covered + cov, minutes + w["menit"]
    rows = []
    for mv in mvs:
        m, p = sum(manual[(mv, c)] for c in CLASSES), sum(program[(mv, c)] for c in CLASSES)
        rows.append({"gerakan": mv, "manual": m, "program": p, "selisih": p - m, "persen": _pct(p, m),
                     "geh": round(geh(m, p, minutes), 1)})
    per_class = []
    for c in CLASSES:
        m, p = sum(manual[(mv, c)] for mv in mvs), sum(program[(mv, c)] for mv in mvs)
        per_class.append({"kelas": c, "manual": m, "program": p, "selisih": p - m, "persen": _pct(p, m)})
    extra = sum(n for (mv, _), n in program.items() if mv not in mvs)
    tm, tp = sum(r["manual"] for r in rows), sum(r["program"] for r in rows)
    result = {
        "mulai": windows[0]["mulai"].strftime("%Y-%m-%d %H:%M:%S"), "menit": minutes,
        "menit_video_tercakup": round(covered, 1), "total_manual": tm, "total_program": tp,
        "program_tidak_teridentifikasi": unknown, "program_di_gerakan_luar_form": extra,
        "selisih_total_persen": _pct(tp, tm), "gerakan_geh_di_bawah_5": sum(r["geh"] < 5 for r in rows),
        "jumlah_gerakan": len(rows), "per_rentang": per_window, "per_gerakan": rows, "per_kelas": per_class,
    }
    if out_path:
        _write_result(project, form_path, out_path, result)
    return result


def _write_result(project: dict, form_path, out_path, res: dict):
    wb = openpyxl.load_workbook(form_path)
    if "VALIDASI" in wb.sheetnames:
        del wb["VALIDASI"]
    ws = wb.create_sheet("VALIDASI", 0)
    ws.append([f"VALIDASI {project['nama'].upper()}: mulai {res['mulai']}, {res['menit']} menit"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([f"Video tercakup {res['menit_video_tercakup']} dari {res['menit']} menit. Total manual {res['total_manual']}, "
               f"program {res['total_program']} (+{res['program_tidak_teridentifikasi']} tidak teridentifikasi gerakannya)."])
    ws.append([])
    ws.append(["Gerakan", "Manual", "Program", "Selisih", "Selisih %", "GEH"])
    for r in res["per_gerakan"]:
        ws.append([r["gerakan"].replace("->", " ke "), r["manual"], r["program"], r["selisih"], r["persen"], r["geh"]])
        if r["geh"] >= 5:
            ws.cell(ws.max_row, 6).fill = PatternFill("solid", fgColor="F8CBAD")
    ws.append([])
    ws.append(["Kelas", "Manual", "Program", "Selisih", "Selisih %"])
    for r in res["per_kelas"]:
        ws.append([r["kelas"], r["manual"], r["program"], r["selisih"], r["persen"]])
    ws.append([])
    ws.append(["Rentang", "Manual", "Program", "Selisih %", "Menit video tercakup"])
    for w in res["per_rentang"]:
        ws.append([f"{w['sheet']} ({w['mulai']}, {w['menit']} mnt)", w["manual"], w["program"], w["persen"], w["tercakup"]])
    for row in ws.iter_rows():
        if row[0].value in ("Gerakan", "Kelas", "Rentang"):
            for c in row:
                c.font = BOLD
    ws.column_dimensions["A"].width = 30
    try:
        wb.save(out_path)
    except PermissionError:
        raise SystemExit(f"Tidak bisa menulis {out_path}: tutup dulu file itu di Excel, lalu ulangi.") from None


def format_result(res: dict) -> str:
    lines = [f"mulai {res['mulai']}, {res['menit']} menit (video tercakup {res['menit_video_tercakup']} menit)",
             f"total manual {res['total_manual']} | program {res['total_program']} "
             f"({res['selisih_total_persen']}%) | tidak teridentifikasi {res['program_tidak_teridentifikasi']} | "
             f"GEH<5: {res['gerakan_geh_di_bawah_5']} dari {res['jumlah_gerakan']} gerakan",
             f"{'gerakan':24s} {'manual':>7s} {'program':>8s} {'selisih':>8s} {'%':>7s} {'GEH':>5s}"]
    for r in res["per_gerakan"]:
        lines.append(f"{r['gerakan']:24s} {r['manual']:7d} {r['program']:8d} {r['selisih']:+8d} "
                     f"{'' if r['persen'] is None else r['persen']:>7} {r['geh']:5.1f}")
    lines.append(f"{'kelas':24s} {'manual':>7s} {'program':>8s} {'selisih':>8s} {'%':>7s}")
    for r in res["per_kelas"]:
        lines.append(f"{r['kelas']:24s} {r['manual']:7d} {r['program']:8d} {r['selisih']:+8d} "
                     f"{'' if r['persen'] is None else r['persen']:>7}")
    if len(res["per_rentang"]) > 1:
        lines.append(f"{'rentang':24s} {'manual':>7s} {'program':>8s} {'%':>7s}")
        for w in res["per_rentang"]:
            lines.append(f"{w['sheet'] + ' ' + w['mulai']:24s} {w['manual']:7d} {w['program']:8d} "
                         f"{'' if w['persen'] is None else w['persen']:>7}")
    return "\n".join(lines)
