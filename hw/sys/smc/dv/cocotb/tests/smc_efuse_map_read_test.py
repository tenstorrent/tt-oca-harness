# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS P1 coverage-gap: SMC_EFUSE_MAP direct read."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_efuse_map_read_test_seq import smc_efuse_map_read_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_efuse_map_read_test(smc_base_test):
    """P1 coverage-gap depth: SMC_EFUSE_MAP direct read."""

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
            # Directed stimulus floor: 4 SEP_IN AXI SMC_EFUSE_MAP reads.
            # Literal here, not read from `seq.accesses`.
            min_csr_accesses=4,
            csr_accesses=seq.accesses,
            proxy=False,
            # Narrowed to what the four compared words actually establish: a
            # transport/decode claim over four named SMC_EFUSE_MAP fields, not
            # the map window as a whole and not fuse programming.
            details=(
                "SMC_EFUSE_MAP direct read: LOCKS lo/hi, BIRA and CHIPLET_ID "
                "compared against preload-asset / LOCKS-derived expectations "
                "(transport proof; eFuse bank is the DV model)"
            ),
        )
