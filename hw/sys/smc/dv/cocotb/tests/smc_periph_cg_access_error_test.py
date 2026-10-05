# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Clock-gated peripherals answer SLVERR with 0xBADCAB1E instead of stalling.

Each of the five CLOCK_GATE_CONTROL peripheral enables (AVSBus, I2C, UART,
telemetry, I3C) is set in turn. A probe register of the gated peripheral must
answer a read with SLVERR and the error-slave word, refuse a write with SLVERR,
and return its recorded word again once the enable is cleared.

Run:
    python3 tools/dv/run_dv.py --dut smc --items smc_periph_cg_access_error_test \\
        --stage flist --stage hdl_compile --stage sim
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_periph_cg_access_error_test_seq import (
    PERIPHERALS,
    smc_periph_cg_access_error_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_periph_cg_access_error_test(smc_base_test):
    """Every gated peripheral window answers SLVERR/0xBADCAB1E and recovers when ungated."""

    required_evidence = tuple(
        sorted(
            [f"CHK-PERIPH-CG-ACCESS-ERROR-{periph}" for periph, _cg, _reg, _addr in PERIPHERALS]
            + ["CHK-PERIPH-CG-ACCESS-ERROR-SWEEP"]
        )
    )
    min_evidence = len(required_evidence)

    async def run_scenario(self) -> None:
        seq = smc_periph_cg_access_error_test_seq("periph_cg_access_error_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # Re-derive the verdict from the per-peripheral outcomes, not from the
        # sequence's access counter: every peripheral must have answered the
        # positive control, refused both gated accesses and come back.
        names = [periph for periph, _cg, _reg, _addr in PERIPHERALS]
        assert sorted(seq.ungated_words) == sorted(names), (
            f"positive control covered {sorted(seq.ungated_words)}, expected {names}"
        )
        assert seq.gated_refused == names, (
            f"gated read and write refused with SLVERR on {seq.gated_refused}, expected {names}"
        )
        assert seq.recovered == names, (
            f"recovery read returned the recorded word on {seq.recovered}, expected {names}"
        )
