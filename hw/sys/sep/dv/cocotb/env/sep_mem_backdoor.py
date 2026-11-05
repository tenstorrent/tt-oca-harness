# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Direct access to the SEP SRAM and ICCM storage arrays, for the ROM memory-clear checks.

Both arrays are reachable only through the Verilator public scope
(``sep_public_scope.vlt``: ``prim_ram_1p`` ``mem`` and ``ram_16384x39`` ``ram_core``),
so tests that use this module run on Verilator. Reads and writes take no simulation
time.

SEP SRAM stores 64-bit words, little-endian. ICCM stores four interleaved banks of
39-bit words, data in bits 31:0 and ECC above: bank ``off[3:2]``, row ``off[17:4]``
(``tb/tb_top.sv``, ``BD_ICCM``).
"""

from __future__ import annotations

import cocotb
from sep_reg_meta import sym

SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
SRAM_WORD_BYTES = 8
SRAM_WORDS = sym("SEP_SRAM_MEM_SIZE") // SRAM_WORD_BYTES

ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
ICCM_BYTES = sym("SEP_ICCM_MEM_SIZE")
ICCM_BANKS = 4

_IPI = ("u_dut", "u_sep_ip_integration")


def _walk(parts) -> object:
    node = cocotb.top
    walked = ["sep_uvm_top"]
    try:
        for part in parts:
            if isinstance(part, tuple):
                node = getattr(node, part[0])[part[1]]
                walked.append(f"{part[0]}[{part[1]}]")
            else:
                node = getattr(node, part)
                walked.append(part)
    except Exception as exc:  # noqa: BLE001 - report where the walk stopped
        raise AssertionError(
            f"cannot reach a memory array from cocotb.top; the walk reached "
            f"{'.'.join(walked)} and then failed with {type(exc).__name__}: {exc}. "
            f"The arrays are public only on Verilator (sep_public_scope.vlt)"
        ) from exc
    return node


def sram_array():
    """Handle of the SEP SRAM macro's 64-bit word array."""
    return _walk(_IPI + ("u_sep_sram", ("gen_ram_inst", 0), "u_mem", "mem"))


def iccm_banks() -> list:
    """Handles of the four ICCM bank arrays, bank 0 first."""
    return [
        _walk(
            _IPI
            + (
                "u_sep_tcm_wrapper",
                "gen_iccm",
                ("gen_bank", b),
                "gen_iccm_ram",
                "u_ram",
                "ram_core",
            )
        )
        for b in range(ICCM_BANKS)
    ]


def _iccm_slot(addr: int) -> tuple[int, int]:
    off = addr - ICCM_BASE
    if not 0 <= off < ICCM_BYTES or off & 3:
        raise ValueError(f"0x{addr:08x} is not an aligned ICCM word address")
    return (off >> 2) & 0x3, (off >> 4) & 0x3FFF


def iccm_word(banks: list, addr: int) -> int:
    """Data bits of the ICCM word at byte address ``addr``."""
    bank, row = _iccm_slot(addr)
    return int(banks[bank][row].value) & 0xFFFF_FFFF


def iccm_set(banks: list, addr: int, stored: int) -> None:
    """Write the whole stored word (data and ECC bits) at byte address ``addr``."""
    from cocotb.handle import Immediate

    bank, row = _iccm_slot(addr)
    banks[bank][row].value = Immediate(stored)
