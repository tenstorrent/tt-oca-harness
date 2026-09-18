# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cluster PLIC claim path, driven from the CPU because nothing else can.

The 0xC400_0000 aperture answers SEP_IN AXI reads but takes no writes from it,
so the enable/priority/threshold path has no cocotb route in this integration.
`fw/tests/plic_sanity` programs it from the CPU and claims a real external
interrupt; this testcase supplies the interrupt and holds the ordering.

Requires the staged image and a held boot:
  +smc_scratch_ram_hex=plic_sanity.ecc.hex   (bare basename; staged by c_compile)
  +smc_hold_cpu_boot
Must NOT use +skip_fuse_sense -- see dv_policy 1.6.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_fw_plic_claim_test_seq import smc_fw_plic_claim_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_fw_plic_claim_test(smc_base_test):
    """Firmware claims ext_interrupts_i[0] through the cluster PLIC."""

    required_evidence = (
        "CHK-FW-PLIC-CLAIM",
        "CHK-FW-PLIC-QUIET",
        "CHK-FW-PLIC-STIMULUS",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_fw_plic_claim_test_seq("fw_plic_claim_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # The boot contract raises on TEST_FAIL, on the 0xBAD0_xxxx namespace,
        # on a PASS not preceded by the arm word, and on the poll bound
        # expiring. These two assertions cover what it cannot say for itself:
        # that a check ran at all, and that the negative control actually
        # executed rather than being skipped over.
        assert seq.boot.get("boot_checked") is True, f"firmware boot was not checked: {seq.boot}"
        assert seq.quiet_ok, (
            "the quiet window never ran, so the PASS was not shown to depend on ext_interrupts_i[0]"
        )
