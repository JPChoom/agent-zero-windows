@echo off
title Agent Zero

cd /d "%~dp0"

echo ========================================
echo        Starting Agent Zero
echo ========================================
echo.

start "" powershell.exe -NoProfile -WindowStyle Hidden -Command ^
"$health='http://localhost:5000/api/health'; ^
$ui='http://localhost:5000/'; ^
for($i=0; $i -lt 90; $i++) { ^
    try { ^
        $r=Invoke-WebRequest -Uri $health -UseBasicParsing -TimeoutSec 2; ^
        if($r.StatusCode -eq 200) { ^
            Start-Process $ui; ^
            exit ^
        } ^
    } catch {} ^
    Start-Sleep -Seconds 1 ^
}; ^
Start-Process $ui"

".\.venv\Scripts\python.exe" "run_ui.py"

echo.
echo ========================================
echo        Agent Zero has stopped
echo ========================================
echo.

pause