@echo off
cd /d "%~dp0"
rem コンソールをUTF-8にする。既定のcp932のままだと、Pythonが出す日本語が
rem 文字化けする(Python側は正しくUTF-8で出力しているが、表示側が合っていない)
chcp 65001 >nul
python news.py
if errorlevel 1 pause
