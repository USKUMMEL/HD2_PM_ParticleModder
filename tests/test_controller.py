import os
import json
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication

from pm_particle_modder.application.controller import Document, ParticleController
from pm_particle_modder.core import ParticleEffect, TextureBinding
from test_particle import make_particle


class ControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.controller = ParticleController()
        effect = ParticleEffect.from_bytes(make_particle())
        self.document = Document(Path("fixture.particles"), effect, QUndoStack())
        self.controller.documents_model.append(self.document)
        self.document.undo_stack.setClean()
        self.controller.setCurrentDocument(0)

    def test_graph_edit_supports_undo_and_dirty_state(self):
        graph = self.controller.opacity_model.graph_at(0)
        original = graph.y[1]

        self.controller.setTableCell("opacity", 0, 3, "0.5")
        self.assertEqual(graph.y[1], 0.5)
        self.assertFalse(self.document.undo_stack.isClean())
        self.assertTrue(self.controller.canUndo)

        self.controller.undo()
        self.assertEqual(graph.y[1], original)
        self.assertTrue(self.document.undo_stack.isClean())

        self.controller.redo()
        self.assertEqual(graph.y[1], 0.5)

    def test_fill_selection_is_one_undo_step(self):
        graph = self.controller.opacity_model.graph_at(0)
        original = [graph.y[0], graph.y[1], graph.y[2]]
        selection = [[0, 1], [0, 3], [0, 5]]

        self.controller.fillTable("opacity", selection, "0.25")
        self.assertEqual(graph.y[:3], [0.25, 0.25, 0.25])
        self.assertEqual(self.document.undo_stack.count(), 1)

        self.controller.undo()
        self.assertEqual(graph.y[:3], original)

    def test_region_paste_starts_at_top_left_cell(self):
        graph = self.controller.opacity_model.graph_at(0)
        QApplication.clipboard().setText("0.25\t1.5\t0.5\t2.5")

        self.controller.pasteTable("opacity", [[0, 0]])
        self.assertEqual(graph.x[:2], [0.25, 0.5])
        self.assertEqual(graph.y[:2], [1.5, 2.5])
        self.assertEqual(self.document.undo_stack.count(), 1)

    def test_color_fill_and_selection_presets(self):
        graph = self.controller.color_model.graph_at(0)
        self.controller.fillTable("color", [[0, 1], [0, 3]], "10, 20, 30")
        self.assertEqual(graph.colors[:2], [[10.0, 20.0, 30.0], [10.0, 20.0, 30.0]])

        selection = [[0, 1], [0, 3]]
        self.controller.updateSelection("color", selection)
        self.controller.saveColorPreset(0, selection)
        self.assertEqual(self.controller.selectionFor("color"), selection)
        self.assertEqual(self.controller.colorPreset(0), selection)

    def test_texture_overview_uses_strings_for_64_bit_ids(self):
        material_id = 16915718763308572383
        texture_id = 14790446551990181426
        self.controller._texture_system_indices = [0]
        self.controller._texture_materials_by_system = {0: [material_id]}
        self.controller._all_texture_bindings = [
            TextureBinding(0, material_id, texture_id, "fixture", False)
        ]

        row = self.controller.textureOverviewRows[0]
        texture = row["textures"][0]
        self.assertEqual(texture["materialId"], str(material_id))
        self.assertEqual(texture["textureId"], str(texture_id))

    def test_groups_sort_files_and_preserve_current_document(self):
        second = Document(
            Path("zeta.particles"),
            ParticleEffect.from_bytes(make_particle()),
            QUndoStack(),
        )
        self.controller.documents_model.append(second)

        self.controller.addDocumentsToGroup([0, 1], "Gameplay")
        self.assertEqual(self.document.group, "Gameplay")
        self.assertEqual(second.group, "Gameplay")
        self.assertIs(self.controller.current_document, self.document)
        self.assertEqual(self.controller.groupNames, ["Gameplay"])
        group_role = self.controller.documents_model.GroupRole
        second_index = self.controller.documents_model.documents.index(second)
        self.assertEqual(
            self.controller.documents_model.data(
                self.controller.documents_model.index(second_index), group_role
            ),
            "Gameplay",
        )

        self.controller.removeDocumentsFromGroup([0, 1])
        self.assertEqual(self.document.group, "")
        self.assertEqual(second.group, "")
        self.assertIs(self.controller.current_document, self.document)

    def test_save_is_atomic_and_marks_document_clean(self):
        self.controller.setLifetime("min", "2")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "saved.particles"
            self.assertTrue(self.controller._save_document(self.document, target))
            self.assertEqual(target.read_bytes(), self.document.effect.to_bytes())
            self.assertTrue(self.document.undo_stack.isClean())
            self.assertEqual(self.document.path, target.resolve())

    def test_loads_custom_v2_project_selection_inside_groups(self):
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            particle_path = directory_path / "fixture.particles"
            particle_path.write_bytes(make_particle())
            project_path = directory_path / "custom.pmod"
            project_path.write_text(json.dumps({
                "version": 2,
                "structure": [{
                    "type": "group",
                    "name": "Effects",
                    "children": [{
                        "type": "file",
                        "filepath": "fixture.particles",
                        "note": "custom note",
                    }],
                }],
                "selectionStates": {
                    "fixture.particles": {
                        "selection": [[0, 1], [0, 3]],
                        "presets": [[[0, 1]], None],
                    }
                },
            }), encoding="utf-8")

            controller = ParticleController()
            controller._open_project(project_path)
            document = controller.current_document
            self.assertIsNotNone(document)
            self.assertEqual(document.note, "custom note")
            self.assertEqual(document.group, "Effects")
            self.assertEqual(document.selections["color"], [(0, 1), (0, 3)])
            self.assertEqual(document.color_presets[0], [(0, 1)])


if __name__ == "__main__":
    unittest.main()
