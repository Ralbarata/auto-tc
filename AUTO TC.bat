@echo off
rem Membuka aplikasi AUTO TC: pilih simpang, tambah video/folder, proses, lalu buat Excel rekap.
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" -m autotc aplikasi
