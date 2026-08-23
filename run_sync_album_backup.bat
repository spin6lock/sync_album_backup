@echo off
chcp 65001 >nul
cd /d "%~dp0"

where python3 >nul 2>&1 && (
    python3 sync_album_backup.py
) || py -3 sync_album_backup.py

pause
