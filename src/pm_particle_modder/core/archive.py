from __future__ import annotations

from dataclasses import dataclass, replace
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

from lz4 import block as lz4_block

from .particle import ParticleEffect


ARCHIVE_MAGIC = 0xF0000011
DSAR_MAGIC = 0x52415344
PARTICLE_TYPE_ID = 12112766700566326628
TEXTURE_TYPE_ID = 14790446551990181426
MATERIAL_TYPE_ID = 16915718763308572383
UNIT_TYPE_ID = 16187218042980615487


class ArchiveError(ValueError):
    """Raised when a Stingray archive cannot be read or written safely."""


@dataclass(frozen=True)
class ArchiveEntry:
    file_id: int
    type_id: int
    toc_offset: int
    stream_offset: int
    gpu_offset: int
    unknown1: int
    unknown2: int
    toc_size: int
    stream_size: int
    gpu_size: int
    unknown3: int
    unknown4: int
    index: int
    toc_data: bytes
    gpu_data: bytes
    stream_data: bytes

    def with_data(self, toc_data: bytes, gpu_data: bytes = b"", stream_data: bytes = b"") -> ArchiveEntry:
        return replace(
            self,
            toc_size=len(toc_data),
            gpu_size=len(gpu_data),
            stream_size=len(stream_data),
            toc_data=bytes(toc_data),
            gpu_data=bytes(gpu_data),
            stream_data=bytes(stream_data),
        )


@dataclass(frozen=True)
class MaterialInfo:
    parent_material_id: int
    texture_ids: tuple[int, ...]


@dataclass(frozen=True)
class TextureInfo:
    dxgi_format: int
    width: int
    height: int
    mip_count: int
    array_size: int
    dds: bytes


@dataclass(frozen=True)
class AssetLink:
    kind: str
    file_id: int
    detail: str
    available: bool
    source_id: int | None = None


@dataclass(frozen=True)
class SlimPackagePart:
    archive_offset: int
    bundle_offset: int
    bundle_index: int


@dataclass(frozen=True)
class SlimPackage:
    name: str
    size: int
    parts: tuple[SlimPackagePart, ...]


class SlimArchiveStore:
    """Reconstruct logical Slim packages from the game's bundle mapping."""

    def __init__(self, data_directory: str | Path):
        self.data_directory = Path(data_directory).expanduser().resolve()
        mapping_path = self.data_directory / "bundles.nxa"
        if not mapping_path.is_file():
            raise ArchiveError("The selected folder does not contain bundles.nxa.")
        mapping = _read_package_data(mapping_path)
        if len(mapping) < 24:
            raise ArchiveError("bundles.nxa is too small.")
        self.packages = self._parse_packages(mapping)
        self._chunk_offsets: dict[str, dict[int, int]] = {}

    def open_archive(self, archive_id: str) -> ArchiveReader:
        normalized = archive_id.lower().removeprefix("0x")
        package = self.packages.get(normalized)
        if package is None:
            raise ArchiveError(f"Archive ID {archive_id} was not found in bundles.nxa.")
        toc = self._reconstruct(package)
        gpu = self._reconstruct_optional(normalized + ".gpu_resources")
        stream = self._reconstruct_optional(normalized + ".stream")
        return ArchiveReader(self.data_directory / normalized, toc, gpu, stream)

    def _reconstruct_optional(self, package_name: str) -> bytes:
        package = self.packages.get(package_name)
        return self._reconstruct(package) if package else b""

    def _parse_packages(self, data: bytes) -> dict[str, SlimPackage]:
        package_count = _u32(data, 16)
        table_end = 24 + package_count * 24
        if table_end > len(data):
            raise ArchiveError("bundles.nxa package table is outside the file.")
        packages: dict[str, SlimPackage] = {}
        for index in range(package_count):
            offset = 24 + index * 24
            size, name_offset, item_count, item_offset = struct.unpack_from("<QIII", data, offset)
            if name_offset >= len(data) or item_offset + item_count * 16 > len(data):
                raise ArchiveError("bundles.nxa contains an invalid package entry.")
            name_end = data.find(b"\0", name_offset)
            if name_end < 0:
                raise ArchiveError("bundles.nxa contains an unterminated package name.")
            name = data[name_offset:name_end].decode("ascii").lower()
            parts = []
            for item_index in range(item_count):
                item = item_offset + item_index * 16
                archive_offset, bundle_offset = struct.unpack_from("<QI", data, item)
                parts.append(SlimPackagePart(archive_offset, bundle_offset, data[item + 15]))
            packages[name] = SlimPackage(name, size, tuple(parts))
        return packages

    def _reconstruct(self, package: SlimPackage) -> bytes:
        output = bytearray(package.size)
        for index, part in enumerate(package.parts):
            next_offset = package.parts[index + 1].archive_offset if index + 1 < len(package.parts) else package.size
            needed = next_offset - part.archive_offset
            if needed < 0:
                raise ArchiveError(f"Slim package {package.name} has unordered parts.")
            data = self._read_bundle_range(part.bundle_index, part.bundle_offset, needed)
            output[part.archive_offset:part.archive_offset + needed] = data[:needed]
        return bytes(output)

    def _read_bundle_range(self, bundle_index: int, offset: int, size: int) -> bytes:
        bundle_name = f"bundles.{bundle_index:02d}.nxa"
        bundle_path = self.data_directory / bundle_name
        if not bundle_path.is_file():
            raise ArchiveError(f"Slim bundle {bundle_name} is missing.")
        offsets = self._chunk_offsets.get(bundle_name)
        if offsets is None:
            offsets = _dsar_chunk_offsets(bundle_path)
            self._chunk_offsets[bundle_name] = offsets
        resources = []
        current_size = 0
        while current_size < size:
            resource = self._read_bundle_resource(bundle_path, offsets, offset + current_size)
            if not resource:
                raise ArchiveError(f"Bundle resource at 0x{offset + current_size:X} is empty.")
            resources.append(resource)
            current_size += len(resource)
        return b"".join(resources)

    @staticmethod
    def _read_bundle_resource(bundle_path: Path, offsets: dict[int, int], offset: int) -> bytes:
        chunk_index = offsets.get(offset)
        if chunk_index is None:
            raise ArchiveError(f"Bundle offset 0x{offset:X} was not found in {bundle_path.name}.")
        chunks = []
        with bundle_path.open("rb") as stream:
            count = _read_u32(stream, 8)
            while chunk_index < count:
                _uncompressed_offset, compressed_offset, unpacked_size, packed_size, compression, chunk_type = _read_dsar_chunk(stream, chunk_index)
                if chunks and chunk_type & 0x02:
                    break
                stream.seek(compressed_offset)
                chunks.append(_decode_dsar_chunk(stream.read(packed_size), unpacked_size, compression))
                chunk_index += 1
        return b"".join(chunks)


class ArchiveReader:
    """Read one standalone Stingray package without loading the Blender SDK."""

    def __init__(self, path: Path, toc_data: bytes, gpu_data: bytes, stream_data: bytes):
        self.path = path
        self.toc_data = bytes(toc_data)
        self.gpu_data = bytes(gpu_data)
        self.stream_data = bytes(stream_data)
        self.entries = _parse_entries(self.toc_data, self.gpu_data, self.stream_data)
        self._by_key = {(entry.file_id, entry.type_id): entry for entry in self.entries}
        self.staged_entries: dict[tuple[int, int], ArchiveEntry] = {}

    @classmethod
    def open(cls, path: str | Path) -> ArchiveReader:
        archive_path = Path(path).expanduser().resolve()
        if not archive_path.is_file():
            raise ArchiveError(f"Archive file was not found: {archive_path}")
        toc_data = _read_package_data(archive_path)
        gpu_path = archive_path.with_name(archive_path.name + ".gpu_resources")
        stream_path = archive_path.with_name(archive_path.name + ".stream")
        gpu_data = _read_package_data(gpu_path) if gpu_path.exists() else b""
        stream_data = _read_package_data(stream_path) if stream_path.exists() else b""
        return cls(archive_path, toc_data, gpu_data, stream_data)

    @classmethod
    def open_slim(cls, data_directory: str | Path, archive_id: str) -> ArchiveReader:
        return SlimArchiveStore(data_directory).open_archive(archive_id)

    def get_entry(self, file_id: int, type_id: int) -> ArchiveEntry | None:
        return self.staged_entries.get((file_id, type_id)) or self._by_key.get((file_id, type_id))

    def entries_of_type(self, type_id: int) -> list[ArchiveEntry]:
        return [entry for entry in self.entries if entry.type_id == type_id]

    def stage(self, entry: ArchiveEntry) -> None:
        if (entry.file_id, entry.type_id) not in self._by_key:
            raise ArchiveError("Only resources from this archive may be staged.")
        self.staged_entries[(entry.file_id, entry.type_id)] = entry

    def particle_assets(self, effect: ParticleEffect) -> list[AssetLink]:
        links: list[AssetLink] = []
        material_ids: set[int] = set()
        for system in effect.particle_systems:
            visualizer = system.visualizer
            if visualizer is None:
                continue
            if visualizer.material_id is not None:
                material_ids.add(visualizer.material_id)
                links.append(AssetLink(
                    "material", visualizer.material_id,
                    f"System {system.index + 1}: {visualizer.type_name}",
                    self.get_entry(visualizer.material_id, MATERIAL_TYPE_ID) is not None,
                    system.index,
                ))
            if visualizer.unit_id is not None:
                unit_entry = self.get_entry(visualizer.unit_id, UNIT_TYPE_ID)
                links.append(AssetLink(
                    "unit", visualizer.unit_id,
                    f"System {system.index + 1}: mesh visualizer unit",
                    unit_entry is not None,
                    system.index,
                ))
                if visualizer.mesh_id is not None:
                    links.append(AssetLink(
                        "mesh", visualizer.mesh_id,
                        f"System {system.index + 1}: mesh in unit {visualizer.unit_id}",
                        unit_entry is not None,
                        visualizer.unit_id,
                    ))
                unit_materials = parse_unit_material_ids(unit_entry.toc_data) if unit_entry else ()
                for material_id in unit_materials:
                    material_ids.add(material_id)
                    links.append(AssetLink(
                        "material", material_id,
                        f"System {system.index + 1}: mesh unit material",
                        self.get_entry(material_id, MATERIAL_TYPE_ID) is not None,
                        system.index,
                    ))

        texture_ids: set[int] = set()
        for material_id in material_ids:
            material_entry = self.get_entry(material_id, MATERIAL_TYPE_ID)
            if material_entry is None:
                continue
            material = parse_material(material_entry.toc_data)
            for texture_id in material.texture_ids:
                if texture_id in texture_ids:
                    continue
                texture_ids.add(texture_id)
                texture_entry = self.get_entry(texture_id, TEXTURE_TYPE_ID)
                detail = f"Material {material_id}"
                if texture_entry:
                    try:
                        info = parse_texture(texture_entry)
                        detail += f" | {info.width}x{info.height} | DXGI {info.dxgi_format}"
                    except ArchiveError:
                        detail += " | invalid texture header"
                links.append(AssetLink(
                    "texture", texture_id, detail, texture_entry is not None, material_id
                ))
        return _unique_links(links)

    def replace_texture_from_dds(self, texture_id: int, dds: bytes) -> ArchiveEntry:
        entry = self.get_entry(texture_id, TEXTURE_TYPE_ID)
        if entry is None:
            raise ArchiveError(f"Texture {texture_id} was not found in this archive.")
        info = parse_texture(entry)
        if len(dds) < 148 or dds[:4] != b"DDS ":
            raise ArchiveError("Texture replacement must be a DDS file with a complete header.")
        dxgi_format = _dds_dxgi_format(dds)
        if dxgi_format != info.dxgi_format:
            raise ArchiveError(
                f"DDS format DXGI {dxgi_format} does not match source DXGI {info.dxgi_format}."
            )
        texture_header = bytearray(12 + 15 * 12)
        struct.pack_into("<III", texture_header, 0, _u32(entry.toc_data, 0), 0, 0xFFFFFFFF)
        texture_header.extend(dds[:148])
        staged = entry.with_data(bytes(texture_header), dds[148:], b"")
        self.stage(staged)
        return staged

    def replace_texture_from_png(self, texture_id: int, png_path: str | Path) -> ArchiveEntry:
        entry = self.get_entry(texture_id, TEXTURE_TYPE_ID)
        if entry is None:
            raise ArchiveError(f"Texture {texture_id} was not found in this archive.")
        info = parse_texture(entry)
        dds = png_to_dds(Path(png_path), info.dxgi_format)
        return self.replace_texture_from_dds(texture_id, dds)

    def write_patch(self, path: str | Path) -> Path:
        if not self.staged_entries:
            raise ArchiveError("There are no staged archive changes to write.")
        output = Path(path).expanduser().resolve()
        write_patch_archive(output, list(self.staged_entries.values()))
        return output


def parse_material(data: bytes) -> MaterialInfo:
    if len(data) < 136:
        raise ArchiveError("Material resource is too small.")
    parent_material_id = _u64(data, 24)
    texture_count = _u32(data, 64)
    texture_offset = 136
    end = texture_offset + texture_count * 12
    if texture_count > 4096 or end > len(data):
        raise ArchiveError("Material texture table is outside the resource.")
    texture_ids = tuple(_u64(data, texture_offset + index * 12 + 4) for index in range(texture_count))
    return MaterialInfo(parent_material_id, texture_ids)


def parse_texture(entry: ArchiveEntry) -> TextureInfo:
    if len(entry.toc_data) < 340:
        raise ArchiveError("Texture resource is too small.")
    dds = entry.toc_data[192:340] + (entry.stream_data or entry.gpu_data)
    if len(dds) < 148 or dds[:4] != b"DDS ":
        raise ArchiveError("Texture resource does not contain a DDS header.")
    return TextureInfo(
        _dds_dxgi_format(dds),
        _u32(dds, 16),
        _u32(dds, 12),
        _u32(dds, 28),
        _u32(dds, 140),
        dds,
    )


def parse_unit_material_ids(data: bytes) -> tuple[int, ...]:
    if len(data) < 116:
        return ()
    materials_offset = _u32(data, 112)
    if materials_offset == 0 or materials_offset + 4 > len(data):
        return ()
    material_count = _u32(data, materials_offset)
    ids_offset = materials_offset + 4 + material_count * 4
    end = ids_offset + material_count * 8
    if material_count > 4096 or end > len(data):
        return ()
    return tuple(_u64(data, ids_offset + index * 8) for index in range(material_count))


def png_to_dds(png_path: Path, dxgi_format: int) -> bytes:
    if not png_path.is_file():
        raise ArchiveError(f"PNG file was not found: {png_path}")
    executable = os.environ.get("PM_TEXCONV") or shutil.which("texconv") or shutil.which("texconv.exe")
    if not executable:
        raise ArchiveError(
            "PNG import needs DirectXTex texconv. Add texconv to PATH or set PM_TEXCONV."
        )
    with tempfile.TemporaryDirectory(prefix="pm-particlemodder-") as directory:
        command = [
            executable, "-y", "-o", directory, "-ft", "dds", "-dx10",
            "-f", dxgi_format_name(dxgi_format), "-sepalpha", "-alpha", "--", str(png_path),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        dds_path = Path(directory) / f"{png_path.stem}.dds"
        if result.returncode != 0 or not dds_path.is_file():
            message = result.stderr.strip() or result.stdout.strip() or "texconv did not create DDS output."
            raise ArchiveError(f"PNG conversion failed: {message}")
        return dds_path.read_bytes()


def dxgi_format_name(value: int) -> str:
    formats = {
        28: "R8G8B8A8_UNORM", 29: "R8G8B8A8_UNORM_SRGB",
        71: "BC1_UNORM", 72: "BC1_UNORM_SRGB", 74: "BC2_UNORM",
        75: "BC2_UNORM_SRGB", 77: "BC3_UNORM", 78: "BC3_UNORM_SRGB",
        80: "BC4_UNORM", 81: "BC4_SNORM", 83: "BC5_UNORM", 84: "BC5_SNORM",
        95: "BC6H_UF16", 96: "BC6H_SF16", 98: "BC7_UNORM", 99: "BC7_UNORM_SRGB",
    }
    try:
        return formats[value]
    except KeyError as error:
        raise ArchiveError(f"DXGI format {value} is not supported for PNG conversion.") from error


def write_patch_archive(path: Path, entries: list[ArchiveEntry]) -> None:
    grouped: dict[int, list[ArchiveEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.type_id, []).append(entry)
    ordered_types = sorted(grouped)
    ordered_entries = [entry for type_id in ordered_types for entry in grouped[type_id]]
    header_size = 72 + len(ordered_types) * 32 + len(ordered_entries) * 80
    toc_cursor = max(header_size, len(ordered_entries) * 256)
    toc_offsets: list[int] = []
    for entry in ordered_entries:
        toc_offsets.append(toc_cursor)
        toc_cursor += len(entry.toc_data)
    gpu_data, gpu_offsets = _pack_sidecar([entry.gpu_data for entry in ordered_entries])
    stream_data, stream_offsets = _pack_sidecar([entry.stream_data for entry in ordered_entries])

    toc = bytearray(toc_cursor)
    struct.pack_into("<IIII", toc, 0, ARCHIVE_MAGIC, len(ordered_types), len(ordered_entries), 0)
    type_cursor = 72
    for type_id in ordered_types:
        struct.pack_into("<QQQII", toc, type_cursor, 0, type_id, len(grouped[type_id]), 16, 64)
        type_cursor += 32
    entry_cursor = 72 + len(ordered_types) * 32
    for index, (entry, toc_offset, gpu_offset, stream_offset) in enumerate(
        zip(ordered_entries, toc_offsets, gpu_offsets, stream_offsets), start=1
    ):
        struct.pack_into(
            "<QQQQQQQIIIIII", toc, entry_cursor,
            entry.file_id, entry.type_id, toc_offset, stream_offset, gpu_offset,
            entry.unknown1, entry.unknown2, len(entry.toc_data), len(entry.stream_data),
            len(entry.gpu_data), entry.unknown3 or 16, entry.unknown4 or 64, index,
        )
        entry_cursor += 80
        toc[toc_offset:toc_offset + len(entry.toc_data)] = entry.toc_data
    _atomic_write(path, bytes(toc))
    _atomic_write(path.with_name(path.name + ".gpu_resources"), gpu_data)
    _atomic_write(path.with_name(path.name + ".stream"), stream_data)


def _parse_entries(toc_data: bytes, gpu_data: bytes, stream_data: bytes) -> list[ArchiveEntry]:
    if len(toc_data) < 72:
        raise ArchiveError("Archive TOC is too small.")
    magic, type_count, file_count, _unknown = struct.unpack_from("<IIII", toc_data, 0)
    if magic != ARCHIVE_MAGIC:
        raise ArchiveError(f"Unsupported archive magic 0x{magic:X}.")
    entry_offset = 72 + type_count * 32
    end = entry_offset + file_count * 80
    if end > len(toc_data):
        raise ArchiveError("Archive entry table is outside the TOC.")
    entries = []
    for index in range(file_count):
        fields = struct.unpack_from("<QQQQQQQIIIIII", toc_data, entry_offset + index * 80)
        file_id, type_id, toc_offset, stream_offset, gpu_offset, unknown1, unknown2, toc_size, stream_size, gpu_size, unknown3, unknown4, entry_index = fields
        _validate_span(toc_data, toc_offset, toc_size, "TOC resource")
        _validate_span(gpu_data, gpu_offset, gpu_size, "GPU resource")
        _validate_span(stream_data, stream_offset, stream_size, "stream resource")
        entries.append(ArchiveEntry(
            file_id, type_id, toc_offset, stream_offset, gpu_offset, unknown1, unknown2,
            toc_size, stream_size, gpu_size, unknown3, unknown4, entry_index,
            toc_data[toc_offset:toc_offset + toc_size], gpu_data[gpu_offset:gpu_offset + gpu_size],
            stream_data[stream_offset:stream_offset + stream_size],
        ))
    return entries


def _read_package_data(path: Path) -> bytes:
    data = path.read_bytes()
    if len(data) >= 4 and _u32(data, 0) == DSAR_MAGIC:
        return _decompress_dsar(data)
    return data


def _decompress_dsar(data: bytes) -> bytes:
    if len(data) < 32:
        raise ArchiveError("DSAR archive is too small.")
    chunk_count = _u32(data, 8)
    table_end = 32 + chunk_count * 32
    if table_end > len(data):
        raise ArchiveError("DSAR chunk table is outside the archive.")
    chunks = []
    for index in range(chunk_count):
        _uncompressed_offset, compressed_offset, uncompressed_size, compressed_size, compression, _kind = struct.unpack_from("<QQIIBB6x", data, 32 + index * 32)
        _validate_span(data, compressed_offset, compressed_size, "DSAR chunk")
        chunk = data[compressed_offset:compressed_offset + compressed_size]
        chunk = _decode_dsar_chunk(chunk, uncompressed_size, compression)
        if len(chunk) != uncompressed_size:
            raise ArchiveError(f"DSAR chunk {index} has an unexpected unpacked size.")
        chunks.append(chunk)
    return b"".join(chunks)


def _dsar_chunk_offsets(path: Path) -> dict[int, int]:
    with path.open("rb") as stream:
        if _read_u32(stream, 0) != DSAR_MAGIC:
            raise ArchiveError(f"{path.name} is not a DSAR bundle.")
        count = _read_u32(stream, 8)
        return {_read_dsar_chunk(stream, index)[0]: index for index in range(count)}


def _read_u32(stream, offset: int) -> int:
    stream.seek(offset)
    data = stream.read(4)
    if len(data) != 4:
        raise ArchiveError("Unexpected end of DSAR file.")
    return struct.unpack("<I", data)[0]


def _read_dsar_chunk(stream, index: int):
    stream.seek(32 + index * 32)
    data = stream.read(32)
    if len(data) != 32:
        raise ArchiveError("Unexpected end of DSAR chunk table.")
    return struct.unpack("<QQIIBB6x", data)


def _decode_dsar_chunk(chunk: bytes, uncompressed_size: int, compression: int) -> bytes:
    if compression == 3:
        try:
            chunk = lz4_block.decompress(chunk, uncompressed_size=uncompressed_size)
        except Exception as error:
            raise ArchiveError(f"Unable to decompress DSAR chunk: {error}") from error
    elif compression != 0:
        raise ArchiveError(f"Unsupported DSAR compression type {compression}.")
    if len(chunk) != uncompressed_size:
        raise ArchiveError("DSAR chunk has an unexpected unpacked size.")
    return chunk


def _pack_sidecar(parts: list[bytes]) -> tuple[bytes, list[int]]:
    data = bytearray()
    offsets = []
    for part in parts:
        if not part:
            offsets.append(0)
            continue
        padding = (-len(data)) % 64
        data.extend(b"\0" * padding)
        offsets.append(len(data))
        data.extend(part)
    return bytes(data), offsets


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _unique_links(links: list[AssetLink]) -> list[AssetLink]:
    unique = []
    seen = set()
    for link in links:
        key = (link.kind, link.file_id)
        if key not in seen:
            seen.add(key)
            unique.append(link)
    return unique


def _validate_span(data: bytes, offset: int, size: int, label: str) -> None:
    if size == 0:
        return
    if offset + size > len(data):
        raise ArchiveError(f"{label} is outside its file.")


def _u32(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise ArchiveError(f"Cannot read u32 at 0x{offset:X}.")
    return struct.unpack_from("<I", data, offset)[0]


def _u64(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 8 > len(data):
        raise ArchiveError(f"Cannot read u64 at 0x{offset:X}.")
    return struct.unpack_from("<Q", data, offset)[0]


def _dds_dxgi_format(dds: bytes) -> int:
    if len(dds) < 148 or dds[84:88] != b"DX10":
        raise ArchiveError("DDS must use the DX10 extended header.")
    return _u32(dds, 128)
