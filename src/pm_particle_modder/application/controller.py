from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QUndoCommand, QUndoStack
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QFileDialog,
    QInputDialog,
    QMessageBox,
)

from pm_particle_modder.core import ColorGraph, Graph, ParticleEffect, ParticleParseError
from pm_particle_modder.ui.models import (
    DocumentListModel,
    ParticleTableModel,
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


class ParticleController(QObject):
    stateChanged = Signal()
    currentDocumentChanged = Signal()
    statusChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.documents_model = DocumentListModel()
        self.color_model = ParticleTableModel("color")
        self.opacity_model = ParticleTableModel("opacity")
        self.intensity_model = ParticleTableModel("intensity")
        for model in (self.color_model, self.opacity_model, self.intensity_model):
            model.edit_handler = self.setTableCell
        self.visualizer_model = VisualizerListModel()
        self._current_index = -1
        self._status = "Ready"

    @Property(int, notify=currentDocumentChanged)
    def currentIndex(self) -> int:
        return self._current_index

    @Property(bool, notify=stateChanged)
    def hasDocument(self) -> bool:
        return self.current_document is not None

    @Property(int, notify=stateChanged)
    def documentCount(self) -> int:
        return len(self.documents_model.documents)

    @Property("QVariantList", notify=stateChanged)
    def groupNames(self):
        return sorted(
            {document.group for document in self.documents_model.documents if document.group},
            key=str.casefold,
        )

    @Property(str, notify=currentDocumentChanged)
    def currentTitle(self) -> str:
        document = self.current_document
        return document.path.name if document else "No file loaded"

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
            "Particle Files (*.particles);;PM Projects (*.pmod);;All Files (*.*)",
        )
        self._open_paths([Path(path) for path in paths])

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
        document = Document(path, effect, stack, note, group)
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
            for item in self._flatten_project_structure(project_data.get("structure", [])):
                value = item.get("filepath", "")
                particle_path = Path(value)
                if not particle_path.is_absolute():
                    particle_path = path.parent / particle_path
                if not particle_path.exists():
                    missing.append(str(particle_path))
                    continue
                document = self._open_particle(
                    particle_path, item.get("note", ""), item.get("_group", "")
                )
                if document is None:
                    continue
                state = states.get(value, states.get(str(particle_path), {}))
                document.selections["color"] = self._selection_pairs(state.get("selection", []))
                presets = state.get("presets", [None, None])[:2]
                document.color_presets = [
                    self._selection_pairs(preset) if preset is not None else None
                    for preset in presets
                ]
                while len(document.color_presets) < 2:
                    document.color_presets.append(None)
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
        if missing:
            QMessageBox.warning(
                None,
                "Project files missing",
                "These files could not be found:\n\n" + "\n".join(missing[:10]),
            )

    @Slot()
    def saveCurrent(self) -> bool:
        document = self.current_document
        return self._save_document(document) if document else False

    @Slot()
    def saveCurrentAs(self) -> bool:
        document = self.current_document
        if document is None:
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
            if not document.undo_stack.isClean():
                success = self._save_document(document) and success
        return success

    @Slot()
    def saveProject(self) -> None:
        if not self.documents_model.documents:
            return
        path, _ = QFileDialog.getSaveFileName(
            None, "Save PM project", "", "PM Projects (*.pmod)"
        )
        if not path:
            return
        output_path = Path(path)
        ungrouped_files = []
        grouped_files: dict[str, list[dict]] = {}
        selection_states = {}
        for document in self.documents_model.documents:
            try:
                stored_path = os.path.relpath(document.path, output_path.parent)
            except ValueError:
                stored_path = str(document.path)
            file_item = {"type": "file", "filepath": stored_path, "note": document.note}
            if document.group:
                grouped_files.setdefault(document.group, []).append(file_item)
            else:
                ungrouped_files.append(file_item)
            selection_states[stored_path] = {
                "selection": document.selections.get("color", []),
                "presets": document.color_presets,
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
            elif item.get("type") == "file":
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
            document.effect.original_data = output
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

    @Slot(int)
    def setCurrentDocument(self, index: int) -> None:
        if index == self._current_index:
            return
        self._current_index = index if 0 <= index < len(self.documents_model.documents) else -1
        effect = self.current_document.effect if self.current_document else None
        self.color_model.set_effect(effect)
        self.opacity_model.set_effect(effect)
        self.intensity_model.set_effect(effect)
        self.visualizer_model.set_effect(effect)
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
        model = self._graph_model(kind)
        cells = self._selection_pairs(selection)
        if model is None or not cells:
            return
        try:
            edits = [
                edit
                for row, column in cells
                if (edit := self._make_cell_edit(model, row, column, text)) is not None
            ]
        except ValueError as error:
            self._show_error("Unable to fill selection", str(error))
            return
        self._push_cell_edits(f"Fill {len(cells)} {kind} cells", model, cells, edits)

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
        return f"{selected.red()}, {selected.green()}, {selected.blue()}"

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
        graph = model.graph_at(row)
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
        old_value = getattr(visualizer, attribute)
        if old_value is None or old_value == value:
            return

        def apply(new_value):
            setattr(visualizer, attribute, new_value)
            self.visualizer_model.refresh(row)

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
