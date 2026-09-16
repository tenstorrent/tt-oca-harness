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
        # Write leg on the same window. Every access this package made to the
        # bank-control port was a read, so the write direction of that port --
        # aw_valid with w_valid through to its B response -- had never been
        # presented at all, and the port's own docs place it outside the eFuse
        # map / interface CSR ranges, which is what makes this address decode to
        # it (smc_efuse_vip_utils.py names the same decode). `init_time` is
        # `sw = rw; hw = r` (hw/ip/efuse/dv/models/regs/efuse_shim_ctrl.rdl), so
        # the readback is a real value compare booked by the scoreboard: a write
        # routed to the interface CSR window instead answers with an error
        # rather than OKAY, and a write that was dropped while its response was
        # still returned leaves the reset value behind. The value is the reset
        # plus one -- `init_time` presets the bank-init down-counter -- and it is
        # restored before the sequence ends.
        probe_value = EFUSE_BANK_INIT_TIME_RESET + 1
        await self.csr_write_readback(
            "EFUSE_SHIM_CTRL_EFUSE_BANK_INIT_TIME_WR", EFUSE_SHIM_CTRL, probe_value
        )
        await self.csr_restore(
            "EFUSE_SHIM_CTRL_EFUSE_BANK_INIT_TIME",
            EFUSE_SHIM_CTRL,
            EFUSE_BANK_INIT_TIME_RESET,
        )
        cocotb.log.info(
            "CHK-EFUSE-SHIM-CTRL: EFUSE_INTERFACE_CTRL and EFUSE_SHIM_CTRL "
            "EFUSE_BANK_INIT_TIME both answered OKAY, the latter compared "
            "against its generated reset 0x%08x; the same window then took "
            "0x%08x through the write direction of the bank-control port, "
            "returned it on readback, and was restored to 0x%08x",
            EFUSE_BANK_INIT_TIME_RESET,
            probe_value,
            EFUSE_BANK_INIT_TIME_RESET,
        )
