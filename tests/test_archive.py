from __future__ import annotations

from pathlib import Path
import struct
import tempfile
import unittest

from pm_particle_modder.core import (
    MATERIAL_TYPE_ID,
    PARTICLE_TYPE_ID,
    TEXTURE_TYPE_ID,
    ArchiveEntry,
    ArchiveReader,
    ParticleEffect,
    SlimArchiveStore,
    parse_material,
    parse_texture,
    parse_unit_material_ids,
)
from pm_particle_modder.core.archive import write_patch_archive
from test_particle import make_particle


PARTICLE_ID = 1001
MATERIAL_ID = 123456789
TEXTURE_ID = 2001


def entry(file_id: int, type_id: int, toc: bytes, gpu: bytes = b"") -> ArchiveEntry:
    return ArchiveEntry(
        file_id, type_id, 0, 0, 0, 0, 0, len(toc), 0, len(gpu), 16, 64, 0, toc, gpu, b""
    )


def make_dds(raw: bytes) -> bytes:
    header = bytearray(148)
    header[:4] = b"DDS "
    struct.pack_into("<I", header, 4, 124)
    struct.pack_into("<II", header, 12, 8, 16)
    struct.pack_into("<I", header, 28, 1)
    header[84:88] = b"DX10"
    struct.pack_into("<II", header, 128, 28, 3)
    struct.pack_into("<I", header, 140, 1)
    return bytes(header) + raw


def make_dsar(payload: bytes) -> bytes:
    data = bytearray(64 + len(payload))
    struct.pack_into("<I", data, 0, 0x52415344)
    struct.pack_into("<I", data, 8, 1)
    struct.pack_into("<QQIIBB", data, 32, 0, 64, len(payload), len(payload), 0, 2)
    data[64:] = payload
    return bytes(data)


def make_dsar_resources(resources: list[bytes]) -> bytes:
    table_size = 32 + len(resources) * 32
    data = bytearray(table_size + sum(len(resource) for resource in resources))
    struct.pack_into("<I", data, 0, 0x52415344)
    struct.pack_into("<I", data, 8, len(resources))
    uncompressed_offset = 0
    compressed_offset = table_size
    for index, resource in enumerate(resources):
        struct.pack_into(
            "<QQIIBB", data, 32 + index * 32,
            uncompressed_offset, compressed_offset, len(resource), len(resource), 0, 2,
        )
        data[compressed_offset:compressed_offset + len(resource)] = resource
        uncompressed_offset += len(resource)
        compressed_offset += len(resource)
    return bytes(data)


class ArchiveTests(unittest.TestCase):
    def test_material_and_unit_reference_parsers(self):
        material = bytearray(148)
        struct.pack_into("<Q", material, 24, 77)
        struct.pack_into("<I", material, 64, 1)
        struct.pack_into("<IQ", material, 136, 2, TEXTURE_ID)
        info = parse_material(bytes(material))
        self.assertEqual(info.parent_material_id, 77)
        self.assertEqual(info.texture_ids, (TEXTURE_ID,))

        unit = bytearray(140)
        struct.pack_into("<I", unit, 112, 116)
        struct.pack_into("<I", unit, 116, 1)
        struct.pack_into("<I", unit, 120, 42)
        struct.pack_into("<Q", unit, 124, MATERIAL_ID)
        self.assertEqual(parse_unit_material_ids(bytes(unit)), (MATERIAL_ID,))

    def test_archive_links_texture_replacement_and_patch_round_trip(self):
        material = bytearray(148)
        struct.pack_into("<I", material, 64, 1)
        struct.pack_into("<IQ", material, 136, 0, TEXTURE_ID)
        dds = make_dds(b"original")
        texture_toc = bytes(192) + dds[:148]

        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "fixture_archive"
            write_patch_archive(archive_path, [
                entry(PARTICLE_ID, PARTICLE_TYPE_ID, make_particle()),
                entry(MATERIAL_ID, MATERIAL_TYPE_ID, bytes(material)),
                entry(TEXTURE_ID, TEXTURE_TYPE_ID, texture_toc, dds[148:]),
            ])
            archive = ArchiveReader.open(archive_path)
            particle = archive.get_entry(PARTICLE_ID, PARTICLE_TYPE_ID)
            self.assertIsNotNone(particle)
            links = archive.particle_assets(ParticleEffect.from_bytes(particle.toc_data))
            self.assertEqual([(link.kind, link.file_id) for link in links], [
                ("material", MATERIAL_ID), ("texture", TEXTURE_ID),
            ])
            self.assertEqual(parse_texture(archive.get_entry(TEXTURE_ID, TEXTURE_TYPE_ID)).dds, dds)

            replacement = make_dds(b"replacement")
            archive.replace_texture_from_dds(TEXTURE_ID, replacement)
            patch_path = Path(directory) / "fixture_archive.patch_0"
            archive.write_patch(patch_path)
            patch = ArchiveReader.open(patch_path)
            patched_texture = patch.get_entry(TEXTURE_ID, TEXTURE_TYPE_ID)
            self.assertIsNotNone(patched_texture)
            self.assertEqual(parse_texture(patched_texture).dds, replacement)
            self.assertEqual(len(patch.entries), 1)

    def test_slim_store_reconstructs_archive_by_id(self):
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            archive_id = "0123456789abcdef"
            archive_path = directory_path / "source"
            write_patch_archive(archive_path, [entry(PARTICLE_ID, PARTICLE_TYPE_ID, make_particle())])
            archive_data = archive_path.read_bytes()
            split = len(archive_data) // 2
            (directory_path / "bundles.00.nxa").write_bytes(
                make_dsar_resources([archive_data[:split], archive_data[split:]])
            )

            mapping = bytearray(128)
            struct.pack_into("<II", mapping, 12, 1, 1)
            struct.pack_into("<QIII", mapping, 24, len(archive_data), 64, 1, 96)
            mapping[64:81] = archive_id.encode() + b"\0"
            struct.pack_into("<QI", mapping, 96, 0, 0)
            mapping[111] = 0
            (directory_path / "bundles.nxa").write_bytes(make_dsar(bytes(mapping)))

            archive = SlimArchiveStore(directory_path).open_archive(archive_id)
            self.assertIsNotNone(archive.get_entry(PARTICLE_ID, PARTICLE_TYPE_ID))


if __name__ == "__main__":
    unittest.main()
