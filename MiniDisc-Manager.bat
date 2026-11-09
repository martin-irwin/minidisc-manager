@echo off
rem Opens MiniDisc Manager. Close any other recorder program first: only one program can use the recorder.
cd /d "%~dp0"
start "" pythonw himd_app.py

