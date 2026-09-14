# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""All four harts of the cluster run firmware and check in with each other.

Firmware test: `fw/tests/hello_world_multicore` is loaded into scratch by the
firmware loader and run from the reset vector on every hart. Hart 0 spins until
harts 1..3 have each incremented a shared atomic, then posts PASS under a
Freedom-Metal lock; each secondary hart writes its hart id into SCRATCH[hartid]
before checking in. `smc_fw_hello_world_test` proves hart 0's store only.

Bench observation: after the PASS word the sequence reads SCRATCH_2 and
SCRATCH_3 over SEP_IN AXI and requires the hart ids 2 and 3 -- words hart 0
never writes, one of them cleared by the bench before release and the other
overwritten by the seed publish, so neither can be a residue. The verdict word
itself already depends on three harts releasing hart 0.

Tokens: CHK-FW-MULTICORE-BOOT, CHK-FW-MULTICORE-HART-MARKERS.

Requires the staged image and a held boot:
  +smc_scratch_ram_hex=hello_world_multicore.ecc.hex   (bare basename; staged by c_compile)
  +smc_hold_cpu_boot
Must NOT use +skip_fuse_sense -- see dv_policy 1.6.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_fw_hello_world_multicore_test_seq import (
    smc_fw_hello_world_multicore_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_fw_hello_world_multicore_test(smc_base_test):
    """Four harts check in; the bench reads harts 2 and 3's own markers."""

    auto_protocol_vip = False
    required_evidence = (
        "CHK-FW-MULTICORE-BOOT",
        "CHK-FW-MULTICORE-HART-MARKERS",
    )
    min_evidence = 2

    async def run_scenario(self) -> None:
        seq = smc_fw_hello_world_multicore_test_seq("fw_hello_world_multicore_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.boot.get("boot_checked") is True, f"firmware boot was not checked: {seq.boot}"
        assert seq.hart_markers_ok, f"hart markers were not read back: {seq.hart_markers}"
