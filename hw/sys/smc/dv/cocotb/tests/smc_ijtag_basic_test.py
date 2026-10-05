# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM iJTAG-adjacent pin-level smoke."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_ijtag_basic_test_seq import smc_ijtag_basic_test_seq
from seq_lib.smc_jtag_vip_utils import (
    MIN_CPU_JTAG_TCK_EDGES,
    check_cpu_jtag_pin_vip,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_ijtag_basic_test(smc_base_test):
    """Run the SMC OSS iJTAG-adjacent CSR and CPU JTAG pin scenario."""

    required_evidence = (
        "CHK-CPU-JTAG-DTMCS",
        "CHK-CPU-JTAG-IDCODE",
        "CHK-CPU-JTAG-SCAN-ACTIVITY",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_ijtag_basic_test_seq("ijtag_basic_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # Returns the tb_cpu_jtag_tck rising edges it measured at the pin, and
        # asserts them against MIN_CPU_JTAG_TCK_EDGES inside the helper:
        # `min_csr_accesses` below counts SEP_IN AXI CSR traffic from
        # smc_ijtag_basic_test_seq, which is unrelated to the TAP.
        tck_edges = await check_cpu_jtag_pin_vip()
        await self.record_protocol_vip(
            SmcProtocolVipKind.JTAG,
            type(self).__name__,
            # `seq.accesses` directly, not getattr(..., 0): a renamed attribute
            # must raise rather than silently record 0 accesses.
            csr_accesses=seq.accesses,
            # Directed stimulus floor: 5 SEP_IN AXI accesses, the same count
            # smc_ijtag_basic_test_seq.body asserts. Literal here, not read from
            # `seq.accesses`. This floors the CSR half only; the JTAG half is
            # floored by the TCK-edge assert inside check_cpu_jtag_pin_vip.
            min_csr_accesses=5,
            proxy=False,
            details=(
                "CPU JTAG TAP reset + IDCODE + DTMCS scanned and value-checked; "
                f"{tck_edges} tb_cpu_jtag_tck rising edges measured at the pin "
                f"(floor {MIN_CPU_JTAG_TCK_EDGES})"
            ),
        )
