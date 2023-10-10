@echo off
if "%CONDA_PREFIX%"=="" (set pfx="%PREFIX%") else (set pfx="%CONDA_PREFIX%")
"%pfx%\python.exe" -m anaconda_anon_usage.install --enable --quiet >>"%pfx%\.messages.txt" 2>&1 && if errorlevel 1 exit 1
