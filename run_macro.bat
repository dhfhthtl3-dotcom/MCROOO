@echo off
cd /d "%~dp0"
title Game Macro

set "PY=C:\Users\tooya\AppData\Local\Programs\Python\Python311\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" main_gui.py

if errorlevel 1 pause
