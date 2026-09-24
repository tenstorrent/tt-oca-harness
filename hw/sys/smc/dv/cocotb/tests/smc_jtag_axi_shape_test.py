# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG AXI port: multi-beat bursts and the fabric's error responses.

The third inbound manager of the input fabric is held to the burst and
error-response behaviour the SEP_IN and SYS_IN shape leaves establish: INCR
bursts of three lengths into the SPM read back in order, outstanding accesses
under a BREADY/RREADY hold stall the port and still read back, an unimplemented
region answers DECERR, and the GPIO access filter refuses an unprivileged JTAG
access the same way it refuses one from SEP_IN.

Run:
    CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smc \\
        --items smc_jtag_axi_shape_test --tool verilator
"""

from __future__ import annotations

import cocotb
import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_jtag_axi_shape_test_seq import (
    EXPECTED_JTAG_ACCESSES,
    EXPECTED_SEP_ACCESSES,
    smc_jtag_axi_shape_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_jtag_axi_shape_test(smc_base_test):
    """Bursts of three lengths and both error responses on the JTAG AXI port."""

    required_evidence = (
        "CHK-JTAG-AXI-BACKPRESSURE",
        "CHK-JTAG-AXI-BURSTS",
        "CHK-JTAG-AXI-ERRORS",
        "CHK-JTAG-AXI-PORT",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_jtag_axi_shape_test_seq("jtag_axi_shape_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.unimplemented_resp is not None and seq.denied_write_resp is not None, (
            "the sequence ended without both error-response legs"
        )
        cocotb.log.info(
            "CHK-JTAG-AXI-PORT: %d JTAG AXI accesses and %d SEP_IN accesses completed; "
            "unimplemented read resp=%d, refused write resp=%d",
            EXPECTED_JTAG_ACCESSES,
            seq.accesses,
            seq.unimplemented_resp,
            seq.denied_write_resp,
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.AXI,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=EXPECTED_SEP_ACCESSES,
            proxy=False,
            fabric_bus="JTAG AXI",
            fabric_accesses=EXPECTED_JTAG_ACCESSES,
            min_fabric_accesses=EXPECTED_JTAG_ACCESSES,
            fabric_access_label="JTAG AXI read/write",
            details=(
                "JTAG AXI INCR bursts of 2, 8 and 32 beats read back in order; unimplemented "
                f"read resp={seq.unimplemented_resp}, refused filter write resp="
                f"{seq.denied_write_resp}"
            ),
        )
