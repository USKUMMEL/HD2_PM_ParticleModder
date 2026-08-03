from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
import math
import os
from pathlib import Path
import re
import tempfile
from urllib.request import urlopen
import xml.etree.ElementTree as ET
import zlib

from PySide6.QtCore import Property, QObject, QRunnable, QStandardPaths, QThreadPool, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QUndoCommand, QUndoStack
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QFileDialog,
    QInputDialog,
    QMessageBox,
)

from pm_particle_modder import __version__
from pm_particle_modder.core import (
    MATERIAL_TYPE_ID,
    PARTICLE_TYPE_ID,
    TEXTURE_TYPE_ID,
    UNIT_TYPE_ID,
    ArchiveEntry,
    ArchiveError,
    ArchiveReader,
    ColorGraph,
    dds_to_png,
    Graph,
    ParticleEffect,
    ParticleParseError,
    parse_texture,
    parse_material,
    preview_dds,
    replace_material_variable,
    SlimArchiveStore,
    write_patch_archive,
)
from pm_particle_modder.ui.models import (
    ArchiveParticleListModel,
    AssetLinkListModel,
    DocumentListModel,
    FoundArchiveListModel,
    ParticleTableModel,
    MaterialVariableListModel,
    TextureBindingListModel,
    TextureOverviewListModel,
    VisualizerListModel,
)


@dataclass(eq=False)
class Document:
    path: Path
    effect: ParticleEffect
    undo_stack: QUndoStack
    note: str = ""
    group: str = ""
    selections: dict[str, list[tuple[int, int]]] = field(
        default_factory=lambda: {"color": [], "opacity": [], "intensity": []}
    )
    color_presets: list[list[tuple[int, int]] | None] = field(
        default_factory=lambda: [None, None]
    )
    archive: ArchiveReader | None = None
    archive_entry_id: int | None = None
    title: str = ""
    source_data: bytes = b""
    include_in_patch: bool = False
    apply_included: bool = False
    patch_entry_id: int | None = None
    modified_texture_ids: set[int] = field(default_factory=set)


@dataclass
class PatchTarget:
    path: Path
    name: str
    archive: ArchiveReader
    needs_write: bool = False


class ValueEditCommand(QUndoCommand):
    def __init__(self, label: str, apply_value, old_value, new_value):
        super().__init__(label)
        self.apply_value = apply_value
        self.old_value = old_value
        self.new_value = new_value

    def undo(self) -> None:
        self.apply_value(self.old_value)

    def redo(self) -> None:
        self.apply_value(self.new_value)


class BulkEditCommand(QUndoCommand):
    def __init__(self, label: str, edits, refresh):
        super().__init__(label)
        self.edits = edits
        self.refresh = refresh

    def undo(self) -> None:
        for setter, old_value, _new_value in reversed(self.edits):
            setter(old_value)
        self.refresh()

    def redo(self) -> None:
        for setter, _old_value, new_value in self.edits:
            setter(new_value)
        self.refresh()


class TexturePreviewSignals(QObject):
    loaded = Signal(int, object, str, str, str)


class TexturePreviewTask(QRunnable):
    """Resolve and convert one texture without blocking the QML event loop."""

    def __init__(self, request_id: int, archive: ArchiveReader, binding):
        super().__init__()
        self.request_id = request_id
        self.archive = archive
        self.binding = binding
        self.signals = TexturePreviewSignals()

    def run(self) -> None:
        preview_url = ""
        original_preview_url = ""
        result = self.binding
        try:
            entry = self.archive.find_entry(self.binding.texture_id, TEXTURE_TYPE_ID)
            if entry is None:
                message = "Texture was not found in the available Slim archives."
            else:
                try:
                    result, preview_url = self._convert_entry(entry, "current")
                except ArchiveError:
                    full_entry = self.archive.reload_entry_full(self.binding.texture_id, TEXTURE_TYPE_ID)
                    if full_entry is None or full_entry is entry:
                        raise
                    result, preview_url = self._convert_entry(full_entry, "current")
                source_entry = self.archive.source_entry(self.binding.texture_id, TEXTURE_TYPE_ID)
                if source_entry is not None:
                    try:
                        _source_result, original_preview_url = self._convert_entry(source_entry, "original")
                    except ArchiveError:
                        original_preview_url = ""
                self.signals.loaded.emit(
                    self.request_id, result, preview_url, original_preview_url, result.detail
                )
                return
        except ArchiveError as error:
            message = str(error)
        self.signals.loaded.emit(
            self.request_id, replace(result, detail=message, preview_state="failed"), preview_url,
            original_preview_url, message
        )

    def _convert_entry(self, entry, variant: str):
        info = parse_texture(entry)
        result = replace(
            self.binding,
            detail=f"{info.width} x {info.height} | DXGI {info.dxgi_format}",
            available=True,
        )
        cache_directory = Path(tempfile.gettempdir()) / "pm-particlemodder" / "texture-previews"
        preview = dds_to_png(
            preview_dds(info), cache_directory,
            f"{self.binding.texture_id}-{variant}-{zlib.crc32(info.dds):08x}",
        )
        return replace(result, preview_url=QUrl.fromLocalFile(str(preview)).toString(), preview_state="ready"), QUrl.fromLocalFile(str(preview)).toString()


class ParticleController(QObject):
    stateChanged = Signal()
    currentDocumentChanged = Signal()
    statusChanged = Signal()
    tableSelectionsChanged = Signal(str)
    ARCHIVE_LIST_URL = "https://raw.githubusercontent.com/Boxofbiscuits97/HD2SDK-CommunityEdition/main/hashlists/archivehashes.json"
    BASE_PATCH_ARCHIVE_ID = "9ba626afa44a3aa3"

    def __init__(self, parent=None, settings_path: str | Path | None = None):
        super().__init__(parent)
        self.documents_model = DocumentListModel()
        self.color_model = ParticleTableModel("color")
        self.opacity_model = ParticleTableModel("opacity")
        self.intensity_model = ParticleTableModel("intensity")
        for model in (self.color_model, self.opacity_model, self.intensity_model):
            model.edit_handler = self.setTableCell
        self.visualizer_model = VisualizerListModel()
        self.material_variable_model = MaterialVariableListModel()
        self.archive_particles_model = ArchiveParticleListModel()
        self.found_archives_model = FoundArchiveListModel()
        self.asset_links_model = AssetLinkListModel()
        self.texture_bindings_model = TextureBindingListModel()
        self.texture_overview_model = TextureOverviewListModel()
        self._current_index = -1
        self._archive: ArchiveReader | None = None
        self._project_path: Path | None = None
        self._patch_targets: list[PatchTarget] = []
        self._selected_patch_index = -1
        self._next_patch_number = 0
        self._game_data_directory: Path | None = None
        self._slim_store: SlimArchiveStore | None = None
        self._last_project_open_directory: Path | None = None
        self._last_project_save_directory: Path | None = None
        self._settings_path = Path(settings_path) if settings_path is not None else self._default_settings_path()
        self._custom_picker_colors: list[str] = []
        self._archive_names: dict[str, str] | None = None
        self._selected_asset_index = -1
        self._selected_texture_index = -1
        self._all_texture_bindings = []
        self._texture_system_indices: list[int] = []
        self._texture_material_ids: list[int] = []
        self._material_ids_by_system: dict[int, list[int]] = {}
        self._material_system_indices: list[int] = []
        self._selected_material_system = -1
        self._selected_material_id = -1
        self._texture_materials_by_system: dict[int, list[int]] = {}
        self._selected_texture_system = -1
        self._selected_texture_material = -1
        self._texture_patch_choices: dict[tuple[int, int], bool] = {}
        self._texture_list_view = False
        self._texture_preview_url = ""
        self._texture_original_preview_url = ""
        self._texture_preview_message = "Select a texture to preview it."
        self._texture_preview_request = 0
        self._texture_preview_pool = QThreadPool(self)
        self._texture_preview_pool.setMaxThreadCount(1)
        self._texture_overview_request = 0
        self._texture_overview_pool = QThreadPool(self)
        self._texture_overview_pool.setMaxThreadCount(1)
        self._status = "Ready"
        self._load_preferences()

    @Property(int, notify=currentDocumentChanged)
    def currentIndex(self) -> int:
        return self._current_index

    @Property(bool, notify=stateChanged)
    def hasDocument(self) -> bool:
        return self.current_document is not None

    @Property(str, constant=True)
    def applicationVersion(self) -> str:
        return __version__

    @Property(int, notify=stateChanged)
    def documentCount(self) -> int:
        return len(self.documents_model.documents)

    @Property(int, notify=stateChanged)
    def applyParticleCount(self) -> int:
        return sum(1 for document in self.documents_model.documents if document.apply_included)

    @Property(bool, notify=stateChanged)
    def hasArchive(self) -> bool:
        return self._archive is not None

    @Property(bool, notify=stateChanged)
    def hasGameDataDirectory(self) -> bool:
        return self._game_data_directory is not None

    @Property(str, notify=stateChanged)
    def gameDataDirectory(self) -> str:
        return str(self._game_data_directory) if self._game_data_directory else "Game data folder not selected"

    @Property(str, notify=stateChanged)
    def archiveName(self) -> str:
        return self._archive.path.name if self._archive else "No archive loaded"

    @Property(int, notify=stateChanged)
    def archiveParticleCount(self) -> int:
        return self.archive_particles_model.rowCount()

    @Property(int, notify=stateChanged)
    def assetCount(self) -> int:
        return self.asset_links_model.rowCount()

    @Property(int, notify=stateChanged)
    def textureCount(self) -> int:
        return self.texture_bindings_model.rowCount()

    @Property("QVariantList", notify=stateChanged)
    def textureSystemOptions(self):
        return [f"Particle System {index + 1}" for index in self._texture_system_indices]

    @Property("QVariantList", notify=stateChanged)
    def textureMaterialOptions(self):
        return [str(material_id) for material_id in self._texture_material_ids]

    @Property("QVariantList", notify=stateChanged)
    def materialSystemOptions(self):
        return [f"Particle System {index + 1}" for index in self._material_system_indices]

    @Property("QVariantList", notify=stateChanged)
    def materialOptions(self):
        return [str(material_id) for material_id in self._material_ids_by_system.get(self._selected_material_system, [])]

    @Property(bool, notify=stateChanged)
    def hasMaterialChoice(self) -> bool:
        return len(self._material_ids_by_system.get(self._selected_material_system, [])) > 1

    @Property(int, notify=stateChanged)
    def selectedMaterialSystemIndex(self) -> int:
        return self._selected_material_system

    @Property(str, notify=stateChanged)
    def selectedMaterialId(self) -> str:
        return str(self._selected_material_id) if self._selected_material_id >= 0 else ""

    @Property(bool, notify=stateChanged)
    def hasTextureMaterialChoice(self) -> bool:
        return len(self._texture_material_ids) > 1

    @Property(bool, notify=stateChanged)
    def textureListView(self) -> bool:
        return self._texture_list_view

    @Property(str, notify=stateChanged)
    def texturePreviewUrl(self) -> str:
        return self._texture_preview_url

    @Property(str, notify=stateChanged)
    def textureOriginalPreviewUrl(self) -> str:
        return self._texture_original_preview_url

    @Property(bool, notify=stateChanged)
    def hasTextureReplacement(self) -> bool:
        binding = self._selected_texture_binding()
        if binding is None:
            return False
        key = (binding.texture_id, TEXTURE_TYPE_ID)
        return any(key in archive.staged_entries for archive in self._archives_for_patch())

    @Property(bool, notify=stateChanged)
    def selectedTextureUsesImported(self) -> bool:
        binding = self._selected_texture_binding()
        document = self.current_document
        if binding is None or document is None or document.archive is None:
            return True
        return self._texture_patch_choices.get((id(document.archive), binding.texture_id), True)

    @Property(str, notify=stateChanged)
    def texturePreviewMessage(self) -> str:
        return self._texture_preview_message

    @Property(bool, notify=stateChanged)
    def hasSelectedTexture(self) -> bool:
        if not 0 <= self._selected_texture_index < self.texture_bindings_model.rowCount():
            return False
        return self.texture_bindings_model.binding_at(self._selected_texture_index).available

    @Property(int, notify=stateChanged)
    def selectedTextureSystemIndex(self) -> int:
        binding = self._selected_texture_binding()
        return binding.system_index if binding is not None else -1

    @Property(str, notify=stateChanged)
    def selectedTextureMaterialId(self) -> str:
        binding = self._selected_texture_binding()
        return str(binding.material_id) if binding is not None else ""

    @Property(str, notify=stateChanged)
    def selectedTextureId(self) -> str:
        binding = self._selected_texture_binding()
        return str(binding.texture_id) if binding is not None else ""

    @Property(int, notify=stateChanged)
    def stagedChangeCount(self) -> int:
        included = sum(1 for document in self.documents_model.documents if document.include_in_patch)
        staged = sum(
            1
            for archive in self._archives_for_patch()
            for _file_id, type_id in archive.staged_entries
            if type_id != PARTICLE_TYPE_ID
        )
        return included + staged

    @Property(bool, notify=stateChanged)
    def canWritePatch(self) -> bool:
        return self.stagedChangeCount > 0 or (
            self.hasSelectedPatch and self._patch_targets[self._selected_patch_index].needs_write
        )

    @Property("QVariantList", notify=stateChanged)
    def patchOptions(self):
        return [target.name for target in self._patch_targets]

    @Property(str, notify=stateChanged)
    def selectedPatchName(self) -> str:
        if 0 <= self._selected_patch_index < len(self._patch_targets):
            return self._patch_targets[self._selected_patch_index].name
        return "Select patch"

    @Property(bool, notify=stateChanged)
    def hasSelectedPatch(self) -> bool:
        return 0 <= self._selected_patch_index < len(self._patch_targets)

    @Property(bool, notify=stateChanged)
    def canSaveParticle(self) -> bool:
        document = self.current_document
        return document is not None and document.archive is None

    @Property("QVariantList", notify=stateChanged)
    def groupNames(self):
        return sorted(
            {document.group for document in self.documents_model.documents if document.group},
            key=str.casefold,
        )

    @Property(str, notify=currentDocumentChanged)
    def currentTitle(self) -> str:
        document = self.current_document
        return (document.title or document.path.name) if document else "No file loaded"

    @Property(str, notify=currentDocumentChanged)
    def currentPath(self) -> str:
        document = self.current_document
        return str(document.path) if document else ""

    @Property(str, notify=currentDocumentChanged)
    def versionText(self) -> str:
        document = self.current_document
        return f"0x{document.effect.version:X}" if document else ""

    @Property(float, notify=currentDocumentChanged)
    def lifetimeMin(self) -> float:
        document = self.current_document
        return document.effect.min_lifetime if document else 0.0

    @Property(float, notify=currentDocumentChanged)
    def lifetimeMax(self) -> float:
        document = self.current_document
        return document.effect.max_lifetime if document else 0.0

    @Property(bool, notify=stateChanged)
    def canUndo(self) -> bool:
        document = self.current_document
        return document.undo_stack.canUndo() if document else False

    @Property(bool, notify=stateChanged)
    def canRedo(self) -> bool:
        document = self.current_document
        return document.undo_stack.canRedo() if document else False

    @Property(str, notify=statusChanged)
    def statusMessage(self) -> str:
        return self._status

    @property
    def current_document(self) -> Document | None:
        if 0 <= self._current_index < len(self.documents_model.documents):
            return self.documents_model.documents[self._current_index]
        return None

    @Slot()
    def openFiles(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            None,
            "Open particle files",
            "",
            "Particle Files (*.particle *.particles);;PM Projects (*.pmod);;All Files (*.*)",
        )
        self._open_paths([Path(path) for path in paths])

    @Slot()
    def openProject(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            None,
            "Open PM project",
            str(self._last_project_open_directory) if self._last_project_open_directory else "",
            "PM Projects (*.pmod)",
        )
        if path:
            self._open_project(Path(path))

    @Slot()
    def openArchive(self) -> None:
        self.selectArchiveFile()

    @Slot()
    def selectArchiveFile(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            None,
            "Select Helldivers 2 or mod archive",
            str(self._game_data_directory) if self._game_data_directory else "",
            "Archive and patch files (*);;All Files (*.*)",
        )
        if path:
            self._open_archive(Path(path))

    @Slot()
    def selectGameDataDirectory(self) -> None:
        directory = QFileDialog.getExistingDirectory(None, "Select Helldivers 2 data folder")
        if not directory:
            return
        data_directory = Path(directory).resolve()
        if not (data_directory / "bundles.nxa").is_file():
            self._show_error("Invalid game data folder", "Could not find bundles.nxa in this folder.")
            return
        if self._game_data_directory != data_directory:
            self._slim_store = None
        self._game_data_directory = data_directory
        self._save_preferences()
        self._set_status(f"Game data folder set: {data_directory}")
        self.stateChanged.emit()

    @Slot(str)
    def loadArchive(self, value: str) -> None:
        archive_id = value.strip().lower().removeprefix("0x")
        if len(archive_id) != 16 or any(character not in "0123456789abcdef" for character in archive_id):
            self.searchFoundArchives(value)
            return
        self._load_slim_archive(archive_id, self._load_archive_names().get(archive_id))

    @Slot(str)
    def searchFoundArchives(self, query: str) -> None:
        normalized_query = query.strip().casefold()
        matches = sorted([
            (archive_id, name) for archive_id, name in self._load_archive_names().items()
            if not normalized_query or normalized_query in name.casefold()
        ], key=lambda item: item[1].casefold())
        self.found_archives_model.set_entries(matches)
        self.stateChanged.emit()

    @Slot(int)
    def loadFoundArchive(self, row: int) -> None:
        if not 0 <= row < self.found_archives_model.rowCount():
            return
        archive_id, display_name = self.found_archives_model.entry_at(row)
        self._load_slim_archive(archive_id, display_name)

    def _load_slim_archive(self, archive_id: str, display_name: str | None) -> None:
        if self._game_data_directory is None:
            self.selectGameDataDirectory()
            if self._game_data_directory is None:
                return
        try:
            archive = self._open_slim_archive(archive_id)
        except (OSError, ArchiveError) as error:
            self._show_error("Unable to load Slim archive", str(error))
            return
        self._activate_archive(archive)
        group = f"Archive: {display_name or archive_id}"
        opened = 0
        last_document = None
        for entry in archive.entries_of_type(PARTICLE_TYPE_ID):
            document = self._open_archive_particle(entry, group, select=False)
            if document is not None:
                opened += 1
                last_document = document
        if last_document is not None:
            self._sort_documents(last_document)
        self._set_status(f"Loaded {opened} particle resource(s) from {group}")

    def _open_slim_archive(self, archive_id: str) -> ArchiveReader:
        if self._game_data_directory is None:
            raise ArchiveError("Select a Helldivers 2 data folder before loading a Slim archive.")
        if (
            self._slim_store is None
            or self._slim_store.data_directory != self._game_data_directory
        ):
            self._slim_store = SlimArchiveStore(self._game_data_directory)
        return self._slim_store.open_archive(archive_id)

    def _load_archive_names(self) -> dict[str, str]:
        if self._archive_names is not None:
            return self._archive_names
        try:
            with urlopen(self.ARCHIVE_LIST_URL, timeout=8) as response:
                raw_data = json.loads(response.read().decode("utf-8"))
            self._archive_names = {
                archive_id.lower(): f"{category_name}: {name}"
                for category_name, category in raw_data.items()
                for archive_id, name in category.items()
            }
        except (OSError, ValueError, UnicodeDecodeError):
            self._archive_names = {}
        return self._archive_names

    @Slot("QVariantList")
    def openUrls(self, urls) -> None:
        paths = []
        for value in urls:
            url = value if isinstance(value, QUrl) else QUrl(str(value))
            if url.isLocalFile():
                paths.append(Path(url.toLocalFile()))
        self._open_paths(paths)

    def _open_paths(self, paths: list[Path]) -> None:
        for path in paths:
            if path.suffix.lower() == ".pmod":
                self._open_project(path)
            else:
                self._open_particle(path)

    def _open_archive(self, path: Path) -> None:
        try:
            archive = ArchiveReader.open(path)
        except (OSError, ArchiveError) as error:
            self._show_error("Unable to open archive", f"{path.name}\n\n{error}")
            return
        self._activate_archive(archive)
        self._set_status(
            f"Loaded {path.name}: {self.archive_particles_model.rowCount()} particle resource(s)"
        )

    def _activate_archive(self, archive: ArchiveReader) -> None:
        self._archive = archive
        self.archive_particles_model.set_entries(archive.entries_of_type(PARTICLE_TYPE_ID))
        self.asset_links_model.set_links([])
        self._all_texture_bindings = []
        self.texture_bindings_model.set_bindings([])
        self.texture_overview_model.set_bindings([], [])
        self._selected_asset_index = -1
        self._selected_texture_index = -1
        self._texture_system_indices = []
        self._texture_material_ids = []
        self._texture_materials_by_system = {}
        self._selected_texture_system = -1
        self._selected_texture_material = -1
        self._texture_preview_url = ""
        self._texture_original_preview_url = ""
        self._texture_preview_message = "Open an archive particle to preview textures."
        self.stateChanged.emit()

    @Slot(int)
    def openArchiveParticle(self, row: int) -> None:
        if self._archive is None or not 0 <= row < self.archive_particles_model.rowCount():
            return
        entry = self.archive_particles_model.entry_at(row)
        self._open_archive_particle(entry, "", select=True)

    def _open_archive_particle(self, entry, group: str, select: bool):
        if self._archive is None:
            return None
        return self._open_archive_particle_from(self._archive, entry, group, select)

    def _open_archive_particle_from(
        self, archive: ArchiveReader, entry, group: str, select: bool
    ) -> Document | None:
        path = archive.path.with_name(f"{archive.path.name} [{entry.file_id}].particles")
        try:
            effect = ParticleEffect.from_bytes(entry.toc_data)
        except ParticleParseError as error:
            self._show_error("Unable to open archive particle", f"{entry.file_id}\n\n{error}")
            return
        for index, document in enumerate(self.documents_model.documents):
            if document.path == path:
                if group:
                    document.group = group
                if select:
                    self.setCurrentDocument(index)
                return document
        stack = QUndoStack(self)
        document = Document(
            path, effect, stack, group=group, archive=archive,
            archive_entry_id=entry.file_id, title=f"{entry.file_id}.particle",
            source_data=entry.toc_data,
        )
        stack.cleanChanged.connect(lambda _clean, doc=document: self._document_state_changed(doc))
        stack.canUndoChanged.connect(lambda _value: self.stateChanged.emit())
        stack.canRedoChanged.connect(lambda _value: self.stateChanged.emit())
        document_row = self.documents_model.append(document)
        stack.setClean()
        if select:
            self.setCurrentDocument(document_row)
            self._set_status(f"Opened archive particle {entry.file_id}")
        return document

    def _open_particle(
        self, path: Path, note: str = "", group: str = ""
    ) -> Document | None:
        path = path.resolve()
        for index, document in enumerate(self.documents_model.documents):
            if document.path == path:
                if group and document.group != group:
                    document.group = group
                    self._sort_documents(document)
                else:
                    self.setCurrentDocument(index)
                return document
        try:
            effect = ParticleEffect.from_bytes(path.read_bytes())
        except (OSError, ParticleParseError) as error:
            self._show_error("Unable to open particle file", f"{path.name}\n\n{error}")
            return None

        stack = QUndoStack(self)
        document = Document(path, effect, stack, note, group, source_data=effect.original_data)
        stack.cleanChanged.connect(lambda _clean, doc=document: self._document_state_changed(doc))
        stack.canUndoChanged.connect(lambda _value: self.stateChanged.emit())
        stack.canRedoChanged.connect(lambda _value: self.stateChanged.emit())
        row = self.documents_model.append(document)
        stack.setClean()
        self.setCurrentDocument(row)
        self._set_status(f"Opened {path.name}")
        return document

    def _open_project(self, path: Path) -> None:
        missing = []
        try:
            project_data = json.loads(path.read_text(encoding="utf-8"))
            states = project_data.get("selectionStates", {})
            archive_cache: dict[tuple[str, str], ArchiveReader] = {}
            for item in self._flatten_project_structure(project_data.get("structure", [])):
                value = item.get("filepath", "")
                archive_item = item if item.get("type") == "archive_particle" else self._legacy_archive_item(value)
                if archive_item is not None:
                    document, error = self._open_project_archive_particle(
                        archive_item, item.get("note", ""), item.get("_group", ""), path, archive_cache
                    )
                    if error:
                        missing.append(error)
                    state_key = self._archive_state_key(archive_item)
                else:
                    particle_path = Path(value)
                    if not particle_path.is_absolute():
                        particle_path = path.parent / particle_path
                    if not particle_path.exists():
                        missing.append(str(particle_path))
                        continue
                    document = self._open_particle(
                        particle_path, item.get("note", ""), item.get("_group", "")
                    )
                    state_key = value
                if document is None:
                    continue
                state = states.get(state_key, states.get(value, {}))
                document.selections["color"] = self._selection_pairs(state.get("selection", []))
                presets = state.get("presets", [None, None])[:2]
                document.color_presets = [
                    self._selection_pairs(preset) if preset is not None else None
                    for preset in presets
                ]
                while len(document.color_presets) < 2:
                    document.color_presets.append(None)
                enabled_systems = state.get("enabledSystems")
                if isinstance(enabled_systems, list):
                    for system, enabled in zip(document.effect.particle_systems, enabled_systems):
                        system.enabled = bool(enabled)
                document.include_in_patch = bool(item.get("includeInPatch", False))
                document.apply_included = bool(item.get("applyIncluded", False))
                document.patch_entry_id = self._valid_patch_entry_id(item.get("patchEntryId"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            try:
                root = ET.parse(path).getroot()
                files = root.findall("./project/project_files/file")
                for item in files:
                    value = item.findtext("filepath")
                    if not value:
                        continue
                    particle_path = Path(value)
                    if not particle_path.is_absolute():
                        particle_path = path.parent / particle_path
                    if particle_path.exists():
                        self._open_particle(particle_path, item.findtext("note", ""))
                    else:
                        missing.append(str(particle_path))
            except (OSError, ET.ParseError) as error:
                self._show_error("Unable to open project", f"{path.name}\n\n{error}")
                return
        except OSError as error:
            self._show_error("Unable to open project", f"{path.name}\n\n{error}")
            return
        if self.current_document is not None:
            self._sort_documents(self.current_document)
        self._project_path = path.resolve()
        self._last_project_open_directory = self._project_path.parent
        self._save_preferences()
        if missing:
            QMessageBox.warning(
                None,
                "Project files missing",
                "These files could not be found:\n\n" + "\n".join(missing[:10]),
            )

    @staticmethod
    def _legacy_archive_item(value: str) -> dict | None:
        match = re.search(r"(?i)([0-9a-f]{16}) \[(\d+)\]\.particles$", value)
        if match is None:
            return None
        return {
            "type": "archive_particle",
            "archiveSource": "slim",
            "archiveId": match.group(1).lower(),
            "entryId": match.group(2),
        }

    @staticmethod
    def _archive_state_key(item: dict) -> str:
        source = item.get("archiveSource", "slim")
        archive = item.get("archiveId", "") if source == "slim" else item.get("archivePath", "")
        return f"archive:{source}:{archive}:{item.get('entryId', '')}"

    def _open_project_archive_particle(
        self,
        item: dict,
        note: str,
        group: str,
        project_path: Path,
        archive_cache: dict[tuple[str, str], ArchiveReader],
    ) -> tuple[Document | None, str | None]:
        source = item.get("archiveSource", "slim")
        entry_value = item.get("entryId")
        try:
            entry_id = int(str(entry_value))
        except (TypeError, ValueError):
            return None, f"Invalid archive particle entry: {entry_value}"

        if source == "slim":
            archive_id = str(item.get("archiveId", "")).lower().removeprefix("0x")
            if not re.fullmatch(r"[0-9a-f]{16}", archive_id):
                return None, f"Invalid Slim archive ID: {archive_id or '(empty)'}"
            if self._game_data_directory is None:
                return None, f"Archive {archive_id} requires a Helldivers 2 Data folder."
            cache_key = (source, archive_id)
            try:
                archive = archive_cache.get(cache_key)
                if archive is None:
                    archive = self._open_slim_archive(archive_id)
                    archive_cache[cache_key] = archive
            except (OSError, ArchiveError) as error:
                return None, f"Archive {archive_id}: {error}"
        elif source == "file":
            archive_value = str(item.get("archivePath", ""))
            archive_path = Path(archive_value)
            if not archive_path.is_absolute():
                archive_path = project_path.parent / archive_path
            archive_path = archive_path.resolve()
            if not archive_path.is_file():
                return None, str(archive_path)
            cache_key = (source, str(archive_path))
            try:
                archive = archive_cache.get(cache_key)
                if archive is None:
                    archive = ArchiveReader.open(archive_path)
                    archive_cache[cache_key] = archive
            except (OSError, ArchiveError) as error:
                return None, f"Archive {archive_path.name}: {error}"
        else:
            return None, f"Unsupported archive source: {source}"

        entry = archive.get_entry(entry_id, PARTICLE_TYPE_ID)
        if entry is None:
            return None, f"Archive {archive.path.name} does not contain particle {entry_id}."
        document = self._open_archive_particle_from(archive, entry, group, select=True)
        return document, None

    @Slot()
    def saveCurrent(self) -> bool:
        return self.saveParticle()

    @Slot(result=bool)
    def saveParticle(self) -> bool:
        document = self.current_document
        return self._save_document(document) if document is not None and document.archive is None else False

    @Slot()
    def saveCurrentAs(self) -> bool:
        document = self.current_document
        if document is None:
            return False
        if document.archive is not None:
            self._show_error("Archive particle", "Use Write Patch to save archive resources.")
            return False
        path, _ = QFileDialog.getSaveFileName(
            None,
            "Save particle file as",
            str(document.path),
            "Particle Files (*.particles);;All Files (*.*)",
        )
        return self._save_document(document, Path(path)) if path else False

    @Slot()
    def saveAll(self) -> bool:
        success = True
        for document in self.documents_model.documents:
            if document.archive is None and not document.undo_stack.isClean():
                success = self._save_document(document) and success
        return success

    @Slot()
    def saveProject(self) -> None:
        if not self.documents_model.documents:
            return
        if self._project_path is not None:
            self._write_project(self._project_path)
            return
        self.saveProjectAs()

    @Slot()
    def saveProjectAs(self) -> None:
        if not self.documents_model.documents:
            return
        path, _ = QFileDialog.getSaveFileName(
            None,
            "Save PM project",
            str(self._last_project_save_directory) if self._last_project_save_directory else "",
            "PM Projects (*.pmod)",
        )
        if not path:
            return
        self._write_project(Path(path))

    def _write_project(self, output_path: Path) -> None:
        ungrouped_files = []
        grouped_files: dict[str, list[dict]] = {}
        selection_states = {}
        for document in self.documents_model.documents:
            if document.archive is not None and document.archive_entry_id is not None:
                if document.archive._slim_store is not None:
                    file_item = {
                        "type": "archive_particle",
                        "archiveSource": "slim",
                        "archiveId": document.archive.path.name,
                        "entryId": str(document.archive_entry_id),
                        "note": document.note,
                        "includeInPatch": document.include_in_patch,
                        "applyIncluded": document.apply_included,
                    }
                else:
                    try:
                        stored_archive_path = os.path.relpath(document.archive.path, output_path.parent)
                    except ValueError:
                        stored_archive_path = str(document.archive.path)
                    file_item = {
                        "type": "archive_particle",
                        "archiveSource": "file",
                        "archivePath": stored_archive_path,
                        "entryId": str(document.archive_entry_id),
                        "note": document.note,
                        "includeInPatch": document.include_in_patch,
                        "applyIncluded": document.apply_included,
                    }
                stored_path = self._archive_state_key(file_item)
            else:
                try:
                    stored_path = os.path.relpath(document.path, output_path.parent)
                except ValueError:
                    stored_path = str(document.path)
                file_item = {
                    "type": "file",
                    "filepath": stored_path,
                    "note": document.note,
                    "includeInPatch": document.include_in_patch,
                    "applyIncluded": document.apply_included,
                    "patchEntryId": str(document.patch_entry_id) if document.patch_entry_id is not None else "",
                }
            if document.group:
                grouped_files.setdefault(document.group, []).append(file_item)
            else:
                ungrouped_files.append(file_item)
            selection_states[stored_path] = {
                "selection": document.selections.get("color", []),
                "presets": document.color_presets,
                "enabledSystems": [system.enabled for system in document.effect.particle_systems],
            }
        structure = ungrouped_files + [
            {"type": "group", "name": name, "children": files}
            for name, files in grouped_files.items()
        ]
        project_data = {
            "version": 2,
            "project_name": "PM ParticleModder project",
            "structure": structure,
            "selectionStates": selection_states,
        }
        try:
            output_path.write_text(
                json.dumps(project_data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            self._project_path = output_path.resolve()
            self._last_project_save_directory = self._project_path.parent
            self._save_preferences()
            self._set_status(f"Saved project {output_path.name}")
        except OSError as error:
            self._show_error("Unable to save project", str(error))

    @staticmethod
    def _flatten_project_structure(structure, group: str = ""):
        for item in structure:
            if item.get("type") == "group":
                yield from ParticleController._flatten_project_structure(
                    item.get("children", []), item.get("name", "")
                )
            elif item.get("type") in {"file", "archive_particle"}:
                file_item = dict(item)
                file_item["_group"] = group
                yield file_item

    def _save_document(self, document: Document, path: Path | None = None) -> bool:
        target = (path or document.path).resolve()
        temporary_path = None
        try:
            output = document.effect.to_bytes()
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb", delete=False, dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
            ) as temporary:
                temporary.write(output)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, target)
            document.path = target
            document.undo_stack.setClean()
            self.documents_model.refresh(self.documents_model.documents.index(document))
            self.currentDocumentChanged.emit()
            self._set_status(f"Saved {target.name}")
            return True
        except (OSError, ValueError) as error:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            self._show_error("Unable to save particle file", f"{target.name}\n\n{error}")
            return False

    def _stage_archive_document(self, document: Document) -> bool:
        if document.archive is None or document.archive_entry_id is None:
            return False
        entry = document.archive.get_entry(document.archive_entry_id, PARTICLE_TYPE_ID)
        if entry is None:
            self._show_error("Unable to stage particle", "The source archive resource is unavailable.")
            return False
        try:
            output = document.effect.to_bytes()
            document.archive.stage(entry.with_data(output, entry.gpu_data, entry.stream_data))
            self.documents_model.refresh(self.documents_model.documents.index(document))
            self._set_status(f"Staged archive particle {document.archive_entry_id}")
            return True
        except (ArchiveError, ValueError) as error:
            self._show_error("Unable to stage particle", str(error))
            return False

    def _patch_archive(self) -> ArchiveReader | None:
        document = self.current_document
        return document.archive if document is not None and document.archive is not None else self._archive

    def _archives_for_patch(self) -> list[ArchiveReader]:
        archives = []
        for archive in [self._archive, *(document.archive for document in self.documents_model.documents)]:
            if archive is not None and not any(archive is existing for existing in archives):
                archives.append(archive)
        return archives

    @staticmethod
    def _valid_patch_entry_id(value) -> int | None:
        try:
            entry_id = int(str(value), 0)
        except (TypeError, ValueError):
            return None
        return entry_id if 0 <= entry_id <= 0xFFFFFFFFFFFFFFFF else None

    @staticmethod
    def _patch_entry_id_from_path(path: Path) -> int | None:
        return ParticleController._valid_patch_entry_id(path.stem)

    @Slot(int)
    def togglePatchInclude(self, index: int) -> None:
        if not 0 <= index < len(self.documents_model.documents):
            return
        document = self.documents_model.documents[index]
        if document.archive is None and document.patch_entry_id is None:
            document.patch_entry_id = self._patch_entry_id_from_path(document.path)
            if document.patch_entry_id is None:
                value, accepted = QInputDialog.getText(
                    None,
                    "Particle patch ID",
                    "Particle File ID:",
                )
                if not accepted:
                    return
                document.patch_entry_id = self._valid_patch_entry_id(value)
                if document.patch_entry_id is None:
                    self._show_error("Invalid particle ID", "Enter a 64-bit decimal or 0x hexadecimal File ID.")
                    return
        document.include_in_patch = not document.include_in_patch
        if not document.include_in_patch and document.archive is not None and document.archive_entry_id is not None:
            document.archive.staged_entries.pop((document.archive_entry_id, PARTICLE_TYPE_ID), None)
        self._mark_selected_patch_for_write()
        self.documents_model.refresh(index)
        self.stateChanged.emit()

    @Slot(int)
    def toggleApplyInclude(self, index: int) -> None:
        if not 0 <= index < len(self.documents_model.documents):
            return
        document = self.documents_model.documents[index]
        document.apply_included = not document.apply_included
        self.documents_model.refresh(index)
        self.stateChanged.emit()

    @Slot(int)
    def resetDocument(self, index: int) -> None:
        if not 0 <= index < len(self.documents_model.documents):
            return
        document = self.documents_model.documents[index]
        try:
            document.effect = ParticleEffect.from_bytes(document.source_data)
        except ParticleParseError as error:
            self._show_error("Unable to reset particle", str(error))
            return
        document.undo_stack.clear()
        document.undo_stack.setClean()
        document.selections = {"color": [], "opacity": [], "intensity": []}
        document.color_presets = [None, None]
        self._reset_document_texture_replacements(document)
        if document.archive is not None and document.archive_entry_id is not None:
            document.archive.staged_entries.pop((document.archive_entry_id, PARTICLE_TYPE_ID), None)
        self._mark_selected_patch_for_write()
        self.documents_model.refresh(index)
        if index == self._current_index:
            self._current_index = -2
            self.setCurrentDocument(index)
        self.stateChanged.emit()
        self._set_status(f"Reset {document.title or document.path.name}")

    @Slot(int)
    def selectTexture(self, row: int) -> None:
        self._selected_texture_index = row if 0 <= row < self.texture_bindings_model.rowCount() else -1
        self._texture_preview_url = ""
        self._texture_original_preview_url = ""
        self._texture_preview_request += 1
        request_id = self._texture_preview_request
        if self._selected_texture_index < 0:
            self._texture_preview_message = "Select a texture to preview it."
            self.stateChanged.emit()
            return
        binding = self.texture_bindings_model.binding_at(self._selected_texture_index)
        document = self.current_document
        archive = document.archive if document is not None else None
        if archive is None:
            self._texture_preview_message = "This particle is not backed by an archive."
            self.stateChanged.emit()
            return
        self._texture_preview_message = "Loading texture..."
        self._texture_preview_pool.clear()
        task = TexturePreviewTask(request_id, archive, binding)
        task.signals.loaded.connect(self._finish_texture_preview)
        self._texture_preview_pool.start(task)
        self.stateChanged.emit()

    @Slot(int, object, str, str, str)
    def _finish_texture_preview(
        self, request_id: int, binding, preview_url: str, original_preview_url: str, message: str
    ) -> None:
        if request_id != self._texture_preview_request:
            return
        if binding.available:
            self._update_texture_binding(binding)
        self._texture_preview_url = preview_url
        self._texture_original_preview_url = original_preview_url
        self._texture_preview_message = message
        self.stateChanged.emit()

    @Slot(int)
    def selectTextureSystem(self, option_index: int) -> None:
        if not 0 <= option_index < len(self._texture_system_indices):
            return
        self._selected_texture_system = self._texture_system_indices[option_index]
        self._texture_material_ids = self._texture_materials_by_system.get(
            self._selected_texture_system, []
        )
        self._selected_texture_material = self._texture_material_ids[0] if self._texture_material_ids else -1
        self._apply_texture_filter()
        if not self._texture_list_view and self.texture_bindings_model.rowCount() > 0:
            self.selectTexture(0)

    @Slot(int)
    def selectTextureMaterial(self, option_index: int) -> None:
        if not 0 <= option_index < len(self._texture_material_ids):
            return
        self._selected_texture_material = self._texture_material_ids[option_index]
        self._apply_texture_filter()

    @Slot(bool)
    def setTextureListView(self, enabled: bool) -> None:
        if self._texture_list_view == enabled:
            return
        selected_binding = self._selected_texture_binding()
        self._texture_list_view = enabled
        self._texture_overview_request += 1
        self._texture_overview_pool.clear()
        if not enabled and selected_binding is not None:
            self._selected_texture_system = selected_binding.system_index
            self._texture_material_ids = self._texture_materials_by_system.get(
                selected_binding.system_index, []
            )
            self._selected_texture_material = selected_binding.material_id
        self._apply_texture_filter()
        if enabled:
            self._queue_texture_overview_previews()
        elif selected_binding is not None:
            for row in range(self.texture_bindings_model.rowCount()):
                binding = self.texture_bindings_model.binding_at(row)
                if (binding.system_index, binding.material_id, binding.texture_id) == (
                    selected_binding.system_index,
                    selected_binding.material_id,
                    selected_binding.texture_id,
                ):
                    self.selectTexture(row)
                    break

    @Slot(int, str, str)
    def selectTextureBinding(self, system_index: int, material_id: str, texture_id: str) -> None:
        material_value = int(material_id)
        texture_value = int(texture_id)
        for row in range(self.texture_bindings_model.rowCount()):
            binding = self.texture_bindings_model.binding_at(row)
            if (binding.system_index, binding.material_id, binding.texture_id) == (
                system_index, material_value, texture_value,
            ):
                self.selectTexture(row)
                return

    @Slot()
    def importSelectedTexturePng(self) -> None:
        texture_id = self._selected_texture_id()
        binding = self._selected_texture_binding()
        document = self.current_document
        archive = document.archive if document is not None else None
        if texture_id is None or archive is None:
            return
        path, _ = QFileDialog.getOpenFileName(None, "Replace texture from PNG", "", "PNG (*.png)")
        if not path:
            return
        try:
            archive.replace_texture_from_png(texture_id, Path(path))
            document.modified_texture_ids.add(texture_id)
            self._texture_patch_choices[(id(archive), texture_id)] = True
            self.documents_model.refresh(self.documents_model.documents.index(document))
            self._mark_selected_patch_for_write()
            self._reload_selected_texture()
            self._set_status(f"Staged PNG replacement for texture {texture_id}")
        except ArchiveError as error:
            self._show_error("Unable to import PNG texture", str(error))

    @Slot()
    def importSelectedTextureDds(self) -> None:
        texture_id = self._selected_texture_id()
        binding = self._selected_texture_binding()
        document = self.current_document
        archive = document.archive if document is not None else None
        if texture_id is None or archive is None:
            return
        path, _ = QFileDialog.getOpenFileName(None, "Replace texture from DDS", "", "DDS (*.dds)")
        if not path:
            return
        try:
            archive.replace_texture_from_dds(texture_id, Path(path).read_bytes())
            document.modified_texture_ids.add(texture_id)
            self._texture_patch_choices[(id(archive), texture_id)] = True
            self.documents_model.refresh(self.documents_model.documents.index(document))
            self._mark_selected_patch_for_write()
            self._reload_selected_texture()
            self._set_status(f"Staged DDS replacement for texture {texture_id}")
        except (OSError, ArchiveError) as error:
            self._show_error("Unable to import DDS texture", str(error))

    @Slot()
    def resetSelectedTexture(self) -> None:
        binding = self._selected_texture_binding()
        if binding is None:
            return
        key = (binding.texture_id, TEXTURE_TYPE_ID)
        reset = False
        for archive in self._archives_for_patch():
            reset = archive.staged_entries.pop(key, None) is not None or reset
        if not reset:
            return
        self._clear_texture_replacement_tracking(binding.texture_id)
        self._mark_selected_patch_for_write()
        self._reload_selected_texture()
        self._set_status(f"Reset texture {binding.texture_id}")

    @Slot(bool)
    def setSelectedTexturePatchVersion(self, use_imported: bool) -> None:
        binding = self._selected_texture_binding()
        document = self.current_document
        if binding is None or document is None or document.archive is None:
            return
        key = (id(document.archive), binding.texture_id)
        if self._texture_patch_choices.get(key, True) == use_imported:
            return
        self._texture_patch_choices[key] = use_imported
        self._mark_selected_patch_for_write()
        self.stateChanged.emit()

    @Slot(int)
    def toggleParticleSystem(self, system_index: int) -> None:
        document = self.current_document
        if document is None:
            return
        system = next(
            (item for item in document.effect.particle_systems if item.index == system_index), None
        )
        if system is None:
            return
        old_value = system.enabled

        def apply(enabled):
            system.enabled = enabled
            self.visualizer_model.refresh_system(system.index)
            self._refresh_assets()
            self._document_state_changed(document)

        self._push_edit(
            f"{'Enable' if not old_value else 'Disable'} particle system {system.index + 1}",
            apply,
            old_value,
            not old_value,
        )

    def _restore_texture_binding(self, binding) -> None:
        if binding is None:
            return
        try:
            system_option = self._texture_system_indices.index(binding.system_index)
            self.selectTextureSystem(system_option)
            material_option = self._texture_material_ids.index(binding.material_id)
            self.selectTextureMaterial(material_option)
        except ValueError:
            return
        for row in range(self.texture_bindings_model.rowCount()):
            candidate = self.texture_bindings_model.binding_at(row)
            if candidate.texture_id == binding.texture_id:
                self.selectTexture(row)
                return

    def _reload_selected_texture(self) -> None:
        if self._selected_texture_index >= 0:
            self.selectTexture(self._selected_texture_index)
        else:
            self.stateChanged.emit()

    def _clear_texture_replacement_tracking(self, texture_id: int) -> None:
        for document in self.documents_model.documents:
            if texture_id in document.modified_texture_ids:
                document.modified_texture_ids.discard(texture_id)
                self.documents_model.refresh(self.documents_model.documents.index(document))
            if document.archive is not None:
                self._texture_patch_choices.pop((id(document.archive), texture_id), None)

    def _reset_document_texture_replacements(self, document: Document) -> None:
        for texture_id in tuple(document.modified_texture_ids):
            for archive in self._archives_for_patch():
                archive.staged_entries.pop((texture_id, TEXTURE_TYPE_ID), None)
            self._clear_texture_replacement_tracking(texture_id)

    @Slot()
    def exportSelectedTextureDds(self) -> None:
        texture_id, entry = self._selected_texture_entry()
        if texture_id is None or entry is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            None,
            "Export texture as DDS",
            f"{texture_id}.dds",
            "DDS files (*.dds)",
        )
        if not path:
            return
        try:
            Path(path).write_bytes(parse_texture(entry).dds)
            self._set_status(f"Exported texture {texture_id} as DDS")
        except (OSError, ArchiveError) as error:
            self._show_error("Unable to export DDS texture", str(error))

    @Slot()
    def exportSelectedTexturePng(self) -> None:
        texture_id, entry = self._selected_texture_entry()
        if texture_id is None or entry is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            None,
            "Export texture as PNG",
            f"{texture_id}.png",
            "PNG files (*.png)",
        )
        if not path:
            return
        try:
            info = parse_texture(entry)
            cache_directory = Path(tempfile.gettempdir()) / "pm-particlemodder" / "texture-exports"
            preview = dds_to_png(
                preview_dds(info), cache_directory,
                f"{texture_id}-export-{zlib.crc32(info.dds):08x}",
            )
            Path(path).write_bytes(preview.read_bytes())
            self._set_status(f"Exported texture {texture_id} as PNG")
        except (OSError, ArchiveError) as error:
            self._show_error("Unable to export PNG texture", str(error))

    @Slot()
    def writePatch(self) -> None:
        if not self.hasSelectedPatch:
            self._show_error("No patch selected", "Create a patch from the active archive first.")
            return
        target = self._patch_targets[self._selected_patch_index]
        archive = target.archive
        entries: dict[tuple[int, int], ArchiveEntry] = {}
        for document in self.documents_model.documents:
            if not document.include_in_patch:
                continue
            if document.archive is not None:
                if not self._stage_archive_document(document):
                    return
                entries[(document.archive_entry_id, PARTICLE_TYPE_ID)] = document.archive.staged_entries[
                    (document.archive_entry_id, PARTICLE_TYPE_ID)
                ]
            elif document.patch_entry_id is not None:
                entries[(document.patch_entry_id, PARTICLE_TYPE_ID)] = self._standalone_particle_entry(document)

        for source_archive in self._archives_for_patch():
            for key, entry in source_archive.staged_entries.items():
                if entry.type_id != PARTICLE_TYPE_ID and self._should_write_staged_entry(source_archive, entry):
                    entries[key] = entry
        if not entries and not target.needs_write:
            return
        try:
            output = (
                archive.write_patch(target.path, list(entries.values()))
                if entries else self._write_empty_patch(target.path)
            )
            target.needs_write = False
            self._set_status(f"Wrote patch {output.name}")
            self.stateChanged.emit()
        except (OSError, ArchiveError) as error:
            self._show_error("Unable to write patch", str(error))

    @Slot()
    def createPatch(self) -> None:
        archive = self._patch_archive()
        if archive is None:
            self._show_error("No archive loaded", "Load an archive before creating a patch.")
            return
        patch_directory = self._game_data_directory or archive.path.parent
        target_path = self._next_patch_path(patch_directory)
        target = PatchTarget(target_path, target_path.name, archive)
        self._patch_targets.append(target)
        self._selected_patch_index = len(self._patch_targets) - 1
        self._set_status(f"Created patch {target.path.name}")
        self.stateChanged.emit()

    @Slot(int)
    def selectPatch(self, index: int) -> None:
        if not 0 <= index < len(self._patch_targets):
            return
        self._selected_patch_index = index
        self.stateChanged.emit()

    @Slot(str)
    def renameSelectedPatchTo(self, name: str) -> None:
        if not self.hasSelectedPatch:
            return
        current = self._patch_targets[self._selected_patch_index]
        normalized = name.strip()
        if not normalized or normalized == current.name:
            return
        if Path(normalized).name != normalized or any(character in normalized for character in '<>:"/\\|?*'):
            self._show_error("Invalid patch name", "Use a file name only, without path characters.")
            return
        current.name = normalized
        current.path = current.path.with_name(normalized)
        self._set_status(f"Renamed patch to {normalized}")
        self.stateChanged.emit()

    def _next_patch_path(self, directory: Path) -> Path:
        target = directory / f"{self.BASE_PATCH_ARCHIVE_ID}.patch_{self._next_patch_number}"
        self._next_patch_number += 1
        return target

    @staticmethod
    def _write_empty_patch(path: Path) -> Path:
        output = path.expanduser().resolve()
        write_patch_archive(output, [])
        return output

    def _mark_selected_patch_for_write(self) -> None:
        if self.hasSelectedPatch:
            self._patch_targets[self._selected_patch_index].needs_write = True

    def _should_write_staged_entry(self, archive: ArchiveReader, entry: ArchiveEntry) -> bool:
        return (
            entry.type_id != TEXTURE_TYPE_ID
            or self._texture_patch_choices.get((id(archive), entry.file_id), True)
        )

    @staticmethod
    def _standalone_particle_entry(document: Document) -> ArchiveEntry:
        return ArchiveEntry(
            file_id=document.patch_entry_id,
            type_id=PARTICLE_TYPE_ID,
            toc_offset=0,
            stream_offset=0,
            gpu_offset=0,
            unknown1=0,
            unknown2=0,
            toc_size=0,
            stream_size=0,
            gpu_size=0,
            unknown3=16,
            unknown4=64,
            index=0,
            toc_data=document.effect.to_bytes(),
            gpu_data=b"",
            stream_data=b"",
        )

    def _selected_texture_id(self):
        texture_id, _entry = self._selected_texture_entry()
        return texture_id

    def _selected_texture_entry(self):
        binding = self._selected_texture_binding()
        document = self.current_document
        archive = document.archive if document is not None else None
        if binding is None or archive is None:
            return None, None
        try:
            entry = archive.find_entry(binding.texture_id, TEXTURE_TYPE_ID)
        except ArchiveError:
            return None, None
        return (binding.texture_id, entry) if entry is not None else (None, None)

    def _selected_texture_binding(self):
        if not 0 <= self._selected_texture_index < self.texture_bindings_model.rowCount():
            return None
        return self.texture_bindings_model.binding_at(self._selected_texture_index)

    def _refresh_assets(self) -> None:
        document = self.current_document
        if document is not None and document.archive is not None:
            self.asset_links_model.set_links(document.archive.particle_assets(document.effect))
            self._all_texture_bindings = document.archive.texture_bindings(document.effect)
            self._texture_materials_by_system = {}
            textured_materials = {
                (binding.system_index, binding.material_id)
                for binding in self._all_texture_bindings
            }
            particle_material_ids = document.archive.particle_material_ids(document.effect)
            self._material_ids_by_system = {}
            for system_index, material_id in particle_material_ids:
                self._material_ids_by_system.setdefault(system_index, []).append(material_id)
            self._material_system_indices = list(self._material_ids_by_system)
            self._selected_material_system = self._material_system_indices[0] if self._material_system_indices else -1
            selected_materials = self._material_ids_by_system.get(self._selected_material_system, [])
            self._selected_material_id = selected_materials[0] if selected_materials else -1
            self._refresh_material_variables()
            for system_index, material_id in particle_material_ids:
                if (system_index, material_id) in textured_materials:
                    self._texture_materials_by_system.setdefault(system_index, []).append(material_id)
            self._texture_system_indices = list(self._texture_materials_by_system)
            self._selected_texture_system = self._texture_system_indices[0] if self._texture_system_indices else -1
            self._texture_material_ids = self._texture_materials_by_system.get(
                self._selected_texture_system, []
            )
            self._selected_texture_material = self._texture_material_ids[0] if self._texture_material_ids else -1
            self.texture_overview_model.set_bindings(
                self._all_texture_bindings, self._texture_system_indices
            )
        else:
            self.asset_links_model.set_links([])
            self._all_texture_bindings = []
            self._texture_system_indices = []
            self._texture_material_ids = []
            self._texture_materials_by_system = {}
            self._material_ids_by_system = {}
            self._material_system_indices = []
            self._selected_material_system = -1
            self._selected_material_id = -1
            self.material_variable_model.set_variables([])
            self.texture_overview_model.set_bindings([], [])
            self._selected_texture_system = -1
            self._selected_texture_material = -1
        self._selected_asset_index = -1
        self._apply_texture_filter(emit_state=False)
        self.stateChanged.emit()
        if self._texture_list_view:
            self._queue_texture_overview_previews()

    def _refresh_material_variables(self) -> None:
        document = self.current_document
        if document is None or document.archive is None or self._selected_material_id < 0:
            self.material_variable_model.set_variables([])
            return
        try:
            entry = document.archive.find_entry(self._selected_material_id, MATERIAL_TYPE_ID)
            material = parse_material(entry.toc_data) if entry is not None else None
        except ArchiveError:
            material = None
        self.material_variable_model.set_variables(material.shader_variables if material else [])

    @Slot(int)
    def selectMaterialSystem(self, option_index: int) -> None:
        if not 0 <= option_index < len(self._material_system_indices):
            return
        self._selected_material_system = self._material_system_indices[option_index]
        materials = self._material_ids_by_system.get(self._selected_material_system, [])
        self._selected_material_id = materials[0] if materials else -1
        self._refresh_material_variables()
        self.stateChanged.emit()

    @Slot(int)
    def selectMaterial(self, option_index: int) -> None:
        materials = self._material_ids_by_system.get(self._selected_material_system, [])
        if not 0 <= option_index < len(materials):
            return
        self._selected_material_id = materials[option_index]
        self._refresh_material_variables()
        self.stateChanged.emit()

    @Slot(int, int, str)
    def setMaterialVariableValue(self, variable_index: int, value_index: int, text: str) -> None:
        document = self.current_document
        if document is None or document.archive is None or self._selected_material_id < 0:
            return
        try:
            value = float(text)
            if not math.isfinite(value):
                raise ValueError
            variable = self.material_variable_model.variables[variable_index]
            entry = document.archive.find_entry(self._selected_material_id, MATERIAL_TYPE_ID)
            if entry is None:
                raise ArchiveError("Material resource was not found.")
            document.archive.stage(replace_material_variable(entry, variable, value_index, value))
        except (ValueError, IndexError, ArchiveError):
            self._refresh_material_variables()
            return
        self._mark_selected_patch_for_write()
        self._refresh_material_variables()
        self._set_status(f"Staged material {self._selected_material_id}")

    @Slot(int)
    def pickMaterialVariableColor(self, variable_index: int) -> None:
        document = self.current_document
        if document is None or document.archive is None or self._selected_material_id < 0:
            return
        try:
            variable = self.material_variable_model.variables[variable_index]
            initial = QColor.fromRgbF(*variable.values[:3])
            color = QColorDialog.getColor(initial, None, "Material shader color")
            if not color.isValid():
                return
            entry = document.archive.find_entry(self._selected_material_id, MATERIAL_TYPE_ID)
            if entry is None:
                raise ArchiveError("Material resource was not found.")
            for value_index, value in enumerate((color.redF(), color.greenF(), color.blueF())):
                entry = replace_material_variable(entry, variable, value_index, value)
            document.archive.stage(entry)
        except (IndexError, ArchiveError):
            self._refresh_material_variables()
            return
        self._mark_selected_patch_for_write()
        self._refresh_material_variables()
        self._set_status(f"Staged material {self._selected_material_id}")

    def _mesh_archive_locations(self, document: Document | None) -> dict[int, str]:
        if document is None or document.archive is None:
            return {}
        locations: dict[int, str] = {}
        archives = [document.archive, *self._archives_for_patch()]
        for system in document.effect.particle_systems:
            visualizer = system.visualizer
            if visualizer is None or visualizer.mesh_id is None or visualizer.unit_id is None:
                continue
            for archive in archives:
                archive_id = archive.resource_archive_id(visualizer.unit_id, UNIT_TYPE_ID)
                if archive_id is not None:
                    locations[system.index] = archive_id
                    break
            else:
                locations[system.index] = "Not found in available archives"
        return locations

    def _queue_texture_overview_previews(self) -> None:
        self._texture_overview_request += 1
        request_id = self._texture_overview_request
        self._texture_overview_pool.clear()
        document = self.current_document
        archive = document.archive if document is not None else None
        if archive is None:
            return
        pending = [
            replace(binding, preview_state="loading")
            if binding.preview_state != "ready" else binding
            for binding in self._all_texture_bindings
        ]
        self._all_texture_bindings = pending
        self.texture_bindings_model.set_bindings(pending)
        self.texture_overview_model.set_bindings(pending, self._texture_system_indices)
        for binding in pending:
            if binding.preview_state != "loading":
                continue
            task = TexturePreviewTask(request_id, archive, binding)
            task.signals.loaded.connect(self._finish_texture_overview_preview)
            self._texture_overview_pool.start(task)
        self.stateChanged.emit()

    @Slot(int, object, str, str)
    def _finish_texture_overview_preview(self, request_id: int, binding, _preview_url: str, _message: str) -> None:
        if request_id != self._texture_overview_request or not self._texture_list_view:
            return
        self._update_texture_binding(binding)
        self.stateChanged.emit()

    def _update_texture_binding(self, binding) -> None:
        self._all_texture_bindings = [
            binding if (item.system_index, item.material_id, item.texture_id) ==
            (binding.system_index, binding.material_id, binding.texture_id) else item
            for item in self._all_texture_bindings
        ]
        for row in range(self.texture_bindings_model.rowCount()):
            item = self.texture_bindings_model.binding_at(row)
            if (item.system_index, item.material_id, item.texture_id) == (
                binding.system_index, binding.material_id, binding.texture_id,
            ):
                self.texture_bindings_model.update_binding(row, binding)
                break
        self.texture_overview_model.update_binding(binding)

    def _apply_texture_filter(self, emit_state: bool = True) -> None:
        self._texture_preview_request += 1
        self.texture_bindings_model.set_bindings([
            binding for binding in self._all_texture_bindings
            if self._texture_list_view or (
                binding.system_index == self._selected_texture_system
                and binding.material_id == self._selected_texture_material
            )
        ])
        self._selected_texture_index = -1
        self._texture_preview_url = ""
        self._texture_original_preview_url = ""
        self._texture_preview_message = "Select a texture to preview it."
        if emit_state:
            self.stateChanged.emit()

    @Slot(int)
    def setCurrentDocument(self, index: int) -> None:
        if index == self._current_index:
            return
        self._current_index = index if 0 <= index < len(self.documents_model.documents) else -1
        effect = self.current_document.effect if self.current_document else None
        self.color_model.set_effect(effect)
        self.opacity_model.set_effect(effect)
        self.intensity_model.set_effect(effect)
        active_archive = self.current_document.archive if self.current_document else None
        for archive in self._archives_for_patch():
            if archive is not active_archive and hasattr(archive, "clear_payload_cache"):
                archive.clear_payload_cache()
        self._refresh_assets()
        self.visualizer_model.set_effect(effect, self._mesh_archive_locations(self.current_document))
        self.currentDocumentChanged.emit()
        self.stateChanged.emit()

    def _sort_documents(self, current_document: Document) -> None:
        self.documents_model.sort_by_group()
        current_index = self.documents_model.documents.index(current_document)
        self._current_index = -2
        self.setCurrentDocument(current_index)

    def _documents_for_indexes(self, indexes) -> list[Document]:
        documents = []
        seen = set()
        for value in indexes:
            index = int(value)
            if index in seen or not 0 <= index < len(self.documents_model.documents):
                continue
            seen.add(index)
            documents.append(self.documents_model.documents[index])
        return documents

    def _set_documents_group(self, documents: list[Document], group: str) -> None:
        if not documents:
            return
        normalized_group = " ".join(group.split())
        changed_documents = [
            document
            for document in documents
            if document.group != normalized_group
        ]
        if not changed_documents:
            return
        current_document = self.current_document or documents[0]
        for document in changed_documents:
            document.group = normalized_group
        self._sort_documents(current_document)
        label = normalized_group or "Ungrouped"
        self._set_status(f"Moved {len(changed_documents)} particle file(s) to {label}")

    def _set_document_group(self, document: Document, group: str) -> None:
        self._set_documents_group([document], group)

    @Slot("QVariantList")
    def createGroup(self, indexes) -> None:
        documents = self._documents_for_indexes(indexes)
        if not documents:
            return
        group, accepted = QInputDialog.getText(
            None,
            "Create particle group",
            "Group name:",
        )
        normalized_group = " ".join(group.split())
        if accepted and normalized_group:
            self._set_documents_group(documents, normalized_group)

    @Slot("QVariantList", str)
    def addDocumentsToGroup(self, indexes, group: str) -> None:
        self._set_documents_group(self._documents_for_indexes(indexes), group)

    @Slot("QVariantList")
    def removeDocumentsFromGroup(self, indexes) -> None:
        self._set_documents_group(self._documents_for_indexes(indexes), "")

    @Slot(str)
    def renameGroup(self, group: str) -> None:
        if not group or group == "Ungrouped":
            return
        new_group, accepted = QInputDialog.getText(
            None,
            "Rename group",
            "Group name:",
            text=group,
        )
        if not accepted:
            return
        normalized_group = " ".join(new_group.split())
        documents = [
            document
            for document in self.documents_model.documents
            if document.group == group
        ]
        if not documents:
            return
        for document in documents:
            document.group = normalized_group
        self._sort_documents(self.current_document or documents[0])
        self._set_status(f"Renamed group {group} to {normalized_group or 'Ungrouped'}")

    @Slot(str)
    def ungroupGroup(self, group: str) -> None:
        documents = [
            document
            for document in self.documents_model.documents
            if document.group == group
        ]
        if not documents:
            return
        current_document = self.current_document or documents[0]
        for document in documents:
            document.group = ""
        self._sort_documents(current_document)
        self._set_status(f"Ungrouped {len(documents)} particle files")

    @Slot("QVariantList")
    def closeDocuments(self, indexes) -> None:
        for index in sorted({int(value) for value in indexes}, reverse=True):
            if not self.closeDocument(index):
                break

    @Slot(int, result=bool)
    def closeDocument(self, index: int) -> bool:
        if not 0 <= index < len(self.documents_model.documents):
            return True
        document = self.documents_model.documents[index]
        if not self._confirm_close(document):
            return False
        previous_current = self._current_index
        self.documents_model.remove(index)
        if not self.documents_model.documents:
            next_index = -1
        elif previous_current == index:
            next_index = min(index, len(self.documents_model.documents) - 1)
        elif previous_current > index:
            next_index = previous_current - 1
        else:
            next_index = previous_current
        self._current_index = -2
        self.setCurrentDocument(next_index)
        return True

    @Slot(result=bool)
    def requestExit(self) -> bool:
        for document in list(self.documents_model.documents):
            if not self._confirm_close(document):
                return False
        return True

    def _confirm_close(self, document: Document) -> bool:
        if document.undo_stack.isClean():
            return True
        result = QMessageBox.question(
            None,
            "Unsaved changes",
            f"Save changes to {document.path.name}?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if result == QMessageBox.StandardButton.Cancel:
            return False
        if result == QMessageBox.StandardButton.Save:
            return self._save_document(document)
        return True

    @Slot()
    def undo(self) -> None:
        if self.current_document:
            self.current_document.undo_stack.undo()

    @Slot()
    def redo(self) -> None:
        if self.current_document:
            self.current_document.undo_stack.redo()

    @Slot(str, int, int, str, result=bool)
    def setTableCell(self, kind: str, row: int, column: int, text: str) -> bool:
        model = self._graph_model(kind)
        if model is None or not (0 <= row < model.rowCount()) or not (0 <= column < 20):
            return False
        try:
            edit = self._make_cell_edit(model, row, column, text)
        except ValueError as error:
            self._show_error("Invalid cell value", str(error))
            model.refresh_cells([(row, column)])
            return False
        if edit is None:
            return True
        setter, old_value, new_value = edit
        if old_value == new_value:
            return True

        def apply(value):
            setter(value)
            model.refresh_cells([(row, column)])

        self._push_edit(f"Edit {kind} cell", apply, old_value, new_value)
        return True

    @Slot(str, "QVariantList", str)
    def fillTable(self, kind: str, selection, text: str) -> None:
        current_document = self.current_document
        current_cells = self._selection_pairs(selection)
        if current_document is None:
            return
        changed_cells = self._fill_document_table(current_document, kind, current_cells, text)
        if changed_cells:
            self._set_status(f"Filled {changed_cells} {kind} cells in current particle")

    @Slot(str, str)
    def fillAppliedTables(self, kind: str, text: str) -> None:
        changed_cells = 0
        changed_documents = 0
        for document in self.documents_model.documents:
            if not document.apply_included:
                continue
            count = self._fill_document_table(document, kind, document.selections.get(kind, []), text)
            if count:
                changed_cells += count
                changed_documents += 1
        if changed_cells:
            self._set_status(
                f"Filled {changed_cells} {kind} cells across {changed_documents} applied particles"
            )

    @Slot(str)
    def selectAllTableCells(self, kind: str) -> None:
        document = self.current_document
        if document is None:
            return
        document.selections[kind] = self._all_table_cells(document, kind)
        self.tableSelectionsChanged.emit(kind)

    @Slot(str)
    def clearTableSelection(self, kind: str) -> None:
        document = self.current_document
        if document is None:
            return
        document.selections[kind] = []
        self.tableSelectionsChanged.emit(kind)

    @Slot(str)
    def selectAllLoadedTableCells(self, kind: str) -> None:
        changed = False
        for document in self.documents_model.documents:
            cells = self._all_table_cells(document, kind)
            if document.selections.get(kind) != cells:
                document.selections[kind] = cells
                changed = True
        if changed:
            self.tableSelectionsChanged.emit(kind)
            self._set_status(f"Selected all {kind} cells in loaded particles")

    @Slot(str)
    def clearAllLoadedTableSelections(self, kind: str) -> None:
        changed = False
        for document in self.documents_model.documents:
            if document.selections.get(kind):
                document.selections[kind] = []
                changed = True
        if changed:
            self.tableSelectionsChanged.emit(kind)
            self._set_status(f"Cleared {kind} selections in loaded particles")

    @Slot(str, "QVariantList")
    def pasteTable(self, kind: str, selection) -> None:
        model = self._graph_model(kind)
        selected_cells = self._selection_pairs(selection)
        text = QApplication.clipboard().text().replace("\r\n", "\n").rstrip("\n")
        if model is None or not selected_cells or not text:
            return
        if "\n" not in text and "\t" not in text:
            self.fillTable(kind, selected_cells, text)
            return

        matrix = [line.split("\t") for line in text.split("\n")]
        start_row = min(row for row, _column in selected_cells)
        start_column = min(column for _row, column in selected_cells)
        targets = []
        try:
            for row_offset, values in enumerate(matrix):
                for column_offset, value in enumerate(values):
                    row = start_row + row_offset
                    column = start_column + column_offset
                    if row >= model.rowCount() or column >= model.columnCount():
                        continue
                    edit = self._make_cell_edit(model, row, column, value)
                    if edit is not None:
                        targets.append(((row, column), edit))
        except ValueError as error:
            self._show_error("Unable to paste cells", str(error))
            return
        cells = [cell for cell, _edit in targets]
        edits = [edit for _cell, edit in targets]
        self._push_cell_edits(f"Paste {len(cells)} {kind} cells", model, cells, edits)

    @Slot(str, "QVariantList")
    def copyTable(self, kind: str, selection) -> None:
        model = self._graph_model(kind)
        cells = set(self._selection_pairs(selection))
        if model is None or not cells:
            return
        min_row = min(row for row, _column in cells)
        max_row = max(row for row, _column in cells)
        min_column = min(column for _row, column in cells)
        max_column = max(column for _row, column in cells)
        rows = []
        for row in range(min_row, max_row + 1):
            rows.append("\t".join(
                model.value_at(row, column) if (row, column) in cells else ""
                for column in range(min_column, max_column + 1)
            ))
        QApplication.clipboard().setText("\n".join(rows))
        self._set_status(f"Copied {len(cells)} cells")

    @Slot(str, result=str)
    def pickApplyColor(self, current_rgb: str) -> str:
        try:
            parts = [part.strip() for part in current_rgb.strip().strip("()[]").split(",")]
            if len(parts) != 3:
                raise ValueError
            initial = QColor(*[
                round(max(0.0, min(255.0, self._parse_number(part))))
                for part in parts
            ])
        except ValueError:
            initial = QColor(255, 255, 255)

        selected = QColorDialog.getColor(
            initial,
            None,
            "Pick RGB / Hue",
            QColorDialog.ColorDialogOption.DontUseNativeDialog,
        )
        if not selected.isValid():
            return ""
        self._remember_custom_picker_color(selected)
        return f"{selected.red()}, {selected.green()}, {selected.blue()}"

    @staticmethod
    def _default_settings_path() -> Path:
        location = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppConfigLocation
        )
        return Path(location) / "preferences.json"

    def _load_preferences(self) -> None:
        try:
            data = json.loads(self._settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            data = {}

        game_data_path = data.get("gameDataDirectory")
        if isinstance(game_data_path, str):
            candidate = Path(game_data_path).expanduser()
            if (candidate / "bundles.nxa").is_file():
                self._game_data_directory = candidate.resolve()

        colors = data.get("customPickerColors", [])
        if isinstance(colors, list):
            self._custom_picker_colors = self._valid_picker_colors(colors)
            self._apply_custom_picker_colors()

        self._last_project_open_directory = self._preference_directory(
            data.get("lastProjectOpenDirectory")
        )
        self._last_project_save_directory = self._preference_directory(
            data.get("lastProjectSaveDirectory")
        )

    def _save_preferences(self) -> None:
        data = {
            "gameDataDirectory": str(self._game_data_directory) if self._game_data_directory else "",
            "customPickerColors": self._custom_picker_colors,
            "lastProjectOpenDirectory": (
                str(self._last_project_open_directory) if self._last_project_open_directory else ""
            ),
            "lastProjectSaveDirectory": (
                str(self._last_project_save_directory) if self._last_project_save_directory else ""
            ),
        }
        try:
            self._settings_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._settings_path.with_suffix(self._settings_path.suffix + ".tmp")
            temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
            temporary.replace(self._settings_path)
        except OSError:
            pass

    @staticmethod
    def _preference_directory(value) -> Path | None:
        if not isinstance(value, str) or not value:
            return None
        candidate = Path(value).expanduser()
        try:
            return candidate.resolve() if candidate.is_dir() else None
        except OSError:
            return None

    @staticmethod
    def _valid_picker_colors(colors) -> list[str]:
        maximum = QColorDialog.customCount()
        valid = []
        for value in colors:
            color = QColor(str(value))
            if color.isValid() and color.name() not in valid:
                valid.append(color.name())
            if len(valid) >= maximum:
                break
        return valid

    def _apply_custom_picker_colors(self) -> None:
        for index, value in enumerate(self._custom_picker_colors):
            QColorDialog.setCustomColor(index, QColor(value).rgb())

    def _remember_custom_picker_color(self, color: QColor) -> None:
        value = color.name()
        self._custom_picker_colors = self._valid_picker_colors(
            [value] + self._custom_picker_colors
        )
        self._apply_custom_picker_colors()
        self._save_preferences()
        self.stateChanged.emit()

    @Slot(str, "QVariantList")
    def updateSelection(self, kind: str, selection) -> None:
        document = self.current_document
        if document is not None and kind in document.selections:
            document.selections[kind] = self._selection_pairs(selection)

    @Slot(str, result="QVariantList")
    def selectionFor(self, kind: str):
        document = self.current_document
        if document is None:
            return []
        return [[row, column] for row, column in document.selections.get(kind, [])]

    @Slot(int, "QVariantList")
    def saveColorPreset(self, preset_index: int, selection) -> None:
        document = self.current_document
        cells = self._selection_pairs(selection)
        if document is None or not 0 <= preset_index < 2 or not cells:
            return
        document.color_presets[preset_index] = cells
        self._set_status(f"Saved color selection P{preset_index + 1}")

    @Slot(int, result="QVariantList")
    def colorPreset(self, preset_index: int):
        document = self.current_document
        if document is None or not 0 <= preset_index < 2:
            return []
        preset = document.color_presets[preset_index]
        return [] if preset is None else [[row, column] for row, column in preset]

    def _make_cell_edit(self, model, row: int, column: int, text: str):
        if not (0 <= row < model.rowCount() and 0 <= column < model.columnCount()):
            return None
        return self._make_graph_cell_edit(model.graph_at(row), column, text)

    def _make_graph_cell_edit(self, graph: Graph | ColorGraph, column: int, text: str):
        if not 0 <= column < 20:
            return None
        point = column // 2
        if column % 2 == 0:
            values = graph.x
            new_value = self._parse_number(text)
        elif isinstance(graph, Graph):
            values = graph.y
            new_value = self._parse_number(text)
        elif isinstance(graph, ColorGraph):
            values = graph.colors[point]
            old_value = list(values)
            cleaned = text.strip().strip("()[]")
            parts = [part.strip() for part in cleaned.split(",")]
            if len(parts) != 3:
                raise ValueError("Color cells require three comma-separated RGB values.")
            new_value = [max(0.0, min(255.0, self._parse_number(part))) for part in parts]

            def setter(value, target=values):
                target[:] = value

            return setter, old_value, new_value
        else:
            return None
        old_value = values[point]

        def setter(value, target=values, target_point=point):
            target[target_point] = value

        return setter, old_value, new_value

    @staticmethod
    def _document_graphs(document: Document, kind: str) -> list[Graph | ColorGraph]:
        attribute = {
            "color": "color_graphs",
            "opacity": "opacity_graphs",
            "intensity": "scale_graphs",
        }.get(kind)
        if attribute is None:
            return []
        return [
            graph
            for system in document.effect.particle_systems
            for graph in getattr(system, attribute)
        ]

    def _all_table_cells(self, document: Document, kind: str) -> list[tuple[int, int]]:
        return [
            (row, column)
            for row, _graph in enumerate(self._document_graphs(document, kind))
            for column in range(20)
        ]

    def _fill_document_table(self, document: Document, kind: str, cells, text: str) -> int:
        graphs = self._document_graphs(document, kind)
        pairs = self._selection_pairs(cells)
        if kind == "color":
            pairs = [(row, column) for row, column in pairs if column % 2 == 1]
        if not graphs or not pairs:
            return 0
        try:
            edits = [
                edit
                for row, column in pairs
                if 0 <= row < len(graphs)
                and (edit := self._make_graph_cell_edit(graphs[row], column, text)) is not None
                and edit[1] != edit[2]
            ]
        except ValueError as error:
            self._show_error("Unable to fill selection", str(error))
            return 0
        if not edits:
            return 0

        def refresh():
            if document is self.current_document:
                model = self._graph_model(kind)
                if model is not None:
                    model.refresh_cells(pairs)
            self._document_state_changed(document)

        document.undo_stack.push(BulkEditCommand(f"Fill {len(edits)} {kind} cells", edits, refresh))
        return len(edits)

    @staticmethod
    def _parse_number(text: str) -> float:
        try:
            value = float(text.strip())
        except ValueError as error:
            raise ValueError(f"'{text}' is not a valid number.") from error
        if not math.isfinite(value):
            raise ValueError("Cell values must be finite numbers.")
        return value

    def _push_cell_edits(self, label, model, cells, edits) -> None:
        document = self.current_document
        if document is None or not edits:
            return

        def refresh():
            model.refresh_cells(cells)

        document.undo_stack.push(BulkEditCommand(label, edits, refresh))
        self._set_status(label)

    @Slot(str, str)
    def setLifetime(self, field: str, text: str) -> None:
        document = self.current_document
        if document is None or field not in {"min", "max"}:
            return
        try:
            value = float(text)
            if not math.isfinite(value):
                raise ValueError
        except ValueError:
            self._show_error("Invalid lifetime", "Lifetime must be a finite number.")
            self.currentDocumentChanged.emit()
            return

        effect = document.effect
        attribute = "min_lifetime" if field == "min" else "max_lifetime"
        other = effect.max_lifetime if field == "min" else effect.min_lifetime
        if (field == "min" and value > other) or (field == "max" and value < other):
            self._show_error("Invalid lifetime", "Minimum lifetime cannot exceed maximum lifetime.")
            self.currentDocumentChanged.emit()
            return
        old_value = getattr(effect, attribute)
        if old_value == value:
            return

        def apply(new_value):
            setattr(effect, attribute, new_value)
            self.currentDocumentChanged.emit()

        self._push_edit(f"Edit {field} lifetime", apply, old_value, value)

    @Slot(int, str, str)
    def setVisualizerId(self, row: int, field: str, text: str) -> None:
        if not 0 <= row < self.visualizer_model.rowCount():
            return
        attribute = {"material": "material_id", "unit": "unit_id", "mesh": "mesh_id"}.get(field)
        if attribute is None:
            return
        try:
            value = int(text, 0)
            if not 0 <= value <= 0xFFFFFFFFFFFFFFFF:
                raise ValueError
        except ValueError:
            self._show_error("Invalid asset ID", "Use an unsigned 64-bit decimal or 0x-prefixed value.")
            self.visualizer_model.refresh(row)
            return
        visualizer = self.visualizer_model.visualizer_at(row)
        if visualizer is None:
            return
        old_value = getattr(visualizer, attribute)
        if old_value is None or old_value == value:
            return

        def apply(new_value):
            setattr(visualizer, attribute, new_value)
            self._refresh_assets()
            self.visualizer_model.set_effect(document.effect, self._mesh_archive_locations(document))

        self._push_edit(f"Edit {field} ID", apply, old_value, value)

    def _graph_model(self, kind: str) -> ParticleTableModel | None:
        return {
            "color": self.color_model,
            "opacity": self.opacity_model,
            "intensity": self.intensity_model,
        }.get(kind)

    @staticmethod
    def _selection_pairs(selection) -> list[tuple[int, int]]:
        pairs = []
        if selection is None:
            return pairs
        for item in selection:
            try:
                if isinstance(item, dict):
                    row, column = int(item["row"]), int(item["column"])
                else:
                    row, column = int(item[0]), int(item[1])
            except (KeyError, TypeError, ValueError, IndexError):
                continue
            if row >= 0 and column >= 0:
                pairs.append((row, column))
        return sorted(set(pairs))

    def _push_edit(self, label: str, apply, old_value, new_value) -> None:
        document = self.current_document
        if document is not None:
            document.undo_stack.push(ValueEditCommand(label, apply, old_value, new_value))

    def _document_state_changed(self, document: Document) -> None:
        try:
            row = self.documents_model.documents.index(document)
        except ValueError:
            return
        self.documents_model.refresh(row)
        self.stateChanged.emit()

    def _set_status(self, message: str) -> None:
        self._status = message
        self.statusChanged.emit()

    @staticmethod
    def _show_error(title: str, message: str) -> None:
        QMessageBox.critical(None, title, message)
