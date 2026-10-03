# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS AVSBus clock/config bounded VIP test."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_avsbus_clock_config_proxy_test_seq import (
    AVS_CFG_WINDOWS,
    AXI_RESP_SLVERR,
    EXPECTED_ACCESSES,
    smc_avsbus_clock_config_proxy_test_seq,
)
from seq_lib.smc_sideband_vip_utils import check_sideband_observability
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_avsbus_clock_config_proxy_test(smc_base_test):
    """AVS_CFG answers OKAY with AVS_CG_EN cleared and SLVERR/0xBADCAB1E when set."""

    required_evidence = (
        "CHK-AVSBUS-CG",
        "CHK-SIDEBAND-OBSERVABILITY",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_avsbus_clock_config_proxy_test_seq("avsbus_clock_config_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # Re-derive the verdict from the measurements, not from the sequence's
        # own access counters: the positive control must have answered on every
        # window, every gated access must have been refused with the exact code,
        # and every window must have come back with its recorded word.
        n = len(AVS_CFG_WINDOWS)
        assert len(seq.ungated_words) == n, (
            f"positive control covered {len(seq.ungated_words)}/{n} AVS_CFG windows: "
            f"{seq.ungated_words}"
        )
        assert seq.gated_errors == n, (
            f"{seq.gated_errors} of {n} AVS_CFG windows answered SLVERR with the "
            f"error-slave word while AVS_CG_EN was set"
        )
        assert seq.gated_write_resp == AXI_RESP_SLVERR, (
            f"the write into {AVS_CFG_WINDOWS[0][0]} while AVS_CG_EN was set completed with "
            f"resp={seq.gated_write_resp}, expected SLVERR ({AXI_RESP_SLVERR})"
        )
        assert seq.recovered == n, (
            f"{seq.recovered} of {n} AVS_CFG windows returned the positive control's word "
            f"after AVS_CG_EN was cleared again"
        )
        await check_sideband_observability()
        await self.record_protocol_vip(
            SmcProtocolVipKind.SIDEBAND,
            type(self).__name__,
            # Directed stimulus floor: the AVSBus clock/config CSR accesses this
            # scenario issues. Literal here, not read from `seq.accesses`.
            min_csr_accesses=EXPECTED_ACCESSES,
            csr_accesses=seq.accesses,
            timeouts=seq.timeouts,
            proxy=True,
            details=(
                "AVS_CFG windows answer OKAY with AVS_CG_EN cleared (positive "
                "control), SLVERR with 0xBADCAB1E and a refused write with AVS_CG_EN "
                "set, and their recorded words again once it is cleared"
            ),
        )
