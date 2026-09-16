# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smc_6agent_observability_test.

All six agents (reset / i2c / clk / irq / gpio / axil) sampled in one scenario.
The ultimate full-env demonstration.

Each agent's mapped expectation is asserted here and only then does the body
emit that agent's ``CHK-6AGENT-<AGENT>:`` evidence token, so no token can be
printed from the setup path or from an item whose compare did not run
(`[EVIDENCE-TOKEN-CONDITIONAL]`).

The composition claim is gated on the **scoreboard's typed counters**
(``EXPECTED_SAMPLES``), which are incremented on the analysis path: a mis-bound
agent, a dropped item type or a monitor that never published fails the gate.
The ordered ``chk_seen`` list is a readable record of which legs ran -- it is
appended by ``_chk`` itself in the same straight-line body, so
comparing it against a literal could not fail on any RTL, so it is not the
composition check (`[NO-ALWAYS-PASS-CHECKER]`).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from env.smc_axil_item import (
    AXIL_CHECKABLE_FIELDS,
    AXIL_UNBACKABLE_FIELDS,
    SmcAxilItem,
    SmcAxilOp,
)
from env.smc_clk_item import SmcClkItem, SmcClkOp
from env.smc_gpio_item import SmcGpioItem, SmcGpioOp
from env.smc_i2c_item import SmcI2cItem, SmcI2cOp
from env.smc_irq_item import IRQ_SAMPLE_FIELDS, SmcIrqItem, SmcIrqOp
from env.smc_probe_liveness import probe_alive, probe_evidence
from env.smc_reset_item import RESET_SAMPLE_FIELDS, SmcResetItem, SmcResetOp

from .smc_base_test_seq import smc_base_test_seq
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


class smc_6agent_observability_test_seq(smc_base_test_seq):
    # Exact per-type item counts this body dispatches; the end gate compares the
    # scoreboard's typed counters against them. The test's declared probe
    # positive controls dispatch no agent SAMPLE items, so these are exact.
    EXPECTED_SAMPLES = {
        "reset_samples_seen": 1,
        "i2c_samples_seen": 1,
        "irq_samples_seen": 1,
        "gpio_samples_seen": 2,  # observed-only reference + exact-compared
        "axil_samples_seen": 1,
        "clk_samples_seen": 1,
    }

    # Gap between the GPIO reference sample and the sample that carries it as
    # `expect_*`. Long enough for a spurious pad-bus change to be visible;
    # this scenario drives nothing onto the pad bus across it.
    GPIO_GAP_REF_CYCLES = 80

    def __init__(self, name: str = "smc_6agent_observability_test_seq") -> None:
        super().__init__(name)
        self.dispatch_reset = None
        self.dispatch_i2c = None
        self.dispatch_clk = None
        self.dispatch_irq = None
        self.dispatch_gpio = None
        self.dispatch_axil = None
        self.chk_seen: list[str] = []

    def _chk(self, name: str, line: str, *args) -> None:
        cocotb.log.info(f"CHK-6AGENT-{name}: {line}", *args)
        self.chk_seen.append(name)

    def _resolve_env(self):
        """The env this sequence runs in.

        ``smc_6agent_observability_test`` starts this sequence directly (it
        supplies per-agent dispatchers instead of going through
        ``smc_base_test.start_seq``), so ``self.env`` may be unset. Walk up from
        the sequencer -- a passive read of the UVM component tree, no DUT
        access.
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
            f"{self.sequencer}; the per-type composition gate needs the "
            f"scoreboard"
        )

    async def body(self) -> None:
        env = self._resolve_env()
        before = {name: getattr(env.scoreboard, name) for name in self.EXPECTED_SAMPLES}

        r = SmcResetItem("reset")
        r.op = SmcResetOp.SAMPLE
        await self.dispatch_reset(r)
        assert r.resolvable, f"reset sample is X/Z: {r}"
        for field in RESET_SAMPLE_FIELDS:
            got = getattr(r, field)
            assert got == 1, f"reset {field} = {got}, expected 1 (released) post bring-up ({r})"
        self._chk(
            "RESET", "all %d reset observables read 1 (released): %s", len(RESET_SAMPLE_FIELDS), r
        )

        i = SmcI2cItem("i2c")
        i.op = SmcI2cOp.SAMPLE
        await self.dispatch_i2c(i)
        assert i.resolvable, f"I2C sample is X/Z: {i}"
        assert i.cg_en == 0, f"tb_i2c_cg_en = {i.cg_en}, expected 0 ({i})"
        self._chk("I2C", "tb_i2c_cg_en == 0 on a resolved sample: %s", i)

        ir = SmcIrqItem("irq")
        ir.op = SmcIrqOp.SAMPLE
        await self.dispatch_irq(ir)
        assert ir.resolvable, f"IRQ sample is X/Z: {ir}"
        for field in IRQ_SAMPLE_FIELDS:
            got = getattr(ir, field)
            assert got == 0, (
                f"tb_{field} = {got}, expected 0 with no interrupt source driven ({ir})"
            )
        # Idle-zero legs backed in *this* run: the three aggregates' positive
        # controls are declared by this testcase's own
        # `probe_positive_controls` (tests:22-29 -- `sync_irq`, `uart_irq_any`,
        # `gpio_irq_any`), each drives the probe's real producer, requires it
        # observed at 1 inside a bounded window and back at 0, and credits the
        # passive liveness ledger the scoreboard consults, so the scoreboard
        # exact-compares all three legs instead of booking them OBSERVED-ONLY
        # ([NEGATIVE-NEEDS-POSITIVE-CONTROL]). No cross-testcase delegation.
        self._chk(
            "IRQ",
            "%s all read 0 with no interrupt source driven: %s",
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
        # wrap 0 as TX: exactly one new output-enable bit, its value following
        # the register high then low, then a bit-for-bit restore) and credits
        # `gpio_core2pad_vec` / `gpio_core2pad_en_vec`, so the compare below is
        # booked as checked evidence rather than OBSERVED-ONLY. With the control
        # restored and this scenario touching no GPIO CSR and no pad, the two
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
                f"control already restored and no GPIO CSR programming or pad "
                f"drive in this scenario: reference={g_ref} sample={g}"
            )
        for probe in ("gpio_core2pad_en_vec",):
            assert probe_alive(probe), (
                f"GPIO pad-bus leg has no same-run liveness credit for {probe} "
                f"({probe_evidence(probe)}), so the scoreboard books the "
                f"vector compare OBSERVED-ONLY instead of checked evidence"
            )
        self._chk(
            "GPIO",
            "pad-bus vectors %s exact-compared by the scoreboard against the "
            "reference sample %d clk_ref_i cycles later, both probes carrying a "
            "same-run liveness credit (%s); tb_gpio_*_any aggregates "
            "OBSERVED-ONLY: %s",
            ", ".join(f"tb_{f}=0x{getattr(g_ref, f):x}" for f in GPIO_STABLE_VECTOR_FIELDS),
            self.GPIO_GAP_REF_CYCLES,
            probe_evidence("gpio_core2pad_en_vec"),
            g,
        )

        a = SmcAxilItem("axil")
        a.op = SmcAxilOp.SAMPLE
        await self.dispatch_axil(a)
        assert a.resolvable, f"AXIL sample is X/Z: {a}"
        # Only the backable probes are exact-compared. `dtp_csr_active` can have
        # no positive control in this TB (tb_top ties `axil_dtp_csr_resp = '0'`),
        # so comparing it would be an unbacked negative check
        # ([NEGATIVE-NEEDS-POSITIVE-CONTROL]); its value is reported
        # OBSERVED-ONLY, exactly as the scoreboard books it. The others carry
        # same-run liveness credits from this test's declared
        # `probe_positive_controls`.
        for field in AXIL_CHECKABLE_FIELDS:
            got = getattr(a, field)
            assert got == 0, (
                f"tb_axil_{field} = {got}, expected 0 (no AXI-Lite master "
                f"traffic is driven in this scenario) ({a})"
            )
        self._chk(
            "AXIL",
            "%s all read 0 [OBSERVED-ONLY, NOT checked evidence: %s]: %s",
            "/".join(f"tb_axil_{f}" for f in AXIL_CHECKABLE_FIELDS),
            ", ".join(f"tb_axil_{f}={getattr(a, f)}" for f in AXIL_UNBACKABLE_FIELDS),
            a,
        )

        c = SmcClkItem("clk")
        c.op = SmcClkOp.COUNT_EDGES
        c.window_ref_cycles = 25
        await self.dispatch_clk(c)
        assert c.gated_probe_resolvable, f"{c.gated_cg_en_probe} is not resolvable: {c}"
        self._chk(
            "CLK",
            "COUNT_EDGES window passed its scoreboard legs (SETUP ref=%d smc=%d "
            "periph=%d; DUT %s=%d edges with %s=%d): %s",
            c.ref_rising_edges,
            c.smc_rising_edges,
            c.periph_rising_edges,
            c.gated_clk_probe,
            c.gated_clk_rising_edges,
            c.gated_cg_en_probe,
            c.gated_cg_en,
            c,
        )

        # Per-type composition gate: each of the six item types must have
        # reached the type-dispatched scoreboard exactly as many times as this
        # body dispatched it. The counters are incremented on the analysis path,
        # so a mis-bound agent, a dropped type or an unpublished item fails --
        # unlike the ordered `chk_seen` list, which this body appends itself and
        # which therefore could not fail on any RTL ([NO-ALWAYS-PASS-CHECKER]).
        # The scoreboard's own check_phase only requires a non-zero total, which
        # a missing type would satisfy.
        sb = env.scoreboard
        observed = {name: getattr(sb, name) - before[name] for name in self.EXPECTED_SAMPLES}
        assert observed == self.EXPECTED_SAMPLES, (
            f"6-agent composition mismatch: scoreboard booked {observed}, "
            f"expected {self.EXPECTED_SAMPLES}"
        )
        cocotb.log.info(
            "CHK-6AGENT-COMPOSITION: all six item types reached the "
            "type-dispatched scoreboard with the exact counts this sequence "
            "dispatched: %s (legs that ran, record only: %s)",
            observed,
            self.chk_seen,
        )
