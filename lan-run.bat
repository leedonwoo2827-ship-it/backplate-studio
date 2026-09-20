@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

if not exist ".venv-app\Scripts\python.exe" (
  echo [ERROR] Not set up yet. Run setup.bat first.
  echo.
  pause
  exit /b 1
)

REM --- Keep the console from freezing the server ------------------------
REM Same QuickEdit issue as run.bat -- see there for the full explanation.
REM Separate title from run.bat's so the two don't collide over one
REM registry key if someone ever runs both (don't -- see the port note
REM below).
reg add "HKCU\Console\Developer Showcase Agent (LAN)" /v QuickEdit /t REG_DWORD /d 0 /f >nul 2>&1

if "%SA_CONSOLE%"=="1" goto serve
set "SA_CONSOLE=1"
REM /k, not /c -- see run.bat: keeps the window open after a crash so the
REM error log stays readable instead of vanishing on the next keypress.
start "Developer Showcase Agent (LAN)" cmd /k ""%~f0""
exit /b

:serve
REM --- Port: one source of truth is showcase.config.json ---------------
REM The literal below is only the fallback for when python cannot answer
REM (not set up yet, broken config). Editing the .json is what counts.
REM 5278, not 5178: the previous generation of this app (260918) still
REM runs on 5178 here, and two of them must be able to sit side by side.
set "PORT=5278"
for /f "usebackq tokens=* delims=" %%P in (`".venv-app\Scripts\python.exe" -c "import core.config as c;print(c.load()['port'])" 2^>nul`) do set "PORT=%%P"
if not "%SHOWCASE_PORT%"=="" set "PORT=%SHOWCASE_PORT%"
set "SHOWCASE_OPEN_BROWSER=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"

REM * Plain ASCII only in this file, on purpose. A Korean-locale cmd.exe
REM   parses .bat files in the system codepage (CP949), not UTF-8 -- and
REM   even `chcp 65001` right after @echo off does not reliably fix it
REM   for lines that follow in the SAME script (verified 2026-08-14: it
REM   still corrupted the very next line and shifted --no-access-log into
REM   becoming the --port value). run.bat has never hit this because it
REM   has no non-ASCII bytes at all -- so this file matches that instead
REM   of fighting the codepage.
echo Developer Showcase Agent (LAN demo)
echo ====================================
echo.
echo   Give a coworker on the same network (same office Wi-Fi/router) one
echo   of the addresses below -- pick the one that looks like your office
echo   Wi-Fi range (usually 192.168.x.x). If you're on a VPN, unrelated
echo   virtual-adapter IPs may show up too -- ignore those.
echo.
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /C:"IPv4"') do (
  set "ip=%%a"
  echo     http://!ip: =!:%PORT%
)
echo.
echo   On this PC             : http://localhost:%PORT%
echo.
echo   [NOTE] While this window is open, anyone on the same network can
echo          open that address and view/edit projects -- there is no
echo          login check. Close it (Ctrl+C) when the demo is done.
echo   [NOTE] Uses the same port (%PORT%) as run.bat (local-only) -- don't
echo          run both at once, they'll conflict. Keep only one open.
echo   [FIRST RUN] If Windows Firewall pops up asking to block/allow this,
echo               click "Allow access" or your coworker won't connect.
echo.
echo Press Ctrl+C to stop.
echo.

REM --host 0.0.0.0 is the only real difference from run.bat -- listens on
REM every network interface instead of just 127.0.0.1 (this PC only).
".venv-app\Scripts\python.exe" -m uvicorn server:app --host 0.0.0.0 --port %PORT% --no-access-log

echo.
echo Server stopped (exit code %ERRORLEVEL%).
pause
