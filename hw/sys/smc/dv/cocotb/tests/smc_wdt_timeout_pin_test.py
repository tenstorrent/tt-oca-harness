# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Per-core WDT first and second timeout on the smc_wrapper pins, each followed by the warm reset."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_wdt_timeout_pin_test_seq import (
    SECOND_TIMEOUT_SLACK_CYCLES,
    WDT_TIMEOUT_RESET,
    smc_wdt_timeout_pin_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_wdt_timeout_pin_test(smc_base_test):
    """A programmed first timeout raises smc_wdt_first_timeout_o; uncleared, the second follows."""

    required_evidence = (
        "CHK-WDT-TIMEOUT-CORES",
        "CHK-WDT-TIMEOUT-FIRST",
        "CHK-WDT-TIMEOUT-RESET",
        "CHK-WDT-TIMEOUT-SECOND",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_wdt_timeout_pin_test_seq("wdt_timeout_pin_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # Re-derive the verdict from the measured cycle counts, not from the
        # sequence having returned: every one of these is None until the DUT
        # pin was actually observed.
        assert seq.first_seen_cycles is not None, "first timeout never observed"
        assert seq.second_gap_cycles is not None, "second timeout never observed"
        assert seq.warm_reset_cycles is not None, "warm reset never observed"
        assert seq.stage2_cycles == WDT_TIMEOUT_RESET, (
            f"stage-2 count read 0x{seq.stage2_cycles:x}, expected the cpu_ctrl.rdl "
            f"reset 0x{WDT_TIMEOUT_RESET:x}"
        )
        assert (
            seq.stage2_cycles
            <= seq.second_gap_cycles
            <= seq.stage2_cycles + SECOND_TIMEOUT_SLACK_CYCLES
        ), (
            f"second timeout {seq.second_gap_cycles} cycles after the first, "
            f"outside [0x{seq.stage2_cycles:x}, +{SECOND_TIMEOUT_SLACK_CYCLES}]"
        )
        assert sorted(seq.other_cores) == [1, 2, 3], (
            f"cores {sorted(seq.other_cores)} ran both stages, expected 1, 2 and 3"
        )
        assert seq.live_after_reset == (0, 0), (
            f"live pins {seq.live_after_reset} after the warm reset released"
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.CPU,
            type(self).__name__,
            # Activity stamp, not a check: the proof is the three bounded pin
            # observations asserted in the sequence and re-derived above.
            auto_evidence=True,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"core-0 WDT armed over SEP_IN (KEY, CMP, COUNT, CTRL); "
                f"smc_wdt_first_timeout_o latched after {seq.first_seen_cycles} "
                f"cycles, smc_wdt_second_timeout_o {seq.second_gap_cycles} cycles "
                f"later (WDT_TIMEOUT=0x{seq.stage2_cycles:x}), rst_warm asserted "
                f"{seq.warm_reset_cycles} cycles after that and released"
            ),
        )
