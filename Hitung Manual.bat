@echo off
rem Membuka alat hitung manual. Seret berkas proyek (.json) ke sini, atau klik ganda lalu pilih proyeknya.
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" -m autotc manual %*
