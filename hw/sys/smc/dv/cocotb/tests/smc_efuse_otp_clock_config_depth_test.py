# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS eFuse OTP clock/timing config depth test."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_efuse_otp_clock_config_depth_test_seq import (
    smc_efuse_otp_clock_config_depth_test_seq,
)
from seq_lib.smc_efuse_vip_utils import check_efuse_otp_observability
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_efuse_otp_clock_config_depth_test(smc_base_test):
    """Run eFuse OTP clock/timing register programming depth checks."""

    required_evidence = (
        "CHK-EFUSE-BANK-AXIL-ACTIVE",
        "CHK-EFUSE-BANK-IDLE",
        "CHK-EFUSE-CLOCK-GATE-DEPTH",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_efuse_otp_clock_config_depth_test_seq("efuse_otp_clock_config_depth_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # The sequence ran `prove_efuse_bank_axil_activity` first, so this idle
        # re-check consumes a real positive-control credit and emits
        # CHK-EFUSE-BANK-IDLE instead of the "NOT closure evidence" WARNING.
        await check_efuse_otp_observability()
        assert "CHK-EFUSE-CLOCK-GATE-DEPTH" in seq.chk_seen, (
            f"missing CHK evidence token: CHK-EFUSE-CLOCK-GATE-DEPTH (seen={sorted(seq.chk_seen)})"
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.EFUSE,
            type(self).__name__,
            # Directed stimulus floor: 10 SEP_IN AXI accesses (1 eFuse-bank
            # positive control + 4 CHIP_CONFIG proxy reads + 5 CLOCK_GATE_CONTROL
            # save/write/read/restore/re-read). Literal here, not read from
            # `seq.accesses`.
            min_csr_accesses=10,
            csr_accesses=seq.accesses,
            proxy=False,
            # The CHIP_CONFIG CHIP_ID / LC_STATE reads are observed-only; the
            # checked items are the clock-gate RW depth
            # (write/masked-readback/restore) and the eFuse-bank idle claim with
            # its same-run positive control.
            details=(
                "SMC_BASE_CONFIG CLOCK_GATE_CONTROL RW depth (pattern under "
                "mask 0x1FFF + restore) checked; CHIP_CONFIG VERSION_LO/HI "
                "compared against generated RDL resets; eFuse-bank AXI-Lite "
                "idle backed by a same-run positive control"
            ),
        )
