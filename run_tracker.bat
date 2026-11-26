@echo off
cd /d "%~dp0"
python portfolio_tracker.py >> tracker_log.txt 2>&1
