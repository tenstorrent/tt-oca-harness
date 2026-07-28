# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Tenstorrent Inc.
"""
ocah_memory_image — unified firmware / ROM / SRAM / OTBN image loader for SEP.

This package provides a single Python API that tests use to load firmware,
ROM, SRAM, and OTBN images into SEP-style memory banks. Tests do not need
per-bank backdoor knowledge; they call one loader with an ELF/hex/bin image
and the loader routes sections to the correct banks via testbench plusargs.

Primary exports
---------------
OcahMemoryImage
    Main loader class.  Accepts ELF, Intel HEX, and raw binary images.
    Emits ``+<bank>_preload=<file>`` plusargs for the cocotb runner.

SepMemoryLayout
    Dataclass-like container describing every SEP memory bank (base address,
    depth, word width, plusarg name).  ``SepMemoryLayout.default()`` returns
    the seven-bank layout from Task #9 INTERFACE.md.

MemoryBank
    Descriptor for a single bank (name, plusarg, base_addr, size_bytes,
    depth, data_width_bits).

backdoor_sim_write
    Async helper for runtime patching of a live simulation via cocotb
    hierarchical handles (peek/poke).

Quick-start
-----------
::

    from ocah_memory_image import OcahMemoryImage

    img = OcahMemoryImage(run_dir="/tmp/sim_run")
    img.load_elf("fw/sep/tests/hello_world/hello_world.elf")
    plusargs = img.write_plusargs()
    # plusargs is now a list like:
    #   ['+sep_boot_rom_preload=/tmp/sim_run/sep_boot_rom.hex',
    #    '+sep_sram_preload=/tmp/sim_run/sep_sram.hex']
    # Pass this list to your cocotb runner or simulation command line.

See ``examples/example_load_elf.py`` for a complete cocotb runner snippet.

Dependencies
------------
- Python stdlib only for hex / binary loading.
- ``pyelftools`` for ELF loading (``pip install pyelftools``).
- ``pyyaml`` for YAML layout files (``pip install pyyaml``; optional).
- ``cocotb`` for ``backdoor_sim_write`` (only needed at simulation time).
"""

from .sep_memory_layout import MemoryBank, SepMemoryLayout
from .ocah_memory_image import OcahMemoryImage, OcahMemoryImageError, backdoor_sim_write

__all__ = [
    "OcahMemoryImage",
    "OcahMemoryImageError",
    "SepMemoryLayout",
    "MemoryBank",
    "backdoor_sim_write",
]

__version__ = "0.1.0"
