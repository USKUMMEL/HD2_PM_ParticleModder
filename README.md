# PM ParticleModder

Personal particle modding tool for Helldivers 2. PM ParticleModder is a Windows desktop editor for opening particle files and Slim archive resources, editing particle data, inspecting linked textures, and writing mod patches.

## Highlights

- Open standalone `.particle` / `.particles` files and `.pmod` projects.
- Load Helldivers 2 Slim archives by ID, choose from the found-archive list, or select a game/mod archive manually.
- Keep open archive particles grouped by archive in the particle list.
- Spreadsheet-style Color, Opacity, and Intensity editors with multi-cell selection, bulk apply, copy/paste, Ctrl drag selection, and undo/redo shortcuts.
- Edit lifetime, visualizer IDs, and disable individual particle systems for a patch.
- Browse materials and linked textures in Viewer or List mode.
- Import PNG or DDS texture replacements, compare original/imported versions, reset a replacement, and export PNG or DDS.
- Create, rename, and write patch archives. Use the shield next to a particle to choose whether it is included in the selected patch.
- Save/open project state including groups, selections, archive particles, disabled systems, and patch settings.
- Remember the game data folder, custom picker colors, and recent Open Project / Save Project directories.

## Using The Tool

1. Launch PM ParticleModder. The window opens maximized by default.
2. In `File`, select the Helldivers 2 `data` folder. The folder must contain `bundles.nxa`.
3. Open a `.particle` file, a project, or use `Load Archive` to load particle resources from game data.
4. Use `Create Patch`, select its name from the drop-down, enable the shield for resources to include, then choose `Write Patch`.

Standalone particles can be saved directly. Archive particles and texture replacements are saved through a patch archive.

## Run From Source

Python 3.11 or newer is required.

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
