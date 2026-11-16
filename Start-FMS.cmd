@echo off
setlocal
pushd "%~dp0" || exit /b 1
set "FMS_PYTHON=.venv\Scripts\python.exe"

if not exist "%FMS_PYTHON%" (
    where py.exe >nul 2>&1
    if errorlevel 1 (
        python -c "import sys; sys.exit(sys.version_info[:2] != (3, 12))" && python -m venv .venv
    ) else (
        py -3.12 -m venv .venv
    )
    if not exist "%FMS_PYTHON%" (
        echo Install Python 3.12 with the Windows py launcher, then run Start-FMS.cmd again.
        goto :failed
    )
)

if not exist ".venv\fms-requirements.txt" goto :install
fc /b "requirements.txt" ".venv\fms-requirements.txt" >nul
if not errorlevel 1 goto :launch

:install
"%FMS_PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 goto :failed
copy /y "requirements.txt" ".venv\fms-requirements.txt" >nul
if errorlevel 1 goto :failed

:launch
if /i "%~1"=="--install-only" goto :done
"%FMS_PYTHON%" flightmanagementsystems_public.py
if errorlevel 1 goto :failed

:done
popd
exit /b 0

:failed
echo FMS could not start. Review the error above.
if /i not "%~1"=="--install-only" pause
popd
exit /b 1
