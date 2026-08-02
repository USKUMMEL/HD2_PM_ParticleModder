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

from pm_particle_modder.core import ArchiveEntry, AssetLink, ColorGraph, Graph, ParticleEffect, Visualizer


class DocumentListModel(QAbstractListModel):
    TitleRole = Qt.ItemDataRole.UserRole + 1
    PathRole = TitleRole + 1
    DirtyRole = PathRole + 1
    VersionRole = DirtyRole + 1
    GroupRole = VersionRole + 1

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

    def __init__(self):
        super().__init__()
        self.entries: list[tuple[int, Visualizer]] = []

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
        }

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.entries)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.entries):
            return None
        system_index, visualizer = self.entries[index.row()]
        if role == self.SystemRole:
            return f"Particle System {system_index}"
        if role == self.TypeRole:
            return visualizer.type_name
        if role == self.MaterialRole:
            return "" if visualizer.material_id is None else str(visualizer.material_id)
        if role == self.UnitRole:
            return "" if visualizer.unit_id is None else str(visualizer.unit_id)
        if role == self.MeshRole:
            return "" if visualizer.mesh_id is None else str(visualizer.mesh_id)
        if role == self.HasMaterialRole:
            return visualizer.material_id is not None
        if role == self.HasUnitRole:
            return visualizer.unit_id is not None
        if role == self.HasMeshRole:
            return visualizer.mesh_id is not None
        return None

    def set_effect(self, effect: ParticleEffect | None) -> None:
        self.beginResetModel()
        self.entries.clear()
        if effect is not None:
            self.entries.extend(
                (system.index, system.visualizer)
                for system in effect.particle_systems
                if system.visualizer is not None
            )
        self.endResetModel()

    def visualizer_at(self, row: int) -> Visualizer:
        return self.entries[row][1]

    def refresh(self, row: int) -> None:
        if 0 <= row < len(self.entries):
            index = self.index(row, 0)
            self.dataChanged.emit(index, index, list(self.roleNames()))


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


def _color_hex(color: list[float]) -> str:
    channels = [max(0, min(255, round(value))) for value in color]
    return "#{:02X}{:02X}{:02X}".format(*channels)


def _format_number(value: float) -> str:
    if value == 10000.0:
        return "10000"
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"
