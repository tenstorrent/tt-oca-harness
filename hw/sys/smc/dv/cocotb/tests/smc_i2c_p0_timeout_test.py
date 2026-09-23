# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C1 stretch-timeout while I2C0 target holds SCL."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_i2c_p0_timeout_test_seq import smc_i2c_p0_timeout_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_p0_timeout_test(smc_base_test):
    """Stretch timeout measured against a target proven live on the same bus."""

    required_evidence = (
        "CHK-I2C-P0-TIMEOUT",
        "CHK-I2C-P0-TIMEOUT-RELEASE",
        "CHK-I2C-P0-TIMEOUT-TARGET-LIVE",
        "CHK-I2C-TIMEOUT-CSR-SWEEP",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_p0_timeout_test_seq("i2c_p0_timeout_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.allow_ok and seq.stretch_ok and seq.release_ok, (
            f"legs incomplete: allow={seq.allow_ok} timeout={seq.stretch_ok} "
            f"release={seq.release_ok}"
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.I2C,
            type(self).__name__,
            # Stimulus floor, literal here rather than read from `seq.accesses`.
            # STIMULUS DECLARATION, not a check: the scoreboard evaluates
            # `csr_accesses >= min_csr_accesses` against the sequence's own
            # counter, so once the number is accurate it is `N >= N` and cannot
            # fail ([NO-ALWAYS-PASS-CHECKER]). The fail-capable content is the
            # sweep's `expected=` compares and the rclr two-sided read, both
            # scoreboard-enforced.
            min_csr_accesses=50,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"allow read ok={seq.allow_ok}; STRETCH_TIMEOUT with the target reporting "
                f"TX_STRETCH stretch_ok={seq.stretch_ok}; release read ok={seq.release_ok}"
            ),
        )
