"""Rekap satu simpang ke satu berkas Excel: form TC per 5 menit (satu sheet per gerakan per hari),
ditambah LHR dan jam puncak tiap hari.

Hasil analisis tiap video (daftar kendaraan: waktu, asal, tujuan, kelas) disimpan di samping berkas
lintasan sebagai `<nama>.kend.json`, supaya Excel bisa dibuat ulang tanpa menghitung ulang lintasan.
Simpanan itu otomatis diabaikan bila gerbang proyek, lintasan, atau kelasnya berubah.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path

from openpyxl.styles import Alignment, Font, PatternFill

from .movements import UNKNOWN, analyze, track_class

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "template" / "form_tc.xlsx"
VERSION = 1   # naikkan bila cara menghitung berubah, supaya simpanan lama tidak dipakai


def _key(npz: Path, project: dict) -> str:
    """Sidik jari semua yang menentukan hasil hitungan satu video."""
    kelas = npz.with_suffix(".kelas.npz")
    parts = [VERSION, npz.stat().st_size, int(npz.stat().st_mtime),
             (kelas.stat().st_size, int(kelas.stat().st_mtime)) if kelas.exists() else None,
             project.get("gerbang"), project.get("gerakan_tidak_ada"), project.get("peta_kelas")]
    return hashlib.sha1(json.dumps(parts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def cache_path(npz: str | Path) -> Path:
    npz = Path(npz)
    return npz.with_name(npz.stem + ".kend.json")


def video_vehicles(npz: str | Path, project: dict, use_cache: bool = True) -> dict:
    """{"mulai", "selesai": datetime, "kendaraan": [(waktu, asal, tujuan, kelas)]} untuk satu berkas lintasan.
    Semua lintasan bergerak ikut, termasuk yang asal/tujuannya tidak terbaca."""
    npz = Path(npz)
    cp, key = cache_path(npz), _key(npz, project)
    if use_cache and cp.exists():
        try:
            d = json.loads(cp.read_text(encoding="utf-8"))
            if d.get("kunci") == key:
                return {"mulai": datetime.fromisoformat(d["mulai"]), "selesai": datetime.fromisoformat(d["selesai"]),
                        "kendaraan": [(datetime.fromisoformat(t), a, b, k) for t, a, b, k in d["kendaraan"]]}
        except (ValueError, KeyError):
            pass
    meta, tracks, _ = analyze(npz, project)
    if not meta["start"]:
        raise SystemExit(f"Jam mulai rekaman tidak terbaca: {npz.name}")
    start = meta["start"]
    veh = [(start + timedelta(seconds=float(t.frames[0]) / meta["fps"]), t.origin, t.dest, track_class(t, meta, project))
           for t in tracks]
    end = start + timedelta(seconds=meta["seconds"])
    cp.write_text(json.dumps({"kunci": key, "mulai": start.isoformat(), "selesai": end.isoformat(),
                              "kendaraan": [(t.isoformat(), a, b, k) for t, a, b, k in veh]}), encoding="utf-8")
    return {"mulai": start, "selesai": end, "kendaraan": veh}


def _work(args):
    npz, project = args
    return str(npz), video_vehicles(npz, project)


def gather(npz_files: list, project: dict, progress=None, workers: int = 4) -> list[dict]:
    """Daftar kendaraan semua video. Yang belum punya simpanan dihitung bersamaan di beberapa proses."""
    files = [Path(f) for f in npz_files]
    out, todo = {}, []
    for f in files:
        cp = cache_path(f)
        try:
            ok = cp.exists() and json.loads(cp.read_text(encoding="utf-8")).get("kunci") == _key(f, project)
        except ValueError:
            ok = False
        if ok:
            out[str(f)] = video_vehicles(f, project)
        else:
            todo.append(f)
    done = len(out)
    if progress:
        progress(done, len(files))
    if len(todo) == 1 or workers <= 1:
        for f in todo:
            out[str(f)] = video_vehicles(f, project)
            done += 1
            if progress:
                progress(done, len(files))
    elif todo:
        with ProcessPoolExecutor(max_workers=min(workers, len(todo))) as pool:
            for fut in as_completed([pool.submit(_work, (f, project)) for f in todo]):
                name, res = fut.result()
                out[name] = res
                done += 1
                if progress:
                    progress(done, len(files))
    return [out[str(f)] for f in files]


def _split_by_day(coverage: list[tuple[datetime, datetime]]) -> dict[date, list[tuple[datetime, datetime]]]:
    """Potong rentang rekaman di tengah malam. Rekaman yang sama (berkas ganda) digabung."""
    merged = []
    for s, e in sorted(coverage):
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    days: dict[date, list] = {}
    for s, e in merged:
        while s < e:
            nxt = min(e, datetime.combine(s.date() + timedelta(days=1), datetime.min.time()))
            days.setdefault(s.date(), []).append((s, nxt))
            s = nxt
    return days


def _dedupe(videos: list[dict]) -> list[tuple]:
    """Kendaraan dari semua video; video yang rekamannya sama persis (berkas ganda) hanya dihitung sekali."""
    seen, veh = set(), []
    for v in sorted(videos, key=lambda v: v["mulai"]):
        if (v["mulai"], v["selesai"]) in seen:
            continue
        seen.add((v["mulai"], v["selesai"]))
        veh += v["kendaraan"]
    return veh


HEAD = PatternFill("solid", fgColor="DDEBF7")


def _summary_sheet(wb, project: dict, per_day: dict, day_of: dict, skipped: list, index: int, spread_info=None):
    from .excel import _tanggal
    from .lhr import CLASSES, MOTORIZED
    ws = wb.create_sheet("LHR & JAM PUNCAK", index)
    ws["A1"] = f"LHR dan jam puncak - Simpang {project.get('nama', '')}"
    ws["A1"].font = Font(bold=True, size=13)
    ws["A2"] = ("Volume = kendaraan bermotor yang masuk simpang, hasil hitungan program (belum dikoreksi). "
                "Hari yang rekamannya tidak 24 jam bukan LHR penuh: lihat kolom jam video.")
    arms = [g["nama"] for g in project["gerbang"]]
    head = ["Hari", "Tanggal", "Jam video", *[f"Masuk {a}" for a in arms], "Total simpang", *CLASSES[:5], "KTB",
            "Jam puncak", "Volume puncak (kend/jam)", "PHF", "Puncak pagi", "Volume", "Puncak siang", "Volume",
            "Puncak sore", "Volume"]
    for j, h in enumerate(head, 1):
        c = ws.cell(4, j, h)
        c.font, c.fill, c.alignment = Font(bold=True), HEAD, Alignment(horizontal="center", wrap_text=True)
    r = 5
    for d in sorted(per_day):
        s = per_day[d]
        row = [f"D{day_of[d]}", _tanggal(d), round(s["menit_tercakup"] / 60, 1)]
        row += [sum(s["lhr"][a][c] for c in MOTORIZED) for a in arms]
        row += [sum(s["lhr"][a][c] for a in arms for c in MOTORIZED)]
        row += [sum(s["lhr"][a][c] for a in arms) for c in CLASSES[:5]] + [sum(s["lhr"][a].get("KTB", 0) for a in arms)]
        p = s["puncak"]["simpang"]
        row += [f"{p['mulai']:%H:%M} - {p['mulai'] + timedelta(hours=1):%H:%M}", p["volume"], p["phf"]] if p else ["-", None, None]
        for k in ("pagi", "siang", "sore"):
            p = s["puncak"][k]
            row += [f"{p['mulai']:%H:%M} - {p['mulai'] + timedelta(hours=1):%H:%M}", p["volume"]] if p else ["-", None]
        for j, v in enumerate(row, 1):
            ws.cell(r, j, v).alignment = Alignment(horizontal="center")
        r += 1
    if any(s["menit_tercakup"] < 23.5 * 60 for s in per_day.values()):
        ws.cell(r, 1, "Hari yang rekamannya tidak 24 jam: volume di atas BUKAN LHR, hanya jumlah selama jam video.")
        ws.cell(r, 1).font = Font(bold=True, color="C00000")
        r += 1
    if spread_info:
        from .sebar import KINDS
        r += 1
        ws.cell(r, 1, "Kekekalan arus: kendaraan yang gerakannya tidak teridentifikasi sudah disebar ke gerakan yang sah "
                      "sesuai proporsi gerakan pada kelas PKJI yang sama (jam yang sama), sehingga jumlah masuk = jumlah keluar.")
        ws.cell(r, 1).font = Font(bold=True)
        r += 1
        head = ["Hari", "Tanggal", "Teridentifikasi", *[KINDS[k] for k in KINDS], "Jumlah disebar", "% disebar", "Total"]
        for j, h in enumerate(head, 1):
            c = ws.cell(r, j, h)
            c.font, c.fill, c.alignment = Font(bold=True), HEAD, Alignment(horizontal="center", wrap_text=True)
        ws.row_dimensions[r].height = 45
        for d in sorted(per_day):
            r += 1
            add = spread_info["per_hari"].get(d, {})
            tot = sum(per_day[d]["lhr"][a][c] for a in per_day[d]["lhr"] for c in per_day[d]["lhr"][a])
            n = sum(add.values())
            row = [f"D{day_of[d]}", _tanggal(d), tot - n, *[add.get(k, 0) for k in KINDS], n,
                   round(100 * n / tot, 1) if tot else None, tot]
            for j, v in enumerate(row, 1):
                ws.cell(r, j, v).alignment = Alignment(horizontal="center")
        if spread_info.get("dibuang"):
            r += 1
            ws.cell(r, 1, "Tidak dihitung (dianggap potongan lintasan, bukan kendaraan baru): " + ", ".join(
                f"{KINDS[k]} {n}" for k, n in spread_info["dibuang"].items()))
        r += 1
    if skipped:
        ws.cell(r + 1, 1, "Tanggal yang rekamannya kurang dari 1 jam tidak dibuatkan sheet: "
                + ", ".join(f"{d:%d-%m-%Y}" for d in skipped))
    ws.column_dimensions["A"].width = 7
    ws.column_dimensions["B"].width = 26
    for j in range(3, len(head) + 1):
        ws.column_dimensions[ws.cell(4, j).column_letter].width = 13
    ws.row_dimensions[4].height = 32
    ws.freeze_panes = "C5"


def build(project: dict, npz_files: list, out_path: str | Path, per_day_files: bool = False, progress=None,
          template: str | Path = TEMPLATE, min_hours: float = 1.0, workers: int = 4, spread: bool = True) -> dict:
    """Buat Excel rekap. `per_day_files=False`: semua hari dalam satu berkas (sheet berbeda);
    True: satu berkas per tanggal, `out_path` dipakai sebagai nama dasar."""
    from .excel import export
    from .lhr import add_sheets, summarize
    videos = gather(npz_files, project, progress, workers)
    veh = _dedupe(videos)
    days = _split_by_day([(v["mulai"], v["selesai"]) for v in videos])
    # potongan pendek di ujung hari lain (mis. 23:28-24:00 dari folder hari sebelumnya) tidak dijadikan hari survei;
    # bila semua rekaman memang pendek (uji beberapa menit), semua tanggal tetap direkap
    keep = sorted(d for d, cov in days.items() if sum((e - s).total_seconds() for s, e in cov) >= min_hours * 3600)
    if not keep:
        keep = sorted(days)
    skipped = sorted(set(days) - set(keep))
    day_of = {date.fromisoformat(k): v for k, v in project.get("hari", {}).items()}
    if not all(d in day_of for d in keep):
        day_of = {d: i + 1 for i, d in enumerate(keep)}
    proj = {**project, "hari": {d.isoformat(): day_of[d] for d in keep}}
    spread_info = None
    if spread:   # kekekalan arus: kendaraan tak teridentifikasi disebar ke gerakan sesuai proporsi (lihat sebar.py)
        from .sebar import distribute
        spread_counts, spread_info = distribute([v for v in veh if v[0].date() in keep], project)

    out_path = Path(out_path)
    groups = [[d] for d in keep] if per_day_files else [keep]
    results = []
    for group in groups:
        counts = Counter()
        if spread:
            counts.update({key: n for key, n in spread_counts.items() if key[0].date() in group})
        else:
            for t, a, b, k in veh:
                if t.date() in group:
                    counts[(t.replace(minute=t.minute - t.minute % 5, second=0, microsecond=0), f"{a}->{b}", k)] += 1
        coverage = [r for d in group for r in days[d]]
        per_day = {}
        for d in group:
            if spread:
                from .sebar import as_vehicles
                dv = as_vehicles(Counter({key: n for key, n in spread_counts.items() if key[0].date() == d}))
            else:
                dv = [{"waktu": t, "asal": a, "tujuan": b, "kelas": k} for t, a, b, k in veh if t.date() == d and a != b]
            per_day[d] = summarize(dv, sorted(days[d]), project)

        def extra(wb, group=group, per_day=per_day):
            _summary_sheet(wb, project, per_day, day_of, skipped, 1, spread_info)
            i = 2
            for d in group:
                i = add_sheets(wb, per_day[d], project, prefix=f"D{day_of[d]} ", index=i)

        target = out_path
        if per_day_files:
            target = out_path.with_name(f"{out_path.stem} {group[0]:%Y-%m-%d}{out_path.suffix}")
        res = export(dict(counts), coverage, {**proj, "hari": {d.isoformat(): day_of[d] for d in group}}, template, target,
                     extra_sheets=extra)
        res["tanggal"] = [d.isoformat() for d in group]
        results.append(res)
    return {"berkas": [r["berkas"] for r in results], "hari": len(keep), "video": len(videos),
            "kendaraan_terisi": sum(r["kendaraan_terisi"] for r in results),
            "tidak_teridentifikasi": sum(r["tidak_teridentifikasi"] for r in results),
            "ktb_di_rekap": sum(r["ktb_di_rekap"] for r in results),
            "disebar": sum(spread_info["disebar"].values()) if spread_info else 0,
            "tanggal_dilewati": [d.isoformat() for d in skipped]}


def default_name(project: dict, npz_files: list) -> str:
    return f"TC {project.get('nama', 'Simpang')}.xlsx"
