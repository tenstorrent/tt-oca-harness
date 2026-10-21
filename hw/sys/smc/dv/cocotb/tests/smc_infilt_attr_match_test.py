# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_B4_003 ANCHOR: smc_infilt_attr_match_test
# DV-TESTCASE-CONTRACT-REVISION: 1 RECORD-SHA256: 7662a0a2f29ee58ebcc45d7e779fac8325cfeb4c644db7fec2fcc1127be1af1c
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/docs/SMC_VPLAN.adoc section 364 `smc_infilt_attr_match_test` ENV: cocotb
"""The inbound filter matches AxPROT[1], the source ID, same-page ranges and entry-15 bursts."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_infilt_attr_match_test_seq import smc_infilt_attr_match_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_infilt_attr_match_test(smc_base_test):
    """Inbound entries match AxPROT[1] equality, fall through, ignore group_id, widen
    same-page ranges for entries 4 to 15 and decide SYS_IN INCR bursts at entry 15."""

    required_evidence = (
        "CHK-INB-E15-BURST-DISALLOWED",
        "CHK-INB-E15-BURST-PERMIT",
        "CHK-INB-E15-PERM-DENY",
        "CHK-INB-E15-SRCID-MISMATCH",
        "CHK-INB-GRANULE-WIDEN",
        "CHK-INB-GROUPID-INERT",
        "CHK-INB-NS-FALLTHROUGH",
        "CHK-INB-NS-PER-CHANNEL",
        "CHK-INB-NS0-EQUALITY",
        "CHK-INB-NS1-EQUALITY",
        "CHK-INB-PAGE-HIT",
        "CHK-INB-PAGE-OUTSIDE",
        "CHK-INB-PAGE-WIDEN",
        "CHK-INB-PROT-BITS-IGNORED",
        "CHK-INB-SRCID-NONZERO-VS-ZERO",
        "CHK-INB-SRCID-WILDCARD-ZERO",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 18

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_infilt_attr_match_test_seq("smc_infilt_attr_match_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        total = seq.accesses + seq.sys_accesses
        assert total >= 83, f"{total} accesses, fewer than the required floor of 83"
