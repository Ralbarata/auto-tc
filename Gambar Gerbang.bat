@echo off
rem Membuka editor gerbang. Seret berkas proyek (.json) ke atas berkas ini untuk membukanya langsung.
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" -m autotc gerbang %*
