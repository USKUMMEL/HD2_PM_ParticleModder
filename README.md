# PM ParticleModder

Personal particle modding tool for Helldivers 2.

## Run

Python 3.11 or newer and PySide6 6.10 are required.

```powershell
python -m pip install -e .
pm-particle-modder
```

For development without installing the package:

```powershell
.\run_pm.bat
```

## Tests

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

The editor provides spreadsheet-style color, opacity, and intensity tables with
multi-cell selection, bulk fill, matrix paste, color/hue editing, two color
selection presets, and per-file selection state. Particle lifetime and
visualizer asset IDs are also editable.

Files are patched in place so unsupported binary chunks and the source particle
version remain unchanged. PM projects use JSON v2 and can import the older XML
project format.
