# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""FLR cool overlapped with rst_cold_ni; cold wins."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_cool_reset_x_cold_reset_test_seq import (
    _COLD_PAT,
    _SCRATCH_RESET,
    _SMCEN,
    _WARM_PAT,
    smc_cool_reset_x_cold_reset_test_seq,
)
from smc_base_test import smc_base_test

_ARMED = (_WARM_PAT, _COLD_PAT)
_CLEARED = (_SCRATCH_RESET, _SCRATCH_RESET)


@pyuvm.test()
class smc_cool_reset_x_cold_reset_test(smc_base_test):
    """FLR×cold interaction; not rst_cool_ni alias or BMC Force cool."""

    required_evidence = (
        "CHK-FLR-COLD-ISO-LIVE",
        "CHK-FLR-COLD-POS-COOL",
        "CHK-FLR-COLD-SCRATCH",
        "CHK-FLR-COLD-WINS",
        "CHK-FLR-COOL-SCRATCH-CLEAR",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cool_reset_x_cold_reset_test_seq("flr_x_cold_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # Gate on the values the run MEASURED, not on flags the body set next to
        # the checks that would already have raised.
        assert seq.iso_live == _SMCEN, (
            f"isolate_req_o was 0x{seq.iso_live:x} while the FLR cool was live, "
            f"expected the programmed SMCEN word 0x{_SMCEN:x}"
        )
        assert (seq.iso_last, seq.cool_last) == (0, 1), (
            f"cold did not win: isolate_req_o=0x{seq.iso_last:x} "
            f"rst_cool_from_flr={seq.cool_last}, expected 0x0 / 1"
        )
        assert (seq.cool_scratch_before, seq.cool_scratch_after) == (_ARMED, _CLEARED), (
            f"FLR-only cool: scratch banks {seq.cool_scratch_before} -> "
            f"{seq.cool_scratch_after}, expected {_ARMED} -> {_CLEARED}"
        )
        assert (seq.cold_scratch_pre, seq.cold_scratch_post) == (_ARMED, _CLEARED), (
            f"FLR-cool x cold overlap: scratch banks {seq.cold_scratch_pre} -> "
            f"{seq.cold_scratch_post}, expected {_ARMED} -> {_CLEARED}"
        )
