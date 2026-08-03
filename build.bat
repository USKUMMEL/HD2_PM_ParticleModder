@echo off
setlocal

cd /d "%~dp0"
set "ROOT=%~dp0"
:: remove trailing backslash for cleaner concatenation
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

if exist "%ROOT%\dist\PM_ParticleModder" rmdir /s /q "%ROOT%\dist\PM_ParticleModder"

set "ICON=%ROOT%\Icon\icon2.ico"
if not exist "%ICON%" (
    echo Missing %ICON%
    echo Place your tool icon at Icon\icon2.ico, then run this script again.
    exit /b 1
)

python -m pip install --upgrade pyinstaller || exit /b 1

python -m PyInstaller ^
    --noconfirm --clean --onefile --windowed ^
    --name PM_ParticleModder ^
    --icon "%ICON%" ^
    --paths "%ROOT%\src" ^
    --add-data "%ROOT%\src\pm_particle_modder\ui\qml;pm_particle_modder\ui\qml" ^
    --add-data "%ROOT%\src\pm_particle_modder\ui\assets;pm_particle_modder\ui\assets" ^
    --add-data "%ROOT%\src\pm_particle_modder\tools;pm_particle_modder\tools" ^
    --add-data "%ICON%;pm_particle_modder\ui\assets" ^
    --workpath "%ROOT%\build\pyinstaller" ^
    --specpath "%ROOT%\build" ^
    --distpath "%ROOT%\dist" ^
    "%ROOT%\src\pm_particle_modder\app.py"

if errorlevel 1 exit /b %errorlevel%

echo.
echo Build complete: dist\PM_ParticleModder.exe
endlocal
