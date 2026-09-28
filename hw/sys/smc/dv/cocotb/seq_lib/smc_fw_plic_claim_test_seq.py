# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Firmware programs the cluster PLIC, then claims a real external interrupt.

`fw/tests/plic_sanity/plic_sanity.c` clears every context's enable words, gives
the eight contexts distinct thresholds, registers a handler for one source,
enables it, publishes an arm word, and parks in `wfi`. Its handler calls
`test_pass(0)`.

What ties the verdict to source 1 is the registration, not the ID compare
inside the handler. `riscv_plic0.c:106-107` dispatches `metal_exint_table[idx]`
where `idx` is the value the PLIC's claim register returned, and
`plic_sanity.c` registers a handler at one index only; every other source
reaches `__metal_plic0_default_handler`, which posts no verdict. So the pass
word can only follow a claim of the registered source. The handler's own
`id != TEST_INTERRUPT_ID` branch is unreachable for that same reason and is
not relied on here.

The CPU is the only master that can program this PLIC: the aperture at
0xC400_0000 answers SEP_IN AXI reads but takes no writes from it, so the
enable/threshold/priority path is driven by firmware. The path proven is
pin -> synchroniser -> gateway -> enable and priority against threshold ->
MEIP -> trap -> claim -> the ID the CPU reads back -> complete;
`smc_ext_interrupts_pin_test` watches `ext_interrupts_i[0]` through the
synchroniser only, and `smc_hang_detector_plic_route_test` checks a route with
testbench probes and reads no PLIC register.

The stimulus is `ext_interrupts_i[0]`, driven on the same `tb_ext_interrupt_0_i`
that `smc_ext_interrupts_pin_test` drives. No forced internal state: the pin is
a DUT input, and everything between it and the verdict is the DUT
([NO-FORCED-INTERNAL-STATE]).

Ordering is what makes it a measurement rather than a coincidence:

1. The arm word has to arrive first. `check_cpu_firmware_boot_contract` fails a
   PASS that was never preceded by it, so an image that reached its verdict
   without going through the wait state cannot be counted.
2. The pin stays low for a bounded window after the arm word, and SCRATCH_0
   must still hold the arm word at the end of it. Without this the PASS could
   have come from any interrupt already pending, and the whole testcase would
   be satisfied by a DUT that traps on something else.
3. Only then do the pins rise. Source 1 is claimed, completed and re-delivered
   alone; the firmware then enables sources 2-17 against the pins already high
   and raises I2C0 (source 280) through INTR_TEST, requires every one of them
   to arrive once under its own ID in priority order, then claims each source
   alone at thresholds 1-6 and reads an idle claim at every threshold.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_cpu_vip_utils import CPU_CTRL_SCRATCH_0, check_cpu_firmware_boot_contract
from .smc_csr_seq_utils import SmcCsrSeq

# `write_scratch(0, 0xaaaaaaaa)` in plic_sanity.c, published after the PLIC is
# programmed and immediately before the wfi loop.
FW_ARMED_WORD = 0xAAAA_AAAA

# How long the pin stays low after the arm word, in clk_smc_i cycles. Long
# enough that a spontaneous trap-and-claim would have landed: the firmware
# takes well under this to get from its own store to the wfi.
QUIET_CYCLES = 2_000

# Verdict-poll bound, in units of 100 clk_smc_i cycles. This image is slow
# before it arms: __metal_driver_riscv_plic0_init walks all 336 sources,
# disabling each and zeroing its priority, and plic_sanity.c clears every
# context's enable words on top of that -- each one an MMIO round trip across
# the cluster boundary, so the verdict lands after the default bound. The
# bound leaves a few multiples of headroom above that init time without letting
# a genuine failure run long before it reports.
POLL_ITERATIONS = 6_000


class smc_fw_plic_claim_test_seq(SmcCsrSeq):
    """Arm the firmware, prove nothing fires on its own, then raise the pin."""

    def __init__(self, name: str = "smc_fw_plic_claim_test_seq") -> None:
        super().__init__(name)
        self.boot: dict[str, object] = {}
        self.quiet_ok = False

    async def _raise_ext_irq0(self) -> None:
        dut = cocotb.top
        assert hasattr(dut, "tb_ext_interrupt_0_i"), "tb_ext_interrupt_0_i missing"

        # Negative control first: with the PLIC armed and the pin still low,
        # the verdict must not move.
        await ClockCycles(dut.clk_smc_i, QUIET_CYCLES)
        still = await self.csr_read("PLIC_QUIET_SCRATCH0", CPU_CTRL_SCRATCH_0)
        assert still == FW_ARMED_WORD, (
            f"CHK-FW-PLIC-QUIET: SCRATCH_0 moved to 0x{still:08x} during "
            f"{QUIET_CYCLES} cycles with the PLIC armed and "
            f"ext_interrupts_i[0] still low. Whatever produced that was not "
            f"the interrupt this testcase raises, so a later PASS would not "
            f"be evidence for the claim path."
        )
        self.quiet_ok = True
        cocotb.log.info(
            "CHK-FW-PLIC-QUIET: SCRATCH_0 held 0x%08x for %d cycles with the pin "
            "low, so the verdict below depends on the pin.",
            FW_ARMED_WORD,
            QUIET_CYCLES,
        )

        # Every pin the firmware registers rises together: source 1 first
        # (the only enabled one, so the claim and re-delivery legs see it
        # alone), then sources 2-17 are enabled by the firmware against pins
        # already high, and the I2C0 source is raised by the firmware itself.
        dut.tb_ext_interrupt_0_i.value = 1
        dut.tb_temp_interrupt_i.value = 1
        dut.tb_ext_interrupts_hi_i.value = (1 << 15) - 1
        cocotb.log.info(
            "CHK-FW-PLIC-STIMULUS: ext_interrupts_i[16:0] driven high; PLIC sources 1-17"
        )

    async def body(self) -> None:
        cocotb.top.tb_ext_interrupt_0_i.value = 0
        cocotb.top.tb_temp_interrupt_i.value = 0
        cocotb.top.tb_ext_interrupts_hi_i.value = 0
        self.boot = await check_cpu_firmware_boot_contract(
            self,
            require_image=True,
            arm_value=FW_ARMED_WORD,
            on_armed=self._raise_ext_irq0,
            poll_iterations=POLL_ITERATIONS,
        )
        cocotb.log.info(
            "CHK-FW-PLIC-CLAIM: %s",
            ", ".join(f"{k}={v}" for k, v in sorted(self.boot.items())),
        )
