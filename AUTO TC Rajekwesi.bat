@echo off
rem Membuka aplikasi pencacahan untuk Simpang Rajekwesi.
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" -m autotc aplikasi proyek\rajekwesi.json
