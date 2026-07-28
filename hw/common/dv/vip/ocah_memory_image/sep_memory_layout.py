# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Tenstorrent Inc.
"""
sep_memory_layout.py — SEP memory bank descriptors for OcahMemoryImage.

Defines the ``MemoryBank`` dataclass, the ``SepMemoryLayout`` container, and
the ``SepMemoryLayout.default()`` factory that returns the default SEP-style
memory banks used by the image loader.

A user can supply a custom layout by constructing ``SepMemoryLayout`` with an
explicit list of ``MemoryBank`` entries, or by loading a YAML file produced
from the ``examples/example_layout.yaml`` template.

Bank routing relies solely on the ``base_addr`` / ``size_bytes`` window of
each bank.  For wide-word memories (KM ROM/SRAM at 36 bits, OTBN IMEM at 39
bits, OTBN DMEM at 312 bits) the ``data_width_bits`` field is used by the hex
serialiser in ``ocah_memory_image.py``.  ECC / parity fields in those wider
words are zeroed unless the caller pre-encodes them.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Dict, List, Optional

__all__ = ["MemoryBank", "SepMemoryLayout"]

log = logging.getLogger(__name__)


@dataclasses.dataclass
class MemoryBank:
    """Descriptor for a single SEP memory bank.

    Attributes
    ----------
    name:
        Short tag used as a dict key and in log messages (e.g. ``"sep_sram"``).
    plusarg:
        Simulator plusarg that this bank responds to (e.g.
        ``"+sep_sram_preload"``).  The leading ``+`` is included.
    base_addr:
        Byte base address of the bank in the SEP address space.  Used for ELF
        section routing.  Pass ``None`` for banks that are not directly mapped
        into the CPU address space (KM ROM/SRAM, OTBN IMEM/DMEM) — those banks
        can only be loaded explicitly via ``load_hex``/``load_bin``.
    size_bytes:
        Total byte capacity of the bank.  Used to reject oversized images.
    depth:
        Number of addressable words.
    data_width_bits:
        Bits per word as seen at the memory interface (including ECC/parity if
        the bank has them).  Determines hex digit count per line.
    """

    name: str
    plusarg: str
    base_addr: Optional[int]  # None = not CPU-mapped (KM ROM/SRAM, OTBN)
    size_bytes: int
    depth: int
    data_width_bits: int

    # ------------------------------------------------------------------ #
    # Derived helpers                                                       #
    # ------------------------------------------------------------------ #

    @property
    def hex_digits_per_word(self) -> int:
        """Number of hex characters needed to represent one word, MSB first.

        Rounded up to an integer number of nibbles (4-bit groups).
        """
        return (self.data_width_bits + 3) // 4

    @property
    def bytes_per_word(self) -> int:
        """Byte width of the *data* portion (floor division; ignores ECC).

        For standard banks the data portion is ``data_width_bits``.
        For banks with ECC/parity the ECC is stored in the upper nibbles of
        the hex representation.  The byte count here is the payload only —
        used when splitting a byte stream into words for hex emission.

        For KM ROM/SRAM (36-bit) and OTBN IMEM (39-bit) the data portion is
        32 bits = 4 bytes; for OTBN DMEM (312-bit) the data portion is 256
        bits = 32 bytes.
        """
        # For non-power-of-2 widths, round down to data bytes.
        # This table matches what firmware loaders actually care about:
        # the pure data bits per word without ECC.
        _data_bits: Dict[int, int] = {
            64: 64,   # SEP SRAM, boot ROM — no ECC stored in the hex file
            39: 32,   # TCM / OTBN IMEM (39-bit: 32 data + 7 ECC)
            36: 32,   # KM ROM / SRAM (36-bit: 32 data + 4 parity)
            312: 256, # OTBN DMEM (312-bit: 8 x 39-bit sub-words = 256 data bits)
        }
        bits = _data_bits.get(self.data_width_bits, self.data_width_bits)
        return bits // 8

    def contains_addr(self, byte_addr: int) -> bool:
        """Return True if ``byte_addr`` falls within this bank's address window."""
        if self.base_addr is None:
            return False
        return self.base_addr <= byte_addr < self.base_addr + self.size_bytes

    def word_offset_for(self, byte_addr: int) -> int:
        """Convert a CPU byte address to a zero-based word index into this bank."""
        if self.base_addr is None:
            raise ValueError(f"Bank {self.name!r} is not CPU-mapped")
        return (byte_addr - self.base_addr) // self.bytes_per_word


# --------------------------------------------------------------------------- #
# SEP memory layout container                                                   #
# --------------------------------------------------------------------------- #

class SepMemoryLayout:
    """Container for a set of ``MemoryBank`` descriptors.

    Build via ``SepMemoryLayout.default()`` or supply an explicit list of
    ``MemoryBank`` objects.  Banks are keyed by their ``name`` attribute.
    """

    def __init__(self, banks: List[MemoryBank]) -> None:
        self._banks: Dict[str, MemoryBank] = {}
        for b in banks:
            if b.name in self._banks:
                raise ValueError(f"Duplicate bank name: {b.name!r}")
            self._banks[b.name] = b

    # ------------------------------------------------------------------ #
    # Factory                                                               #
    # ------------------------------------------------------------------ #

    @classmethod
    def default(cls) -> "SepMemoryLayout":
        """Return the canonical SEP layout from Task #9 INTERFACE.md.

        Address windows are taken from the SEP memory map and the SEP top-level
        address decoder. The values below match the loader defaults; if your
        chip configuration uses a different base, construct a custom layout.

        SEP address map (typical):
          - SEP SRAM:      0x2000_0000 .. 0x2003_FFFF  (256 KB)
          - SEP Boot ROM:  0x0000_0000 .. 0x0001_FFFF  (128 KB)
          - SEP TCM:       0x4000_0000 .. 0x4003_FFFF  (256 KB, ICCM+DCCM)
          - KM ROM:        None (not CPU-mapped)
          - KM SRAM:       None (not CPU-mapped)
          - OTBN IMEM:     None (loaded by SEP firmware via AXI fabric)
          - OTBN DMEM:     None (loaded by SEP firmware via AXI fabric)

        NOTE: Base addresses here are *illustrative* defaults derived from
        the OSS documentation.  The authoritative address map is in the SEP
        top-level register map / address decoder RTL.  Adjust via a custom
        layout YAML if your chip address map differs.
        """
        return cls([
            MemoryBank(
                name="sep_sram",
                plusarg="+sep_sram_preload",
                base_addr=0x2000_0000,
                size_bytes=256 * 1024,      # 256 KB
                depth=32768,                # 32768 × 64-bit words
                data_width_bits=64,
            ),
            MemoryBank(
                name="sep_boot_rom",
                plusarg="+sep_boot_rom_preload",
                base_addr=0x0000_0000,
                size_bytes=128 * 1024,      # 128 KB
                depth=16384,                # 16384 × 64-bit words
                data_width_bits=64,
            ),
            MemoryBank(
                name="sep_tcm",
                plusarg="+sep_tcm_preload",
                base_addr=0x4000_0000,
                size_bytes=256 * 1024,      # 256 KB (ICCM + DCCM combined)
                depth=32768,                # EL2-param driven; 39-bit words
                data_width_bits=39,
            ),
            MemoryBank(
                name="km_rom",
                plusarg="+km_rom_preload",
                base_addr=None,             # not CPU-mapped
                size_bytes=4096 * 4,        # 4096 × 4-byte data words = 16 KB
                depth=4096,                 # 4096 × 36-bit words
                data_width_bits=36,
            ),
            MemoryBank(
                name="km_sram",
                plusarg="+km_sram_preload",
                base_addr=None,             # not CPU-mapped
                size_bytes=4096 * 4,        # 4096 × 4-byte data words = 16 KB
                depth=4096,                 # 4096 × 36-bit words
                data_width_bits=36,
            ),
            MemoryBank(
                name="otbn_imem",
                plusarg="+otbn_imem_preload",
                base_addr=None,             # loaded via AXI fabric
                size_bytes=4096 * 4,        # 4096 × 4-byte data words = 16 KB
                depth=4096,                 # 4096 × 39-bit words
                data_width_bits=39,
            ),
            MemoryBank(
                name="otbn_dmem",
                plusarg="+otbn_dmem_preload",
                base_addr=None,             # loaded via AXI fabric
                size_bytes=1024 * 32,       # 1024 × 32-byte data words = 32 KB
                depth=1024,                 # 1024 × 312-bit words
                data_width_bits=312,
            ),
        ])

    @classmethod
    def from_yaml(cls, path: str) -> "SepMemoryLayout":
        """Load a layout from a YAML file.

        The YAML must be a list of dicts, each with keys matching the
        ``MemoryBank`` field names.  See ``examples/example_layout.yaml``.

        Requires PyYAML (``pip install pyyaml``).
        """
        import yaml  # type: ignore  # optional dependency

        with open(path, "r") as fh:
            raw = yaml.safe_load(fh)

        if not isinstance(raw, list):
            raise ValueError(
                f"Layout YAML {path!r} must be a list of bank dicts, got {type(raw).__name__}"
            )

        banks: List[MemoryBank] = []
        for entry in raw:
            base = entry.get("base_addr")
            if isinstance(base, str):
                base = int(base, 0)
            banks.append(
                MemoryBank(
                    name=entry["name"],
                    plusarg=entry["plusarg"],
                    base_addr=base,
                    size_bytes=int(entry["size_bytes"]),
                    depth=int(entry["depth"]),
                    data_width_bits=int(entry["data_width_bits"]),
                )
            )
        return cls(banks)

    # ------------------------------------------------------------------ #
    # Accessors                                                             #
    # ------------------------------------------------------------------ #

    def bank(self, name: str) -> MemoryBank:
        """Return the ``MemoryBank`` for *name*, raising ``KeyError`` if absent."""
        return self._banks[name]

    @property
    def banks(self) -> Dict[str, MemoryBank]:
        """All banks keyed by name (read-only view)."""
        return dict(self._banks)

    def bank_for_addr(self, byte_addr: int) -> Optional[MemoryBank]:
        """Return the first bank whose address window contains ``byte_addr``.

        Returns ``None`` if no bank covers the address.
        """
        for b in self._banks.values():
            if b.contains_addr(byte_addr):
                return b
        return None

    def __repr__(self) -> str:
        names = list(self._banks)
        return f"SepMemoryLayout(banks={names!r})"
