# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Scratch-register reset-domain driver for ``sep_warm_cold_reset_scratch_test``.

Direct-AXI R/W of the SEP System-block dual scratch banks over the CPU-LSU bus
(the no_cpu splice). The two banks live in different reset domains:

  * SCRATCH_COLD (base 0x1080_2000) -- COLD domain: cleared only by ``rst_ni``.
  * SCRATCH_WARM (base 0x1080_2080) -- WARM domain: cleared by a warm reset
    (``wdt_rst_ni_i``). See VPLAN ``sep_warm_cold_reset_scratch_test``.

Each bank is 8 x 64-bit registers (sep_scratch.rdl), 0x8 stride, only the lower
32 bits used; the reset value comes from the RDL metadata. The driver carries the per-index addresses and
the distinct per-register patterns the bank sweep uses. This driver only issues
CSR R/W; the reset
stimulus (the ``wdt_rst_ni_i`` warm pulse / ``rst_ni`` cold resense) is driven by
the test.
"""

from __future__ import annotations

from sep_reg_meta import RegBlock, sym

from seq_lib.sep_axi_reg_driver import SepAxiRegDriver

# SEP System-block scratch register addresses (sep_system_csr.sv aperture).
SCRATCH_COLD_0 = sym("SEP_SCRATCH_COLD_REG_MAP_BASE_ADDR")  # cold domain: .arst_n(rst_ni)
SCRATCH_WARM_0 = sym("SEP_SCRATCH_WARM_REG_MAP_BASE_ADDR")  # warm domain: .arst_n(rst_warm_ni)
# Reset value of every SCRATCH register, from the generated RDL register
# metadata (sep_scratch.rdl `data` field reset), at the 32-bit DV access width.
# Both banks instantiate the same RDL type, so they must agree.
SCRATCH_RESET_DEFAULT = RegBlock("SEP_SCRATCH_COLD").reset32("SCRATCH_0_")
if RegBlock("SEP_SCRATCH_WARM").reset32("SCRATCH_0_") != SCRATCH_RESET_DEFAULT:
    raise RuntimeError(
        "SEP_SCRATCH_COLD and SEP_SCRATCH_WARM SCRATCH_0 resets differ in the "
        "register export; the scratch reset golden has no single source"
    )


def _bank_addrs(bank: str) -> tuple[int, ...]:
    """Every SCRATCH register of one bank, in index order, from the register export.

    The depth is the array the RDL declares, not a number a sequence carries: a
    sweep with its own literal silently stops short of the tail the day
    ``sep_scratch.rdl`` grows the array, and reports a clean pass over the part
    it still reaches.
    """
    addrs: list[int] = []
    while True:
        try:
            addrs.append(sym(f"SEP_SCRATCH_{bank}_SCRATCH_{len(addrs)}__REG_ADDR"))
        except KeyError:
            break
    if not addrs:
        raise RuntimeError(
            f"no SEP_SCRATCH_{bank}_SCRATCH_<n>__REG_ADDR symbols in the register "
            "export; the scratch sweep would walk nothing"
        )
    return tuple(addrs)


SCRATCH_COLD_ADDRS = _bank_addrs("COLD")
SCRATCH_WARM_ADDRS = _bank_addrs("WARM")
SCRATCH_N = len(SCRATCH_COLD_ADDRS)
if len(SCRATCH_WARM_ADDRS) != SCRATCH_N:
    raise RuntimeError(
        f"scratch banks differ in depth (cold {SCRATCH_N}, warm "
        f"{len(SCRATCH_WARM_ADDRS)}); the paired sweeps assume one depth"
    )
# Register pitch, taken from the export so a width change moves it.
SCRATCH_STRIDE = SCRATCH_COLD_ADDRS[1] - SCRATCH_COLD_ADDRS[0]

# Test patterns (mirror the reference sep_clock_uvm_warm_reset_vs_cold_reset_test_seq).
COLD_PATTERN = 0xCAFE_BABE
WARM_PATTERN = 0xDEAD_BEEF
WARM_PATTERN2 = 0xA5A5_5A5A  # post-warm-reset recovery write
COLD_PATTERN2 = 0xBEEF_CAFE  # post-warm-reset cold-bank write

# One distinct nonzero pattern per register, and no value repeated between the two
# banks: a readback that matches its own index proves per-register storage, and any
# index-to-index or bank-to-bank aliasing shows up as a mismatch. Index 0 keeps the
# reference patterns above so the single-index checks and the bank sweep agree.
COLD_PATTERNS = (COLD_PATTERN,) + tuple(0xC01D_0000 | (i << 8) | i for i in range(1, SCRATCH_N))
WARM_PATTERNS = (WARM_PATTERN,) + tuple(0x5EED_0000 | (i << 8) | i for i in range(1, SCRATCH_N))


class SepScratchReset(SepAxiRegDriver):
    """CSR R/W of the warm/cold scratch banks over the CPU-LSU AXI splice."""

    _DRIVER_TAG = "SCRATCH"

    async def write(self, addr: int, data: int) -> None:
        await self._wr(addr, data)

    async def read(self, addr: int) -> int:
        return await self._rd(addr)

    async def write_bank(self, addrs, patterns) -> None:
        """Write one distinct pattern into every register of a bank."""
        for addr, pattern in zip(addrs, patterns):
            await self._wr(addr, pattern)

    async def read_bank(self, addrs) -> list[int]:
        """Read every register of a bank, in index order."""
        return [await self._rd(addr) for addr in addrs]
