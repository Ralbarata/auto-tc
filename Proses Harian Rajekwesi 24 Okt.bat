@echo off
rem Memproses semua video Rajekwesi tanggal 24 Oktober (sekitar 10-11 jam), lalu membuat rekap LHR dan jam puncak.
rem Boleh ditutup dan dijalankan lagi: video yang sudah selesai dilewati.
cd /d "%~dp0"
title Proses harian Rajekwesi 24 Oktober
".venv\Scripts\python.exe" -u -m autotc harian "D:\24 RAJEKWESI" "hasil\rajekwesi_24"
if errorlevel 1 goto gagal
".venv\Scripts\python.exe" -m autotc lhr "proyek\rajekwesi.json" "hasil\rajekwesi_24\LHR Rajekwesi 2026-10-24.xlsx" "hasil\rajekwesi_24" --tanggal 2026-10-24
echo.
echo Selesai. Rekap ada di hasil\rajekwesi_24\LHR Rajekwesi 2026-10-24.xlsx
pause
exit /b
:gagal
echo.
echo Proses berhenti karena galat. Jalankan lagi berkas ini untuk melanjutkan.
pause
