# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""P1 coverage-gap: PLL AWM FREQUENCY + CGM sub-block sweep.

Each AWM (0/1) exposes 6 FREQUENCY + 3 CGM sub-blocks. Under
``smc_wrapper``, ``pll_wrap`` returns OKAY + 0 for the whole window.
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


class smc_pll_awm_freq_sweep_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        for a_idx, base in enumerate(_AWM_BASES):
            for name, off in _SUB_BLOCKS:
                await self.csr_read(f"AWM_{a_idx}_{name}", base + off, expected=0)
        expected = len(_AWM_BASES) * len(_SUB_BLOCKS)
        assert self.accesses == expected, "PLL AWM sub-block sweep count mismatch"
