@echo off
setlocal
set "PYTHONUTF8=1"
python "%~dp0agy.py" --interactive --cwd "%CD%" %*
exit /b %errorlevel%
