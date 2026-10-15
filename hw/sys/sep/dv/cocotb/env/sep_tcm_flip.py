# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Driver of the TCM bit-flip hook (error inject, docs/SEP_TB_ARCH.adoc).

Each ICCM and DCCM word is stored as 39 bits in the macro array: bits 31:0 hold
the data and bits 38:32 the ECC. The hook XORs a 39-bit mask into the stored
word that holds a byte address:

* ``tcm_flip(dut, addr, mask)`` pulses ``tcm_flip_i`` while the simulation
  runs.
* ``write_flip_list(path, flips)`` writes the time-0 list that
  ``+sep_tcm_flip_list=<path>`` applies after each ``tcm_load_i`` image load,
  so a firmware leg starts with the errors in place.

The ICCM and DCCM bases and sizes come from the generated RDL register map
(``sep_reg_meta.sym``). The module has no simulator import at load time.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from sep_reg_meta import sym

# Aperture bases and sizes from the generated RDL register map.
ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
ICCM_BYTES = sym("SEP_ICCM_MEM_SIZE")
DCCM_BASE = sym("SEP_DCCM_MEM_BASE_ADDR")
DCCM_BYTES = sym("SEP_DCCM_MEM_SIZE")
DATA_BITS = 32
ECC_BITS = 7
WORD_BITS = DATA_BITS + ECC_BITS
MASK_ALL = (1 << WORD_BITS) - 1


def in_iccm(addr: int) -> bool:
    return ICCM_BASE <= addr < ICCM_BASE + ICCM_BYTES


def in_dccm(addr: int) -> bool:
    return DCCM_BASE <= addr < DCCM_BASE + DCCM_BYTES


def bit_mask(*bits: int) -> int:
    """Mask with the named stored-word bits set (0-31 data, 32-38 ECC)."""
    mask = 0
    for b in bits:
        if not 0 <= b < WORD_BITS:
            raise ValueError(f"stored-word bit {b} is outside 0..{WORD_BITS - 1}")
        if mask >> b & 1:
            raise ValueError(f"stored-word bit {b} is named twice")
        mask |= 1 << b
    return mask


def _check(addr: int, mask: int) -> None:
    if not (in_iccm(addr) or in_dccm(addr)):
        raise ValueError(f"address 0x{addr:08x} is outside ICCM and DCCM")
    if not 0 < mask <= MASK_ALL:
        raise ValueError(f"mask 0x{mask:x} is not a non-zero {WORD_BITS}-bit mask")


async def tcm_flip(dut, addr: int, mask: int) -> None:
    """Pulse the TCM bit-flip hook once."""
    from cocotb.triggers import Timer

    _check(addr, mask)
    dut.tcm_flip_addr_i.value = addr
    dut.tcm_flip_mask_i.value = mask
    await Timer(1, units="ns")
    dut.tcm_flip_i.value = 1
    await Timer(1, units="ns")
    dut.tcm_flip_i.value = 0
    await Timer(1, units="ns")


def write_flip_list(path: str | Path, flips: Iterable[tuple[int, int]]) -> Path:
    """Write the time-0 flip list: one ``<hex addr> <hex mask>`` line per flip."""
    lines = []
    for addr, mask in flips:
        _check(addr, mask)
        lines.append(f"{addr:08x} {mask:010x}")
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + ("\n" if lines else ""))
    return p


if __name__ == "__main__":
    # Self-check (no simulator).
    assert bit_mask(0) == 1
    assert bit_mask(38) == 1 << 38
    assert bit_mask(3, 35) == (1 << 3) | (1 << 35)
    assert in_iccm(ICCM_BASE) and not in_iccm(DCCM_BASE)
    assert in_dccm(DCCM_BASE + DCCM_BYTES - 4) and not in_dccm(DCCM_BASE + DCCM_BYTES)
    for bad in ((0x1000_0000, 1), (ICCM_BASE, 0), (ICCM_BASE, 1 << WORD_BITS)):
        try:
            _check(*bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted {bad}")
    print("sep_tcm_flip self-check PASS")
