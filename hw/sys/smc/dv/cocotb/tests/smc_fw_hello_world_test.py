# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Smallest SMC firmware image, booted end to end.

Runs a DV C image from hw/sys/smc/dv/fw/tests/ and proves the firmware path
itself -- c_compile, output staging, the striped scratch load, the reset-vector
handoff and the MMIO verdict -- rather than any DUT feature, so the image is
`test_pass(0)` and nothing else.

Requires the staged image and a held boot:
  +smc_scratch_ram_hex=hello_world.ecc.hex   (bare basename; staged by c_compile)
  +smc_hold_cpu_boot
Must NOT use +skip_fuse_sense -- see dv_policy 1.6.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_fw_hello_world_test_seq import smc_fw_hello_world_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_fw_hello_world_test(smc_base_test):
    """Firmware boots from the scratch image and posts its own PASS word."""

    required_evidence = ("CHK-FW-HELLO-WORLD-BOOT",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_fw_hello_world_test_seq("fw_hello_world_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # check_cpu_firmware_boot_contract raises on TEST_FAIL, on the
        # 0xBAD0_xxxx fatal namespace, on a missing image and on the poll bound
        # expiring, so reaching here means the PASS magic was read back. The
        # assertion below is the one thing the sequence cannot enforce for
        # itself: that the contract actually ran a check rather than reporting
        # a skip.
        assert seq.boot.get("boot_checked") is True, f"firmware boot was not checked: {seq.boot}"
