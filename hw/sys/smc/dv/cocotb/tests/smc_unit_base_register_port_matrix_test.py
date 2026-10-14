# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Base-register reset readback of the unit apertures from three ports at two bases.

Spec sources: smc.rdl unit and array placements, smc_base_config.rdl, dfx_ctrl_status.rdl,
memmap.adoc Address Space Organization, fabric.adoc Alias Remap Registers.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_unit_base_register_port_matrix_test_seq import (
    smc_unit_base_register_port_matrix_test_seq,
)
from smc_base_test import smc_base_test

# Accesses the sequence issues: 20 pre-setup array reads, 3 setup writes, 24 watchdog, 6 reset
# unit, 24 spare, 18 base config, 6 hang detector, 18 DFX, 10 SYS_IN array bases, 30 last
# instances, 22 DMA and zeroer, 5 CPU control, 4 inbound entry restore.
STIMULUS_FLOOR = 190


@pyuvm.test()
class smc_unit_base_register_port_matrix_test(smc_base_test):
    """Unit base registers read from sep_axi_in, sys_axi_in and jtag_axi_in at both bases."""

    required_evidence = (
        "CHK-BASE-CONFIG-RESETS-PORTS",
        "CHK-CPU-CTRL-FIRST-REG-PORTS",
        "CHK-DFX-REGS-PORTS",
        "CHK-DMA-ZEROER-BASE-PORTS",
        "CHK-FABRIC-ARRAY-BASES-PORTS",
        "CHK-FABRIC-ARRAY-LAST-INSTANCE",
        "CHK-HANG-DET-RESETS",
        "CHK-NONVAC",
        "CHK-RESET-UNIT-BASE-PORTS",
        "CHK-SPARE-FIRST-REGS-PORTS",
        "CHK-TIMEOUT-PATHS",
        "CHK-WDT-BASE-PORTS",
    )
    min_evidence = 12

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_unit_base_register_port_matrix_test_seq("unit_base_register_port_matrix_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        seq.assert_all_reachable(STIMULUS_FLOOR, "UNIT_BASE_REGISTER_PORT_MATRIX")
        seq.log_timeout_paths()
        seq.nonvac_fence(STIMULUS_FLOOR)
