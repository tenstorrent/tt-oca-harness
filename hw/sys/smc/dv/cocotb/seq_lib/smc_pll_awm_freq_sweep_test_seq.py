# SPDX-License-Identifier: Apache-2.0
"""P1 coverage-gap round 3: PLL AWM FREQUENCY + CGM sub-block sweep.

Each AWM (0/1) exposes 6 FREQUENCY sub-blocks + 3 CGM sub-blocks:

  AWM_0 base = 0xC000_3400
  * AWM_FREQUENCY0_A @ +0x100
  * AWM_FREQUENCY1_A @ +0x140
  * AWM_FREQUENCY2_A @ +0x180
  * AWM_FREQUENCY3_A @ +0x1C0
  * AWM_FREQUENCY4_A @ +0x200
  * AWM_FREQUENCY5_A @ +0x240
  * AWM_CGM0_A       @ +0x280
  * AWM_CGM1_A       @ +0x380
  * AWM_CGM2_A       @ +0x480

  AWM_1 base = 0xC000_3A00 with same sub-block offsets.

Round 1 `smc_pll_cgm_awm_config_test` only touched the AWM base.
"""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

_AWM_BASES = [0xC000_3400, 0xC000_3A00]  # AWM_0, AWM_1

_SUB_BLOCKS = [
    ("AWM_FREQUENCY0", 0x100),
    ("AWM_FREQUENCY1", 0x140),
    ("AWM_FREQUENCY2", 0x180),
    ("AWM_FREQUENCY3", 0x1C0),
    ("AWM_FREQUENCY4", 0x200),
    ("AWM_FREQUENCY5", 0x240),
    ("AWM_CGM0",       0x280),
    ("AWM_CGM1",       0x380),
    ("AWM_CGM2",       0x480),
]


# The whole PLL_WRAP window (0xC0003000..0xC0003EE2) is an externalised macro
# port terminated by the OSS bench DECERR boundary responder, so every read
# returns DECERR + the 0xBADCAB1E signature on both Verilator and VCS. See
# tb_top.sv u_pll_macro_model (prim_axi_lite_err_slv).


class smc_pll_awm_freq_sweep_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        # csr_read_err_signature asserts the error response AND the exact
        # 0xBADCAB1E signature (no timeout tolerated) -- stricter than the
        # previous bounded read + value-only check.
        for a_idx, base in enumerate(_AWM_BASES):
            for name, off in _SUB_BLOCKS:
                await self.csr_read_err_signature(f"AWM_{a_idx}_{name}", base + off)
        expected = len(_AWM_BASES) * len(_SUB_BLOCKS)
        assert self.accesses == expected, "PLL AWM sub-block sweep count mismatch"
