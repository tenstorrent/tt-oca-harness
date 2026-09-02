# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Scratch-register reset-domain driver for ``sep_warm_cold_reset_scratch_test``.

Direct-AXI R/W of the SEP System-block dual scratch banks over the CPU-LSU bus
(the no_cpu splice). The two banks live in different reset domains:

  * SCRATCH_COLD (base 0x1080_2000) -- COLD domain: its register block is reset by
    ``rst_ni`` only (sep_system_csr.sv u_sep_scratch_reg_cold ``.arst_n(rst_ni)``).
  * SCRATCH_WARM (base 0x1080_2080) -- WARM domain: reset by
    ``rst_ni && rst_warm_ni`` (u_sep_scratch_reg_warm), where
    ``rst_warm_ni = sep_cpu_reset_n = sep_reset_n & wdt_rst_ni`` (sep.sv:816,
    sep_reset_ctrl.sv:59).

Each bank is 8 x 64-bit registers (sep_scratch.rdl), 0x8 stride, only the lower
32 bits used, reset default 0x0. The driver carries the per-index addresses and
the distinct per-register patterns the bank sweep uses. This driver only issues
CSR R/W; the reset
stimulus (the ``wdt_rst_ni_i`` warm pulse / ``rst_ni`` cold resense) is driven by
the test.
"""

from __future__ import annotations

from sep_reg_meta import sym

from seq_lib.sep_axi_reg_driver import SepAxiRegDriver

# SEP System-block scratch register addresses (sep_system_csr.sv aperture).
SCRATCH_COLD_0 = sym("SEP_SCRATCH_COLD_REG_MAP_BASE_ADDR")  # cold domain: .arst_n(rst_ni)
SCRATCH_WARM_0 = sym(
    "SEP_SCRATCH_WARM_REG_MAP_BASE_ADDR"
)  # warm domain: .arst_n(rst_ni && rst_warm_ni)
SCRATCH_RESET_DEFAULT = 0x0000_0000

# Both banks hold SCRATCH[8] (sep_scratch.rdl), 0x8 stride.
SCRATCH_N = 8
SCRATCH_COLD_ADDRS = tuple(sym(f"SEP_SCRATCH_COLD_SCRATCH_{i}__REG_ADDR") for i in range(SCRATCH_N))
SCRATCH_WARM_ADDRS = tuple(sym(f"SEP_SCRATCH_WARM_SCRATCH_{i}__REG_ADDR") for i in range(SCRATCH_N))

# Test patterns (mirror the reference sep_clock_uvm_warm_reset_vs_cold_reset_test_seq).
COLD_PATTERN = 0xCAFE_BABE
WARM_PATTERN = 0xDEAD_BEEF
WARM_PATTERN2 = 0xA5A5_5A5A  # post-warm-reset recovery write

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
