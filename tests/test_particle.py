import struct
import unittest

from pm_particle_modder.core import ParticleEffect, ParticleParseError


def make_graph(x_start: float, y_start: float) -> bytes:
    x = [x_start + index for index in range(10)]
    y = [y_start + index for index in range(10)]
    return struct.pack("<40f", *(x + y + [0.0] * 20))


def make_color_graph() -> bytes:
    times = [index / 10 for index in range(10)]
    colors = [value for index in range(10) for value in (index, index + 1, index + 2)]
    return struct.pack("<40f", *(times + colors))


def make_particle() -> bytes:
    header = bytearray(80)
    struct.pack_into("<Iff", header, 0, 0x73, 1.0, 3.0)
    struct.pack_into("<II", header, 20, 0, 1)

    component = (
        struct.pack("<III", 0x05, 0x20, 0)
        + make_graph(0.0, 10.0)
        + make_graph(1.0, 20.0)
        + make_color_graph()
        + bytes(16)
    )
    system_size = 260 + 260 + len(component)
    system = bytearray(system_size)
    struct.pack_into("<II", system, 0, 100, 1)
    struct.pack_into("<I", system, 76, 0)
    struct.pack_into("<I", system, 232, 260)
    struct.pack_into("<I", system, 240, 260)
    struct.pack_into("<II", system, 252, 260, system_size)

    visualizer_offset = 260
    struct.pack_into("<IIIQ", system, visualizer_offset, 0, 4, 8, 123456789)
    system[520:] = component
    return bytes(header + system)


def make_two_system_particle() -> bytes:
    source = bytearray(make_particle())
    struct.pack_into("<I", source, 24, 2)
    source.extend(source[80:])
    return bytes(source)


class ParticleEffectTests(unittest.TestCase):
    def test_unchanged_file_round_trips_byte_for_byte(self):
        source = make_particle()
        effect = ParticleEffect.from_bytes(source)
        self.assertEqual(effect.to_bytes(), source)
        self.assertEqual(effect.version, 0x73)
        self.assertEqual(len(effect.particle_systems[0].color_graphs), 1)

    def test_edits_only_patch_supported_fields(self):
        source = make_particle()
        effect = ParticleEffect.from_bytes(source)
        system = effect.particle_systems[0]
        effect.min_lifetime = 2.0
        system.visualizer.material_id = 42
        system.opacity_graphs[0].y[3] = 0.25

        output = effect.to_bytes()
        self.assertEqual(struct.unpack_from("<f", output, 4)[0], 2.0)
        self.assertEqual(struct.unpack_from("<Q", output, 80 + 272)[0], 42)
        self.assertEqual(effect.version, struct.unpack_from("<I", output, 0)[0])

        allowed = set(range(4, 8))
        allowed.update(range(80 + 272, 80 + 280))
        opacity_value_offset = system.opacity_graphs[0].y_offset + (3 * 4)
        allowed.update(range(opacity_value_offset, opacity_value_offset + 4))
        changed = {index for index, pair in enumerate(zip(source, output)) if pair[0] != pair[1]}
        self.assertTrue(changed)
        self.assertTrue(changed.issubset(allowed))

    def test_disabled_systems_have_no_particle_capacity(self):
        source = make_two_system_particle()
        effect = ParticleEffect.from_bytes(source)
        self.assertEqual(len(effect.particle_systems), 2)
        effect.particle_systems[0].enabled = False

        output = effect.to_bytes()

        self.assertEqual(struct.unpack_from("<I", output, 24)[0], 2)
        self.assertEqual(struct.unpack_from("<I", output, 80)[0], 0)
        self.assertEqual(struct.unpack_from("<I", output, 80 + 76)[0], 0)
        self.assertEqual(len(ParticleEffect.from_bytes(output).particle_systems), 2)

    def test_parses_variables_and_unedited_system_blocks(self):
        source = bytearray(make_particle())
        system = source[80:]
        header = bytearray(96)
        struct.pack_into("<Iff", header, 0, 0x73, 1.0, 3.0)
        struct.pack_into("<II", header, 20, 1, 1)
        struct.pack_into("<I", header, 80, 0xE783D2BD)
        struct.pack_into("<3f", header, 84, 1.0, 2.0, 3.0)
        struct.pack_into("<II", system, 4, 3, 0x10)
        struct.pack_into("<2I", system, 12, 0x10, 0x04)
        struct.pack_into("<3f", system, 168, 4.0, 5.0, 6.0)
        effect = ParticleEffect.from_bytes(bytes(header + system))

        self.assertEqual(effect.variables[0].name_hash, 0xE783D2BD)
        self.assertEqual(effect.variables[0].default_value, (1.0, 2.0, 3.0))
        parsed_system = effect.particle_systems[0]
        self.assertEqual(parsed_system.max_num_particles, 100)
        self.assertEqual(parsed_system.component_count, 3)
        self.assertEqual(parsed_system.component_bit_flags, (0x10, 0x04, 0))
        self.assertEqual(parsed_system.position, (4.0, 5.0, 6.0))
        self.assertEqual(parsed_system.component_data.offset, parsed_system.offset + 260)
        self.assertEqual(parsed_system.emitter_data.size, 0)
        self.assertEqual(effect.to_bytes(), bytes(header + system))

    def test_rejects_unsupported_version(self):
        with self.assertRaisesRegex(ParticleParseError, "Unsupported particle version"):
            ParticleEffect.from_bytes(struct.pack("<I", 0x99) + bytes(100))

    def test_rejects_truncated_system(self):
        data = bytearray(100)
        struct.pack_into("<Iff", data, 0, 0x73, 1.0, 2.0)
        struct.pack_into("<II", data, 20, 0, 1)
        with self.assertRaisesRegex(ParticleParseError, "truncated header"):
            ParticleEffect.from_bytes(bytes(data))


if __name__ == "__main__":
    unittest.main()
