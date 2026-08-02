@echo off
setlocal
set "PYTHONPATH=%~dp0src"
python -m pm_particle_modder.app
endlocal
