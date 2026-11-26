"""Ekspor hitungan ke Excel: satu sheet per gerakan per hari, tata letak mengikuti form asli.

Form asli: baris 8-295 = 288 interval 5 menit (00:00-24:00), kolom D-H = SM, MP, KS, BB, TB,
kolom I = total (rumus), baris 296 = total harian.
"""
from __future__ import annotations

import copy
import io
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import openpyxl
from openpyxl.drawing.image import Image
from openpyxl.styles import Font, PatternFill

from .movements import UNKNOWN

CLASS_COL = {"SM": "D", "MP": "E", "KS": "F", "BB": "G", "TB": "H"}
FIRST_ROW, LAST_ROW, TOTAL_ROW = 8, 295, 296
PARTIAL_FILL = PatternFill("solid", fgColor="FFF2CC")
BULAN = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober",
         "November", "Desember"]
HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]


def _tanggal(d: date) -> str:
    return f"{HARI[d.weekday()]}, {d.day} {BULAN[d.month - 1]} {d.year}"


def _row(t: datetime, interval_min: int) -> int:
    return FIRST_ROW + (t.hour * 60 + t.minute) // interval_min


def _sheet_name(day: int, origin: str, dest: str) -> str:
    return f"D{day} {origin}-{dest}"[:31]


def export(counts: dict, coverage: list[tuple[datetime, datetime]], project: dict, template: str | Path,
           out_path: str | Path, extra_sheets=None) -> dict:
    """counts: {(mulai_interval, "Asal->Tujuan", kelas): jumlah}; coverage: rentang waktu video yang diproses."""
    interval = project.get("interval_menit", 5)
    if interval != 5:
        raise ValueError("Form asli memakai interval 5 menit; interval lain belum didukung.")
    gates = [g["nama"] for g in project["gerbang"]]
    skip = {tuple(m) for m in project.get("gerakan_tidak_ada", [])}
    movements = [(o, d) for o in gates for d in gates if o != d and (o, d) not in skip]

    # hari survei: dari proyek ({"2026-10-21": 1, ...}) atau urutan tanggal yang ada di data
    dates = sorted({s.date() for s, _ in coverage} | {e.date() for _, e in coverage if e.time() != datetime.min.time()})
    day_of = {date.fromisoformat(k): v for k, v in project.get("hari", {}).items()} or {d: i + 1 for i, d in enumerate(dates)}

    # interval yang tercakup video: penuh, sebagian, atau tidak sama sekali
    covered = defaultdict(float)
    step = timedelta(minutes=interval)
    for s, e in coverage:
        t = s.replace(minute=s.minute - s.minute % interval, second=0, microsecond=0)
        while t < e:
            covered[t] += (min(e, t + step) - max(s, t)).total_seconds()
            t += step

    wb = openpyxl.load_workbook(template)
    master = wb[wb.sheetnames[0]]
    images = list(master._images)
    for col in "DEFGHI":  # perbaikan form asli: total harian hanya menjumlah 2 jam pertama
        master[f"{col}{TOTAL_ROW}"] = f"=SUM({col}{FIRST_ROW}:{col}{LAST_ROW})"

    by_sheet = defaultdict(Counter)   # (tanggal, asal, tujuan) -> {(baris, kolom): n}
    unknown = Counter()               # tanggal -> jumlah tidak teridentifikasi
    totals = defaultdict(Counter)     # (tanggal, asal, tujuan) -> {kelas: n}
    ignored, ktb = Counter(), Counter()
    for (bucket, mv, kelas), n in counts.items():
        o, d = mv.split("->")
        if UNKNOWN in (o, d) or o == d or (o, d) in skip:
            unknown[bucket.date()] += n
        elif kelas == "KTB":           # form PKJI hanya memuat kendaraan bermotor; KTB dicatat di rekap
            ktb[(bucket.date(), o, d)] += n
        elif kelas not in CLASS_COL:
            ignored[kelas] += n
        else:
            by_sheet[(bucket.date(), o, d)][(_row(bucket, interval), CLASS_COL[kelas])] += n
            totals[(bucket.date(), o, d)][kelas] += n

    made = []
    for day_date in sorted(day_of, key=day_of.get):
        for o, d in movements:
            ws = wb.copy_worksheet(master)
            ws.title = _sheet_name(day_of[day_date], o, d)
            ws.print_area = f"A1:J{TOTAL_ROW}"
            ws.freeze_panes = master.freeze_panes
            ws["C3"] = f"Simpang {project['nama']}: {o} ke {d}"
            ws["C4"] = _tanggal(day_date)
            cells = by_sheet.get((day_date, o, d), {})
            for t, secs in covered.items():
                if t.date() != day_date:
                    continue
                r = _row(t, interval)
                for col in CLASS_COL.values():
                    ws[f"{col}{r}"] = cells.get((r, col), 0)
                    if secs < interval * 60 - 1:
                        ws[f"{col}{r}"].fill = PARTIAL_FILL
            made.append(ws.title)
    for name in [s for s in wb.sheetnames if s not in made]:
        del wb[name]

    # sheet rekap di depan
    rk = wb.create_sheet("REKAP", 0)
    rk["A1"] = f"REKAP PENCACAHAN SIMPANG {project['nama'].upper()}"
    rk["A1"].font = Font(bold=True, size=14)
    rk["A2"] = "Video yang diproses:"
    for i, (s, e) in enumerate(sorted(coverage)):
        rk[f"B{2 + i}"] = f"{s:%d-%m-%Y %H:%M:%S} s.d. {e:%H:%M:%S}"
    r = 3 + len(coverage)
    rk[f"A{r}"] = "Sel kuning pada sheet gerakan = interval yang hanya terekam sebagian. Sel kosong = belum diproses."
    r += 1
    if project.get("catatan_kelas"):
        rk[f"A{r}"] = f"Catatan kelas: {project['catatan_kelas']}"
        r += 1
    rk[f"A{r}"] = "KTB (kendaraan tak bermotor) hanya dicatat di rekap ini; sheet gerakan mengikuti form PKJI."
    r += 2
    head = ["Hari", "Tanggal", "Asal", "Tujuan", *CLASS_COL, "Total", "KTB", "Sheet"]
    for c, h in enumerate(head, 1):
        rk.cell(r, c, h).font = Font(bold=True)
    for day_date in sorted(day_of, key=day_of.get):
        for o, d in movements:
            r += 1
            tot = totals.get((day_date, o, d), Counter())
            name = _sheet_name(day_of[day_date], o, d)
            row = [day_of[day_date], _tanggal(day_date), o, d, *[tot[k] for k in CLASS_COL], sum(tot.values()),
                   ktb[(day_date, o, d)], name]
            for c, v in enumerate(row, 1):
                rk.cell(r, c, v)
            rk.cell(r, len(row)).hyperlink = f"#'{name}'!A1"
            rk.cell(r, len(row)).font = Font(color="0563C1", underline="single")
        r += 1
        rk.cell(r, 3, "Tidak teridentifikasi gerakannya")
        rk.cell(r, 10, unknown[day_date])
    for col, w in zip("ABCDEFGHIJKL", [6, 26, 14, 14, 7, 7, 7, 7, 7, 8, 7, 24]):
        rk.column_dimensions[col].width = w
    for im in images:  # tabel dan gambar acuan klasifikasi PKJI dari form asli
        new = Image(io.BytesIO(im._data()))
        new.width, new.height = im.width, im.height
        new.anchor = copy.deepcopy(im.anchor)
        new.anchor._from.col = 13
        rk.add_image(new)

    if extra_sheets:   # sheet tambahan (LHR, jam puncak) dari pemanggil
        extra_sheets(wb)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        wb.save(out_path)
    except PermissionError:
        raise SystemExit(f"Tidak bisa menulis {out_path}: tutup dulu file itu di Excel, lalu ulangi.") from None
    return {
        "berkas": str(out_path), "jumlah_sheet": len(wb.sheetnames),
        "kendaraan_terisi": sum(sum(c.values()) for c in totals.values()),
        "ktb_di_rekap": sum(ktb.values()),
        "tidak_teridentifikasi": sum(unknown.values()), "kelas_di_luar_form": dict(ignored),
    }
