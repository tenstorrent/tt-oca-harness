# SPDX-License-Identifier: Apache-2.0
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
32 bits used, reset default 0x0. This driver only issues CSR R/W; the reset
stimulus (the ``wdt_rst_ni_i`` warm pulse / ``rst_ni`` cold resense) is driven by
the test.
"""

from __future__ import annotations

from seq_lib.sep_axi_reg_driver import SepAxiRegDriver

# SEP System-block scratch register addresses (sep_system_csr.sv aperture).
SCRATCH_COLD_0 = 0x1080_2000   # cold domain: .arst_n(rst_ni)
SCRATCH_WARM_0 = 0x1080_2080   # warm domain: .arst_n(rst_ni && rst_warm_ni)
SCRATCH_WARM_1 = 0x1080_2088
SCRATCH_RESET_DEFAULT = 0x0000_0000

# Test patterns (mirror the OCAH sep_clock_uvm_warm_reset_vs_cold_reset_test_seq).
COLD_PATTERN = 0xCAFE_BABE
WARM_PATTERN = 0xDEAD_BEEF
WARM_PATTERN2 = 0xA5A5_5A5A    # post-warm-reset recovery write


class SepScratchReset(SepAxiRegDriver):
    """CSR R/W of the warm/cold scratch banks over the CPU-LSU AXI splice."""

    _DRIVER_TAG = "SCRATCH"

    async def write(self, addr: int, data: int) -> None:
        await self._wr(addr, data)

    async def read(self, addr: int) -> int:
        return await self._rd(addr)
