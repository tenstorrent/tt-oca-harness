# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smc_5agent_observability_test.

Single scenario that samples all five agents (reset, i2c, clock, irq, gpio).
Verifies the full env composition: 5 agents, 5 item types, type-dispatched
scoreboard handling them all in one run.

Three proof obligations shape the body:

* A bare idle IRQ sample, whose ``sync_irq`` / ``gpio_irq_any`` /
  ``uart_irq_any`` == 0 compares also pass on a stuck-at-0 or mis-bound probe,
  proves nothing on its own. The SAMPLE is therefore preceded by a
  **positive control**: GPIO0 is armed
  over the real SEP_IN AXI frontdoor and driven low at the pad until
  ``tb_gpio_irq_any`` is observed at 1, and an IRQ item carrying
  ``expect_gpio_irq_any = 1`` is sampled inside that window
  (`[NEGATIVE-NEEDS-POSITIVE-CONTROL]`).
* A single SAMPLE gated only on ``item.resolvable`` gives ``CHK-5AGENT-GPIO``
  no FAIL-ON path, because ``resolvable`` cannot be False on a 2-state
  simulator (Verilator). The GPIO leg is therefore a *pair* of
  SAMPLEs whose expectation is stated on the **raw pad-bus vectors**
  (``tb_core2pad_o`` / ``tb_core2pad_en_o``), backed in the same run by
  ``ensure_gpio_pad_bus_control``. The three ``tb_gpio_*_any`` aggregates are
  unbackable in this TB and stay OBSERVED-ONLY -- the scoreboard refuses a
  stated expectation on them (`[EVIDENCE-TOKEN-CONDITIONAL]`,
  `[NEGATIVE-NEEDS-POSITIVE-CONTROL]`).
* The 5-agent composition claim is gated on the **per-type** scoreboard
  counters, not on the aggregate ``total > 0`` gate, so a missing item type is
  a composition failure instead of an invisible hole (`[EXACT-EXPECTATION]`).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from env.smc_clk_item import SmcClkItem, SmcClkOp
from env.smc_gpio_item import SmcGpioItem, SmcGpioOp
from env.smc_i2c_item import SmcI2cItem, SmcI2cOp
from env.smc_irq_item import IRQ_SAMPLE_FIELDS, SmcIrqItem, SmcIrqOp
from env.smc_probe_liveness import probe_alive, probe_evidence
from env.smc_reset_item import SmcResetItem, SmcResetOp

from .smc_base_test_seq import smc_base_test_seq
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_gpio_irq_active_test_seq import (
    GPIO0_DATA_CTRL,
    GPIO_INPUT_ACTIVE_LOW_IRQ,
)

# Bounded pad -> aggregate poll published by smc_gpio_vip_utils (expiry is a
# failure, never a settle delay). `check_gpio0_active_low_irq` cannot be used
# here because it releases the pad before returning, leaving no window in which
# an IRQ item can be sampled while the aggregate is asserted;
# `await_gpio_irq_level` is the assert-and-hold seam that module publishes for
# exactly that, so this is a plain public import with no private-name fallback
# (`[REUSE-AND-LAYERING]`).
from .smc_gpio_vip_utils import await_gpio_irq_level
from .smc_probe_positive_control import ensure_gpio_pad_bus_control

# Of the two backable pad-bus vectors, only the output-ENABLE vector is a
# defensible cross-sample expectation here. `tb_core2pad_o` (the pad *value*
# bus) carries live DUT outputs -- the AVSBus clock on pad 49 can toggle inside
# the sampling window -- so a "did not move" claim on it is a flaky claim about
# traffic this scenario does not own. `tb_core2pad_en_o` only changes when a
# GPIO wrap's direction is programmed, which this scenario does not do after
# the pad-bus control restores it, so its persistence is a real property. Its
# liveness credit comes from the same control (exactly one new enable bit
# appears and is then released), so a stuck / undriven / mis-bound enable
# vector cannot pass.
GPIO_STABLE_VECTOR_FIELDS = ("core2pad_en_vec",)


class _Gpio0IrqArmSeq(SmcCsrSeq):
    """Frontdoor CSR leg: arm GPIO0 as RX + active-low level interrupt.

    Same register and same generated-header field symbols as
    ``smc_gpio_irq_active_test_seq`` (`[ADDRESS-FROM-AUTHORITATIVE-MAP]`); it
    runs on the SEP_IN AXI sequencer because the IRQ/GPIO observability agents
    are SAMPLE-only and cannot produce stimulus.
    """

    async def body(self) -> None:
        await self.csr_write(
            "GPIO0_INPUT_ACTIVE_LOW_IRQ",
            GPIO0_DATA_CTRL,
            GPIO_INPUT_ACTIVE_LOW_IRQ,
        )


class smc_5agent_observability_test_seq(smc_base_test_seq):
    # Exact per-type item counts this body dispatches; the end gate compares the
    # scoreboard's typed counters against them.
    EXPECTED_SAMPLES = {
        "reset_samples_seen": 1,
        "i2c_samples_seen": 1,
        "irq_samples_seen": 2,  # positive control + idle re-check
        "gpio_samples_seen": 2,  # observed-only reference + exact-compared
        "clk_samples_seen": 1,
    }

    # Gap between the GPIO reference sample and the sample that carries it as
    # `expect_*`. Long enough for a spurious pad-bus change to be visible;
    # nothing in this scenario drives the pad bus across it.
    GPIO_GAP_REF_CYCLES = 80

    def __init__(self, name: str = "smc_5agent_observability_test_seq") -> None:
        super().__init__(name)
        self.dispatch_reset = None
        self.dispatch_i2c = None
        self.dispatch_clk = None
        self.dispatch_irq = None
        self.dispatch_gpio = None
        self.irq_positive = None
        self.irq_idle = None

    def _resolve_env(self):
        """The env this sequence runs in.

        ``smc_5agent_observability_test`` starts this sequence directly (it
        supplies per-agent dispatchers instead of going through
        ``smc_base_test.start_seq``), so ``self.env`` may be unset. Walk up from
        the sequencer this sequence was started on -- a passive read of the UVM
        component tree, no DUT access.
        """
        if self.env is not None:
            return self.env
        node = self.sequencer
        while node is not None:
            if hasattr(node, "scoreboard"):
                return node
            node = node.get_parent()
        raise AssertionError(
            f"{self.get_name()}: could not resolve SmcEnv from sequencer "
            f"{self.sequencer}; the per-type end gate needs the scoreboard"
        )

    async def _prove_irq_positive_control(self, env) -> None:
        """Make ``tb_gpio_irq_any`` read 1 and sample it through the IRQ agent."""
        dut = cocotb.top
        arm = _Gpio0IrqArmSeq("gpio0_irq_arm")
        arm.cfg = self.cfg
        arm.env = env
        await arm.start(env.sys_axi_agent.sequencer)

        dut.tb_gpio_ext_drive_en.value = 0x1
        dut.tb_gpio_ext_drive_value.value = 0x1
        await await_gpio_irq_level(dut, 0, "5agent_gpio0_pad_high_idle")

        dut.tb_gpio_ext_drive_value.value = 0x0
        cycles = await await_gpio_irq_level(dut, 1, "5agent_gpio0_pad_low_assert")
        pos = SmcIrqItem("irq_positive")
        pos.op = SmcIrqOp.SAMPLE
        pos.expect_gpio_irq_any = 1
        await self.dispatch_irq(pos)
        self.irq_positive = pos
        assert pos.resolvable, f"IRQ positive-control sample is X/Z: {pos}"
        assert pos.gpio_irq_any == 1, (
            f"IRQ positive control: tb_gpio_irq_any = {pos.gpio_irq_any}, "
            f"expected 1 while GPIO0 is held low ({pos})"
        )
        cocotb.log.info(
            "CHK-5AGENT-IRQ-POSITIVE: GPIO0 driven low asserted tb_gpio_irq_any "
            "after %d clk_smc_i cycles and the IRQ agent sampled it as 1 "
            "(expect_gpio_irq_any=1 exact-compared by the scoreboard): %s",
            cycles,
            pos,
        )

        dut.tb_gpio_ext_drive_value.value = 0x1
        await await_gpio_irq_level(dut, 0, "5agent_gpio0_pad_high_clear")
        dut.tb_gpio_ext_drive_en.value = 0x0

    async def body(self) -> None:
        env = self._resolve_env()

        r = SmcResetItem("reset")
        r.op = SmcResetOp.SAMPLE
        await self.dispatch_reset(r)
        assert r.resolvable, f"reset sample is X/Z: {r}"
        cocotb.log.info(
            "CHK-5AGENT-RESET: post-bring-up reset SAMPLE passed its exact "
            "all-released expectation: %s",
            r,
        )

        i = SmcI2cItem("i2c")
        i.op = SmcI2cOp.SAMPLE
        await self.dispatch_i2c(i)
        assert i.resolvable and i.cg_en == 0, f"I2C idle sample unexpected: {i}"
        cocotb.log.info(
            "CHK-5AGENT-I2C: I2C SAMPLE passed tb_i2c_cg_en == 0: %s",
            i,
        )

        # IRQ: positive control first, then the idle re-check it backs.
        await self._prove_irq_positive_control(env)
        ir = SmcIrqItem("irq")
        ir.op = SmcIrqOp.SAMPLE
        await self.dispatch_irq(ir)
        self.irq_idle = ir
        assert ir.resolvable, f"IRQ idle sample is X/Z: {ir}"
        for field in IRQ_SAMPLE_FIELDS:
            got = getattr(ir, field)
            assert got == 0, (
                f"IRQ idle re-check: tb_{field} = {got}, expected 0 after the "
                f"GPIO0 pad was released ({ir})"
            )
        cocotb.log.info(
            "CHK-5AGENT-IRQ-IDLE: with no interrupt source driven, %s all read "
            "0 -- backed by CHK-5AGENT-IRQ-POSITIVE in this same run: %s",
            "/".join(f"tb_{f}" for f in IRQ_SAMPLE_FIELDS),
            ir,
        )

        # GPIO: a *pair* of SAMPLEs, not one, and the compare is on the raw
        # pad-bus vectors -- not on the three tb_gpio_*_any aggregates.
        #
        # The aggregates are OR-reductions over the WHOLE pad bus (tb_top.sv
        # :1375-1377), which also carries idle-high LSIO pads (UART TX): they
        # read 1 from reset onward and no frontdoor stimulus can drive them to 0,
        # so they are declared in `env.smc_probe_liveness.UNBACKABLE_PROBES` and
        # `SmcScoreboard._check_gpio` REFUSES a stated `expect_` on them. And
        # `assert g.resolvable` alone is not a check either: on a 2-state
        # simulator (Verilator) `value.is_resolvable` cannot be False.
        #
        # `tb_core2pad_o` / `tb_core2pad_en_o` DO move under real frontdoor GPIO
        # CSR programming, which is what makes an expectation on them backable.
        # `ensure_gpio_pad_bus_control` runs the pad-bus positive control (GPIO
        # wrap 0 programmed as TX: exactly one new output-enable bit, its value
        # following the register high then low, then a bit-for-bit restore) and
        # credits `gpio_core2pad_vec` / `gpio_core2pad_en_vec`, so the compare
        # below is booked as checked evidence rather than OBSERVED-ONLY. With the
        # control restored and nothing else touching the pad bus, the two
        # vectors cannot move between the reference sample and the checked one
        # ([EVIDENCE-TOKEN-CONDITIONAL] / [EXACT-EXPECTATION] /
        # [NEGATIVE-NEEDS-POSITIVE-CONTROL]).
        self.env = env
        await ensure_gpio_pad_bus_control(self)
        g_ref = SmcGpioItem("gpio_ref")
        g_ref.op = SmcGpioOp.SAMPLE
        await self.dispatch_gpio(g_ref)
        assert g_ref.resolvable, f"GPIO reference sample is X/Z: {g_ref}"
        assert g_ref.vec_width > 0, (
            f"GPIO reference sample carries no pad-bus vector (tb_core2pad_o / "
            f"tb_core2pad_en_o mirror missing), so this leg would have no "
            f"backable observable: {g_ref}"
        )
        cocotb.log.info(
            "GPIO reference sample (pad-bus vectors are the checked observables; "
            "the tb_gpio_*_any aggregates are OBSERVED-ONLY): %s",
            g_ref,
        )
        await ClockCycles(cocotb.top.clk_ref_i, self.GPIO_GAP_REF_CYCLES)
        g = SmcGpioItem("gpio")
        g.op = SmcGpioOp.SAMPLE
        for field in GPIO_STABLE_VECTOR_FIELDS:
            setattr(g, "expect_" + field, getattr(g_ref, field))
        await self.dispatch_gpio(g)
        assert g.resolvable, f"GPIO sample is X/Z: {g}"
        for field in GPIO_STABLE_VECTOR_FIELDS:
            exp = getattr(g_ref, field)
            got = getattr(g, field)
            assert got == exp, (
                f"GPIO {field} changed between the reference sample and the "
                f"checked sample (0x{exp:x} -> 0x{got:x}) over "
                f"{self.GPIO_GAP_REF_CYCLES} clk_ref_i cycles, with the pad-bus "
                f"control already restored and no other GPIO CSR write or pad "
                f"drive in between: reference={g_ref} sample={g}"
            )
        for probe in ("gpio_core2pad_en_vec",):
            assert probe_alive(probe), (
                f"GPIO pad-bus leg has no same-run liveness credit for {probe} "
                f"({probe_evidence(probe)}), so the scoreboard books the "
                f"vector compare OBSERVED-ONLY instead of checked evidence"
            )
        cocotb.log.info(
            "CHK-5AGENT-GPIO: pad-bus vectors %s exact-compared by the "
            "scoreboard against the reference sample %d clk_ref_i cycles "
            "later, both probes carrying a same-run liveness credit (%s): %s",
            ", ".join(f"tb_{f}=0x{getattr(g_ref, f):x}" for f in GPIO_STABLE_VECTOR_FIELDS),
            self.GPIO_GAP_REF_CYCLES,
            probe_evidence("gpio_core2pad_en_vec"),
            g,
        )

        c = SmcClkItem("clk")
        c.op = SmcClkOp.COUNT_EDGES
        c.window_ref_cycles = 25
        await self.dispatch_clk(c)
        cocotb.log.info(
            "CHK-5AGENT-CLK: COUNT_EDGES window passed its scoreboard legs "
            "(ref=%d smc=%d periph=%d SETUP; %s=%d edges with %s=%d): %s",
            c.ref_rising_edges,
            c.smc_rising_edges,
            c.periph_rising_edges,
            c.gated_clk_probe,
            c.gated_clk_rising_edges,
            c.gated_cg_en_probe,
            c.gated_cg_en,
            c,
        )

        # Per-type composition gate: each of the five item types must have
        # reached the scoreboard exactly as many times as this body dispatched
        # it. The scoreboard's own check_phase only requires a non-zero total,
        # which a missing type would satisfy.
        sb = env.scoreboard
        observed = {name: getattr(sb, name) for name in self.EXPECTED_SAMPLES}
        assert observed == self.EXPECTED_SAMPLES, (
            f"5-agent composition mismatch: scoreboard saw {observed}, "
            f"expected {self.EXPECTED_SAMPLES}"
        )
        cocotb.log.info(
            "CHK-5AGENT-COMPOSITION: all five item types reached the "
            "type-dispatched scoreboard with the exact counts this sequence "
            "dispatched: %s",
            observed,
        )
