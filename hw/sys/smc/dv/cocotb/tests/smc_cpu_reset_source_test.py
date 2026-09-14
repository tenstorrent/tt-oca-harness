# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SW RESET_CTRL.core0 to RESET_TIMEOUT.reset_applied."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_cpu_reset_source_test_seq import (
    APPLIED,
    CORE0_N,
    smc_cpu_reset_source_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cpu_reset_source_test(smc_base_test):
    """SW core0 level reset; no Force drain / no FLR isolate_req_o."""

    required_evidence = (
        "CHK-CPU-RST-BASIC",
        "CHK-CPU-RST-IDLE",
        "CHK-CPU-RST-REL",
        "CHK-CPU-RST-SW",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cpu_reset_source_test_seq("cpu_rst_src_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # Re-derive the verdict from the measured DUT words, not from flags the
        # sequence set itself. `CORE0_N` / `APPLIED` are the generated-header
        # field masks the sequence addressed with, so a weakened compare inside
        # body() still fails here.
        samples = {
            "RESET_CTRL idle": seq.ctrl_idle,
            "RESET_CTRL asserted": seq.ctrl_asserted,
            "RESET_CTRL released": seq.ctrl_released,
            "RESET_TIMEOUT idle": seq.tmo_idle,
            "RESET_TIMEOUT asserted": seq.tmo_asserted,
            "RESET_TIMEOUT hold": seq.tmo_hold,
            "RESET_TIMEOUT released": seq.tmo_released,
        }
        missing = [k for k, v in samples.items() if v is None]
        assert not missing, f"never sampled: {missing}"

        core0_n = [
            1 if (seq.ctrl_idle & CORE0_N) else 0,
            1 if (seq.ctrl_asserted & CORE0_N) else 0,
            1 if (seq.ctrl_released & CORE0_N) else 0,
        ]
        assert core0_n == [1, 0, 1], (
            f"RESET_CTRL.core0_reset_n sequence was {core0_n}, expected [1, 0, 1] "
            f"(idle / SW-asserted / released); raw words "
            f"0x{seq.ctrl_idle:x} 0x{seq.ctrl_asserted:x} 0x{seq.ctrl_released:x}"
        )
        applied = [
            1 if (seq.tmo_idle & APPLIED) else 0,
            1 if (seq.tmo_asserted & APPLIED) else 0,
            1 if (seq.tmo_hold & APPLIED) else 0,
            1 if (seq.tmo_released & APPLIED) else 0,
        ]
        assert applied == [0, 1, 1, 0], (
            f"RESET_TIMEOUT.reset_applied sequence was {applied}, expected "
            f"[0, 1, 1, 0] (idle / SW-asserted / still held at the release "
            f"write / released); raw words 0x{seq.tmo_idle:x} "
            f"0x{seq.tmo_asserted:x} 0x{seq.tmo_hold:x} 0x{seq.tmo_released:x}"
        )
