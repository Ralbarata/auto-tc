@echo off
rem Memproses semua video Rajekwesi tanggal 26 Oktober (sekitar 10-11 jam), lalu membuat rekap LHR dan jam puncak.
rem Boleh ditutup dan dijalankan lagi: video yang sudah selesai dilewati.
cd /d "%~dp0"
title Proses harian Rajekwesi 26 Oktober
".venv\Scripts\python.exe" -u -m autotc harian "D:\26 RAJEKWESI" "hasil\rajekwesi_26"
if errorlevel 1 goto gagal
".venv\Scripts\python.exe" -m autotc lhr "proyek\rajekwesi.json" "hasil\rajekwesi_26\LHR Rajekwesi 2026-10-26.xlsx" "hasil\rajekwesi_26" --tanggal 2026-10-26
echo.
echo Selesai. Rekap ada di hasil\rajekwesi_26\LHR Rajekwesi 2026-10-26.xlsx
pause
exit /b
:gagal
echo.
echo Proses berhenti karena galat. Jalankan lagi berkas ini untuk melanjutkan.
pause