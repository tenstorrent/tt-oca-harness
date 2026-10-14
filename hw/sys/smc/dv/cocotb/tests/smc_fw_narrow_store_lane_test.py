# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CPU word stores into one half of a 64-bit register word leave the other half alone.

Firmware test: `fw/tests/narrow_store_lane` stores all ones to the half of
each target word that its writable fields do not occupy. The core replicates
the word onto the fields' lanes with their strobes clear. The targets are:

* CLOCK_GATE_CONTROL, the three HANG_DET_*_CTRL registers, DEBUG_CTRL and
  RESET_TIMEOUT;
* the four CPU_CTRL MUTEX registers, stored to while free and while held;
* alias-remap `region_attrs`, which takes the store in its lower half.

The image compares every target before and after its store.

Bench observation: every target is read over SEP_IN with the cores held and
again after PASS, against the RDL reset word, and `region_attrs` is read after
PASS as the stored half taken and the other half held.

Tokens: CHK-FW-NARROW-STORE-BOOT, CHK-FW-NARROW-STORE-HELD.

Requires the staged image and a held boot:
  +smc_scratch_ram_hex=narrow_store_lane.ecc.hex   (bare basename; staged by c_compile)
  +smc_hold_cpu_boot
Must not use +skip_fuse_sense: a run with the fuse sense skipped is not
evidence for the fuse-derived boot path.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_fw_narrow_store_lane_test_seq import smc_fw_narrow_store_lane_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_fw_narrow_store_lane_test(smc_base_test):
    """Word stores to one half of a 64-bit register word; the other half holds."""

    auto_protocol_vip = False
    required_evidence = (
        "CHK-FW-NARROW-STORE-BOOT",
        "CHK-FW-NARROW-STORE-HELD",
    )
    min_evidence = 2

    async def run_scenario(self) -> None:
        seq = smc_fw_narrow_store_lane_test_seq("fw_narrow_store_lane_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.boot.get("boot_checked") is True, f"firmware boot was not checked: {seq.boot}"
        assert seq.held_ok, "the targets were not read back after PASS"
