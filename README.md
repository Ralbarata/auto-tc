# AUTO TC

Pencacahan lalu lintas (traffic counting) otomatis dari rekaman CCTV simpang. Program mendeteksi dan melacak setiap kendaraan, menentukan **gerakannya** (lengan asal → lengan tujuan) dan **kelasnya** menurut PKJI 2023, lalu menulis hasilnya ke Excel:

- form TC per **5 menit**, satu sheet per gerakan per hari, mengikuti tata letak form asli;
- **LHR** (volume harian per lengan), **jam puncak** simpang, pagi, siang, sore, dan tiap lengan, beserta PHF;
- volume per jam dan rekap per gerakan.

Kelas kendaraan: **SM** (sepeda motor), **MP** (mobil penumpang), **KS** (kendaraan sedang), **BB** (bus besar), **TB** (truk besar), ditambah **KTB** (kendaraan tak bermotor). KTB hanya muncul di rekap, tidak di sheet gerakan.

---

## Cara pakai singkat

1. Buka **`AUTO TC.bat`**.
2. Pilih simpang di daftar **Simpang**. Untuk titik survei baru, tekan **Simpang baru...**, lalu **Atur gerbang...** (lihat [Gerbang](#gerbang)).
3. Tekan **Tambah folder...** dan pilih folder video satu hari, misalnya `D:\26 RAJEKWESI`. Video otomatis diurutkan menurut jam rekaman. Video yang sudah pernah diproses langsung berstatus **Selesai**.
4. Tekan **Mulai proses**. Kalau dihentikan, video yang sudah selesai tidak diulang.
5. Pilih video yang sudah selesai untuk melihat gambar lintasan dan tabel gerakannya.
6. Tekan **Buat Excel rekap**:
   - jika **"Semua hari dalam satu berkas Excel"** dicentang, semua tanggal masuk ke satu berkas per simpang, tiap hari dengan sheet sendiri;
   - jika tidak dicentang, dibuat satu berkas Excel per tanggal.
7. Tekan **Buka Excel**.

Kolom **Proses hanya awal video** dipakai untuk uji cepat, misalnya hanya 2 menit pertama tiap video. Kosongkan untuk memproses seluruh video.

### Lama proses

Dengan TensorRT di RTX 5070 Ti, prosesnya kira-kira **1,6–2,8 kali waktu nyata**: satu video 70 menit selesai dalam sekitar 25–45 menit, dan satu hari penuh dalam sekitar 9–15 jam. Malam lebih cepat dari siang karena kendaraannya lebih sedikit. Dua proses yang berjalan bersamaan berbagi satu kartu grafis, sehingga masing-masing hampir dua kali lebih lambat dan hampir tidak ada waktu yang dihemat.

### Kalau ada video yang gagal atau macet

Selama memproses, aplikasi mengawasi proses tiap video:
- Proses yang mati tanpa kabar, atau tidak mengeluarkan apa pun selama 30 menit, dihentikan dan videonya ditandai **Gagal**.
- Video yang gagal diulang sekali di akhir antrean, sementara video lain tetap jalan.
- Catatan tiap video ada di `hasil\<simpang>\log\`, dan galat tak terduga ada di `hasil\autotc_galat.log`.
- Aplikasi mencegah Windows tidur karena diam selama memproses. Ini tidak berlaku kalau ada program lain yang sengaja menidurkan PC, jadi matikan program semacam itu selama memproses.

Saat pertama kali dijalankan di komputer baru, atau untuk video dengan ukuran gambar baru, program menyiapkan mesin TensorRT terlebih dahulu. Ini berlangsung sekali saja, beberapa menit.

---

## Berkas `.bat`

| Berkas | Kegunaan |
|---|---|
| `AUTO TC.bat` | Aplikasi utama: pilih simpang, proses video, buat Excel rekap. |
| `Proses Harian Rajekwesi <tgl> Okt.bat` | Proses satu folder hari lewat jendela perintah, lalu buat rekap LHR. Boleh ditutup dan dijalankan lagi untuk melanjutkan. Hasilnya otomatis terbaca di aplikasi. |
| `Gambar Gerbang.bat` | Editor gerbang (poligon lengan simpang). |
| `Hitung Manual.bat` | Alat hitung manual untuk validasi: putar video, satu tombol per kendaraan, lalu ekspor ke form. |
| `Label Kelas.bat` | Melabeli potongan gambar kendaraan ke kelas PKJI (untuk melatih pengklasifikasi). |
| `Label Kotak.bat` | Menggambar kotak kendaraan pada frame (untuk melatih ulang detektor, misalnya detektor malam). |
| `AUTO TC Rajekwesi.bat` | Versi lama aplikasi yang langsung membuka Rajekwesi. |

---

## Gerbang

Gerbang adalah poligon di gambar kamera yang menandai mulut tiap lengan simpang. Gerakan kendaraan ditentukan dari gerbang yang dilewatinya saat masuk dan keluar. Gerbang disimpan di `proyek/<simpang>.json` dalam koordinat relatif (0–1), sehingga tetap berlaku untuk resolusi video yang berbeda.

- **Nama gerbang harus sesuai arah mata angin sebenarnya**, karena nama itulah yang muncul di Excel. Contoh di Rajekwesi: sisi kanan gambar = Utara, kiri = Selatan, jembatan = Barat, dekat kamera = Timur.
- Gerbang dapat diubah kapan saja tanpa memproses ulang video. Lintasan disimpan mentah, dan Excel berikutnya otomatis memakai gerbang baru.
- Gerakan yang tidak mungkin terjadi (misalnya dilarang belok) bisa didaftarkan di `gerakan_tidak_ada` pada berkas proyek supaya tidak dibuatkan sheet.

---

## Isi Excel rekap

| Sheet | Isi |
|---|---|
| `REKAP` | Daftar video yang diproses, total per gerakan per hari, KTB, jumlah kendaraan yang tidak teridentifikasi, dan tautan ke tiap sheet. |
| `LHR & JAM PUNCAK` | Satu baris per hari: jam video, volume masuk tiap lengan, total per kelas, serta jam puncak simpang, pagi (05–11), siang (11–15), dan sore (15–21). |
| `D1 LHR`, `D1 JAM PUNCAK`, `D1 PER JAM`, `D1 GERAKAN` | Rincian hari ke-1; begitu pula D2, D3, dan seterusnya. |
| `D1 Utara-Timur`, ... | Form TC per 5 menit untuk satu gerakan pada satu hari. **Sel kuning** berarti interval itu hanya terekam sebagian. **Sel kosong** berarti interval itu tidak ada rekamannya. |

Catatan:
- **Volume lengan** = kendaraan yang **masuk** simpang dari lengan tersebut. Kendaraan yang asalnya terbaca tetapi tujuannya tidak tetap dihitung di lengan asal.
- **Kekekalan arus (masuk = keluar):** kendaraan yang gerakannya tidak teridentifikasi disebar ke gerakan yang sah, mengikuti proporsi gerakan kendaraan teridentifikasi pada kelas PKJI dan jam yang sama. Aturannya:
  - asal terbaca → disebar ke gerakan dari lengan itu;
  - tujuan terbaca → disebar ke gerakan menuju lengan itu;
  - keduanya tidak terbaca → disebar ke semua gerakan;
  - lintasan yang hanya menyentuh satu gerbang **dibuang**, karena dianggap potongan dari kendaraan yang sudah terhitung.

  Jumlah yang disebar dan dibuang dicatat di sheet `LHR & JAM PUNCAK`. Penyebaran bisa dimatikan lewat centang di aplikasi atau `--tanpa-sebar`. Jenis yang disebar bisa diubah per simpang dengan `"sebar_jenis": ["asal", "tujuan", "semua"]` di berkas proyek.

  Pada validasi malam Rajekwesi (19:00–19:30), aturan ini memberi selisih total −4,1% dan GEH < 5 pada 6 dari 12 gerakan. Tanpa penyebaran hasilnya −13,7% dan 9 dari 12: total lebih tepat, tetapi sebaran per gerakan sedikit menurun.
- Hari yang rekamannya tidak 24 jam diberi tanda: angkanya bukan LHR, hanya jumlah selama jam video.
- Potongan rekaman kurang dari 1 jam di ujung hari lain (misalnya 23:28–24:00 dari folder hari sebelumnya) tidak dijadikan hari survei.
- Berkas video ganda (rekaman yang sama di dua folder) hanya dihitung sekali.
- Angka adalah hasil hitungan program dan **belum dikoreksi** dengan faktor dari validasi manual.

---

## Ketelitian (validasi)

Program dibandingkan dengan hitung manual di Simpang Rajekwesi. Hasil lengkapnya ada di `hasil/validasi/`.

| Rentang | Manual | Program | Keterangan |
|---|---|---|---|
| Malam, 23 Okt 19:00–19:30, semua lengan | 1.641 | 1.416 (−13,7%) | GEH < 5 pada 9 dari 12 gerakan |
| Pagi, 21 Okt 06:40–06:55, masuk dari Utara | 283 | 295 (+4,2%) | GEH 1,4; SM dan MP selisih 2–3% |

Kelemahan yang diketahui:
- **Lengan Barat (jembatan)** pada malam hari: gerakan Barat→Utara hampir tidak terbaca karena tertutup pohon (12 dari 135). Barat→Selatan dan Selatan→Barat sekitar −45%.
- **Kelas pada malam hari:** KS cenderung berlebih (+44%), sedangkan MP dan TB kurang. Sebagian MP dan TB terbaca sebagai KS.
- Kendaraan yang tidak teridentifikasi sekitar 1.500–1.700 per hari di Rajekwesi.
- Validasi siang baru mencakup satu lengan selama 15 menit.

---

## Model

| Berkas di `model/` | Kegunaan |
|---|---|
| `yolo26m.pt` | Detektor siang (COCO). |
| `deteksi_malam.pt` | Detektor malam, dilatih ulang dengan frame malam Rajekwesi. |
| `kelas_pkji.pt` | Pengklasifikasi kelas PKJI per kendaraan. |
| `yolo26n-cls.pt` | Tulang punggung ReID (pencocokan tampilan kendaraan antar-frame). |
| `*_736x1280.engine`, `reid_yolo26n_224.engine` | Mesin TensorRT FP16 dari model di atas, dibuat otomatis. Hanya berlaku di kartu grafis dan driver tempat mesin itu dibuat; di komputer lain dibuat ulang. |

Mode **siang/malam** dipilih otomatis dari jam rekaman: malam berlaku pukul 17:30–05:30. Mode malam memakai ambang deteksi lebih rendah dan detektor malam.

Pengaturan ada di `autotc/tracking.py`:
- `USE_ENGINE`: pakai TensorRT.
- `FAST_REID`: ReID dijalankan sekaligus di GPU.
- `AGNOSTIC_NMS`: buang kotak ganda pada satu kendaraan.

Ketiganya `True` sejak 16 Nov 2026. Pada uji 10 menit, kombinasi ini 1,3–2 kali lebih cepat daripada model `.pt` dan lebih dekat ke hitung manual. Hasil harian Rajekwesi 21–25 Okt dibuat dengan model lama, sedangkan 26 Okt ke atas dengan TensorRT.

---

## Perintah baris (untuk pengguna lanjut)

Semua perintah dijalankan dari folder proyek:

```bash
.venv\Scripts\python.exe -m autotc <perintah> ...
```

| Perintah | Kegunaan |
|---|---|
| `aplikasi [proyek.json]` | Buka aplikasi. |
| `harian <folder video> <folder hasil>` | Proses semua video satu folder (bisa dilanjutkan). |
| `rekap <proyek.json> <keluaran.xlsx> <npz/folder...> [--per-hari]` | Excel rekap: TC 5 menit, LHR, dan jam puncak. |
| `lhr <proyek.json> <keluaran.xlsx> <npz/folder...> [--tanggal YYYY-MM-DD]` | Rekap LHR dan jam puncak saja. |
| `proses <video> <keluaran.npz> [--detik N] [--proyek proyek.json]` | Lacak dan klasifikasi satu video. |
| `hitung <lintasan.npz> <proyek.json> [--gambar audit.jpg]` | Tabel gerakan satu video di layar. |
| `video <lintasan.npz> <proyek.json> <keluaran.mp4>` | Video beranotasi untuk diperiksa. |
| `validasi <proyek.json> <form manual.xlsx> <npz...>` | Bandingkan form manual dengan program (GEH). |
| `form-manual`, `manual`, `gerbang`, `label`, `kotak`, `latih`, `kelas`, `potong`, `indeks` | Alat pendukung; lihat `-h` pada tiap perintah. |

---

## Struktur folder

```
AUTO TC by rangga/
├── autotc/          kode program
├── proyek/          satu berkas .json per simpang (nama, gerbang, peta kelas)
├── model/           bobot model dan mesin TensorRT
├── konfig/          pengaturan pelacak (siang, malam)
├── template/        form TC asli (form_tc.xlsx)
├── hasil/           keluaran: <simpang>_<tgl>/*.npz (lintasan), *.kelas.npz, *.kend.json, Excel
├── data/            label kelas, kotak, hitungan manual, dataset latih
└── *.bat            peluncur
```

Per video, program menyimpan tiga berkas di folder hasil:
- `.npz`: lintasan mentah;
- `.kelas.npz`: kelas PKJI tiap kendaraan;
- `.kend.json`: daftar kendaraan per gerakan, yang mempercepat pembuatan Excel. Berkas ini otomatis dihitung ulang bila gerbang berubah.

Jangan menghapus `.npz` kalau video sumbernya sudah tidak ada, karena berkas itu tidak bisa dibuat lagi.

---

## Kebutuhan

- Windows 11, kartu grafis NVIDIA (diuji dengan RTX 5070 Ti, driver 616).
- Python 3.12 dengan lingkungan `.venv`: PyTorch 2.11 + CUDA 12.8, Ultralytics 8.4, TensorRT 11, PySide6, OpenCV, openpyxl.
- FFmpeg (terpasang lewat winget), untuk membaca rekaman Hikvision (HEVC, MPEG-PS) dan membuat salinan ringan bagi alat hitung manual.
