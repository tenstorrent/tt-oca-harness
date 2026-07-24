# SPDX-License-Identifier: Apache-2.0
"""SMC OSS CPU firmware boot contract test (U3).

Requires a preload plusarg:
  +smc_scratch_ram_hex=<ecc hex>  (hello_world @ 0xC006_0000), or
  +smc_rom_hex=<hex>              (ROM window @ 0xC004_0000)

Without an image this test fails (unlike smc_cpu_sanity_test which is gated).
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_cpu_firmware_boot_test_seq import smc_cpu_firmware_boot_test_seq


@pyuvm.test()
class smc_cpu_firmware_boot_test(smc_base_test):
    """U3: real FW boot to scratch PASS magic 0xACAFACA1 with image preload."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cpu_firmware_boot_test_seq("cpu_fw_boot_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CPU,
            type(self).__name__,
            csr_accesses=seq.accesses,
            proxy=False,
            details=str(seq.boot.get("reason", "firmware boot checked")),
        )
