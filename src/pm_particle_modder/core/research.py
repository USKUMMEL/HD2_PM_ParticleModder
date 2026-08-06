"""Neutral helpers for comparing researched particle-system data.

The helpers intentionally describe byte layout rather than guessing gameplay
semantics.  This keeps experimental edits small and auditable.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import struct

from .particle import ParticleDataBlock, ParticleSlot, ParticleSystem


@dataclass(frozen=True)
class SystemSignature:
    """Structure used to decide whether system-relative comparison is sound."""

    component_count: int
    particle_stride: int
    slot_widths: tuple[int, ...]
    behavior_size: int
    emitter_size: int
    visualizer_type: int | None


@dataclass(frozen=True)
class SystemCompatibility:
    level: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class WordDifference:
    """A four-byte, block-relative difference between two particle systems."""

    relative_offset: int
    left_offset: int
    right_offset: int
    left_bytes: bytes
    right_bytes: bytes
    left_u32: int
    right_u32: int
    left_i32: int
    right_i32: int
    left_f32: float
    right_f32: float
    likely_scalar: bool
    slot: ParticleSlot | None = None


def system_signature(system: ParticleSystem) -> SystemSignature:
    return SystemSignature(
        component_count=system.component_count,
        particle_stride=system.particle_stride,
        slot_widths=system.slot_widths,
        behavior_size=system.behavior_data.size if system.behavior_data else 0,
        emitter_size=system.emitter_data.size if system.emitter_data else 0,
        visualizer_type=system.visualizer.visualizer_type if system.visualizer else None,
    )


def compare_systems(left: ParticleSystem, right: ParticleSystem) -> SystemCompatibility:
    """Return a conservative compatibility level with visible reasons."""
    left_signature = system_signature(left)
    right_signature = system_signature(right)
    reasons = []
    if left_signature.slot_widths == right_signature.slot_widths:
        reasons.append("Same slot layout")
    else:
        reasons.append("Different slot layout")
    if left_signature.behavior_size == right_signature.behavior_size:
        reasons.append("Same behavior block size")
    else:
        reasons.append("Different behavior block size")
    if left_signature.visualizer_type == right_signature.visualizer_type:
        reasons.append("Same visualizer type")
    else:
        reasons.append("Different visualizer type")
    if left_signature.emitter_size == right_signature.emitter_size:
        reasons.append("Same emitter block size")
    else:
        reasons.append("Different emitter block size")

    if left_signature == right_signature:
        level = "Exact"
    elif (
        left_signature.slot_widths == right_signature.slot_widths
        and left_signature.behavior_size == right_signature.behavior_size
        and left_signature.visualizer_type == right_signature.visualizer_type
    ):
        level = "Strong"
    elif left_signature.slot_widths == right_signature.slot_widths:
        level = "Partial"
    else:
        level = "Incompatible"
    return SystemCompatibility(level, tuple(reasons))


def system_blocks(system: ParticleSystem) -> dict[str, ParticleDataBlock]:
    """Return only blocks with known, stable boundaries for word comparison."""
    blocks = {}
    if system.header_size:
        blocks["header"] = ParticleDataBlock(system.offset, system.header_size)
    if system.behavior_data is not None and system.behavior_data.size:
        blocks["behavior"] = system.behavior_data
    if system.emitter_data is not None and system.emitter_data.size:
        blocks["emitter"] = system.emitter_data
    if system.visualizer_data is not None and system.visualizer_data.size:
        blocks["visualizer"] = system.visualizer_data
    return blocks


def word_differences(
    left_data: bytes,
    right_data: bytes,
    left_system: ParticleSystem,
    right_system: ParticleSystem,
    block_name: str,
) -> tuple[WordDifference, ...]:
    """Compare a known block by aligned 32-bit words, without guessing fields."""
    left_block = system_blocks(left_system).get(block_name)
    right_block = system_blocks(right_system).get(block_name)
    if left_block is None or right_block is None:
        return ()
    word_count = min(left_block.size, right_block.size) // 4
    slots = {slot.offset: slot for slot in left_system.slots}
    differences = []
    for word_index in range(word_count):
        relative_offset = word_index * 4
        left_offset = left_block.offset + relative_offset
        right_offset = right_block.offset + relative_offset
        left_bytes = left_data[left_offset:left_offset + 4]
        right_bytes = right_data[right_offset:right_offset + 4]
        if left_bytes == right_bytes:
            continue
        left_u32 = struct.unpack("<I", left_bytes)[0]
        right_u32 = struct.unpack("<I", right_bytes)[0]
        left_f32 = struct.unpack("<f", left_bytes)[0]
        right_f32 = struct.unpack("<f", right_bytes)[0]
        differences.append(WordDifference(
            relative_offset=relative_offset,
            left_offset=left_offset,
            right_offset=right_offset,
            left_bytes=left_bytes,
            right_bytes=right_bytes,
            left_u32=left_u32,
            right_u32=right_u32,
            left_i32=struct.unpack("<i", left_bytes)[0],
            right_i32=struct.unpack("<i", right_bytes)[0],
            left_f32=left_f32,
            right_f32=right_f32,
            likely_scalar=(
                math.isfinite(left_f32)
                and math.isfinite(right_f32)
                and max(abs(left_f32), abs(right_f32)) <= 1_000_000.0
            ),
            slot=slots.get(left_u32) if block_name == "behavior" else None,
        ))
    return tuple(differences)
