@echo off
rem Membuka alat label kotak kendaraan (frame malam Rajekwesi).
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" -m autotc kotak %*
