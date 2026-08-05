from __future__ import annotations

from dataclasses import dataclass, field
import math
import struct


CURRENT_PARTICLE_VERSION = 0x73
VALID_PARTICLE_VERSIONS = frozenset({0x73, 0x72, 0x71, 0x6F, 0x6E, 0x6D})
SENTINEL_TIME = 10000.0


class ParticleParseError(ValueError):
    """Raised when a particle file is unsupported or structurally invalid."""


class BinaryReader:
    def __init__(self, data: bytes):
        self.data = data
        self.position = 0

    def seek(self, position: int) -> None:
        if not 0 <= position <= len(self.data):
            raise ParticleParseError(
                f"Offset 0x{position:X} is outside the {len(self.data)} byte file."
            )
        self.position = position

    def skip(self, size: int) -> None:
        self.seek(self.position + size)

    def read(self, size: int) -> bytes:
        end = self.position + size
        if size < 0 or end > len(self.data):
            raise ParticleParseError(
                f"Unexpected end of file at 0x{self.position:X}; needed {size} bytes."
            )
        value = self.data[self.position:end]
        self.position = end
        return value

    def unpack(self, format_string: str):
        size = struct.calcsize(format_string)
        return struct.unpack(format_string, self.read(size))

    def u32(self) -> int:
        return self.unpack("<I")[0]

    def u64(self) -> int:
        return self.unpack("<Q")[0]

    def f32(self) -> float:
        return self.unpack("<f")[0]


@dataclass
class Graph:
    x: list[float]
    y: list[float]
    x_offset: int
    y_offset: int

    def validate(self) -> None:
        if len(self.x) != 10 or len(self.y) != 10:
            raise ValueError("Particle graphs must contain exactly 10 points.")
        for value in (*self.x, *self.y):
            if not math.isfinite(value):
                raise ValueError("Graph values must be finite numbers.")

    def write_into(self, output: bytearray) -> None:
        self.validate()
        struct.pack_into("<10f", output, self.x_offset, *self.x)
        struct.pack_into("<10f", output, self.y_offset, *self.y)


@dataclass
class ColorGraph:
    x: list[float]
    colors: list[list[float]]
    x_offset: int
    colors_offset: int

    def validate(self) -> None:
        if len(self.x) != 10 or len(self.colors) != 10:
            raise ValueError("Color graphs must contain exactly 10 points.")
        if any(len(color) != 3 for color in self.colors):
            raise ValueError("Each color point must have three channels.")
        for value in (*self.x, *(channel for color in self.colors for channel in color)):
            if not math.isfinite(value):
                raise ValueError("Color graph values must be finite numbers.")

    def write_into(self, output: bytearray) -> None:
        self.validate()
        struct.pack_into("<10f", output, self.x_offset, *self.x)
        flattened = [channel for color in self.colors for channel in color]
        struct.pack_into("<30f", output, self.colors_offset, *flattened)


@dataclass(frozen=True)
class ParticleVariable:
    """A named vector default stored in the particle effect's variable table."""

    name_hash: int
    default_value: tuple[float, float, float]
    hash_offset: int
    value_offset: int


@dataclass(frozen=True)
class ParticleDataBlock:
    """A read-only span of the original particle bytes."""

    offset: int
    size: int


@dataclass(frozen=True)
class EmitterMarker:
    """A known emitter type signature found in an emitter payload.

    A marker is deliberately not editable: type values can occur inside
    unparsed emitter payloads as well as at record boundaries.
    """

    emitter_type: int
    offset: int

    TYPE_NAMES = {
        0x03: "Unknown 1",
        0x05: "Unknown 2",
        0x0B: "Rate",
        0x0C: "Burst",
        0x19: "Unknown 3",
        0x1C: "Unknown 0",
        0x24: "Unknown 4",
    }

    @property
    def type_name(self) -> str:
        return self.TYPE_NAMES.get(self.emitter_type, f"Unknown {self.emitter_type}")


@dataclass
class Visualizer:
    visualizer_type: int
    material_id: int | None = None
    material_offset: int | None = None
    unit_id: int | None = None
    unit_offset: int | None = None
    mesh_id: int | None = None
    mesh_offset: int | None = None

    TYPE_NAMES = {
        0: "Billboard",
        1: "Light",
        2: "Mesh",
        3: "Unknown 3",
        4: "Unknown 4",
    }

    @property
    def type_name(self) -> str:
        return self.TYPE_NAMES.get(self.visualizer_type, f"Unknown {self.visualizer_type}")

    def write_into(self, output: bytearray) -> None:
        for value, offset, label in (
            (self.material_id, self.material_offset, "material"),
            (self.unit_id, self.unit_offset, "unit"),
            (self.mesh_id, self.mesh_offset, "mesh"),
        ):
            if value is None or offset is None:
                continue
            if not 0 <= value <= 0xFFFFFFFFFFFFFFFF:
                raise ValueError(f"The {label} ID must be an unsigned 64-bit integer.")
            struct.pack_into("<Q", output, offset, value)


@dataclass
class ParticleSystem:
    index: int
    offset: int
    size: int
    non_rendering: int
    max_num_particles: int = 0
    component_count: int = 0
    component_header_type: int = 0
    component_bit_flags: tuple[int, ...] = ()
    header_values: tuple[int, ...] = ()
    rotation_rows: tuple[tuple[float, float, float], ...] = ()
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    component_data: ParticleDataBlock | None = None
    emitter_data: ParticleDataBlock | None = None
    emitter_markers: tuple[EmitterMarker, ...] = ()
    visualizer: Visualizer | None = None
    scale_graphs: list[Graph] = field(default_factory=list)
    opacity_graphs: list[Graph] = field(default_factory=list)
    color_graphs: list[ColorGraph] = field(default_factory=list)
    enabled: bool = True

    @property
    def is_rendering(self) -> bool:
        return self.non_rendering == 0


@dataclass
class ParticleEffect:
    original_data: bytes
    version: int
    min_lifetime: float
    max_lifetime: float
    variables: list[ParticleVariable]
    particle_systems: list[ParticleSystem]

    @classmethod
    def from_bytes(cls, data: bytes) -> ParticleEffect:
        reader = BinaryReader(data)
        try:
            version = reader.u32()
            if version not in VALID_PARTICLE_VERSIONS:
                versions = ", ".join(f"0x{value:X}" for value in sorted(VALID_PARTICLE_VERSIONS))
                raise ParticleParseError(
                    f"Unsupported particle version 0x{version:X}. Supported versions: {versions}."
                )

            min_lifetime = reader.f32()
            max_lifetime = reader.f32()
            reader.skip(8)
            num_variables = reader.u32()
            num_systems = reader.u32()
            reader.skip(44)
            if version in {0x6F, 0x71, 0x72, 0x73}:
                reader.skip(8)

            variable_table_offset = reader.position
            variable_bytes = num_variables * (4 + 12)
            if variable_bytes > len(data) - variable_table_offset:
                raise ParticleParseError("Variable table extends beyond the file.")
            hashes = [reader.u32() for _ in range(num_variables)]
            variables = [
                ParticleVariable(
                    name_hash,
                    reader.unpack("<3f"),
                    variable_table_offset + (index * 4),
                    variable_table_offset + (num_variables * 4) + (index * 12),
                )
                for index, name_hash in enumerate(hashes)
            ]

            systems = [
                _parse_particle_system(reader, index)
                for index in range(num_systems)
            ]
        except struct.error as error:
            raise ParticleParseError(f"Invalid binary value: {error}") from error

        return cls(data, version, min_lifetime, max_lifetime, variables, systems)

    def to_bytes(self) -> bytes:
        if not math.isfinite(self.min_lifetime) or not math.isfinite(self.max_lifetime):
            raise ValueError("Lifetime values must be finite numbers.")
        if self.min_lifetime > self.max_lifetime:
            raise ValueError("Minimum lifetime cannot exceed maximum lifetime.")

        output = bytearray(self.original_data)
        struct.pack_into("<ff", output, 4, self.min_lifetime, self.max_lifetime)
        for system in self.particle_systems:
            if system.visualizer is not None:
                system.visualizer.write_into(output)
            for graph in system.scale_graphs:
                graph.write_into(output)
            for graph in system.opacity_graphs:
                graph.write_into(output)
            for graph in system.color_graphs:
                graph.write_into(output)

        for system in self.particle_systems:
            if not system.enabled and system.non_rendering == 0:
                # Suppress user-disabled systems without changing their binary layout.
                # Native non-rendering systems already use a different compact block.
                struct.pack_into("<I", output, system.offset, 0)
        return bytes(output)


def _parse_particle_system(reader: BinaryReader, index: int) -> ParticleSystem:
    start = reader.position
    if len(reader.data) - start < 260:
        raise ParticleParseError(f"Particle system {index} has a truncated header.")

    max_num_particles = reader.u32()
    component_count = reader.u32()
    component_header = reader.read(68)
    component_header_type = struct.unpack_from("<I", component_header)[0]
    bit_flag_count = min(component_count, 16)
    component_bit_flags = struct.unpack_from(f"<{bit_flag_count}I", component_header, 4)
    non_rendering = reader.u32()
    header_values = reader.unpack("<10I")
    rotation_bytes = reader.read(48)
    rotation_rows = tuple(
        struct.unpack_from("<3f", rotation_bytes, row * 16)
        for row in range(3)
    )
    position = reader.unpack("<3f")
    reader.skip(52)
    component_list_offset = reader.u32()
    reader.skip(4)
    emitter_offset = reader.u32()
    reader.skip(8)
    visualizer_offset = reader.u32()
    size = reader.u32()

    if size < 260 or start + size > len(reader.data):
        raise ParticleParseError(f"Particle system {index} has invalid size 0x{size:X}.")
    if not (0 <= component_list_offset <= emitter_offset <= visualizer_offset <= size):
        raise ParticleParseError(f"Particle system {index} has invalid chunk offsets.")

    component_data = ParticleDataBlock(start + component_list_offset, emitter_offset - component_list_offset)
    emitter_data = ParticleDataBlock(start + emitter_offset, visualizer_offset - emitter_offset)
    system = ParticleSystem(
        index,
        start,
        size,
        non_rendering,
        max_num_particles=max_num_particles,
        component_count=component_count,
        component_header_type=component_header_type,
        component_bit_flags=component_bit_flags,
        header_values=header_values,
        rotation_rows=rotation_rows,
        position=position,
        component_data=component_data,
        emitter_data=emitter_data,
        emitter_markers=_find_emitter_markers(reader.data, emitter_data),
        enabled=non_rendering == 0,
    )
    end = start + size
    if non_rendering == 0 and visualizer_offset != size:
        visualizer, component_start = _parse_visualizer(reader.data, start + visualizer_offset, end)
        system.visualizer = visualizer
        _parse_components(reader.data, component_start, end, system)

    reader.seek(end)
    return system


def _find_emitter_markers(data: bytes, block: ParticleDataBlock) -> tuple[EmitterMarker, ...]:
    markers = []
    for offset in range(block.offset, block.offset + block.size - 3, 4):
        emitter_type = struct.unpack_from("<I", data, offset)[0]
        if emitter_type in EmitterMarker.TYPE_NAMES:
            markers.append(EmitterMarker(emitter_type, offset))
    return tuple(markers)


def _parse_visualizer(data: bytes, offset: int, system_end: int) -> tuple[Visualizer, int]:
    visualizer_type = _u32_at(data, offset, system_end)
    visualizer = Visualizer(visualizer_type)

    if visualizer_type == 0:
        visualizer.material_offset = offset + 12
        visualizer.material_id = _u64_at(data, visualizer.material_offset, system_end)
        size = 260
    elif visualizer_type == 1:
        size = 260
    elif visualizer_type == 2:
        visualizer.unit_offset = offset + 4
        visualizer.mesh_offset = offset + 12
        visualizer.material_offset = offset + 20
        visualizer.unit_id = _u64_at(data, visualizer.unit_offset, system_end)
        visualizer.mesh_id = _u64_at(data, visualizer.mesh_offset, system_end)
        visualizer.material_id = _u64_at(data, visualizer.material_offset, system_end)
        size = 252
    elif visualizer_type == 3:
        visualizer.material_offset = offset + 12
        visualizer.material_id = _u64_at(data, visualizer.material_offset, system_end)
        size = 252
    elif visualizer_type == 4:
        visualizer.material_offset = offset + 4
        visualizer.material_id = _u64_at(data, visualizer.material_offset, system_end)
        size = 260
    else:
        raise ParticleParseError(f"Unknown visualizer type {visualizer_type} at 0x{offset:X}.")

    if offset + size > system_end:
        raise ParticleParseError(f"Visualizer at 0x{offset:X} extends beyond its particle system.")
    return visualizer, offset + size


def _parse_components(
    data: bytes,
    position: int,
    system_end: int,
    system: ParticleSystem,
) -> None:
    while position + 4 <= system_end:
        component_start = position
        component_type = _u32_at(data, position, system_end)
        position += 4

        if component_type in {0x04, 0x05, 0x0F}:
            if position + 4 > system_end:
                break
            subtype = _u32_at(data, position, system_end)
            position += 4
            if subtype < 0x20:
                position -= 4
                continue
            position -= 8
        elif component_type == 0x00:
            continue
        elif component_type == 0x11:
            if position + 284 < system_end:
                position += 284
        elif component_type == 0x0B:
            position = min(position + 24, system_end)
            continue
        else:
            continue

        if position + 16 > system_end:
            break
        header = struct.unpack_from("<4I", data, position)
        position += 16

        if header[0] == 0x04 and header[1] >= 0x20:
            position += 4
            _, position = _read_graph(data, position, system_end)
            position = min(position + 8, system_end)
        elif header[0] == 0x05 and header[1] >= 0x20:
            position -= 4
            scale, position = _read_graph(data, position, system_end)
            opacity, position = _read_graph(data, position, system_end)
            color, position = _read_color_graph(data, position, system_end)
            system.scale_graphs.append(scale)
            system.opacity_graphs.append(opacity)
            system.color_graphs.append(color)
            position = min(position + 16, system_end)
        elif header[1] == 0x05 and header[2] >= 0x20:
            scale, position = _read_graph(data, position, system_end)
            opacity, position = _read_graph(data, position, system_end)
            color, position = _read_color_graph(data, position, system_end)
            system.scale_graphs.append(scale)
            system.opacity_graphs.append(opacity)
            system.color_graphs.append(color)
            position = min(position + 16, system_end)
        elif header[0] == 0x0F and header[1] >= 0x20:
            position -= 4
            opacity, position = _read_graph(data, position, system_end)
            color, position = _read_color_graph(data, position, system_end)
            system.opacity_graphs.append(opacity)
            system.color_graphs.append(color)
            position = min(position + 16, system_end)
        elif header[0] == 0x0B:
            position = min(position + 12, system_end)

        if position <= component_start:
            raise ParticleParseError(f"Component parser stalled at 0x{component_start:X}.")


def _read_graph(data: bytes, offset: int, limit: int) -> tuple[Graph, int]:
    size = 160  # Two layers; PM currently edits the first layer only.
    if offset + size > limit:
        raise ParticleParseError(f"Graph at 0x{offset:X} extends beyond its particle system.")
    x = list(struct.unpack_from("<10f", data, offset))
    y = list(struct.unpack_from("<10f", data, offset + 40))
    return Graph(x, y, offset, offset + 40), offset + size


def _read_color_graph(data: bytes, offset: int, limit: int) -> tuple[ColorGraph, int]:
    size = 160
    if offset + size > limit:
        raise ParticleParseError(f"Color graph at 0x{offset:X} extends beyond its particle system.")
    x = list(struct.unpack_from("<10f", data, offset))
    channels = struct.unpack_from("<30f", data, offset + 40)
    colors = [list(channels[index:index + 3]) for index in range(0, 30, 3)]
    return ColorGraph(x, colors, offset, offset + 40), offset + size


def _u32_at(data: bytes, offset: int, limit: int) -> int:
    if offset < 0 or offset + 4 > min(limit, len(data)):
        raise ParticleParseError(f"Cannot read u32 at 0x{offset:X}.")
    return struct.unpack_from("<I", data, offset)[0]


def _u64_at(data: bytes, offset: int, limit: int) -> int:
    if offset < 0 or offset + 8 > min(limit, len(data)):
        raise ParticleParseError(f"Cannot read u64 at 0x{offset:X}.")
    return struct.unpack_from("<Q", data, offset)[0]
