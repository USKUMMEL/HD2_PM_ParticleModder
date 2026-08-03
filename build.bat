@echo off
setlocal
cd /d "%~dp0"

set "ICON=Icon\icon.ico"
if not exist "%ICON%" (
    echo Missing %ICON%
    echo Place your tool icon at Icon\icon.ico, then run this script again.
    exit /b 1
)

python -m pip install --upgrade pyinstaller || exit /b 1
python -m PyInstaller --noconfirm --clean --onefile --windowed --name PM_ParticleModder --icon "%ICON%" --paths src --collect-all PySide6 --add-data "src\pm_particle_modder\ui\qml;pm_particle_modder\ui\qml" --add-data "src\pm_particle_modder\ui\assets;pm_particle_modder\ui\assets" --add-data "src\pm_particle_modder\tools;pm_particle_modder\tools" --add-data "%ICON%;pm_particle_modder\ui\assets" --workpath build\pyinstaller --specpath build --distpath dist src\pm_particle_modder\app.py
if errorlevel 1 exit /b %errorlevel%

echo.
echo Build complete: dist\PM_ParticleModder.exe
endlocal
