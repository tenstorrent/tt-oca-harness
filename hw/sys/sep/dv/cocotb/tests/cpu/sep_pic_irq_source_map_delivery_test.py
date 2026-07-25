# SPDX-License-Identifier: Apache-2.0
"""SEP PIC interrupt-source map + multi-source delivery test (PyUVM).

CPU-complex Phase-2 rep PIC source-map delivery. OCAH provenance: fw `otbn_plic_test` (OTBN done ->
PIC source 30 -> ISR) + system `sep_irq_connectivity_test` (source->PIC
connectivity, force/INTR_TEST, no real ISR claim).

Boots the VeeR EL2 core and runs the `pic_irq_source_map_test` firmware, which
registers PIC ISRs for a REPRESENTATIVE set of three internal interrupt sources
spanning three IPs and proves the real source -> PIC source-id MAP plus the ISR
delivery to the CPU:

    mailbox[0]     sep_internal_interrupts[0]  -> PIC source 1   (real FIFO push)
    OTBN done      sep_internal_interrupts[29] -> PIC source 30  (INTR_TEST)
    CSRNG cmd done sep_internal_interrupts[23] -> PIC source 24  (INTR_TEST)

PIC source id = sep_internal_interrupts index + 1 (VeeR EL2 extintsrc_req is
1-based). The whole path is internal to bare `sep` -- no testbench injection.

Distinct from Phase-1 `sep_mailbox_plic_test` (ONE source, mailbox=1) and from
`sep_irq_ip_to_aggregator_test` (no_cpu, observes the AGGREGATE vector, no ISR
claim): this is the MULTI-SOURCE delivery-to-CPU-ISR map. Stronger than the OCAH
connectivity test, which is force/INTR_TEST UVM with no real CPU ISR claim.

Firmware-self-checking: the firmware returns its error count and start.S emits
the PASS (0xCAFEBABE) / FAIL (0xDEADBEEF) magic on the 0x8000_0000 mailbox, which
the boot scoreboard gates on. The firmware self-checks, per source: CHK-MAP (exact
meihap claim id), CHK-DELIVER (OTBN ISR wakes the CPU via WFI, no poll), CHK-IP-RW1C
(INTR_STATE / IRQS W1C-clear readback 0), CHK-PIC-COMPLETE (no re-fire storm), and
CHK-ONEHOT (only the asserted source's ISR fires among the three PIC-enabled sources),
plus CHK-NONVAC (no spurious ISR before any trigger). The scoreboard also checks the
banner and ICCM execution. Full 34-bit sep_internal_interrupts vector isolation is
COVERED_BY the no_cpu `sep_irq_ip_to_aggregator_test` (#14); here only the three
representative sources are PIC-enabled, so this proves delivery-path one-hot, not the
whole-vector wire isolation.

cpu / +skip_fuse_sense (no fuse data is read).
"""

from __future__ import annotations

import os
from pathlib import Path

import pyuvm

from sep_base_test import sep_base_test
from env.sep_boot_scoreboard import SepBootScoreboard

_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "tests", "pic_irq_source_map_test")
_ITCM_HEX = os.path.join(_FW_DIR, "pic_irq_source_map_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "pic_irq_source_map_test.dtcm.hex")

_ICCM_BASE = 0xC000_0000
# Three sources, each arm + trigger + ISR + a 256-iteration quiet window; the run
# loop early-exits on fw_done, so this is an upper bound.
_MAX_RUN_CYCLES = 3_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
_BANNER = "SEP PIC IRQ source map delivery test"


@pyuvm.test()
class sep_pic_irq_source_map_delivery_test(sep_base_test):
    """Boot VeeR EL2 and run the multi-source PIC source-map delivery firmware."""

    build_env = False

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    async def run_scenario(self) -> None:
        # Override the boot scoreboard's expected banner here (after its own
        # build_phase, which resets it to the hello_world default).
        self.sb.expected_line = _BANNER
        await self.boot_firmware(
            self.sb, _ITCM_HEX, _DTCM_HEX,
            rst_vec=_ICCM_BASE >> 1,
            max_run_cycles=_MAX_RUN_CYCLES,
            no_boot_cycles=_NO_BOOT_CYCLES,
            progress_every=_PROGRESS_EVERY,
        )
