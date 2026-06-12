@echo off
rem JOTARO file assistant in the CURRENT folder. Works in any terminal (cmd / PowerShell
rem / pwsh) because it's on PATH. %~dp0 = this bin dir, so it finds jotaro.py portably.
python "%~dp0..\jotaro.py" --workspace %*
