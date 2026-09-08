# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""# deferred: no_sep_in_write_path
Cluster PLIC CSR and pending-path test -- NOT ENROLLED.

Written to fill the one coverage hole the porting necessity analysis found: no
enrolled test reads a single cluster PLIC register. It cannot be enrolled,
because the aperture is not writable from SEP_IN AXI. Measured on Verilator
5.050:

  * `PRIORITY[1]` at 0xC4000004 accepts a write with OKAY and stores nothing --
    it reads 0x0 after writing 0x5.
  * `CORE0_MEIP_THRESHOLD` at 0xC4200000, the +2 MB context page, returns
    non-OKAY on write.

So the PLIC is cluster-local in the way that matters: the CPU reaches it over
its own bus, and the external port does not. Filling this hole needs the CPU,
which means the firmware runner, which is blocked on the scratch-load question.

The testcase is kept rather than deleted for the same reason
`smc_clint_csr_test` is kept: `CHK-PLIC-APERTURE-LIVE` is a fail-capable guard
on exactly that access path and starts passing the day the path exists. Same
posture, same group treatment -- no `ci` tag, in no group, runnable by name.

**The positive control earned its place here.** Without
`CHK-PLIC-APERTURE-LIVE` running first, two of the other legs would have
reported success for the wrong reason: `PRIORITY[0]` reading 0 after a write
looks like the spec's reserved source, and `PENDING` unchanged after a write
looks like a correct read-only register. Both read that way because nothing in
the aperture is writable at all.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_cluster_plic_csr_test_seq import smc_cluster_plic_csr_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cluster_plic_csr_test(smc_base_test):
    """PLIC context independence, reserved fields, and the pending path."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cluster_plic_csr_test_seq("cluster_plic_csr_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # Gate on the emitted tokens rather than on a boolean the sequence set:
        # each leg raises on failure, so a relayed flag could only ever report
        # that the line was reached.
        required = (
            "CHK-PLIC-APERTURE-LIVE",
            "CHK-PLIC-CTX-INDEPENDENT",
            "CHK-PLIC-SOURCE0-RESERVED",
            "CHK-PLIC-ENABLE-RW",
            "CHK-PLIC-PENDING-RO",
            "CHK-PLIC-PENDING-SET-ON-IRQ",
            "CHK-PLIC-PENDING-CLEAR-ON-W1C",
        )
        missing = [n for n in required if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
