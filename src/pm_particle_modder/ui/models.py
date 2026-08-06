from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QAbstractListModel,
    QAbstractTableModel,
    QByteArray,
    QModelIndex,
    Qt,
    Slot,
)

from pm_particle_modder.core import ArchiveEntry, AssetLink, ColorGraph, Graph, ParticleEffect, shader_variable_name, ShaderVariableInfo, TextureBinding, Visualizer


class DocumentListModel(QAbstractListModel):
    TitleRole = Qt.ItemDataRole.UserRole + 1
    PathRole = TitleRole + 1
    DirtyRole = PathRole + 1
    VersionRole = DirtyRole + 1
    GroupRole = VersionRole + 1
    ArchiveRole = GroupRole + 1
    PatchIncludedRole = ArchiveRole + 1
    ResettableRole = PatchIncludedRole + 1
    ApplyIncludedRole = ResettableRole + 1

    def __init__(self):
        super().__init__()
        self.documents = []

    def roleNames(self):
        return {
            self.TitleRole: QByteArray(b"title"),
            self.PathRole: QByteArray(b"filePath"),
            self.DirtyRole: QByteArray(b"dirty"),
            self.VersionRole: QByteArray(b"version"),
            self.GroupRole: QByteArray(b"group"),
            self.ArchiveRole: QByteArray(b"archiveBacked"),
            self.PatchIncludedRole: QByteArray(b"patchIncluded"),
            self.ResettableRole: QByteArray(b"resettable"),
            self.ApplyIncludedRole: QByteArray(b"applyIncluded"),
        }

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.documents)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.documents):
            return None
        document = self.documents[index.row()]
        if role == self.TitleRole:
            return document.title or Path(document.path).name
        if role == self.PathRole:
            return str(document.path)
        if role == self.DirtyRole:
            return not document.undo_stack.isClean()
        if role == self.VersionRole:
            return f"0x{document.effect.version:X}"
        if role == self.GroupRole:
            return document.group or "Ungrouped"
        if role == self.ArchiveRole:
            return document.archive is not None
        if role == self.PatchIncludedRole:
            return document.include_in_patch
        if role == self.ApplyIncludedRole:
            return document.apply_included
        if role == self.ResettableRole:
            try:
                return (
                    bool(document.modified_texture_ids)
                    or bool(document.source_data) and document.effect.to_bytes() != document.source_data
                )
            except ValueError:
                return not document.undo_stack.isClean()
        return None

    def append(self, document) -> int:
        row = len(self.documents)
        self.beginInsertRows(QModelIndex(), row, row)
        self.documents.append(document)
        self.endInsertRows()
        return row

    def remove(self, row: int):
        self.beginRemoveRows(QModelIndex(), row, row)
        document = self.documents.pop(row)
        self.endRemoveRows()
        return document

    def refresh(self, row: int) -> None:
        if 0 <= row < len(self.documents):
            index = self.index(row, 0)
            self.dataChanged.emit(index, index, list(self.roleNames()))

    def sort_by_group(self) -> None:
        self.beginResetModel()
        self.documents.sort(
            key=lambda document: (
                document.group.casefold() if document.group else "\uffff",
                document.path.name.casefold(),
            )
        )
        self.endResetModel()


class ParticleTableModel(QAbstractTableModel):
    CellColorRole = Qt.ItemDataRole.UserRole + 1
    TimeCellRole = CellColorRole + 1

    def __init__(self, kind: str):
        super().__init__()
        self.kind = kind
        self.entries: list[tuple[int, int, Graph | ColorGraph]] = []
        self.edit_handler = None

    def roleNames(self):
        return {
            Qt.ItemDataRole.DisplayRole: QByteArray(b"display"),
            Qt.ItemDataRole.EditRole: QByteArray(b"edit"),
            self.CellColorRole: QByteArray(b"cellColor"),
            self.TimeCellRole: QByteArray(b"timeCell"),
        }

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.entries)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 20

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not self._contains(index.row(), index.column()):
            return None
        graph = self.entries[index.row()][2]
        point = index.column() // 2
        is_time = index.column() % 2 == 0
        if role == self.TimeCellRole:
            return is_time
        if role == self.CellColorRole:
            if isinstance(graph, ColorGraph) and not is_time:
                return _color_hex(graph.colors[point])
            return ""
        if role in {Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole}:
            if is_time:
                return _format_number(graph.x[point])
            if isinstance(graph, ColorGraph):
                return ", ".join(_format_number(channel) for channel in graph.colors[point])
            return _format_number(graph.y[point])
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if (
            role in {Qt.ItemDataRole.EditRole, Qt.ItemDataRole.DisplayRole}
            and index.isValid()
            and self.edit_handler is not None
        ):
            return bool(self.edit_handler(self.kind, index.row(), index.column(), str(value)))
        return False

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return (
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsEditable
        )

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            label = "Time" if section % 2 == 0 else self.kind.title()
            return f"{label} {section // 2 + 1}"
        if 0 <= section < len(self.entries):
            return str(section + 1)
        return None

    def set_effect(self, effect: ParticleEffect | None) -> None:
        self.beginResetModel()
        self.entries.clear()
        if effect is not None:
            for system in effect.particle_systems:
                graphs = {
                    "color": system.color_graphs,
                    "opacity": system.opacity_graphs,
                    "intensity": system.scale_graphs,
                }[self.kind]
                self.entries.extend(
                    (system.index, graph_index, graph)
                    for graph_index, graph in enumerate(graphs)
                )
        self.endResetModel()

    def graph_at(self, row: int) -> Graph | ColorGraph:
        return self.entries[row][2]

    def value_at(self, row: int, column: int) -> str:
        return str(self.data(self.index(row, column), Qt.ItemDataRole.DisplayRole))

    @Slot(int, int, result=str)
    def cellText(self, row: int, column: int) -> str:
        return self.value_at(row, column) if self._contains(row, column) else ""

    def refresh_cells(self, cells: list[tuple[int, int]]) -> None:
        for row, column in set(cells):
            if self._contains(row, column):
                index = self.index(row, column)
                self.dataChanged.emit(index, index, list(self.roleNames()))

    @Slot(int, int, result=QModelIndex)
    def cellIndex(self, row: int, column: int) -> QModelIndex:
        return self.index(row, column)

    def _contains(self, row: int, column: int) -> bool:
        return 0 <= row < len(self.entries) and 0 <= column < 20


class VisualizerListModel(QAbstractListModel):
    SystemRole = Qt.ItemDataRole.UserRole + 1
    TypeRole = SystemRole + 1
    MaterialRole = TypeRole + 1
    UnitRole = MaterialRole + 1
    MeshRole = UnitRole + 1
    HasMaterialRole = MeshRole + 1
    HasUnitRole = HasMaterialRole + 1
    HasMeshRole = HasUnitRole + 1
    EnabledRole = HasMeshRole + 1
    SystemIndexRole = EnabledRole + 1
    MeshArchiveRole = SystemIndexRole + 1
    ToggleableRole = MeshArchiveRole + 1

    def __init__(self):
        super().__init__()
        self.entries = []
        self.mesh_archives: dict[int, str] = {}

    def roleNames(self):
        return {
            self.SystemRole: QByteArray(b"systemLabel"),
            self.TypeRole: QByteArray(b"visualizerType"),
            self.MaterialRole: QByteArray(b"materialId"),
            self.UnitRole: QByteArray(b"unitId"),
            self.MeshRole: QByteArray(b"meshId"),
            self.HasMaterialRole: QByteArray(b"hasMaterial"),
            self.HasUnitRole: QByteArray(b"hasUnit"),
            self.HasMeshRole: QByteArray(b"hasMesh"),
            self.EnabledRole: QByteArray(b"systemEnabled"),
            self.SystemIndexRole: QByteArray(b"systemIndex"),
            self.MeshArchiveRole: QByteArray(b"meshArchive"),
            self.ToggleableRole: QByteArray(b"systemToggleable"),
        }

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.entries)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.entries):
            return None
        system = self.entries[index.row()]
        visualizer = system.visualizer
        if role == self.SystemRole:
            return f"Particle System {system.index + 1}"
        if role == self.TypeRole:
            return visualizer.type_name if visualizer is not None else "Non-rendering"
        if role == self.MaterialRole:
            return "" if visualizer is None or visualizer.material_id is None else str(visualizer.material_id)
        if role == self.UnitRole:
            return "" if visualizer is None or visualizer.unit_id is None else str(visualizer.unit_id)
        if role == self.MeshRole:
            return "" if visualizer is None or visualizer.mesh_id is None else str(visualizer.mesh_id)
        if role == self.HasMaterialRole:
            return visualizer is not None and visualizer.material_id is not None
        if role == self.HasUnitRole:
            return visualizer is not None and visualizer.unit_id is not None
        if role == self.HasMeshRole:
            return visualizer is not None and visualizer.mesh_id is not None
        if role == self.EnabledRole:
            return system.enabled
        if role == self.ToggleableRole:
            return visualizer is not None
        if role == self.SystemIndexRole:
            return system.index
        if role == self.MeshArchiveRole:
            return self.mesh_archives.get(system.index, "") if visualizer and visualizer.mesh_id is not None else ""
        return None

    def set_effect(self, effect: ParticleEffect | None, mesh_archives: dict[int, str] | None = None) -> None:
        self.beginResetModel()
        self.entries.clear()
        self.mesh_archives = dict(mesh_archives or {})
        if effect is not None:
            self.entries.extend(effect.particle_systems)
        self.endResetModel()

    def visualizer_at(self, row: int) -> Visualizer | None:
        return self.entries[row].visualizer

    def refresh(self, row: int) -> None:
        if 0 <= row < len(self.entries):
            index = self.index(row, 0)
            self.dataChanged.emit(index, index, list(self.roleNames()))

    def refresh_system(self, system_index: int) -> None:
        for row, system in enumerate(self.entries):
            if system.index == system_index:
                self.refresh(row)
                return


class ArchiveParticleListModel(QAbstractListModel):
    IdRole = Qt.ItemDataRole.UserRole + 1
    SizeRole = IdRole + 1

    def __init__(self):
        super().__init__()
        self.entries: list[ArchiveEntry] = []

    def roleNames(self):
        return {
            self.IdRole: QByteArray(b"resourceId"),
            self.SizeRole: QByteArray(b"resourceSize"),
        }

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.entries)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.entries):
            return None
        entry = self.entries[index.row()]
        if role == self.IdRole:
            return str(entry.file_id)
        if role == self.SizeRole:
            return entry.toc_size
        return None

    def set_entries(self, entries: list[ArchiveEntry]) -> None:
        self.beginResetModel()
        self.entries = list(entries)
        self.endResetModel()

    def entry_at(self, row: int) -> ArchiveEntry:
        return self.entries[row]


class FoundArchiveListModel(QAbstractListModel):
    IdRole = Qt.ItemDataRole.UserRole + 1
    NameRole = IdRole + 1

    def __init__(self):
        super().__init__()
        self.entries: list[tuple[str, str]] = []

    def roleNames(self):
        return {
            self.IdRole: QByteArray(b"archiveId"),
            self.NameRole: QByteArray(b"archiveDisplayName"),
        }

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.entries)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.entries):
            return None
        archive_id, name = self.entries[index.row()]
        if role == self.IdRole:
            return archive_id
        if role == self.NameRole:
            return name
        return None

    def set_entries(self, entries: list[tuple[str, str]]) -> None:
        self.beginResetModel()
        self.entries = list(entries)
        self.endResetModel()

    def entry_at(self, row: int) -> tuple[str, str]:
        return self.entries[row]


class AssetLinkListModel(QAbstractListModel):
    KindRole = Qt.ItemDataRole.UserRole + 1
    IdRole = KindRole + 1
    DetailRole = IdRole + 1
    AvailableRole = DetailRole + 1
    ReplaceableRole = AvailableRole + 1

    def __init__(self):
        super().__init__()
        self.links: list[AssetLink] = []

    def roleNames(self):
        return {
            self.KindRole: QByteArray(b"assetKind"),
            self.IdRole: QByteArray(b"assetId"),
            self.DetailRole: QByteArray(b"assetDetail"),
            self.AvailableRole: QByteArray(b"assetAvailable"),
            self.ReplaceableRole: QByteArray(b"assetReplaceable"),
        }

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.links)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.links):
            return None
        link = self.links[index.row()]
        if role == self.KindRole:
            return link.kind
        if role == self.IdRole:
            return str(link.file_id)
        if role == self.DetailRole:
            return link.detail
        if role == self.AvailableRole:
            return link.available
        if role == self.ReplaceableRole:
            return link.kind == "texture" and link.available
        return None

    def set_links(self, links: list[AssetLink]) -> None:
        self.beginResetModel()
        self.links = list(links)
        self.endResetModel()

    def link_at(self, row: int) -> AssetLink:
        return self.links[row]


class MaterialVariableListModel(QAbstractListModel):
    LabelRole = Qt.ItemDataRole.UserRole + 1
    ValuesRole = LabelRole + 1
    IsColorRole = ValuesRole + 1

    def __init__(self):
        super().__init__()
        self.variables: list[ShaderVariableInfo] = []

    def roleNames(self):
        return {
            self.LabelRole: QByteArray(b"variableLabel"),
            self.ValuesRole: QByteArray(b"variableValues"),
            self.IsColorRole: QByteArray(b"variableIsColor"),
        }

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.variables)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.variables):
            return None
        variable = self.variables[index.row()]
        if role == self.LabelRole:
            kind = {0: "Scalar", 1: "Vector2", 2: "Vector3", 3: "Vector4", 12: "Other"}[variable.klass]
            return f"{kind}: {shader_variable_name(variable.variable_id)}"
        if role == self.ValuesRole:
            return list(variable.values)
        if role == self.IsColorRole:
            return variable.klass == 2
        return None

    def set_variables(self, variables: tuple[ShaderVariableInfo, ...] | list[ShaderVariableInfo]) -> None:
        updated = list(variables)
        same_structure = (
            len(self.variables) == len(updated)
            and all(
                (old.klass, old.variable_id, len(old.values)) == (new.klass, new.variable_id, len(new.values))
                for old, new in zip(self.variables, updated)
            )
        )
        if same_structure:
            self.variables = updated
            if updated:
                self.dataChanged.emit(
                    self.index(0, 0), self.index(len(updated) - 1, 0), list(self.roleNames())
                )
            return
        self.beginResetModel()
        self.variables = updated
        self.endResetModel()


class HexViewerModel(QAbstractListModel):
    """Virtualised, read-only rows for the particle research hex viewer."""

    OffsetRole = Qt.ItemDataRole.UserRole + 1
    CellsRole = OffsetRole + 1
    AsciiRole = CellsRole + 1

    def __init__(self):
        super().__init__()
        self._data = b""
        self._base_offset = 0
        self._patterns: list[dict] = []
        self._safe_patterns: list[dict] = []
        self._selected_pattern = -1
        self._selected_offset = -1
        self._selection_start = -1
        self._selection_end = -1
        self._highlights_visible = True
        self._safe_regions_visible = False

    def roleNames(self):
        return {
            self.OffsetRole: QByteArray(b"hexOffset"),
            self.CellsRole: QByteArray(b"hexCells"),
            self.AsciiRole: QByteArray(b"asciiText"),
        }

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else (len(self._data) + 15) // 16

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < self.rowCount():
            return None
        row_start = index.row() * 16
        if role == self.OffsetRole:
            return f"{self._base_offset + row_start:08X}"
        if role == self.CellsRole:
            return [self._cell(row_start + column) for column in range(16)]
        if role == self.AsciiRole:
            return "".join(
                chr(value) if 32 <= value <= 126 else "."
                for value in self._data[row_start:row_start + 16]
            )
        return None

    def set_content(
        self,
        data: bytes,
        base_offset: int,
        patterns: list[dict],
        safe_patterns: list[dict] | None = None,
    ) -> None:
        self.beginResetModel()
        self._data = bytes(data)
        self._base_offset = base_offset
        self._patterns = list(patterns)
        self._safe_patterns = list(safe_patterns or [])
        self._selected_pattern = -1
        self._selected_offset = -1
        self._selection_start = -1
        self._selection_end = -1
        self.endResetModel()

    def set_selected_pattern(self, pattern_index: int) -> None:
        selected = pattern_index if 0 <= pattern_index < len(self._patterns) else -1
        if selected == self._selected_pattern:
            return
        self._selected_pattern = selected
        if self.rowCount():
            self.dataChanged.emit(
                self.index(0, 0), self.index(self.rowCount() - 1, 0), [self.CellsRole]
            )

    def set_selected_offset(self, absolute_offset: int) -> None:
        selected = absolute_offset if self._base_offset <= absolute_offset < self._base_offset + len(self._data) else -1
        if selected == self._selected_offset:
            return
        self._selected_offset = selected
        if self.rowCount():
            self.dataChanged.emit(
                self.index(0, 0), self.index(self.rowCount() - 1, 0), [self.CellsRole]
            )

    def set_selection_range(self, start: int, end: int) -> None:
        if not (
            self._base_offset <= start < self._base_offset + len(self._data)
            and self._base_offset <= end < self._base_offset + len(self._data)
        ):
            start = end = -1
        if (start, end) == (self._selection_start, self._selection_end):
            return
        self._selection_start = start
        self._selection_end = end
        if self.rowCount():
            self.dataChanged.emit(
                self.index(0, 0), self.index(self.rowCount() - 1, 0), [self.CellsRole]
            )

    def set_highlights_visible(self, visible: bool) -> None:
        if visible == self._highlights_visible:
            return
        self._highlights_visible = visible
        if self.rowCount():
            self.dataChanged.emit(
                self.index(0, 0), self.index(self.rowCount() - 1, 0), [self.CellsRole]
            )

    def set_safe_regions_visible(self, visible: bool) -> None:
        if visible == self._safe_regions_visible:
            return
        self._safe_regions_visible = visible
        if self.rowCount():
            self.dataChanged.emit(
                self.index(0, 0), self.index(self.rowCount() - 1, 0), [self.CellsRole]
            )

    def _cell(self, relative_offset: int) -> dict:
        if not 0 <= relative_offset < len(self._data):
            return {"text": "", "color": "#68707C", "selected": False, "active": False, "safe": False, "safeLabel": "", "offset": -1, "pattern": ""}
        absolute_offset = self._base_offset + relative_offset
        pattern_index, pattern = self._pattern_at(absolute_offset)
        safe_pattern = self._safe_pattern_at(absolute_offset)
        range_start, range_end = sorted((self._selection_start, self._selection_end))
        return {
            "text": f"{self._data[relative_offset]:02X}",
            "color": pattern.get("color", "#B9C2CD") if pattern else "#B9C2CD",
            "selected": pattern_index == self._selected_pattern,
            "active": absolute_offset == self._selected_offset,
            "rangeSelected": range_start <= absolute_offset <= range_end,
            "safe": safe_pattern is not None and self._safe_regions_visible,
            "safeLabel": safe_pattern.get("label", "") if safe_pattern and self._safe_regions_visible else "",
            "offset": absolute_offset,
            "pattern": pattern.get("label", "") if pattern else "",
        }

    def _pattern_at(self, offset: int):
        # Later, more specific patterns intentionally override broad parent ranges.
        result = (-1, None)
        for index, pattern in enumerate(self._patterns):
            start = pattern["offset"]
            if start <= offset < start + pattern["size"]:
                result = (index, pattern)
        return result

    def _safe_pattern_at(self, offset: int):
        for pattern in self._safe_patterns:
            start = pattern["offset"]
            if start <= offset < start + pattern["size"]:
                return pattern
        return None


class TextureBindingListModel(QAbstractListModel):
    SystemRole = Qt.ItemDataRole.UserRole + 1
    MaterialRole = SystemRole + 1
    TextureRole = MaterialRole + 1
    DetailRole = TextureRole + 1
    AvailableRole = DetailRole + 1

    def __init__(self):
        super().__init__()
        self.bindings: list[TextureBinding] = []

    def roleNames(self):
        return {
            self.SystemRole: QByteArray(b"systemLabel"),
            self.MaterialRole: QByteArray(b"materialId"),
            self.TextureRole: QByteArray(b"textureId"),
            self.DetailRole: QByteArray(b"textureDetail"),
            self.AvailableRole: QByteArray(b"textureAvailable"),
        }

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.bindings)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.bindings):
            return None
        binding = self.bindings[index.row()]
        if role == self.SystemRole:
            return f"Particle System {binding.system_index + 1}"
        if role == self.MaterialRole:
            return str(binding.material_id)
        if role == self.TextureRole:
            return str(binding.texture_id)
        if role == self.DetailRole:
            return binding.detail
        if role == self.AvailableRole:
            return binding.available
        return None

    def set_bindings(self, bindings: list[TextureBinding]) -> None:
        self.beginResetModel()
        self.bindings = list(bindings)
        self.endResetModel()

    def binding_at(self, row: int) -> TextureBinding:
        return self.bindings[row]

    def update_binding(self, row: int, binding: TextureBinding) -> None:
        if not 0 <= row < len(self.bindings):
            return
        self.bindings[row] = binding
        index = self.index(row, 0)
        self.dataChanged.emit(index, index, list(self.roleNames()))


class TextureOverviewListModel(QAbstractListModel):
    SystemRole = Qt.ItemDataRole.UserRole + 1
    TexturesRole = SystemRole + 1

    def __init__(self):
        super().__init__()
        self.rows: list[tuple[int, list[TextureBinding]]] = []

    def roleNames(self):
        return {
            self.SystemRole: QByteArray(b"systemIndex"),
            self.TexturesRole: QByteArray(b"systemTextures"),
        }

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        system_index, bindings = self.rows[index.row()]
        if role == self.SystemRole:
            return system_index
        if role == self.TexturesRole:
            return [
                {
                    "systemIndex": binding.system_index,
                    "materialId": str(binding.material_id),
                    "textureId": str(binding.texture_id),
                    "detail": binding.detail,
                    "available": binding.available,
                    "previewUrl": binding.preview_url,
                    "previewState": binding.preview_state,
                }
                for binding in bindings
            ]
        return None

    def set_bindings(self, bindings: list[TextureBinding], system_indices: list[int]) -> None:
        grouped = []
        for system_index in system_indices:
            textures = [binding for binding in bindings if binding.system_index == system_index]
            if textures:
                grouped.append((system_index, textures))
        self.beginResetModel()
        self.rows = grouped
        self.endResetModel()

    def update_binding(self, binding: TextureBinding) -> None:
        key = (binding.system_index, binding.material_id, binding.texture_id)
        for row, (system_index, bindings) in enumerate(self.rows):
            if system_index != binding.system_index:
                continue
            for index, item in enumerate(bindings):
                if (item.system_index, item.material_id, item.texture_id) == key:
                    bindings[index] = binding
                    model_index = self.index(row, 0)
                    self.dataChanged.emit(model_index, model_index, [self.TexturesRole])
                    return


def _color_hex(color: list[float]) -> str:
    channels = [max(0, min(255, round(value))) for value in color]
    return "#{:02X}{:02X}{:02X}".format(*channels)


def _format_number(value: float) -> str:
    if value == 10000.0:
        return "10000"
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"
