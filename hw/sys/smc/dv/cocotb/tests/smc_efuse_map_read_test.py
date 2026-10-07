# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC_EFUSE_MAP direct read over SEP_IN AXI."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_efuse_map_read_test_seq import (
    EFUSE_MAP_READS,
    smc_efuse_map_read_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_efuse_map_read_test(smc_base_test):
    """Read the SMC_EFUSE_MAP words and compare each against its expected word."""

    required_evidence = ("CHK-EFUSE-MAP-READ",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_efuse_map_read_test_seq("smc_efuse_map_read_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert "CHK-EFUSE-MAP-READ" in seq.chk_seen, (
            f"missing CHK evidence token: CHK-EFUSE-MAP-READ (seen={sorted(seq.chk_seen)})"
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.EFUSE,
            type(self).__name__,
            # Directed stimulus floor: every compared SMC_EFUSE_MAP row.
            # Taken from the seq-lib table, not from `seq.accesses`.
            min_csr_accesses=len(EFUSE_MAP_READS),
            csr_accesses=seq.accesses,
            proxy=False,
            # Transport/decode claim over the named 1 KiB map fields, not
            # the window as a whole and not fuse programming.
            details=(
                "SMC_EFUSE_MAP direct read: LOCKS lo/hi, JTAG_PUBLIC_IDENTITY, "
                "SMC_CONFIG, OCCP_TRANSPORT_TIMEOUT, I2C_I3C_ID[0:8], SPARE[0:1] "
                "compared against preload-asset / LOCKS-derived expectations "
                "(transport proof; eFuse bank is the DV model)"
            ),
        )
