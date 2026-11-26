@echo off
rem Membuka alat pelabelan kelas PKJI.
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" -m autotc label
