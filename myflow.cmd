@echo off
REM ============================================================
REM  myflow auto-launcher (runs at every Windows logon)
REM  Replaces the .vbs which Windows had stopped firing reliably.
REM ============================================================
set "LOG=%APPDATA%\myflow\startup.log"
echo ----- launcher .cmd starting at %DATE% %TIME% ----- >> "%LOG%"

REM 1. Kill any orphan myflow processes (zombies from Windows "Restart apps")
for /f "tokens=2 delims==" %%P in ('wmic process where "(Name='pythonw.exe' or Name='python.exe') and CommandLine like '%%myflow%%'" get ProcessId /value 2^>nul ^| find "ProcessId"') do (
  echo killing orphan PID %%P >> "%LOG%"
  taskkill /F /PID %%P >nul 2>&1
)

REM 2. Clear stale single-instance lock (Python re-acquires its own on launch)
if exist "%APPDATA%\myflow\myflow.lock" (
  erase "%APPDATA%\myflow\myflow.lock" >nul 2>&1
  echo cleared stale lock >> "%LOG%"
)

REM 3. Wait briefly for the OS to settle
ping -n 3 127.0.0.1 >nul

REM 4. Launch myflow via the entrypoint script (absolute paths, no OneDrive)
start "" "C:\myflow_venv\Scripts\pythonw.exe" "C:\myflow_app\run_myflow.py"
echo launched myflow >> "%LOG%"
