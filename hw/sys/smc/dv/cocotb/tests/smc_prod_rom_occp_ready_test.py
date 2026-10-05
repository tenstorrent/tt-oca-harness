# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS production boot ROM milestone: reach the OCCP command loop.

Runs product firmware (hw/sys/smc/bootrom/prod, built with I3C_CORE=chipsalliance)
rather than a DV stub image. It is narrower than the OCCP boot tests that build on it: no bus traffic, no
controller. It answers one question -- does the real ROM get all the way from
reset through strap/fuse read, security checks, interface map and OCCP init to
its command processing loop, on the OSS smc_wrapper?

Evidence is the ROM's own POST code (scratch 1, boot phase field 31:28 ==
OCCP_PROC), cross-checked against CPU ROM fetch activity so the phase cannot be
credited to anything but the ROM executing.

Required plusargs:
  +rom_bin64=<prod_rom.bin64>   production ROM image (staged by c_compile)
  +smc_hold_cpu_boot            hold boot_stall from t=0 until the vector is set
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_prod_rom_boot_seq import smc_prod_rom_boot_seq
from seq_lib.smc_prod_rom_defs import describe_post_code
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_prod_rom_occp_ready_test(smc_base_test):
    """Production ROM boots to its OCCP command processing loop."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_prod_rom_boot_seq("prod_rom_boot_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        self.logger.info(
            "prod_rom reached OCCP command loop: POST %s",
            describe_post_code(seq.post_code),
        )
