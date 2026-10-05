# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Each inbound mailbox threshold interrupt reaches the CPU on PIC source ch+1 and not the SMC line.

The test boots the VeeR EL2 core and runs the mailbox_plic firmware, which walks all eight
inbound mailbox channels (axil_mailbox @ 0x10A0_0800, stride 0x1000). Each channel self-triggers its
threshold interrupt by pushing a word into that FIFO, and proves the interrupt
reaches the CPU through the VeeR PIC (WFI + ISR):
PIC source ``ch+1`` (``interrupts.adoc`` Mailbox interrupt ``ch``) -> CPU trap
-> ISR. The whole path is internal to bare ``sep`` -- no testbench injection.

Like the other FW-boot tests this is firmware-self-checking: the firmware
returns its error count and fw/startup/crt0.s emits the PASS (0xCAFEBABE) / FAIL
(0xDEADBEEF) magic on the 0x8000_0000 mailbox, which the boot scoreboard gates
on. The firmware self-checks the exact PIC claim id (== ch+1), the asserted IRQP/
IRQS write bit, the IRQS/IRQP W1C-clear readback, and the absence of an
interrupt storm; a failed check makes fw/startup/crt0.s emit FAIL. The host also counts
eight ``CHK-DELIVER`` / ``CHK-RW1C`` / ``CHK-NOSTORM`` lines so a skip of one
channel cannot hide behind the PASS magic. The scoreboard also checks the
firmware banner and that the core executed out of ICCM.

The host also grades the direction:
  CHK-DIRECTION : the firmware's outbound channel-0 push raises none of the eight
                  inbound PIC sources.
  CHK-SMC-LINE  : no inbound pending interrupt appears on smc_mailbox_interrupt_o,
                  and the outbound channel-0 push leaves exactly bit 0 set.

No fuse data is read, so the testlist entry uses ``+skip_fuse_sense``.
"""

from __future__ import annotations

import os
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import Edge, First, ReadOnly
from cocotb.utils import get_sim_time
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_spec_tables import pic
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "mailbox_plic_test")
_ITCM_HEX = os.path.join(_FW_DIR, "mailbox_plic_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "mailbox_plic_test.dtcm.hex")

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
# Arm + trigger + ISR + a 256-iteration quiet window, eight channels; the run
# loop early-exits on fw_done, so this is an upper bound.
_MAX_RUN_CYCLES = 8_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
_BANNER = "SEP mailbox PLIC test"
_MBOX_N = pic("Mailbox interrupt 7")


@pyuvm.test()
class sep_mailbox_plic_test(sep_base_test):
    """Inbound mailbox interrupts reach the PIC with the exact claim id and skip the SMC line."""

    build_env = False

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    async def run_scenario(self) -> None:
        # Override the boot scoreboard's expected banner here (after its own
        # build_phase, which resets it to the hello_world default).
        self.sb.expected_line = _BANNER

        # Baseline: the SMC-facing line is idle once reset is released and
        # before the firmware pushes anything, so a 1 at the end of the run is
        # this run's doing. Sampled in the post-bring-up hook rather than at
        # time 0: under a four-state simulator the port is X before reset, and
        # a compare there would raise on a healthy run.
        smc_irq = cocotb.top.smc_mailbox_interrupt_o
        irq_vec = cocotb.top.sep_internal_interrupts_probe_o
        inbound_mask = (1 << _MBOX_N) - 1
        # Inbound channel ch drives sep_internal_interrupts[ch] (PIC source ch+1,
        # interrupts.adoc). Every change of that vector or of the SMC-facing
        # line is sampled, so each inbound pending window is seen while it is
        # open, not after the firmware has cleared it.
        inbound_seen = [False] * _MBOX_N
        leaks: list[str] = []

        async def _watch_inbound_vs_smc_line() -> None:
            while True:
                await First(Edge(irq_vec), Edge(smc_irq))
                await ReadOnly()
                inbound = self.rd_known(irq_vec, inbound_mask) & inbound_mask
                smc_now = self.rd_known(smc_irq) & inbound_mask
                for ch in range(_MBOX_N):
                    if (inbound >> ch) & 1:
                        inbound_seen[ch] = True
                        if (smc_now >> ch) & 1:
                            leaks.append(
                                f"inbound ch{ch} pending and smc_mailbox_interrupt_o[{ch}]=1 "
                                f"at {get_sim_time('ns')} ns"
                            )

        async def _smc_line_idle() -> None:
            assert self.rd_known(smc_irq) == 0, (
                "smc_mailbox_interrupt_o is already asserted after reset; the "
                "end-of-run check below could not attribute it to the outbound push"
            )
            cocotb.start_soon(_watch_inbound_vs_smc_line())

        await self.boot_firmware(
            self.sb,
            _ITCM_HEX,
            _DTCM_HEX,
            rst_vec=_ICCM_BASE >> 1,
            max_run_cycles=_MAX_RUN_CYCLES,
            no_boot_cycles=_NO_BOOT_CYCLES,
            progress_every=_PROGRESS_EVERY,
            after_bring_up_hook=_smc_line_idle,
        )
        console = self.sb.console_text()
        for label in ("CHK-DELIVER PASS:", "CHK-RW1C PASS:", "CHK-NOSTORM PASS:"):
            got = console.count(label)
            if got != _MBOX_N:
                raise AssertionError(
                    f"firmware emitted {got} {label!r} lines, expected {_MBOX_N} "
                    "(one per inbound mailbox channel)"
                )
        assert self.sb.fw_done and self.sb.fw_pass, (
            "firmware did not signal a PASS verdict; the console needles above "
            "are not a verdict on their own"
        )
        self.logger.info(
            "CHK-DELIVER PASS: all %d inbound mailbox channels reached the CPU "
            "with RW1C clear and no storm",
            _MBOX_N,
        )

        # Direction, observed rather than reported. The spec gives PIC sources
        # 1-8 to the SMC-to-SEP (inbound) mailbox channels
        # (hw/sys/sep/doc/interrupts.adoc) and gives smc_mailbox_interrupt_o to
        # the mailbox interrupts toward the SMC (hw/sys/sep/doc/port_table.adoc).
        # The firmware left its outbound channel-0 entry pending and cleared
        # every inbound one, so bit 0 must be set and the rest clear. An
        # outbound push routed to the PIC instead leaves this line at 0.
        assert "CHK-DIRECTION PASS:" in console, (
            "firmware console has no CHK-DIRECTION line, so the outbound push "
            f"never ran or reached the CPU. Console was:\n{console}"
        )
        # Positive control: every inbound interrupt was observed pending, so the
        # leak check below ran inside each window rather than on an idle line.
        missing = [ch for ch in range(_MBOX_N) if not inbound_seen[ch]]
        assert not missing, (
            f"CHK-SMC-LINE FAIL: inbound mailbox interrupt(s) {missing} were never seen "
            "pending on sep_internal_interrupts; the per-window check did not run"
        )
        assert not leaks, "CHK-SMC-LINE FAIL: " + "; ".join(leaks)
        smc_bits = self.rd_known(smc_irq)
        assert smc_bits == 0b1, (
            f"smc_mailbox_interrupt_o = 0b{smc_bits:08b}, expected 0b00000001: "
            "bit 0 is the pending outbound push, and the inbound pushes "
            "that reached the CPU must not appear on this line at all"
        )
        self.logger.info(
            "CHK-SMC-LINE PASS: all %d inbound interrupts were seen pending with "
            "smc_mailbox_interrupt_o clear of each, and the outbound push left "
            "0b%s at the end",
            _MBOX_N,
            f"{smc_bits:08b}",
        )
