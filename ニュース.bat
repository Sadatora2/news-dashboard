@echo off
cd /d "%~dp0"
python news.py
if errorlevel 1 pause
