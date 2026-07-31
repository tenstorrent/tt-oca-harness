# SPDX-License-Identifier: Apache-2.0
"""SMC OSS PyUVM CPU firmware boot test.

DV-CARD:          SMC_002   ANCHOR: smc_cpu_firmware_boot_test
DV-CARD-REVISION: 3   RECORD-SHA256: ddd9fadb67a514e9e6ca93f099abd535d284a6fd9e9c89d61ccc78f1a56f3e40
DV-CARD-SOURCE:   hw/sys/smc/dv/tb/SMC_VPLAN_DETAIL.md @ artifact_revision 1   ENV: cocotb

Requires ROM preload for CHK-ROM-IS-TARGET:
  +smc_rom_hex=<rom hex>   (min_pass @ 0xC004_0000)
  +smc_hold_cpu_boot
Must NOT use +smc_scratch_ram_hex or +skip_fuse_sense for this card seed.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_cpu_firmware_boot_test_seq import smc_cpu_firmware_boot_test_seq


@pyuvm.test()
class smc_cpu_firmware_boot_test(smc_base_test):
    """SMC_002: ROM boot to PASS magic with exact CHK evidence."""

    auto_protocol_vip = False

    async def _fuse_sense_watcher(self, seq: smc_cpu_firmware_boot_test_seq) -> None:
        """Capture tb_fuse_sense_done 0→1 during bring-up."""
        dut = cocotb.top
        try:
            for _ in range(500_000):
                await RisingEdge(dut.clk_smc_i)
                if not dut.tb_fuse_sense_done.value.is_resolvable:
                    continue
                v = int(dut.tb_fuse_sense_done.value)
                if v == 0:
                    seq.fuse_saw_low = True
                elif v == 1 and seq.fuse_saw_low:
                    seq.fuse_saw_high = True
                    return
        except Exception:  # noqa: BLE001 — watcher must not kill the test
            return

    async def run_phase(self) -> None:
        self.raise_objection()
        seq = smc_cpu_firmware_boot_test_seq("cpu_fw_boot_seq")
        # Watch fuse sense across cold-reset release / settle.
        watcher = cocotb.start_soon(self._fuse_sense_watcher(seq))
        await self._bring_up()
        await self.run_scenario_with(seq)
        if not watcher.done():
            watcher.kill()
        self.drop_objection()

    async def run_scenario_with(self, seq: smc_cpu_firmware_boot_test_seq) -> None:
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CPU,
            type(self).__name__,
            csr_accesses=seq.accesses,
            proxy=False,
            details=str(seq.boot.get("reason", "firmware boot checked")),
        )

    async def run_scenario(self) -> None:
        # Unused when run_phase overrides; kept for base-class contract.
        seq = smc_cpu_firmware_boot_test_seq("cpu_fw_boot_seq")
        await self.run_scenario_with(seq)
