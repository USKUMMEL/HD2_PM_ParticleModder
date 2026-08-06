import os
import json
from pathlib import Path
import struct
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QUndoStack
from PySide6.QtWidgets import QApplication

from pm_particle_modder.application.controller import Document, ParticleController
from pm_particle_modder.core import (
    ArchiveEntry,
    ArchiveReader,
    MATERIAL_TYPE_ID,
    PARTICLE_TYPE_ID,
    TEXTURE_TYPE_ID,
    ParticleEffect,
    TextureBinding,
    write_patch_archive,
)
from test_particle import make_particle


def particle_archive_entry(file_id: int, data: bytes) -> ArchiveEntry:
    return archive_entry(file_id, PARTICLE_TYPE_ID, data)


def archive_entry(file_id: int, type_id: int, data: bytes) -> ArchiveEntry:
    return ArchiveEntry(
        file_id=file_id,
        type_id=type_id,
        toc_offset=0,
        stream_offset=0,
        gpu_offset=0,
        unknown1=0,
        unknown2=0,
        toc_size=len(data),
        stream_size=0,
        gpu_size=0,
        unknown3=16,
        unknown4=64,
        index=0,
        toc_data=data,
        gpu_data=b"",
        stream_data=b"",
    )


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

    def test_hex_viewer_marks_parsed_particle_ranges(self):
        patterns = self.controller.hexPatternOptions
        labels = [item["label"] for item in patterns]

        self.assertGreater(self.controller.hex_viewer_model.rowCount(), 0)
        self.assertIn("Particle header & tables", labels)
        self.assertIn("System 1: header", labels)
        self.assertIn("System 1: color graph 1", labels)

        self.controller.selectHexScope(1)
        self.assertEqual(self.controller.hexScopeOptions[1], "Particle System 1")
        system_size = self.document.effect.particle_systems[0].size
        self.assertEqual(self.controller.hex_viewer_model.rowCount(), (system_size + 15) // 16)
        self.controller.selectHexPattern(1)
        self.assertEqual(self.controller.selectedHexRow, 0)

        self.controller.selectHexScope(0)
        self.controller.selectHexByte(6)
        self.assertEqual(self.controller.selectedHexValue, "80")
        self.assertIn("Abs 0x6", self.controller.hexInspectorSummary)
        self.assertIn("u32 1065353216", self.controller.hexInspectorSummary)
        self.assertTrue(self.controller.applySelectedHexByte("00"))
        self.assertEqual(struct.unpack_from("<f", self.document.effect.to_bytes(), 4)[0], 0.5)
        self.controller.undo()
        self.assertEqual(struct.unpack_from("<f", self.document.effect.to_bytes(), 4)[0], 1.0)

        self.controller.beginHexSelection(4)
        self.controller.extendHexSelection(7)
        self.assertEqual(self.controller.hexSelectionSize, 4)
        self.assertEqual(self.controller.selectedHexRange, "0x4 - 0x7 (4 bytes)")
        self.controller.clearHexSelection()
        self.assertFalse(self.controller.hasHexSelection)
        self.controller.beginHexSelection(4)
        self.controller.extendHexSelection(7)
        self.controller.copyHexSelection()
        self.assertEqual(QApplication.clipboard().text(), "00 00 80 3F")
        self.assertTrue(self.controller.pasteHexBytes("00 00 00 00"))
        self.assertEqual(struct.unpack_from("<f", self.document.effect.to_bytes(), 4)[0], 0.0)
        self.controller.undo()
        self.assertEqual(struct.unpack_from("<f", self.document.effect.to_bytes(), 4)[0], 1.0)

        self.assertTrue(self.controller.applySelectedHexByte("00"))
        self.assertTrue(self.controller.copyHexSelectionTo(8))
        self.assertEqual(struct.unpack_from("<f", self.document.effect.to_bytes(), 8)[0], 0.0)
        self.controller.undo()
        self.controller.undo()
        self.assertEqual(struct.unpack_from("<ff", self.document.effect.to_bytes(), 4), (1.0, 3.0))

        self.assertFalse(self.controller.hexHighlightsVisible)
        cells = self.controller.hex_viewer_model.data(
            self.controller.hex_viewer_model.index(0, 0),
            self.controller.hex_viewer_model.CellsRole,
        )
        self.assertFalse(cells[4]["safe"])
        self.controller.toggleHexHighlights()
        self.assertTrue(self.controller.hexHighlightsVisible)
        self.assertIn("Minimum particle lifetime", self.controller.hexSafeRegionNoteAt(4))
        cells = self.controller.hex_viewer_model.data(
            self.controller.hex_viewer_model.index(0, 0),
            self.controller.hex_viewer_model.CellsRole,
        )
        self.assertTrue(cells[4]["safe"])
        self.controller.toggleHexHighlights()
        self.assertFalse(self.controller.hexHighlightsVisible)

    def test_hex_viewer_compares_another_open_particle(self):
        comparison = Document(
            Path("comparison.particles"), ParticleEffect.from_bytes(make_particle()), QUndoStack()
        )
        self.controller.documents_model.append(comparison)

        self.assertEqual(self.controller.hexCompareParticleOptions, ["No comparison", "comparison.particles [2]"])
        self.controller.selectHexCompareParticle(1)
        self.assertTrue(self.controller.hasHexComparison)
        self.assertEqual(self.controller.hexCompareTitle, "comparison.particles")
        self.assertGreater(self.controller.hex_compare_viewer_model.rowCount(), 0)

        self.controller.selectHexCompareScope(1)
        system_size = comparison.effect.particle_systems[0].size
        self.assertEqual(self.controller.hex_compare_viewer_model.rowCount(), (system_size + 15) // 16)

        self.controller.setCurrentDocument(1)
        self.assertTrue(self.controller.hasHexComparison)
        self.assertEqual(self.controller.hexCompareTitle, "fixture.particles")

    def test_hex_word_diff_transplants_exactly_one_word(self):
        comparison_data = bytearray(make_particle())
        visualizer_offset = self.document.effect.particle_systems[0].visualizer_data.offset
        struct.pack_into("<f", comparison_data, visualizer_offset + 4, 0.75)
        comparison = Document(
            Path("comparison.particles"), ParticleEffect.from_bytes(bytes(comparison_data)), QUndoStack()
        )
        self.controller.documents_model.append(comparison)

        self.controller.selectHexScope(1)
        self.controller.selectHexCompareParticle(1)
        self.controller.selectHexCompareScope(1)

        self.assertTrue(self.controller.hasHexSystemDiff)
        self.assertIn("Compatibility: Exact", self.controller.hexCompatibilitySummary)
        self.controller.selectHexDiffBlock(
            self.controller.hexDiffBlockOptions.index("Visualizer")
        )
        differences = self.controller.hexWordDifferences
        self.assertEqual(len(differences), 1)
        self.assertEqual(differences[0]["relativeOffset"], "+0x4")
        before = self.document.effect.to_bytes()
        self.assertTrue(self.controller.transplantHexWordDifference(0))
        after = self.document.effect.to_bytes()
        changed = [index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]]
        self.assertTrue(changed)
        self.assertTrue(set(changed).issubset(range(visualizer_offset + 4, visualizer_offset + 8)))
        self.controller.undo()
        self.assertEqual(self.document.effect.to_bytes(), before)

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

    def test_data_undo_and_selection_undo_are_separate(self):
        graph = self.controller.color_model.graph_at(0)
        original = list(graph.colors[0])
        selection = [[0, 1], [0, 3]]

        self.controller.updateSelection("color", selection)
        self.controller.setTableCell("color", 0, 1, "10, 20, 30")

        self.assertTrue(self.controller.canUndo)
        self.assertTrue(self.controller.canUndoSelection)
        self.controller.undo()
        self.assertEqual(graph.colors[0], original)
        self.assertEqual(self.controller.selectionFor("color"), selection)

        self.controller.undoSelection()
        self.assertEqual(self.controller.selectionFor("color"), [])
        self.assertTrue(self.controller.canRedoSelection)
        self.controller.redoSelection()
        self.assertEqual(self.controller.selectionFor("color"), selection)

    def test_color_fill_applies_to_current_particle_only(self):
        second_effect = ParticleEffect.from_bytes(make_particle())
        second_document = Document(Path("second.particles"), second_effect, QUndoStack())
        self.controller.documents_model.append(second_document)
        second_document.selections["color"] = [(0, 3)]

        self.controller.fillTable("color", [[0, 1]], "10, 20, 30")

        self.assertEqual(self.controller.color_model.graph_at(0).colors[0], [10.0, 20.0, 30.0])
        self.assertNotEqual(second_effect.particle_systems[0].color_graphs[0].colors[1], [10.0, 20.0, 30.0])
        self.assertEqual(second_document.undo_stack.count(), 0)

    def test_color_fill_applies_only_to_checked_particles(self):
        second_effect = ParticleEffect.from_bytes(make_particle())
        second_document = Document(Path("second.particles"), second_effect, QUndoStack())
        second_document.selections["color"] = [(0, 3)]
        third_effect = ParticleEffect.from_bytes(make_particle())
        third_document = Document(Path("third.particles"), third_effect, QUndoStack())
        third_document.selections["color"] = [(0, 3)]
        self.controller.documents_model.append(second_document)
        self.controller.documents_model.append(third_document)

        self.controller.toggleApplyInclude(1)
        self.controller.fillAppliedTables("color", "10, 20, 30")

        self.assertEqual(second_effect.particle_systems[0].color_graphs[0].colors[1], [10.0, 20.0, 30.0])
        self.assertNotEqual(third_effect.particle_systems[0].color_graphs[0].colors[1], [10.0, 20.0, 30.0])
        self.assertEqual(self.controller.applyParticleCount, 1)

    def test_select_all_loaded_table_cells_tracks_each_particle(self):
        second_document = Document(
            Path("second.particles"), ParticleEffect.from_bytes(make_particle()), QUndoStack()
        )
        self.controller.documents_model.append(second_document)

        self.controller.selectAllLoadedTableCells("color")

        self.assertEqual(len(self.document.selections["color"]), self.controller.color_model.rowCount() * 20)
        self.assertEqual(len(second_document.selections["color"]), self.controller.color_model.rowCount() * 20)

        self.controller.clearAllLoadedTableSelections("color")
        self.assertEqual(self.document.selections["color"], [])
        self.assertEqual(second_document.selections["color"], [])

    def test_texture_overview_model_uses_strings_for_64_bit_ids(self):
        material_id = 16915718763308572383
        texture_id = 14790446551990181426
        self.controller.texture_overview_model.set_bindings(
            [TextureBinding(0, material_id, texture_id, "fixture", False)], [0]
        )
        index = self.controller.texture_overview_model.index(0, 0)
        texture = self.controller.texture_overview_model.data(
            index, self.controller.texture_overview_model.TexturesRole
        )[0]
        self.assertEqual(texture["materialId"], str(material_id))
        self.assertEqual(texture["textureId"], str(texture_id))

    def test_selecting_texture_system_previews_its_first_texture(self):
        binding = TextureBinding(3, 55, 77, "fixture", False)
        self.controller._texture_system_indices = [3]
        self.controller._texture_materials_by_system = {3: [55]}
        self.controller._all_texture_bindings = [binding]

        self.controller.selectTextureSystem(0)

        self.assertEqual(self.controller._selected_texture_index, 0)

    def test_switching_from_list_view_keeps_the_selected_texture(self):
        first = TextureBinding(1, 11, 101, "first", False)
        selected = TextureBinding(4, 55, 202, "selected", False)
        self.controller._texture_system_indices = [1, 4]
        self.controller._texture_materials_by_system = {1: [11], 4: [55]}
        self.controller._all_texture_bindings = [first, selected]

        self.controller.setTextureListView(True)
        self.controller.selectTexture(1)
        self.controller.setTextureListView(False)

        self.assertEqual(self.controller.selectedTextureSystemIndex, 4)
        self.assertEqual(self.controller.selectedTextureMaterialId, "55")
        self.assertEqual(self.controller.selectedTextureId, "202")
        self.assertEqual(self.controller.texture_bindings_model.rowCount(), 1)

    def test_persists_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_folder = root / "data"
            data_folder.mkdir()
            project_open_folder = root / "open-projects"
            project_open_folder.mkdir()
            project_save_folder = root / "save-projects"
            project_save_folder.mkdir()
            (data_folder / "bundles.nxa").write_bytes(b"fixture")
            settings_path = root / "preferences.json"
            controller = ParticleController(settings_path=settings_path)
            controller._game_data_directory = data_folder
            controller._last_project_open_directory = project_open_folder
            controller._last_project_save_directory = project_save_folder
            controller._remember_custom_picker_color(QColor(12, 34, 56))

            restored = ParticleController(settings_path=settings_path)

            self.assertEqual(restored._game_data_directory, data_folder.resolve())
            self.assertEqual(restored._custom_picker_colors, ["#0c2238"])
            self.assertEqual(restored._last_project_open_directory, project_open_folder.resolve())
            self.assertEqual(restored._last_project_save_directory, project_save_folder.resolve())
            with patch(
                "pm_particle_modder.application.controller.QFileDialog.getOpenFileName",
                return_value=("", ""),
            ) as open_dialog:
                restored.openProject()
            self.assertEqual(open_dialog.call_args.args[2], str(project_open_folder.resolve()))

    def test_project_reopens_slim_archive_particles_by_id(self):
        archive_id = "2f1147605182c6ab"
        particle_id = 17140666081042917137
        archive = SimpleNamespace(
            path=Path(archive_id),
            _slim_store=object(),
            particle_assets=lambda effect: [],
            texture_bindings=lambda effect: [],
            particle_material_ids=lambda effect: [],
            get_entry=lambda file_id, type_id: (
                SimpleNamespace(file_id=particle_id, toc_data=make_particle())
                if (file_id, type_id) == (particle_id, PARTICLE_TYPE_ID)
                else None
            ),
        )
        document = Document(
            Path(f"{archive_id} [{particle_id}].particles"),
            ParticleEffect.from_bytes(make_particle()),
            QUndoStack(),
            archive=archive,
            archive_entry_id=particle_id,
            title=f"{particle_id}.particle",
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_path = root / "archive-project.pmod"
            self.controller.documents_model = type(self.controller.documents_model)()
            self.controller.documents_model.append(document)
            with patch(
                "pm_particle_modder.application.controller.QFileDialog.getSaveFileName",
                return_value=(str(project_path), "PM Projects (*.pmod)"),
            ):
                self.controller.saveProject()

            saved = json.loads(project_path.read_text(encoding="utf-8"))
            item = saved["structure"][0]
            self.assertEqual(item["type"], "archive_particle")
            self.assertEqual(item["archiveId"], archive_id)
            self.assertEqual(item["entryId"], str(particle_id))

            data_directory = root / "data"
            data_directory.mkdir()
            (data_directory / "bundles.nxa").write_bytes(b"fixture")
            restored = ParticleController(settings_path=root / "preferences.json")
            restored._game_data_directory = data_directory
            with patch(
                "pm_particle_modder.application.controller.SlimArchiveStore",
            ) as store_type:
                store_type.return_value.data_directory = data_directory
                store_type.return_value.open_archive.return_value = archive
                restored._open_project(project_path)

            store_type.assert_called_once_with(data_directory)
            store_type.return_value.open_archive.assert_called_once_with(archive_id)
            self.assertEqual(restored.documents_model.rowCount(), 1)
            self.assertEqual(restored.current_document.archive_entry_id, particle_id)

    def test_project_reopens_legacy_slim_archive_paths(self):
        archive_id = "2f1147605182c6ab"
        particle_id = 9614626952868023871
        archive = SimpleNamespace(
            path=Path(archive_id),
            _slim_store=object(),
            particle_assets=lambda effect: [],
            texture_bindings=lambda effect: [],
            particle_material_ids=lambda effect: [],
            get_entry=lambda file_id, type_id: (
                SimpleNamespace(file_id=particle_id, toc_data=make_particle())
                if (file_id, type_id) == (particle_id, PARTICLE_TYPE_ID)
                else None
            ),
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_directory = root / "data"
            data_directory.mkdir()
            (data_directory / "bundles.nxa").write_bytes(b"fixture")
            project_path = root / "legacy.pmod"
            legacy_path = data_directory / f"{archive_id} [{particle_id}].particles"
            project_path.write_text(json.dumps({
                "version": 2,
                "structure": [{"type": "file", "filepath": str(legacy_path)}],
            }), encoding="utf-8")

            controller = ParticleController(settings_path=root / "preferences.json")
            controller._game_data_directory = data_directory
            with patch(
                "pm_particle_modder.application.controller.SlimArchiveStore",
            ) as store_type:
                store_type.return_value.data_directory = data_directory
                store_type.return_value.open_archive.return_value = archive
                controller._open_project(project_path)

            self.assertEqual(controller.documents_model.rowCount(), 1)
            self.assertEqual(controller.current_document.archive_entry_id, particle_id)

    def test_archive_patch_toggle_and_reset_use_the_opened_source(self):
        particle_id = 42
        source = make_particle()
        archive = SimpleNamespace(
            path=Path("fixture_archive"),
            _slim_store=None,
            staged_entries={(particle_id, PARTICLE_TYPE_ID): object()},
            particle_assets=lambda effect: [],
            texture_bindings=lambda effect: [],
            particle_material_ids=lambda effect: [],
        )
        document = Document(
            Path("fixture_archive [42].particles"),
            ParticleEffect.from_bytes(source),
            QUndoStack(),
            archive=archive,
            archive_entry_id=particle_id,
            source_data=source,
        )
        self.controller.documents_model.append(document)
        self.controller.setCurrentDocument(1)
        document.effect.min_lifetime = 9.0

        self.controller.togglePatchInclude(1)
        self.assertTrue(document.include_in_patch)
        self.assertTrue(self.controller.canWritePatch)

        self.controller.togglePatchInclude(1)
        self.assertFalse(document.include_in_patch)
        self.assertNotIn((particle_id, PARTICLE_TYPE_ID), archive.staged_entries)

        self.controller.resetDocument(1)
        self.assertEqual(document.effect.min_lifetime, ParticleEffect.from_bytes(source).min_lifetime)

    def test_standalone_particle_can_be_included_in_a_patch(self):
        particle_id = 17140666081042917137
        source = make_particle()
        document = Document(
            Path(f"{particle_id}.particles"),
            ParticleEffect.from_bytes(source),
            QUndoStack(),
            source_data=source,
        )
        controller = ParticleController()
        controller.documents_model.append(document)
        controller.setCurrentDocument(0)
        controller.togglePatchInclude(0)

        self.assertTrue(document.include_in_patch)
        self.assertEqual(document.patch_entry_id, particle_id)

        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "base_archive"
            write_patch_archive(archive_path, [])
            controller._archive = ArchiveReader.open(archive_path)
            controller.createPatch()
            patch_path = Path(directory) / "9ba626afa44a3aa3.patch_0"
            self.assertEqual(controller.selectedPatchName, patch_path.name)
            controller.writePatch()
            entry = ArchiveReader.open(patch_path).get_entry(particle_id, PARTICLE_TYPE_ID)
            self.assertIsNotNone(entry)
            self.assertEqual(entry.toc_data, source)

    def test_patch_only_writes_particles_with_the_shield_enabled(self):
        first_id = 101
        second_id = 202
        source = make_particle()
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "source_archive"
            write_patch_archive(
                archive_path,
                [particle_archive_entry(first_id, source), particle_archive_entry(second_id, source)],
            )
            archive = ArchiveReader.open(archive_path)
            controller = ParticleController()
            for particle_id in (first_id, second_id):
                entry = archive.get_entry(particle_id, PARTICLE_TYPE_ID)
                controller.documents_model.append(Document(
                    Path(f"{particle_id}.particles"),
                    ParticleEffect.from_bytes(entry.toc_data),
                    QUndoStack(),
                    archive=archive,
                    archive_entry_id=particle_id,
                    title=f"{particle_id}.particle",
                    source_data=entry.toc_data,
                ))
            controller.setCurrentDocument(0)
            controller.togglePatchInclude(0)
            controller.createPatch()
            controller.writePatch()

            patch = ArchiveReader.open(Path(directory) / "9ba626afa44a3aa3.patch_0")
            particle_ids = [entry.file_id for entry in patch.entries_of_type(PARTICLE_TYPE_ID)]
            self.assertEqual(particle_ids, [first_id])

    def test_particle_swap_writes_source_data_at_target_id_with_assets(self):
        source_id, target_id = 101, 202
        material_id, texture_id = 301, 401
        source = make_particle()

        def material_data(texture: int) -> bytes:
            data = bytearray(148)
            struct.pack_into("<I", data, 64, 1)
            struct.pack_into("<Q", data, 140, texture)
            return bytes(data)

        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "source_archive"
            write_patch_archive(archive_path, [
                particle_archive_entry(source_id, source),
                particle_archive_entry(target_id, source),
                archive_entry(material_id, MATERIAL_TYPE_ID, material_data(texture_id)),
                archive_entry(texture_id, TEXTURE_TYPE_ID, b"texture"),
            ])
            archive = ArchiveReader.open(archive_path)
            effect = ParticleEffect.from_bytes(archive.get_entry(source_id, PARTICLE_TYPE_ID).toc_data)
            effect.min_lifetime = 2.0
            effect.particle_systems[0].visualizer.material_id = material_id
            controller = ParticleController()
            controller.documents_model.append(Document(
                Path(f"{source_id}.particles"), effect, QUndoStack(), archive=archive,
                archive_entry_id=source_id, source_data=source,
            ))
            controller.setCurrentDocument(0)

            self.assertTrue(controller.createParticleSwap(0, str(target_id), True))
            self.assertEqual(controller.particleSwapCount, 1)
            controller.createPatch()
            controller.writePatch()

            patch = ArchiveReader.open(Path(directory) / "9ba626afa44a3aa3.patch_0")
            target = patch.get_entry(target_id, PARTICLE_TYPE_ID)
            self.assertIsNotNone(target)
            self.assertEqual(target.toc_data, effect.to_bytes())
            self.assertIsNone(patch.get_entry(source_id, PARTICLE_TYPE_ID))
            self.assertIsNotNone(patch.get_entry(material_id, MATERIAL_TYPE_ID))
            self.assertIsNotNone(patch.get_entry(texture_id, TEXTURE_TYPE_ID))

    def test_patch_only_writes_assets_reachable_from_shield_enabled_particles(self):
        first_id, second_id = 101, 202
        first_material, second_material = 301, 302
        first_texture, second_texture = 401, 402
        source = make_particle()

        def material_data(texture_id: int) -> bytes:
            data = bytearray(148)
            struct.pack_into("<I", data, 64, 1)
            struct.pack_into("<Q", data, 140, texture_id)
            return bytes(data)

        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "source_archive"
            write_patch_archive(archive_path, [
                particle_archive_entry(first_id, source),
                particle_archive_entry(second_id, source),
                archive_entry(first_material, MATERIAL_TYPE_ID, material_data(first_texture)),
                archive_entry(second_material, MATERIAL_TYPE_ID, material_data(second_texture)),
                archive_entry(first_texture, TEXTURE_TYPE_ID, b"first texture"),
                archive_entry(second_texture, TEXTURE_TYPE_ID, b"second texture"),
            ])
            archive = ArchiveReader.open(archive_path)
            controller = ParticleController()
            for particle_id, material_id in ((first_id, first_material), (second_id, second_material)):
                particle_entry = archive.get_entry(particle_id, PARTICLE_TYPE_ID)
                effect = ParticleEffect.from_bytes(particle_entry.toc_data)
                effect.particle_systems[0].visualizer.material_id = material_id
                controller.documents_model.append(Document(
                    Path(f"{particle_id}.particles"), effect, QUndoStack(), archive=archive,
                    archive_entry_id=particle_id, title=f"{particle_id}.particle",
                    source_data=particle_entry.toc_data,
                ))
            archive.stage(archive.get_entry(first_material, MATERIAL_TYPE_ID))
            archive.stage(archive.get_entry(second_material, MATERIAL_TYPE_ID))
            archive.stage(archive.get_entry(first_texture, TEXTURE_TYPE_ID))
            archive.stage(archive.get_entry(second_texture, TEXTURE_TYPE_ID))
            controller.setCurrentDocument(0)
            controller.togglePatchInclude(0)
            controller.createPatch()
            controller.writePatch()

            patch = ArchiveReader.open(Path(directory) / "9ba626afa44a3aa3.patch_0")
            self.assertIsNotNone(patch.get_entry(first_id, PARTICLE_TYPE_ID))
            self.assertIsNone(patch.get_entry(second_id, PARTICLE_TYPE_ID))
            self.assertIsNotNone(patch.get_entry(first_material, MATERIAL_TYPE_ID))
            self.assertIsNone(patch.get_entry(second_material, MATERIAL_TYPE_ID))
            self.assertIsNotNone(patch.get_entry(first_texture, TEXTURE_TYPE_ID))
            self.assertIsNone(patch.get_entry(second_texture, TEXTURE_TYPE_ID))

    def test_patch_names_are_pm_sequence_and_ignore_existing_data_folder_patches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "source_archive"
            write_patch_archive(archive_path, [])
            (root / "9ba626afa44a3aa3.patch_0").write_bytes(b"existing patch")
            controller = ParticleController()
            controller._archive = ArchiveReader.open(archive_path)

            controller.createPatch()
            controller.createPatch()

            self.assertEqual(controller.patchOptions, [
                "9ba626afa44a3aa3.patch_0",
                "9ba626afa44a3aa3.patch_1",
            ])

    def test_renamed_patch_uses_the_new_file_name_when_written(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "source_archive"
            write_patch_archive(archive_path, [])
            controller = ParticleController()
            controller._archive = ArchiveReader.open(archive_path)
            controller.createPatch()

            controller.renameSelectedPatchTo("my_particle_patch")

            self.assertEqual(controller.selectedPatchName, "my_particle_patch")
            self.assertEqual(controller._patch_targets[0].path.name, "my_particle_patch")

    def test_writing_patch_keeps_particle_resettable_against_its_opened_source(self):
        particle_id = 404
        source = make_particle()
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "source_archive"
            write_patch_archive(archive_path, [particle_archive_entry(particle_id, source)])
            archive = ArchiveReader.open(archive_path)
            controller = ParticleController()
            entry = archive.get_entry(particle_id, PARTICLE_TYPE_ID)
            document = Document(
                Path("404.particles"),
                ParticleEffect.from_bytes(entry.toc_data),
                QUndoStack(),
                archive=archive,
                archive_entry_id=particle_id,
                source_data=entry.toc_data,
            )
            controller.documents_model.append(document)
            document.undo_stack.setClean()
            controller.setCurrentDocument(0)
            controller.setLifetime("min", "2")
            controller.togglePatchInclude(0)
            controller.createPatch()
            controller.writePatch()

            resettable_role = controller.documents_model.ResettableRole
            index = controller.documents_model.index(0)
            self.assertFalse(document.undo_stack.isClean())
            self.assertTrue(controller.documents_model.data(index, resettable_role))

    def test_reset_can_overwrite_a_previously_written_patch_with_an_empty_patch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "source_archive"
            write_patch_archive(archive_path, [])
            controller = ParticleController()
            controller._archive = ArchiveReader.open(archive_path)
            controller.createPatch()
            controller._patch_targets[0].needs_write = True

            controller.writePatch()

            patch = ArchiveReader.open(root / "9ba626afa44a3aa3.patch_0")
            self.assertEqual(patch.entries, [])
            self.assertFalse(controller._patch_targets[0].needs_write)

    def test_particle_system_toggle_is_undoable(self):
        system = self.document.effect.particle_systems[0]

        self.controller.toggleParticleSystem(system.index)

        self.assertFalse(system.enabled)
        self.assertFalse(self.document.undo_stack.isClean())
        self.controller.undo()
        self.assertTrue(system.enabled)

    def test_texture_replacement_is_detected_and_reset_from_staged_archive(self):
        texture_id = 77
        archive = SimpleNamespace(
            staged_entries={(texture_id, TEXTURE_TYPE_ID): object()},
            particle_assets=lambda effect: [],
            texture_bindings=lambda effect: [],
            particle_material_ids=lambda effect: [],
            find_entry=lambda file_id, type_id: None,
        )
        self.document.archive = archive
        self.controller.texture_bindings_model.set_bindings([
            TextureBinding(0, 55, texture_id, "fixture", True)
        ])
        self.controller._selected_texture_index = 0

        self.assertTrue(self.controller.hasTextureReplacement)
        self.controller.resetSelectedTexture()

        self.assertFalse(self.controller.hasTextureReplacement)
        self.assertNotIn((texture_id, TEXTURE_TYPE_ID), archive.staged_entries)

    def test_texture_replacement_makes_its_particle_resettable(self):
        texture_id = 77
        self.document.modified_texture_ids.add(texture_id)

        resettable_role = self.controller.documents_model.ResettableRole
        index = self.controller.documents_model.index(0)

        self.assertTrue(self.controller.documents_model.data(index, resettable_role))

    def test_texture_patch_choice_tracks_original_or_imported(self):
        texture_id = 77
        archive = SimpleNamespace(staged_entries={(texture_id, TEXTURE_TYPE_ID): object()})
        self.document.archive = archive
        self.controller.texture_bindings_model.set_bindings([
            TextureBinding(0, 55, texture_id, "fixture", True)
        ])
        self.controller._selected_texture_index = 0

        self.controller.setSelectedTexturePatchVersion(False)

        self.assertFalse(self.controller.selectedTextureUsesImported)
        self.assertFalse(self.controller._texture_patch_choices[(id(archive), texture_id)])

    def test_standalone_particle_resolves_textures_from_the_active_archive(self):
        material_id, texture_id = 301, 401
        material_data = bytearray(148)
        struct.pack_into("<I", material_data, 64, 1)
        struct.pack_into("<Q", material_data, 140, texture_id)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "resources"
            write_patch_archive(archive_path, [
                archive_entry(material_id, MATERIAL_TYPE_ID, bytes(material_data)),
                archive_entry(texture_id, TEXTURE_TYPE_ID, b"texture"),
            ])
            particle_path = root / "standalone.particle"
            effect = ParticleEffect.from_bytes(make_particle())
            effect.particle_systems[0].visualizer.material_id = material_id
            particle_path.write_bytes(effect.to_bytes())
            controller = ParticleController()
            controller._archive = ArchiveReader.open(archive_path)

            document = controller._open_particle(particle_path)
            self.assertIsNotNone(document)
            self.assertIs(document.resource_archive, controller._archive)

            self.assertEqual(controller.texture_bindings_model.rowCount(), 1)
            binding = controller.texture_bindings_model.binding_at(0)
            self.assertEqual(binding.material_id, material_id)
            self.assertEqual(binding.texture_id, texture_id)

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

    def test_exports_original_or_edited_particle_without_changing_document_state(self):
        self.controller.setLifetime("min", "2")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original_target = root / "original.particles"
            edited_target = root / "edited.particles"
            with patch(
                "pm_particle_modder.application.controller.QFileDialog.getSaveFileName",
                return_value=(str(original_target), "Particle Files (*.particles)"),
            ):
                self.assertTrue(self.controller.exportParticles([0], False))
            with patch(
                "pm_particle_modder.application.controller.QFileDialog.getSaveFileName",
                return_value=(str(edited_target), "Particle Files (*.particles)"),
            ):
                self.assertTrue(self.controller.exportParticles([0], True))

            self.assertEqual(original_target.read_bytes(), self.document.effect.original_data)
            self.assertEqual(edited_target.read_bytes(), self.document.effect.to_bytes())
            self.assertFalse(self.document.undo_stack.isClean())

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

    def test_project_restores_disabled_particle_systems(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            particle_path = root / "fixture.particles"
            particle_path.write_bytes(make_particle())
            project_path = root / "disabled-system.pmod"
            project_path.write_text(json.dumps({
                "version": 2,
                "structure": [{"type": "file", "filepath": "fixture.particles"}],
                "selectionStates": {
                    "fixture.particles": {"enabledSystems": [False]},
                },
            }), encoding="utf-8")

            controller = ParticleController()
            controller._open_project(project_path)

            self.assertFalse(controller.current_document.effect.particle_systems[0].enabled)


if __name__ == "__main__":
    unittest.main()
