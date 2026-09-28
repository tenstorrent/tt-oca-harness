# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""sys_axi_in accepts a read and a write into a local register through the inbound filter.

Closes SMC-FAB-EXTPORT.S1 (port_table.adoc: sys_axi_in_req_i; fabric.adoc:
Inbound Filtering): inbound entry 0 is programmed over SEP_IN to admit, then
the SYS_IN port reads a register with a non-zero generated reset and writes a
scratch word that both ports read back; the SYS_IN access count is measured
by the scoreboard, not declared. SMC-FAB-EXTPORT.S5 is left open because no
inbound port is tied off in this bench.

Run:
    CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smc \\
        --items smc_sys_axi_in_port_test --tool verilator
"""

from __future__ import annotations

import cocotb
import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_sys_axi_in_port_test_seq import (
    EXPECTED_SEP_ACCESSES,
    EXPECTED_SYS_IN_ACCESSES,
    smc_sys_axi_in_port_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_sys_axi_in_port_test(smc_base_test):
    """SYS_IN read/write into a local register once inbound entry 0 admits."""

    required_evidence = (
        "CHK-SYS-AXI-IN-BACKPRESSURE",
        "CHK-SYS-AXI-IN-BURST",
        "CHK-SYS-AXI-IN-DUPLEX",
        "CHK-SYS-AXI-IN-ERRORS",
        "CHK-SYS-AXI-IN-NOT-CLOSED",
        "CHK-SYS-AXI-IN-PORT",
        "CHK-SYS-AXI-IN-READ",
        "CHK-SYS-AXI-IN-WRITE",
    )
    min_evidence = 8

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_sys_axi_in_port_test_seq("sys_axi_in_port_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.sys_read_word is not None and seq.sys_scratch_word is not None, (
            "the sequence ended without both SYS_IN reads"
        )
        cocotb.log.info(
            "CHK-SYS-AXI-IN-PORT: SYS_IN read 0x%08x, scratch readback 0x%08x, SEP_IN accesses %d",
            seq.sys_read_word,
            seq.sys_scratch_word,
            seq.accesses,
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.AXI,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=EXPECTED_SEP_ACCESSES,
            proxy=False,
            fabric_bus="SYS_IN AXI",
            fabric_accesses=EXPECTED_SYS_IN_ACCESSES,
            min_fabric_accesses=EXPECTED_SYS_IN_ACCESSES,
            fabric_access_label="SYS_IN AXI read/write",
            details=(
                f"sys_axi_in read 0x{seq.sys_read_word:08x} and scratch write/readback "
                f"0x{seq.sys_scratch_word:08x} through inbound entry 0"
            ),
        )
