# SPDX-License-Identifier: Apache-2.0
"""SMC OSS eFuse JTAG lifecycle access-control test (observable subset).

Covers the CSR-observable part of the SMC eFuse JTAG access-control policy
(`smc_efuse_wrapper.sv`): records `CHIP_CONFIG_LC_STATE` and reads the
always-allowed identity registers (`CHIPLET_ID` / `PACKAGE_ID`), then drives
the CPU JTAG pins and checks TDO.

The full JTAG-side access-control matrix -- writes / non-identity reads
blocked with SLVERR + `0xBADCAB1E` in PROD / RMA_SIP, identity-read
exception, and integrity-error lockdown -- needs an `lc_state_i` drive hook
and a JTAG-side AXI-Lite master that the current `tb_top` does not expose.
That is tracked as P2-15 (`smc_efuse_jtag_lc_access_matrix_test`).
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_efuse_jtag_lc_negative_test_seq import (
    smc_efuse_jtag_lc_negative_test_seq,
)
from seq_lib.smc_jtag_vip_utils import check_cpu_jtag_pin_vip


@pyuvm.test()
class smc_efuse_jtag_lc_negative_test(smc_base_test):
    """eFuse LC observable-subset CSR reads + CPU JTAG pin check."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_efuse_jtag_lc_negative_test_seq("efuse_jtag_lc_negative_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await check_cpu_jtag_pin_vip()
        await self.record_protocol_vip(
            SmcProtocolVipKind.JTAG,
            type(self).__name__,
            csr_accesses=getattr(seq, "accesses", 0),
            proxy=False,
            details=(
                "eFuse LC-state + always-allowed CHIPLET_ID/PACKAGE_ID reads; "
                "CPU JTAG TCK/TMS/TDI/reset driven and TDO checked"
            ),
        )
