"""Perintah baris: python -m autotc <indeks|lacak|hitung|video> ..."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser(prog="autotc", description="Pencacahan lalu lintas otomatis dari video CCTV")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("indeks", help="daftar video di satu folder, urut jam, beserta celah rekaman")
    p.add_argument("folder")

    p = sub.add_parser("lacak", help="deteksi + pelacakan satu video, simpan lintasan (.npz)")
    p.add_argument("video")
    p.add_argument("keluaran")
    p.add_argument("--detik", type=float, default=None, help="hanya proses sekian detik pertama")
    p.add_argument("--lompat", type=int, default=1, help="proses 1 dari N frame (1 = semua frame)")
    p.add_argument("--model", default=None, help="bobot detektor (bawaan mengikuti mode siang/malam)")
    p.add_argument("--mode", choices=["auto", "siang", "malam"], default="auto",
                   help="auto = malam bila jam rekaman antara 17:30 dan 05:30")
    p.add_argument("--ambang", type=float, default=None, help="ambang keyakinan deteksi (bawaan mengikuti mode)")
    p.add_argument("--ukuran", type=int, default=1280, help="ukuran gambar masukan model")
    p.add_argument("--pelacak", default=None, help="berkas pengaturan pelacak (bawaan mengikuti mode)")

    p = sub.add_parser("hitung", help="hitung gerakan dari lintasan + berkas proyek")
    p.add_argument("lintasan")
    p.add_argument("proyek")
    p.add_argument("--gambar", default=None, help="simpan gambar audit lintasan")

    p = sub.add_parser("video", help="buat video beranotasi untuk dicek manual")
    p.add_argument("lintasan")
    p.add_argument("proyek")
    p.add_argument("keluaran")
    p.add_argument("--detik", type=float, default=180)

    p = sub.add_parser("ekspor", help="isi form Excel: satu sheet per gerakan per hari")
    p.add_argument("proyek")
    p.add_argument("keluaran")
    p.add_argument("lintasan", nargs="+", help="satu atau lebih berkas lintasan (.npz)")
    p.add_argument("--template", default=str(ROOT / "template" / "form_tc.xlsx"))

    p = sub.add_parser("gerbang", help="buka editor untuk menggambar gerbang simpang")
    p.add_argument("proyek", nargs="?", default=None, help="berkas proyek (.json); kosongkan untuk proyek baru")
    p.add_argument("--video", default=None, help="video acuan untuk frame latar")
    p.add_argument("--lintasan", default=None, help="berkas lintasan (.npz) untuk ditampilkan sebagai panduan")

    data_default = str(ROOT / "data" / "potongan")
    p = sub.add_parser("potong", help="potong gambar kendaraan dari video untuk dilabeli")
    p.add_argument("simpang", help="nama simpang, mis. rajekwesi")
    p.add_argument("lintasan", nargs="+", help="berkas lintasan (.npz)")
    p.add_argument("--data", default=data_default)

    p = sub.add_parser("label", help="buka alat pelabelan kelas PKJI")
    p.add_argument("--data", default=data_default)

    p = sub.add_parser("latih", help="latih pengklasifikasi kelas PKJI dari label")
    p.add_argument("--data", default=data_default)
    p.add_argument("--putaran", type=int, default=40, help="jumlah epoch")

    p = sub.add_parser("kelas", help="tentukan kelas PKJI untuk berkas lintasan dengan pengklasifikasi")
    p.add_argument("lintasan", nargs="+")

    p = sub.add_parser("form-manual", help="buat form Excel untuk hitung manual pada satu rentang waktu")
    p.add_argument("proyek")
    p.add_argument("keluaran")
    p.add_argument("--mulai", required=True, help='jam mulai, mis. "2026-10-21 16:00"')
    p.add_argument("--menit", type=int, default=15)
    p.add_argument("--selang", type=int, default=None, help="pecah menjadi beberapa sheet, mis. 15 untuk per 15 menit")
    p.add_argument("--video", default="", help="nama video, hanya untuk catatan di form")

    p = sub.add_parser("validasi", help="bandingkan form manual yang sudah diisi dengan hitungan program")
    p.add_argument("proyek")
    p.add_argument("form", help="form manual yang sudah diisi (.xlsx)")
    p.add_argument("lintasan", nargs="+", help="berkas lintasan (.npz) yang mencakup rentang waktu form")
    p.add_argument("--keluaran", default=None, help="simpan hasil sebagai Excel (bawaan: di samping form)")

    p = sub.add_parser("manual", help="buka alat hitung manual (putar video, satu tombol per kendaraan)")
    p.add_argument("proyek", nargs="?", default=None)
    p.add_argument("video", nargs="?", default=None)

    p = sub.add_parser("aplikasi", help="buka aplikasi pencacahan (sementara: Simpang Rajekwesi)")
    p.add_argument("proyek", nargs="?", default=str(ROOT / "proyek" / "rajekwesi.json"))

    p = sub.add_parser("proses", help="lacak + tentukan kelas satu video (dipakai aplikasi; mencetak kemajuan)")
    p.add_argument("video")
    p.add_argument("keluaran")
    p.add_argument("--detik", type=float, default=None)
    p.add_argument("--proyek", default=None, help="berkas proyek: hitung dan simpan daftar kendaraan begitu selesai")

    p = sub.add_parser("kotak", help="buka alat label kotak kendaraan (untuk melatih ulang detektor)")
    p.add_argument("folder", nargs="?", default=str(ROOT / "data" / "kotak" / "rajekwesi"))

    p = sub.add_parser("harian", help="proses semua video di satu folder (urut jam; yang sudah selesai dilewati)")
    p.add_argument("folder")
    p.add_argument("keluaran", help="folder untuk berkas lintasan (.npz)")

    p = sub.add_parser("lhr", help="rekap LHR dan jam puncak dari berkas lintasan (.npz) ke Excel")
    p.add_argument("proyek")
    p.add_argument("keluaran")
    p.add_argument("lintasan", nargs="+", help="berkas .npz atau folder berisi .npz")
    p.add_argument("--tanggal", default=None, help="hanya satu hari kalender, mis. 2026-10-21")

    p = sub.add_parser("rekap", help="satu Excel per simpang: form TC per 5 menit + LHR dan jam puncak tiap hari")
    p.add_argument("proyek")
    p.add_argument("keluaran", help="berkas .xlsx")
    p.add_argument("lintasan", nargs="+", help="berkas .npz, folder berisi .npz, atau @daftar.txt (satu berkas per baris)")
    p.add_argument("--per-hari", action="store_true", help="satu berkas Excel per tanggal (bawaan: semua hari satu berkas)")
    p.add_argument("--tanpa-sebar", action="store_true",
                   help="jangan sebarkan kendaraan tak teridentifikasi (bawaan: disebar supaya masuk = keluar)")

    a = ap.parse_args()
    if a.cmd == "rekap":
        from .movements import load_project
        from .rekap import build
        files = []
        for item in a.lintasan:
            if item.startswith("@"):
                files += [Path(x) for x in Path(item[1:]).read_text(encoding="utf-8").splitlines() if x.strip()]
                continue
            p_ = Path(item)
            files += sorted(f for f in p_.glob("*.npz") if ".kelas" not in f.name and ".sebagian" not in f.name) \
                if p_.is_dir() else [p_]
        res = build(load_project(a.proyek), files, a.keluaran, per_day_files=a.per_hari, spread=not a.tanpa_sebar,
                    progress=lambda n, total: print(f"PROGRES {n} {total}", flush=True))
        print("SELESAI", json.dumps(res), flush=True)
        return
    if a.cmd == "harian":
        import time

        from .classify import WEIGHTS, classify_npz
        from .tracking import track_video
        from .video_index import index_folder
        out_dir = Path(a.keluaran)
        out_dir.mkdir(parents=True, exist_ok=True)
        videos = index_folder(a.folder)
        for k, v in enumerate(videos, 1):
            out = out_dir / (Path(v.path).stem + ".npz")
            if out.exists():
                print(f"[{k}/{len(videos)}] sudah ada: {out.name}", flush=True)
                continue
            t0 = time.time()
            tmp = out.with_name(out.stem + ".sebagian.npz")
            print(f"[{k}/{len(videos)}] mulai {v.start:%d-%m %H:%M} {Path(v.path).name}", flush=True)
            mark = [0]

            def tick(n, total):
                if n * 10 // total > mark[0]:      # satu baris tiap 10%
                    mark[0] = n * 10 // total
                    print(f"      {mark[0] * 10}%  ({(time.time() - t0) / 60:.0f} mnt)", flush=True)

            res = track_video(v.path, tmp, progress=tick)
            if WEIGHTS.exists():
                classify_npz(tmp).replace(out.with_suffix(".kelas.npz"))
            tmp.replace(out)
            print(f"[{k}/{len(videos)}] {v.start:%d-%m %H:%M} {out.name} mode {res['mode']} "
                  f"{res['video_seconds'] / 60:.0f} mnt video dalam {(time.time() - t0) / 60:.0f} mnt", flush=True)
        print("SELESAI", flush=True)
        return
    if a.cmd == "lhr":
        from .lhr import format_summary, summarize, vehicles, write_excel
        from .movements import load_project
        project = load_project(a.proyek)
        files = []
        for item in a.lintasan:
            p_ = Path(item)
            files += sorted(f for f in p_.glob("*.npz") if ".kelas" not in f.name and ".sebagian" not in f.name) \
                if p_.is_dir() else [p_]
        veh, cov = vehicles(files, project)
        if a.tanggal:
            from datetime import datetime, timedelta
            d0 = datetime.strptime(a.tanggal, "%Y-%m-%d")
            d1 = d0 + timedelta(days=1)
            veh = [v for v in veh if d0 <= v["waktu"] < d1]
            cov = [(max(x, d0), min(y, d1)) for x, y in cov if y > d0 and x < d1]
            if not cov:
                raise SystemExit(f"Tidak ada rekaman pada {a.tanggal}.")
        s = summarize(veh, cov, project)
        print(format_summary(s))
        print("tersimpan:", write_excel(s, project, a.keluaran))
        return
    if a.cmd == "kotak":
        from .box_tool import run
        raise SystemExit(run(a.folder))
    if a.cmd == "aplikasi":
        from .app import run
        raise SystemExit(run(a.proyek))
    if a.cmd == "proses":
        from .classify import WEIGHTS, classify_npz
        from .tracking import track_video
        out = Path(a.keluaran)
        tmp = out.with_name(out.stem + ".sebagian.npz")
        res = track_video(a.video, tmp, max_seconds=a.detik,
                          progress=lambda n, total: print(f"PROGRES {n} {total}", flush=True),
                          notice=lambda text: print(f"PESAN {text}", flush=True))
        print("TAHAP kelas", flush=True)
        if WEIGHTS.exists():
            classify_npz(tmp).replace(out.with_suffix(".kelas.npz"))
        tmp.replace(out)
        if a.proyek:   # supaya pembuatan Excel nanti tidak perlu menghitung ulang lintasan
            from .movements import load_project
            from .rekap import video_vehicles
            print("TAHAP hitung", flush=True)
            try:
                video_vehicles(out, load_project(a.proyek))
            except SystemExit:
                pass
        print("SELESAI", json.dumps(res), flush=True)
        return
    if a.cmd == "manual":
        from .manual_tool import run
        raise SystemExit(run(a.proyek, a.video))
    if a.cmd == "form-manual":
        from datetime import datetime

        from .movements import load_project
        from .validate import make_form
        start = datetime.strptime(a.mulai, "%Y-%m-%d %H:%M" if len(a.mulai) <= 16 else "%Y-%m-%d %H:%M:%S")
        print(make_form(load_project(a.proyek), a.keluaran, start, a.menit, a.video, a.selang))
        return
    if a.cmd == "validasi":
        from .movements import load_project
        from .validate import compare, format_result
        out = a.keluaran or str(Path(a.form).with_name(Path(a.form).stem + " - hasil validasi.xlsx"))
        print(format_result(compare(load_project(a.proyek), a.form, a.lintasan, out)))
        print("tersimpan:", out)
        return
    if a.cmd == "potong":
        from .crops import extract
        for npz in a.lintasan:
            print(f"{npz}: {extract(npz, a.simpang, a.data)} potongan baru")
        return
    if a.cmd == "label":
        from .label_tool import run
        raise SystemExit(run(a.data))
    if a.cmd == "latih":
        from .classify import build_dataset, label_summary, train
        print(json.dumps(label_summary(a.data), indent=1))
        ds = ROOT / "data" / "dataset_kelas"
        print(json.dumps(build_dataset(a.data, ds), indent=1))
        print(json.dumps(train(ds, epochs=a.putaran), indent=1))
        return
    if a.cmd == "kelas":
        from .classify import classify_npz
        for npz in a.lintasan:
            print(f"{npz}: {classify_npz(npz)}")
        return
    if a.cmd == "gerbang":
        from .gate_editor import run
        raise SystemExit(run(a.proyek, a.video, a.lintasan))
    if a.cmd == "ekspor":
        from collections import Counter
        from datetime import timedelta

        from .excel import export
        from .movements import analyze, count_table, load_project
        project = load_project(a.proyek)
        counts, coverage = Counter(), []
        for npz in a.lintasan:
            meta, tracks, _ = analyze(npz, project)
            if not meta["start"]:
                raise SystemExit(f"Jam mulai tidak terbaca untuk {npz}; belum bisa diekspor.")
            counts.update(count_table(tracks, meta, project))
            coverage.append((meta["start"], meta["start"] + timedelta(seconds=meta["seconds"])))
        print(json.dumps(export(dict(counts), coverage, project, a.template, a.keluaran), indent=1))
        return
    if a.cmd == "indeks":
        from .video_index import describe
        print(describe(a.folder))
    elif a.cmd == "lacak":
        from .tracking import track_video
        print(json.dumps(track_video(a.video, a.keluaran, model_path=a.model, stride=a.lompat, max_seconds=a.detik,
                                     conf=a.ambang, imgsz=a.ukuran, tracker=a.pelacak, mode=a.mode), indent=1))
    else:
        from .movements import analyze, audit_image, load_project, movement_matrix
        project = load_project(a.proyek)
        meta, tracks, summary = analyze(a.lintasan, project)
        if a.cmd == "hitung":
            print(json.dumps(summary, indent=1))
            mm = movement_matrix(tracks, meta, project)
            classes = sorted({k for c in mm.values() for k in c})
            print("gerakan".ljust(22), *[c.rjust(5) for c in classes], "total".rjust(6))
            for mv in sorted(mm, key=lambda m: -sum(mm[m].values())):
                print(mv.ljust(22), *[str(mm[mv][c]).rjust(5) for c in classes], str(sum(mm[mv].values())).rjust(6))
            if a.gambar:
                audit_image(tracks, meta, project, a.gambar)
        else:
            from .render import render
            print(json.dumps(render(tracks, meta, project, a.keluaran, seconds=a.detik), indent=1))


if __name__ == "__main__":
    main()
