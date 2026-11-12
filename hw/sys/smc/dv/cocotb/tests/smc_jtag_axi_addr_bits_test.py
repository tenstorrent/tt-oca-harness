# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG AXI port: address bits above the SMC map and bit 27 falling after a set.

Reads and writes on the JTAG AXI port with address bits [36:34], [39:38] and [55:41] set above
the unimplemented word below the M-mode region leave the SMC on the output port at the driven
56-bit address and answer OKAY, while the access with those bits clear answers DECERR inside;
a read of the CLINT `MTIME` address, which sets bit 27 and lies beyond the local aperture at
reset, leaves on the output port the same way, and a scratch register whose address clears
bit 27 is then written and read back.

Run:
    python3 tools/dv/run_dv.py --dut smc --items smc_jtag_axi_addr_bits_test --tool vcs
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_jtag_axi_addr_bits_test_seq import (
    CHECKERS,
    PLANNED_ACCESSES,
    smc_jtag_axi_addr_bits_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_jtag_axi_addr_bits_test(smc_base_test):
    """Address bits above the map and bit 27 falling, on the JTAG AXI port."""

    required_evidence = CHECKERS
    min_evidence = len(CHECKERS)

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_jtag_axi_addr_bits_test_seq("jtag_axi_addr_bits_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.accesses == PLANNED_ACCESSES, (
            f"{seq.accesses} JTAG accesses, the plan issues {PLANNED_ACCESSES}"
        )
        missing = [n for n in CHECKERS if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
