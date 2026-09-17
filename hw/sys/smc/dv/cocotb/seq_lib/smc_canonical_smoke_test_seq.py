# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Canonical high-density SMC smoke sequence.

This sequence combines the six-agent observability smoke with the reset recovery
matrix so one canonical test covers the public smoke surface.

Synchronization contract: no step waits a magic number of ``clk_ref_i`` cycles
and then samples. Every one is a bounded poll on the real reset observables via
``SmcResetOp.WAIT_STATE`` -- the driver polls until the exact
expected state appears and the scoreboard converts bound expiry into a testcase
failure with the last observed state (`[NO-BLIND-DELAY-SYNC]`,
`[TIMEOUT-MUST-FAIL]`). Mid-window ``RAW_SAMPLE`` snapshots carry the exact
asserted expectation they are taken for, so they are checked evidence instead of
observations (`[EXACT-EXPECTATION]`). The remaining fixed ``ClockCycles`` are
*driven stimulus widths* (how long a pin is held low), which is the quantity the
sequence owns, never a stand-in for a completion handshake.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from env.smc_axil_item import AXIL_UNBACKABLE_FIELDS, SmcAxilItem, SmcAxilOp
from env.smc_clk_item import SmcClkItem, SmcClkOp
from env.smc_gpio_item import SmcGpioItem, SmcGpioOp
from env.smc_i2c_item import SmcI2cItem, SmcI2cOp
from env.smc_irq_item import SmcIrqItem, SmcIrqOp
from env.smc_probe_liveness import (
    UNBACKABLE_PROBES,
    probe_alive,
    probe_evidence,
)
from env.smc_reset_item import (
    RESET_SAMPLE_FIELDS,
    SmcResetItem,
    SmcResetOp,
)

from .smc_base_test_seq import smc_base_test_seq
from .smc_probe_positive_control import ensure_gpio_pad_bus_control

# Exact state each stimulus must drive the observables to. Active-low resets:
# 0 = asserted, 1 = released.
_POWERGOOD_ASSERTED = {"powergood_stable": 0}
_PRIMARY_ASSERTED = {
    "rst_primary_ref_clk_n": 0,
    "rst_primary_smc_clk_n": 0,
}
_ALL_RELEASED = {field: 1 for field in RESET_SAMPLE_FIELDS}


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


class smc_canonical_smoke_test_seq(smc_base_test_seq):
    """Exercise all public smoke agents across reset recovery events."""

    # Idle-zero probes on this scenario's proof path that must carry a same-run
    # liveness credit before their `== 0` compares count as evidence. The
    # matching controls are declared by `smc_canonical_smoke_test`
    # (`probe_positive_controls`) and run before this sequence
    # ([NEGATIVE-NEEDS-POSITIVE-CONTROL]).
    REQUIRED_LIVE_PROBES = (
        "gpio_core2pad_en_vec",
        "sync_irq",
        "uart_irq_any",
        "gpio_irq_any",
        "i2c_cg_en",
        "axil_external_active",
        "axil_efuse_bank_active",
        "axil_any_master_active",
    )

    # Per-type item / check counts the body dispatches across the four sweeps and
    # three reset events. Compared against the scoreboard's typed counters, which
    # are incremented on the analysis path.
    EXPECTED_COUNTS = {
        "reset_samples_seen": 4,
        "i2c_samples_seen": 4,
        "irq_samples_seen": 4,
        "gpio_samples_seen": 8,  # 4 sweeps x (reference + exact-compared)
        "axil_samples_seen": 4,
        "clk_samples_seen": 4,
        "reset_raw_checks_seen": 3,
        "reset_wait_checks_seen": 6,
    }

    # Gap between each sweep's GPIO reference sample and the sample that
    # carries it as `expect_*`. Long enough for a spurious pad-bus change to be
    # visible; the sweep drives nothing onto the pad bus across it.
    GPIO_GAP_REF_CYCLES = 40

    # --- driven stimulus widths (clk_ref_i cycles the pin is held) ---
    POWERGOOD_GLITCH_REF_CYCLES = 8
    COLD_REASSERT_REF_CYCLES = 40
    COOL_ASSERT_REF_CYCLES = 80
    # --- observation bounds (expiry is a failure, never a settle delay) ---
    ASSERT_BOUND_REF_CYCLES = 200
    # Covers the whole reset-recovery chain; this is the upper bound of a poll,
    # not a fixed wait.
    RELEASE_BOUND_REF_CYCLES = 2000

    def __init__(self, name: str = "smc_canonical_smoke_test_seq") -> None:
        super().__init__(name)
        self.dispatch_reset = None
        self.dispatch_i2c = None
        self.dispatch_clk = None
        self.dispatch_irq = None
        self.dispatch_gpio = None
        self.dispatch_axil = None
        self.multi_agent_samples = 0
        self.gpio_compared_sweeps = 0
        self.raw_reset_checks = 0
        self.wait_state_checks = 0

    async def _reset(self, op: SmcResetOp) -> SmcResetItem:
        item = SmcResetItem(op.value.lower())
        item.op = op
        await self.dispatch_reset(item)
        return item

    async def _wait_state(self, label: str, bound: int, **expects: int) -> SmcResetItem:
        """Bounded poll until the exact reset state in ``expects`` is observed."""
        item = SmcResetItem(label)
        item.op = SmcResetOp.WAIT_STATE
        item.timeout_ref_cycles = bound
        for field, value in expects.items():
            setattr(item, "expect_" + field, value)
        await self.dispatch_reset(item)
        # The scoreboard owns the verdict (it raises on expiry with the last
        # observed state); restated here so the sequence cannot walk past one.
        assert not item.timed_out, (
            f"TIMEOUT {label}: {expects} never observed within {bound} "
            f"clk_ref_i cycles; last observed {item}"
        )
        self.wait_state_checks += 1
        cocotb.log.info(
            "CHK-RESET-WAIT-%s: %s observed after %d clk_ref_i cycles (bound %d, expiry fails): %s",
            label.upper(),
            expects,
            item.wait_ref_cycles,
            bound,
            item,
        )
        return item

    async def _raw_check(self, label: str, **expects: int) -> SmcResetItem:
        """Mid-window RAW_SAMPLE that carries its exact expected state."""
        item = SmcResetItem(label)
        item.op = SmcResetOp.RAW_SAMPLE
        for field, value in expects.items():
            setattr(item, "expect_" + field, value)
        await self.dispatch_reset(item)
        assert item.resolvable, f"{label}: RAW_SAMPLE is X/Z: {item}"
        for field, value in expects.items():
            got = getattr(item, field)
            assert got == value, (
                f"{label}: {field} = {got}, expected {value} inside the driven "
                f"assert window ({item})"
            )
        self.raw_reset_checks += 1
        return item

    async def _hold_remaining(self, width: int, already: int) -> None:
        """Hold the pin for the rest of the intended stimulus width."""
        remaining = width - max(already, 0)
        if remaining > 0:
            await ClockCycles(cocotb.top.clk_ref_i, remaining)

    async def _sample_all(self, label: str) -> None:
        reset = SmcResetItem(f"{label}_reset")
        reset.op = SmcResetOp.SAMPLE
        await self.dispatch_reset(reset)

        i2c = SmcI2cItem(f"{label}_i2c")
        i2c.op = SmcI2cOp.SAMPLE
        await self.dispatch_i2c(i2c)

        irq = SmcIrqItem(f"{label}_irq")
        irq.op = SmcIrqOp.SAMPLE
        await self.dispatch_irq(irq)

        # GPIO: a *pair* of SAMPLEs per sweep, and the compare is on the raw
        # pad-bus vectors -- not on the three tb_gpio_*_any aggregates.
        #
        # The aggregates are OR-reductions over the WHOLE pad bus (tb_top.sv
        # :1375-1377), which also carries idle-high LSIO pads (UART TX): they read
        # 1 from reset onward and no frontdoor stimulus can drive them to 0, so
        # they are declared in `env.smc_probe_liveness.UNBACKABLE_PROBES` and
        # `SmcScoreboard._check_gpio` REFUSES a stated `expect_` on them. With no
        # expectation the only gate would be `assert item.resolvable`, which
        # cannot be False on a 2-state simulator (Verilator).
        #
        # `tb_core2pad_o` / `tb_core2pad_en_o` DO move under real frontdoor GPIO
        # CSR programming, so an expectation on them is backable; `body()` runs
        # the pad-bus positive control once (crediting `gpio_core2pad_vec` /
        # `gpio_core2pad_en_vec` for the whole run) and restores the bus
        # bit-for-bit. Within a sweep this sequence programs no GPIO CSR and
        # drives no pad, and every sweep starts from a quiescent point (after a
        # bounded `_ALL_RELEASED` handshake), so the vectors cannot move across
        # the gap ([EXACT-EXPECTATION] / [NEGATIVE-NEEDS-POSITIVE-CONTROL]).
        gpio_ref = SmcGpioItem(f"{label}_gpio_ref")
        gpio_ref.op = SmcGpioOp.SAMPLE
        await self.dispatch_gpio(gpio_ref)
        assert gpio_ref.resolvable, f"{label}: GPIO reference sample is X/Z: {gpio_ref}"
        assert gpio_ref.vec_width > 0, (
            f"{label}: GPIO reference sample carries no pad-bus vector "
            f"(tb_core2pad_o / tb_core2pad_en_o mirror missing), so this sweep "
            f"would have no backable GPIO observable: {gpio_ref}"
        )
        await ClockCycles(cocotb.top.clk_ref_i, self.GPIO_GAP_REF_CYCLES)
        gpio = SmcGpioItem(f"{label}_gpio")
        gpio.op = SmcGpioOp.SAMPLE
        for field in GPIO_STABLE_VECTOR_FIELDS:
            setattr(gpio, "expect_" + field, getattr(gpio_ref, field))
        await self.dispatch_gpio(gpio)
        for field in GPIO_STABLE_VECTOR_FIELDS:
            exp = getattr(gpio_ref, field)
            got = getattr(gpio, field)
            assert got == exp, (
                f"{label}: GPIO {field} changed between the sweep's reference "
                f"sample and its checked sample (0x{exp:x} -> 0x{got:x}) over "
                f"{self.GPIO_GAP_REF_CYCLES} clk_ref_i cycles, with the pad-bus "
                f"control already restored and no GPIO CSR programming or pad "
                f"drive in this sweep: reference={gpio_ref} sample={gpio}"
            )
        self.gpio_compared_sweeps += 1

        axil = SmcAxilItem(f"{label}_axil")
        axil.op = SmcAxilOp.SAMPLE
        await self.dispatch_axil(axil)

        clk = SmcClkItem(f"{label}_clk")
        clk.op = SmcClkOp.COUNT_EDGES
        clk.window_ref_cycles = 25
        await self.dispatch_clk(clk)

        self.multi_agent_samples += 1

    def _resolve_env(self):
        """The env this sequence runs in (the test starts it directly)."""
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

    async def body(self) -> None:
        env = self._resolve_env()
        before = {name: getattr(env.scoreboard, name) for name in self.EXPECTED_COUNTS}

        # Pad-bus positive control once for the whole run: it credits
        # `gpio_core2pad_vec` / `gpio_core2pad_en_vec` in the liveness ledger and
        # restores both vectors bit-for-bit, which is what makes every sweep's
        # GPIO vector compare checked evidence instead of OBSERVED-ONLY. Run
        # before the baseline sweep so no sweep straddles it.
        self.env = env
        await ensure_gpio_pad_bus_control(self)

        await self._sample_all("baseline")

        # --- powergood glitch -------------------------------------------------
        await self._reset(SmcResetOp.POWERGOOD_LO)
        pg = await self._wait_state(
            "pg_asserted", self.ASSERT_BOUND_REF_CYCLES, **_POWERGOOD_ASSERTED
        )
        await self._hold_remaining(self.POWERGOOD_GLITCH_REF_CYCLES, pg.wait_ref_cycles)
        await self._raw_check("pg_mid_window", **_POWERGOOD_ASSERTED)
        await self._reset(SmcResetOp.POWERGOOD_HI)
        await self._wait_state("pg_released", self.RELEASE_BOUND_REF_CYCLES, **_ALL_RELEASED)
        await self._sample_all("after_powergood")

        # --- cold reset re-assert --------------------------------------------
        await self._reset(SmcResetOp.COLD_RST_LO)
        cold = await self._wait_state(
            "cold_primary_asserted",
            self.ASSERT_BOUND_REF_CYCLES,
            **_PRIMARY_ASSERTED,
        )
        await self._hold_remaining(self.COLD_REASSERT_REF_CYCLES, cold.wait_ref_cycles)
        await self._raw_check("cold_mid_window", **_PRIMARY_ASSERTED)
        await self._reset(SmcResetOp.COLD_RST_HI)
        await self._wait_state("cold_released", self.RELEASE_BOUND_REF_CYCLES, **_ALL_RELEASED)
        await self._sample_all("after_cold")

        # --- cool reset ------------------------------------------------------
        await self._reset(SmcResetOp.COOL_RST_LO)
        cool = await self._wait_state(
            "cool_primary_asserted",
            self.ASSERT_BOUND_REF_CYCLES,
            **_PRIMARY_ASSERTED,
        )
        await self._hold_remaining(self.COOL_ASSERT_REF_CYCLES, cool.wait_ref_cycles)
        await self._raw_check("cool_mid_window", **_PRIMARY_ASSERTED)
        await self._reset(SmcResetOp.COOL_RST_HI)
        await self._wait_state("cool_released", self.RELEASE_BOUND_REF_CYCLES, **_ALL_RELEASED)
        await self._sample_all("after_cool")

        assert self.multi_agent_samples == 4, "expected baseline plus 3 recovery sweeps"
        assert self.gpio_compared_sweeps == self.multi_agent_samples, (
            f"expected one exact-compared GPIO pair per sweep, got "
            f"{self.gpio_compared_sweeps} for {self.multi_agent_samples} sweeps"
        )
        assert self.wait_state_checks == 6, (
            f"expected 6 bounded reset handshakes (3 assert + 3 release), got "
            f"{self.wait_state_checks}"
        )
        assert self.raw_reset_checks == 3, (
            f"expected 3 mid-window RAW_SAMPLE checks (powergood/cold/cool), "
            f"got {self.raw_reset_checks}"
        )

        # Composition: every item type reached the type-dispatched scoreboard
        # exactly as many times as this body dispatched it. The sequence-local
        # counters above are its own bookkeeping; these come from the analysis
        # path, so a mis-bound agent or a dropped type fails.
        sb = env.scoreboard
        observed = {name: getattr(sb, name) - before[name] for name in self.EXPECTED_COUNTS}
        assert observed == self.EXPECTED_COUNTS, (
            f"canonical-smoke composition mismatch: scoreboard booked "
            f"{observed}, expected {self.EXPECTED_COUNTS}"
        )

        # The idle-zero legs this scenario books are evidence only where the
        # same probe was observed at 1 in this run. Assert the credits exist
        # (the controls the test declares must actually have run and been seen
        # by the passive ledger), and state plainly which field is not checked
        # evidence at all ([NEGATIVE-NEEDS-POSITIVE-CONTROL]).
        dead = [p for p in self.REQUIRED_LIVE_PROBES if not probe_alive(p)]
        assert not dead, (
            f"idle-zero legs without a same-run positive control: {dead} -- "
            f"declare them in smc_canonical_smoke_test.probe_positive_controls "
            f"({[probe_evidence(p) for p in dead]})"
        )
        unbackable = ", ".join(
            f"tb_axil_{f} ({UNBACKABLE_PROBES['axil_' + f]})" for f in AXIL_UNBACKABLE_FIELDS
        )
        # Which agents contributed a *compared expectation*, not merely a booked
        # item: reset (five post-release observables exact-compared by the
        # scoreboard), i2c / irq / axil (idle legs exact-compared because this
        # run holds the liveness credits asserted above), gpio (the per-sweep
        # cross-sample `expect_*` pair added here) and clk (COUNT_EDGES window
        # legs). Reported explicitly so the summary line states the strength of
        # the sweep instead of only its item count ([EXACT-EXPECTATION]).
        compared_agents = ("reset", "i2c", "irq", "gpio", "axil", "clk")
        cocotb.log.info(
            "CHK-CANONICAL-SMOKE: %d sweeps in which all %d agents (%s) "
            "contributed a compared expectation -- GPIO via %d exact-compared "
            "tb_core2pad_en_o cross-sample pairs (%d clk_ref_i apart, pad-bus "
            "probe credited this run), the rest via scoreboard value legs; "
            "plus %d bounded reset-state handshakes and %d "
            "expectation-carrying mid-window RAW checks, all passed (no "
            "fixed-delay synchronization on the proof path); scoreboard-booked "
            "per type %s; %d idle probes carry a same-run liveness credit (%s), "
            "and %d idle_legs were exact-compared vs %d booked OBSERVED-ONLY. "
            "NOT checked evidence: %s",
            self.multi_agent_samples,
            len(compared_agents),
            "/".join(compared_agents),
            self.gpio_compared_sweeps,
            self.GPIO_GAP_REF_CYCLES,
            self.wait_state_checks,
            self.raw_reset_checks,
            observed,
            len(self.REQUIRED_LIVE_PROBES),
            ", ".join(self.REQUIRED_LIVE_PROBES),
            sb.idle_legs_checked,
            sb.idle_legs_observed_only,
            unbackable,
        )
