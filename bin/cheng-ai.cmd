@echo off
rem CHENG AI file assistant in the CURRENT folder. Works in any terminal (cmd / PowerShell
rem / pwsh) because it's on PATH. %~dp0 = this bin dir, so it finds cheng.py portably.
python "%~dp0..\cheng.py" --workspace %*
