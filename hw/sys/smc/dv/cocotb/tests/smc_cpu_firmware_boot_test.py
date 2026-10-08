# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM CPU firmware boot test.

DV-CARD:          SMC_002   ANCHOR: smc_cpu_firmware_boot_test

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
from seq_lib.smc_cpu_firmware_boot_test_seq import smc_cpu_firmware_boot_test_seq
from smc_base_test import log_build_model_identity, smc_base_test


@pyuvm.test()
class smc_cpu_firmware_boot_test(smc_base_test):
    """SMC_002: ROM boot to PASS magic with exact CHK evidence."""

    required_evidence = (
        "CHK-CLK-SMC-LIVE",
        "CHK-CPU-BFM-OBSERVABILITY",
        "CHK-EFUSE-SENSE-DONE",
        "CHK-NONVAC",
        "CHK-RESET-VECTOR-FETCH",
        "CHK-ROM-IS-TARGET",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def _fuse_sense_watcher(self, seq: smc_cpu_firmware_boot_test_seq) -> None:
        """Capture tb_fuse_sense_done 0→1 during bring-up."""
        dut = cocotb.top
        try:
            for _ in range(500_000):
                await RisingEdge(dut.clk_smc_i)
                # Verilator is 2-state, so this guard never takes its `continue`
                # branch there. It is a precondition for the 4-state simulators,
                # not a check.
                if not dut.tb_fuse_sense_done.value.is_resolvable:
                    continue
                v = int(dut.tb_fuse_sense_done.value)
                if v == 0:
                    seq.fuse_saw_low = True
                elif v == 1 and seq.fuse_saw_low:
                    seq.fuse_saw_high = True
                    return
        except Exception:  # noqa: BLE001 — watcher must not kill the test
            # Task cancellation is a BaseException in cocotb 2.x and never
            # reaches this handler, so anything caught here is a watcher defect.
            # It is logged with its traceback; it is not fatal because
            # `_wait_fuse_sense_transition` in the sequence re-derives the same
            # 0->1 edge and raises when it cannot.
            cocotb.log.exception(
                "fuse-sense watcher aborted (saw_low=%s saw_high=%s); the "
                "sequence must now re-derive the tb_fuse_sense_done 0->1 edge "
                "itself or fail",
                seq.fuse_saw_low,
                seq.fuse_saw_high,
            )
            return

    async def run_phase(self) -> None:
        self.raise_objection()
        # First line of every kept log's run phase: what RTL this run simulated
        # ([BUILD-MODEL-IDENTITY]). The base `smc_base_test.run_phase` emits it
        # by calling `log_build_model_identity`; this override must too, or the
        # SMC_002 ROM-boot evidence cannot be bound to an elaborated model.
        log_build_model_identity(require_clean_tree=self.require_clean_tree)
        seq = smc_cpu_firmware_boot_test_seq("cpu_fw_boot_seq")
        # Watch fuse sense across cold-reset release / settle.
        watcher = cocotb.start_soon(self._fuse_sense_watcher(seq))
        await self._bring_up()
        await self.run_scenario_with(seq)
        if not watcher.done():
            watcher.kill()
        # The base run_phase grades the log here. This override must too, or a
        # silent ROM-boot scenario would pass without an EVIDENCE_SUMMARY.
        self._finalize_evidence()
        self.drop_objection()

    async def run_scenario_with(self, seq: smc_cpu_firmware_boot_test_seq) -> None:
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CPU,
            type(self).__name__,
            # Directed stimulus floor: 9 SEP_IN AXI CPU boot-control accesses.
            # Literal here, not read from `seq.accesses`.
            min_csr_accesses=9,
            csr_accesses=seq.accesses,
            proxy=False,
            details=str(seq.boot.get("reason", "firmware boot checked")),
        )

    async def run_scenario(self) -> None:
        # Unused when run_phase overrides; the base class requires it.
        seq = smc_cpu_firmware_boot_test_seq("cpu_fw_boot_seq")
        await self.run_scenario_with(seq)
