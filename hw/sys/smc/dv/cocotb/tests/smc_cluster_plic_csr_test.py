# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""# deferred: no_sep_in_write_path
Cluster PLIC CSR and pending-path test.

The PLIC aperture is not writable from SEP_IN AXI: `PRIORITY[1]` at 0xC4000004
accepts a write with OKAY and stores nothing (it reads 0x0 after writing 0x5),
and `CORE0_MEIP_THRESHOLD` at 0xC4200000, the +2 MB context page, returns
non-OKAY on write. The CPU reaches the PLIC over its own bus and the external
port does not, so the PLIC's function is covered from firmware:
`smc_fw_plic_claim_test` programs it and claims `ext_interrupts_i[0]` through
it.

This testcase holds the register-level properties that firmware image does not
read back -- context independence across the eight threshold pages, source 0
and PENDING read-only, PENDING tracking a real interrupt in both directions --
and `CHK-PLIC-APERTURE-LIVE` is a fail-capable guard on the SEP_IN write path
itself.

`CHK-PLIC-APERTURE-LIVE` runs first as the positive control. Without it two of
the other legs pass for the wrong reason: `PRIORITY[0]` reading 0 after a write
looks like the spec's reserved source, and `PENDING` unchanged after a write
looks like a correct read-only register, when both read that way because
nothing in the aperture is writable.
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
