# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Byte-lane, half-word and lane-strobed writes to the narrow-cpuif register blocks.

One register of each register block whose cpuif carries 32 bits (reset unit,
GPIO interface, AVSBus, I2C control, I2C, eFuse interface, UART main and
write-only maps, UART wrapper control, log engine, telemetry receiver, system
timer) takes a preload that sets its writable fields, then 1-byte writes at
every lane, 2-byte writes at offsets 0 and 2, and 4-byte writes with one lane
unstrobed that each complement the plain read-write bits of the lanes they
enable; every readback must hold the lane image (the enabled lanes complemented,
the others as they were), a neighbour register must not change, and a full-width
restore must read back the saved word.

Run:
    python3 tools/dv/run_dv.py --dut smc --items smc_regblock_byte_lane_write_sweep_test --tool vcs
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_regblock_byte_lane_write_sweep_test_seq import (
    CHECKERS,
    planned_accesses,
    smc_regblock_byte_lane_write_sweep_test_seq,
)
from smc_base_test import smc_base_test

REQUIRED = (
    "CHK-LANE-AVSBUS",
    "CHK-LANE-EFUSE-CTRL",
    "CHK-LANE-GPIO",
    "CHK-LANE-I2C",
    "CHK-LANE-I2C-CTRL",
    "CHK-LANE-LOG-ENGINE",
    "CHK-LANE-RESET-UNIT",
    "CHK-LANE-RESTORE",
    "CHK-LANE-TELEMETRY",
    "CHK-LANE-TIMER",
    "CHK-LANE-UART",
    "CHK-LANE-UART-CTRL",
    "CHK-LANE-UART-WO",
    "CHK-NONVAC",
)


@pyuvm.test()
class smc_regblock_byte_lane_write_sweep_test(smc_base_test):
    """Lane-off writes to one register of every narrow-cpuif register block."""

    required_evidence = REQUIRED
    min_evidence = len(REQUIRED)

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_regblock_byte_lane_write_sweep_test_seq()
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        planned = planned_accesses(seq.legs)
        assert seq.accesses == planned, f"{seq.accesses} SEP_IN accesses, the plan issues {planned}"
        assert sorted(CHECKERS) == list(REQUIRED), "checker set differs from required_evidence"
        missing = [n for n in REQUIRED if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
