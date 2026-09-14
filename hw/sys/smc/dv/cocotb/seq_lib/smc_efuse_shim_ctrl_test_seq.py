# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""EFUSE_INTERFACE_CTRL + EFUSE_SHIM_CTRL reachability (TC_SMC_P1CG_05).

Reads the eFuse shim interface control registers (EFUSE_INTERFACE_CTRL and the
EXTERNAL_MANDATORY EFUSE_SHIM_CTRL window) over SEP_IN AXI.
"""

from __future__ import annotations

import cocotb

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_efuse_vip_utils import EFUSE_BANK_INIT_TIME_RESET, EFUSE_SHIM_CTRL_WINDOW

EFUSE_INTERFACE_CTRL = smc_addr(
    "SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_INTERFACE_CTRL_STATUS_BASE_ADDR"
)
# Same window smc_efuse_vip_utils.prove_efuse_bank_axil_activity() and
# smc_probe_positive_control read strictly, so it is imported rather than
# re-derived: one symbol, one authority.
EFUSE_SHIM_CTRL = EFUSE_SHIM_CTRL_WINDOW


class smc_efuse_shim_ctrl_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        # EFUSE_INTERFACE_CTRL is a real internal SMC register: it MUST return an
        # OKAY response. Gate the test on it via csr_read (scoreboard asserts
        # item.resp_ok), so a broken decode / SLVERR / bus hang here fails the test.
        await self.csr_read("EFUSE_INTERFACE_CTRL", EFUSE_INTERFACE_CTRL)
        # EFUSE_SHIM_CTRL answers on this bench: the eFuse-bank model backs the
        # window, and both smc_efuse_vip_utils.prove_efuse_bank_axil_activity()
        # and smc_probe_positive_control read this same address with a strict
        # csr_read and this same expected value. Gate on it with the generated
        # reset value as the expectation.
        await self.csr_read(
            "EFUSE_SHIM_CTRL_EFUSE_BANK_INIT_TIME",
            EFUSE_SHIM_CTRL,
            expected=EFUSE_BANK_INIT_TIME_RESET,
        )
        cocotb.log.info(
            "CHK-EFUSE-SHIM-CTRL: EFUSE_INTERFACE_CTRL and EFUSE_SHIM_CTRL "
            "EFUSE_BANK_INIT_TIME both answered OKAY, the latter compared "
            "against its generated reset 0x%08x",
            EFUSE_BANK_INIT_TIME_RESET,
        )
