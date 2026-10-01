# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS scoreboard."""

from __future__ import annotations

from pyuvm import ConfigDB, uvm_subscriber

from .smc_axil_item import AXIL_SAMPLE_FIELDS, SmcAxilItem, SmcAxilOp
from .smc_clk_item import SmcClkItem, SmcClkOp
from .smc_gpio_item import (
    GPIO_FIELD_PROBES,
    GPIO_FIELD_SIGNALS,
    GPIO_SAMPLE_FIELDS,
    GPIO_VECTOR_FIELDS,
    SmcGpioItem,
    SmcGpioOp,
)
from .smc_i2c_item import SmcI2cItem, SmcI2cOp
from .smc_irq_item import IRQ_SAMPLE_FIELDS, SmcIrqItem, SmcIrqOp
from .smc_memory_model import SmcMemoryModel
from .smc_probe_liveness import (
    UNBACKABLE_PROBES,
    alive_probes,
    probe_alive,
    probe_evidence,
    refuse_expectation_on_unbackable,
)
from .smc_protocol_vip_item import SmcProtocolVipItem
from .smc_reset_item import (
    RESET_POST_STABLE_FIELDS,
    RESET_SAMPLE_FIELDS,
    SmcResetItem,
    SmcResetOp,
)
from .smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp


class SmcScoreboard(uvm_subscriber):
    def build_phase(self) -> None:
        self.i2c_samples_seen = 0
        self.reset_samples_seen = 0
        self.clk_samples_seen = 0
        self.irq_samples_seen = 0
        self.gpio_samples_seen = 0
        self.axil_samples_seen = 0
        self.sys_axi_checks_seen = 0
        self.sys_axi_value_checks_seen = 0
        # MEASURED per-bus tally of AXI accesses that actually completed (the
        # driver stamps `item.bus_name`; a timed-out access is not counted
        # because nothing was performed). This is the observed left-hand side of
        # the protocol-VIP fabric-access floor -- see
        # smc_base_test.record_protocol_vip, which reads it here instead of
        # letting a call site pass the floor constant as its own observation
        # ([NO-ALWAYS-PASS-CHECKER]).
        self.axi_accesses_by_bus: dict[str, int] = {}
        self.memory_model_updates_seen = 0
        self.memory_model_checks_seen = 0
        self.protocol_vip_checks_seen = 0
        self.action_items_seen = 0
        # RAW_SAMPLE / WAIT_STATE bookkeeping. `*_observations_seen` counts
        # snapshots with no expectation set: they are diagnostics, NOT checks,
        # and are reported separately so a retained log cannot present them as
        # checked evidence.
        self.reset_raw_checks_seen = 0
        self.reset_raw_observations_seen = 0
        self.reset_wait_checks_seen = 0
        # TB clock-generator liveness (SETUP self-check, never DUT proof).
        self.clk_setup_checks_seen = 0
        # DUT-generated gated-clock legs that carried a real expectation.
        self.clk_dut_checks_seen = 0
        self.protocol_vip_auto_stamps_seen = 0
        # Idle-zero ("negative") legs on tb_top observability probes, split into
        # exactly two categories and nothing else:
        #
        #   checked       -- the same probe was observed at 1 somewhere in this
        #                    run (env.smc_probe_liveness ledger), so the == 0
        #                    compare distinguishes quiet from dead and IS run.
        #   OBSERVED-ONLY -- the probe was never seen at 1 in this run, so the
        #                    value is logged as a diagnostic and is explicitly
        #                    NOT presented as checked evidence.
        #
        # A leg whose probe is not yet credited when the item arrives is parked
        # here and resolved in check_phase, so a positive control that runs
        # later in the same test still upgrades the leg to a real compare
        # instead of it being silently dropped.
        self.idle_legs_checked = 0
        self.idle_legs_observed_only = 0
        self._pending_idle_legs: list[tuple[str, str, int, int, str]] = []
        # probe -> how many idle legs were skipped because no control can exist.
        self._unbackable_idle_legs: dict[str, int] = {}
        # TB-local golden only — never a DUT hierarchy backdoor (U1-3).
        self.memory_model: SmcMemoryModel | None = None
        try:
            cfg = ConfigDB().get(self, "", "cfg")
            self.memory_model = getattr(cfg, "memory_model", None)
        except Exception:
            self.memory_model = None
        self.events: dict[str, set] = {
            "reset_op": set(),
            "reset_state": set(),
            # Mid-window snapshots that carried no expectation. Kept out of
            # `reset_state` so a coverage roll-up cannot credit an unchecked
            # observation as proven reset state.
            "reset_raw_observed": set(),
            "i2c_state": set(),
            # TB-driven input clocks -- SETUP bin, not DUT coverage.
            "clk_bucket": set(),
            "dut_gated_clk": set(),
            "irq_state": set(),
            "gpio_state": set(),
            "axil_master": set(),
            "sys_axi": set(),
            "protocol_vip": set(),
            # Auto stamps from smc_base_test.run_phase: activity record only.
            "protocol_vip_auto": set(),
            "memory_model": set(),
        }

    def _cov(self, bin_name: str, value) -> None:
        self.events[bin_name].add(value)
        self.logger.info("FUNC_COV_VALUE bin=%s value=%s", bin_name, value)

    # ------------------------------------------------------- idle-leg policy --
    def _idle_leg(self, probe: str, label: str, got: int, exp: int, item) -> str:
        """Book one idle/negative leg on a tb_top observability probe.

        Returns ``"checked"`` when the leg was exact-compared here (its probe
        already carries a same-run liveness credit), ``"pending"`` when the
        compare is deferred to ``check_phase`` (a positive control may still run
        later in this test), or ``"unbackable"`` when no control can exist in
        this TB. Every leg ends up in exactly one of two final categories --
        checked, or OBSERVED-ONLY and declared as such in the kept log
        ([NEGATIVE-NEEDS-POSITIVE-CONTROL]).
        """
        if probe in UNBACKABLE_PROBES:
            # No frontdoor stimulus can make this probe read 1 in this TB, so an
            # exact compare on it would be an unbacked negative check forever.
            # It is logged, never asserted, never counted as checked evidence.
            self.idle_legs_observed_only += 1
            self._unbackable_idle_legs[probe] = self._unbackable_idle_legs.get(probe, 0) + 1
            return "unbackable"
        if probe_alive(probe):
            assert got == exp, (
                f"{label} expected {exp}, got {got} ({item}) "
                f"[positive control: {probe_evidence(probe)}]"
            )
            self.idle_legs_checked += 1
            return "checked"
        self._pending_idle_legs.append((probe, label, got, exp, str(item)))
        return "pending"

    def _resolve_pending_idle_legs(self) -> None:
        """End-of-run resolution of every deferred idle leg (see ``_idle_leg``).

        A leg whose probe got credited anywhere in this run is exact-compared
        now -- expiry of the deferral is not an escape hatch. A booked idle
        ``== 0`` leg whose probe was never observed at 1 is an error: there is
        no third outcome between "checked against a same-run control" and
        "declared unbackable". GPIO vector fields with a stated expectation
        are compared inline in ``_check_gpio`` and are not queued here.
        """
        unbacked: dict[str, int] = {}
        for probe, label, got, exp, item_str in self._pending_idle_legs:
            if probe_alive(probe):
                assert got == exp, (
                    f"{label} expected {exp}, got {got} ({item_str}) "
                    f"[resolved at check_phase; positive control: "
                    f"{probe_evidence(probe)}]"
                )
                self.idle_legs_checked += 1
            else:
                unbacked[probe] = unbacked.get(probe, 0) + 1
                self.idle_legs_observed_only += 1
        self._pending_idle_legs = []
        for probe, count in sorted(self._unbackable_idle_legs.items()):
            self.logger.info(
                "Scoreboard idle leg OBSERVED-ONLY -- NOT checked evidence: "
                "%s sampled %d time(s) and never compared. No positive control "
                "for it can exist in this TB (%s), so its idle value is a "
                "diagnostic only and must not be presented as closure "
                "evidence.",
                probe,
                count,
                UNBACKABLE_PROBES[probe],
            )
        # A probe that is neither credited nor declared unbackable leaves this
        # testcase's idle legs uncompared. There are two legitimate outcomes for
        # an idle leg -- it is checked against a same-run control, or the probe
        # is declared unbackable -- and silently dropping the compare is not a
        # third one. A `tb_top.sv` assign orphaned by an RTL rename reaches this
        # branch, and reporting it at `info` would remove checks from the
        # regression while it stays green.
        if unbacked:
            detail = "; ".join(
                f"{probe}: {count} leg(s) sampled, {probe_evidence(probe)}"
                for probe, count in sorted(unbacked.items())
            )
            raise AssertionError(
                f"idle legs were booked on {len(unbacked)} probe(s) that no "
                f"positive control credited in this run, so their compares did "
                f"not happen: {detail}. Run the control via "
                f"smc_base_test.probe_positive_controls, or declare the probe "
                f"in smc_probe_liveness.UNBACKABLE_PROBES with the reason no "
                f"control can exist."
            )

    def write(self, item) -> None:
        if isinstance(item, SmcI2cItem):
            self._check_i2c(item)
        elif isinstance(item, SmcResetItem):
            self._check_reset(item)
        elif isinstance(item, SmcClkItem):
            self._check_clk(item)
        elif isinstance(item, SmcIrqItem):
            self._check_irq(item)
        elif isinstance(item, SmcGpioItem):
            self._check_gpio(item)
        elif isinstance(item, SmcAxilItem):
            self._check_axil(item)
        elif isinstance(item, SmcSysAxiItem):
            self._check_sys_axi(item)
        elif isinstance(item, SmcProtocolVipItem):
            self._check_protocol_vip(item)
        else:
            # An item the scoreboard has no branch for is a checker that did not
            # run, not a diagnostic.
            raise AssertionError(
                f"SmcScoreboard received {type(item).__name__}, which it has no "
                f"check for: whatever that item was evidence of went unchecked"
            )

    def _check_i2c(self, item):
        if item.op is not SmcI2cOp.SAMPLE:
            return
        self.i2c_samples_seen += 1
        assert item.resolvable, f"I2C not resolvable: {item}"
        checked = ["resolvable"]
        observed_only = []
        # cg_en. A sequence that has programmed the gate on states
        # expect_cg_en=1 and always gets an exact compare -- that is a stated
        # positive expectation, not an idle claim. With no expectation the leg is
        # the idle contract cg_en == 0, which alone cannot distinguish
        # gated-quiet from a stuck-at-0 / mis-bound probe, so it is compared only
        # when this run has a liveness credit for tb_i2c_cg_en. The control that
        # produces one is
        # seq_lib.smc_probe_positive_control.prove_i2c_cg_en_probe (declare it
        # via smc_base_test.probe_positive_controls = ("i2c_cg_en",)).
        if item.expect_cg_en is not None:
            assert item.cg_en == item.expect_cg_en, (
                f"tb_i2c_cg_en expected {item.expect_cg_en}, got {item.cg_en} ({item})"
            )
            checked.append("cg_en")
        else:
            verdict = self._idle_leg("i2c_cg_en", "tb_i2c_cg_en", item.cg_en, 0, item)
            if verdict == "checked":
                checked.append("cg_en")
            else:
                observed_only.append(f"cg_en({verdict})")
        # debug_lo has no SPEC/RDL-sourced reset value in this environment, so
        # it is compared only when the sequence supplies one. With no
        # expectation it stays OBSERVED-ONLY and the log says so, rather than
        # letting a reprinted-but-uncompared field read as checked evidence.
        if item.expect_debug_lo is not None:
            assert item.debug_lo == item.expect_debug_lo, (
                f"tb_i2c_debug_lo expected 0x{item.expect_debug_lo:x}, "
                f"got 0x{item.debug_lo & 0xF:x} ({item})"
            )
            checked.append("debug_lo")
        else:
            observed_only.append("debug_lo")
        self.logger.info(
            "Scoreboard I2C sample #%d: %s [checked: %s | OBSERVED-ONLY (NOT "
            "checked evidence): %s]",
            self.i2c_samples_seen,
            item,
            ", ".join(checked),
            ", ".join(observed_only) or "-",
        )
        self._cov("i2c_state", (int(item.resolvable), int(item.cg_en)))

    # ---------------------------------------------------------------- reset --
    def _assert_reset_expectations(self, item, exps) -> None:
        for field, exp in exps:
            got = getattr(item, field)
            assert got == exp, f"reset {field} = {got}, expected {exp} ({item})"
        if item.expect_left_stable:
            assert not all(getattr(item, f) == 1 for f in RESET_POST_STABLE_FIELDS), (
                "expect_left_stable: DUT is still fully post-stable "
                f"({', '.join(RESET_POST_STABLE_FIELDS)} all released) inside the "
                f"driven assert/glitch window -- the stimulus produced no "
                f"observable effect: {item}"
            )

    def _reset_cov_tuple(self, item):
        return tuple(getattr(item, f) for f in RESET_SAMPLE_FIELDS)

    def _check_reset(self, item):
        self._cov("reset_op", item.op.name)
        if item.op is SmcResetOp.RAW_SAMPLE:
            self._check_reset_raw(item)
            return
        if item.op is SmcResetOp.WAIT_STATE:
            self._check_reset_wait(item)
            return
        if item.op is not SmcResetOp.SAMPLE:
            self.action_items_seen += 1
            return
        self.reset_samples_seen += 1
        assert item.resolvable, f"reset not resolvable: {item}"
        # Post-release invariant: every one of the five sampled observables has
        # a fail-capable compare (rst_wdt_smc_clk_n included -- it is sampled
        # and logged, so leaving it uncompared would hide a stuck WDT reset;
        # [EXACT-EXPECTATION]). A sequence may override any single leg via
        # expect_<field> when its own contract says otherwise.
        for field in RESET_SAMPLE_FIELDS:
            exp = getattr(item, "expect_" + field)
            exp = 1 if exp is None else exp
            got = getattr(item, field)
            assert got == exp, f"reset {field} = {got}, expected {exp} post-release ({item})"
        self._assert_reset_expectations(item, [])
        self.logger.info(
            "Scoreboard reset sample #%d: %s [checked: resolvable + all %d reset observables]",
            self.reset_samples_seen,
            item,
            len(RESET_SAMPLE_FIELDS),
        )
        self._cov("reset_state", self._reset_cov_tuple(item))

    def _check_reset_raw(self, item):
        """Mid-window snapshot: no post-release invariant applies.

        A RAW_SAMPLE taken during a glitch/assert window has no state the
        scoreboard can assert on its own, so it is a *check* only when the
        sequence states one (`expect_<field>` / `expect_left_stable`). With no
        expectation it is booked and logged as OBSERVED-ONLY in its own
        coverage bin, so neither the log nor the coverage roll-up can present
        it as checked reset evidence ([NO-ALWAYS-PASS-CHECKER]).
        """
        exps = item.expectations()
        if not exps and not item.expect_left_stable:
            self.reset_raw_observations_seen += 1
            self.logger.info(
                "Scoreboard reset RAW observation #%d (OBSERVED-ONLY, no "
                "expectation set -- NOT checked evidence): %s",
                self.reset_raw_observations_seen,
                item,
            )
            self._cov("reset_raw_observed", self._reset_cov_tuple(item))
            return
        self.reset_raw_checks_seen += 1
        assert item.resolvable, (
            f"reset RAW_SAMPLE carries expectations but is not resolvable: {item}"
        )
        self._assert_reset_expectations(item, exps)
        self.logger.info(
            "Scoreboard reset RAW check #%d: %s [checked: %s%s]",
            self.reset_raw_checks_seen,
            item,
            ", ".join(f for f, _ in exps) or "-",
            ", left_stable" if item.expect_left_stable else "",
        )
        self._cov("reset_state", self._reset_cov_tuple(item))

    def _check_reset_wait(self, item):
        """Bounded-wait leg: expiry is a failure, never a silent pass."""
        exps = item.expectations()
        assert exps or item.expect_left_stable, (
            "reset WAIT_STATE dispatched with no expect_* / expect_left_stable: "
            "a wait with nothing to wait for cannot fail and is not evidence"
        )
        self.reset_wait_checks_seen += 1
        assert not item.timed_out, (
            f"reset WAIT_STATE expired after {item.timeout_ref_cycles} clk_ref_i "
            f"cycles waiting for "
            f"{[(f, e) for f, e in exps]} left_stable={item.expect_left_stable}; "
            f"last observed {item}"
        )
        assert item.resolvable, f"reset WAIT_STATE match is not resolvable: {item}"
        self._assert_reset_expectations(item, exps)
        self.logger.info(
            "Scoreboard reset WAIT_STATE check #%d matched after %d ref cycles: %s [checked: %s%s]",
            self.reset_wait_checks_seen,
            item.wait_ref_cycles,
            item,
            ", ".join(f for f, _ in exps) or "-",
            ", left_stable" if item.expect_left_stable else "",
        )
        self._cov("reset_state", self._reset_cov_tuple(item))

    # ------------------------------------------------------------------ clk --
    def _check_clk(self, item):
        if item.op is not SmcClkOp.COUNT_EDGES:
            return
        self.clk_samples_seen += 1
        self.clk_setup_checks_seen += 1
        # SETUP self-check ONLY. clk_ref_i / clk_smc_i / clk_periph_i are DUT
        # inputs driven by cocotb Clock(...) in smc_base_test._bring_up, so
        # these four asserts can only fail on a TB clock-generator / timing-
        # randomization mistake -- never on wrong DUT RTL. They are NOT
        # presented as DUT evidence.
        assert item.ref_rising_edges > 0
        assert item.smc_rising_edges > 0
        assert item.periph_rising_edges > 0
        assert item.smc_rising_edges >= item.ref_rising_edges
        self.logger.info(
            "Scoreboard clk SETUP self-check #%d (TB-driven input clocks -- NOT DUT proof): %s",
            self.clk_setup_checks_seen,
            item,
        )
        self._cov(
            "clk_bucket",
            (
                item.ref_rising_edges // 50,
                item.smc_rising_edges // 50,
                item.periph_rising_edges // 50,
            ),
        )
        self._check_clk_dut_gated(item)

    def _check_clk_dut_gated(self, item):
        """The one clock leg that can fail because of DUT RTL.

        `gated_clk_probe` is a passive tb_top read of a DUT clock-gater output.
        Its post-reset level is configuration-dependent, so there is no
        defensible default expectation -- a sequence that has established a
        known gate state sets `expect_gated_clk_running` / `expect_gated_cg_en`
        and gets a real compare. With neither set the counts stay
        OBSERVED-ONLY.
        """
        if item.gated_clk_rising_edges < 0:
            return
        explicit = item.expect_gated_clk_running is not None or item.expect_gated_cg_en is not None
        if not explicit:
            # Derived contract: with the gate enable deasserted the gater must
            # pass its clock through, so a quiet output is a DUT failure. This
            # is the fail-capable DUT leg of COUNT_EDGES -- the three input-clock
            # counts above are TB-driven and can never fail on RTL. With
            # cg_en == 1 the gate state is activity/hysteresis dependent, so
            # there is nothing to assert and the counts stay OBSERVED-ONLY
            # (smc_zeroer_*_cg_test own the programmed-gate proof).
            if not (
                item.gated_clk_contract and item.gated_probe_resolvable and item.gated_cg_en == 0
            ):
                self.logger.info(
                    "Scoreboard clk DUT gated observation (OBSERVED-ONLY, no "
                    "applicable expectation -- NOT checked evidence): %s=%d %s=%d",
                    item.gated_clk_probe,
                    item.gated_clk_rising_edges,
                    item.gated_cg_en_probe,
                    item.gated_cg_en,
                )
                return
            self.clk_dut_checks_seen += 1
            assert item.gated_clk_rising_edges > 0, (
                f"{item.gated_clk_probe} counted 0 rising edges over "
                f"{item.window_ref_cycles} ref cycles while "
                f"{item.gated_cg_en_probe}=0: a clock gater with its enable "
                f"deasserted must pass the clock through ({item})"
            )
            self.logger.info(
                "Scoreboard clk DUT gated check #%d: %s=%d edges with %s=0 "
                "(gate disabled => must free-run)",
                self.clk_dut_checks_seen,
                item.gated_clk_probe,
                item.gated_clk_rising_edges,
                item.gated_cg_en_probe,
            )
            self._cov("dut_gated_clk", (item.gated_clk_probe, 1, 0))
            return
        self.clk_dut_checks_seen += 1
        assert item.gated_probe_resolvable, f"{item.gated_cg_en_probe} is not resolvable: {item}"
        if item.expect_gated_cg_en is not None:
            assert item.gated_cg_en == item.expect_gated_cg_en, (
                f"{item.gated_cg_en_probe} expected {item.expect_gated_cg_en}, "
                f"got {item.gated_cg_en} ({item})"
            )
        if item.expect_gated_clk_running is True:
            assert item.gated_clk_rising_edges > 0, (
                f"{item.gated_clk_probe} expected to be running but counted 0 "
                f"rising edges over {item.window_ref_cycles} ref cycles ({item})"
            )
        elif item.expect_gated_clk_running is False:
            assert item.gated_clk_rising_edges == 0, (
                f"{item.gated_clk_probe} expected gated off but counted "
                f"{item.gated_clk_rising_edges} rising edges ({item})"
            )
        self.logger.info(
            "Scoreboard clk DUT gated check #%d: %s=%d (expect_running=%s) %s=%d (expect=%s)",
            self.clk_dut_checks_seen,
            item.gated_clk_probe,
            item.gated_clk_rising_edges,
            item.expect_gated_clk_running,
            item.gated_cg_en_probe,
            item.gated_cg_en,
            item.expect_gated_cg_en,
        )
        self._cov(
            "dut_gated_clk",
            (item.gated_clk_probe, int(item.gated_clk_rising_edges > 0), item.gated_cg_en),
        )

    def _check_irq(self, item):
        if item.op is not SmcIrqOp.SAMPLE:
            return
        self.irq_samples_seen += 1
        assert item.resolvable, f"IRQ not resolvable: {item}"
        # A stated expectation (expect_<field>, either level) is always
        # exact-compared: the sequence is claiming a value it established.
        #
        # With no expectation the leg is the idle contract `== 0`, which is a
        # pure negative check -- a stuck-at-0, undriven or mis-bound probe passes
        # it identically to a quiet DUT. Such a leg is compared only when this
        # run carries a liveness credit for the same probe
        # ([NEGATIVE-NEEDS-POSITIVE-CONTROL]); otherwise it is booked
        # OBSERVED-ONLY and the log says so. The controls that produce a credit
        # live in seq_lib.smc_probe_positive_control:
        # prove_sync_irq_probe (SYNC_REG.sync over SEP_IN AXI),
        # prove_uart_irq_any_probe (UART0 IER/ITR) and prove_gpio_irq_any_probe
        # (GPIO0 active-low pad drive); a test enables them with
        # probe_positive_controls = ("sync_irq", "uart_irq_any", "gpio_irq_any").
        checked = ["resolvable"]
        observed_only = []
        for field in IRQ_SAMPLE_FIELDS:
            got = getattr(item, field)
            if getattr(item, "expect_" + field) is not None:
                exp = item.expected(field)
                assert got == exp, f"tb_{field} expected {exp}, got {got} ({item})"
                checked.append(field)
                continue
            verdict = self._idle_leg(field, f"tb_{field}", got, 0, item)
            if verdict == "checked":
                checked.append(field)
            else:
                observed_only.append(f"{field}({verdict})")
        self.logger.info(
            "Scoreboard IRQ sample #%d: %s [checked: %s | OBSERVED-ONLY (NOT "
            "checked evidence): %s]",
            self.irq_samples_seen,
            item,
            ", ".join(checked),
            ", ".join(observed_only) or "-",
        )
        self._cov("irq_state", (int(item.sync_irq), int(item.gpio_irq_any), int(item.uart_irq_any)))

    def _check_gpio(self, item):
        if item.op is not SmcGpioOp.SAMPLE:
            return
        self.gpio_samples_seen += 1
        # Two classes of GPIO observable, and only one of them can carry
        # evidence.
        #
        # (a) The three OR-reduction aggregates (tb_gpio_*_any). tb_top.sv
        #     :1375-1377 ORs the WHOLE pad bus, which also carries idle-high LSIO
        #     pads (UART TX) and default-enabled pad inputs, so all three read 1
        #     from reset onward and NO frontdoor stimulus can drive any of them to
        #     0. A net tied to constant 1 is therefore indistinguishable from the
        #     real aggregate, and a cross-sample "it did not move" compare passes
        #     identically on a stuck-at-1, undriven or mis-bound net
        #     ([NEGATIVE-NEEDS-POSITIVE-CONTROL]). All three are listed in
        #     env.smc_probe_liveness.UNBACKABLE_PROBES: their value is logged as a
        #     diagnostic, is never counted as checked evidence, and a stated
        #     expect_<field> on one of them is REFUSED here rather than silently
        #     producing an unbacked compare.
        #
        # (b) The raw pad-output bus vectors (tb_core2pad_o / tb_core2pad_en_o).
        #     These MOVE under real frontdoor GPIO CSR programming, so a stated
        #     expectation on them is backable: it is exact-compared here, and
        #     booked as *checked* evidence only when the same run credited the
        #     matching probe via
        #     seq_lib.smc_probe_positive_control.prove_gpio_pad_bus_probe (which
        #     proves a single-bit wrap-0 delta and restores the bus).
        #
        # Resolvability alone is NOT a DUT-sensitive check: under Verilator
        # (2-state) `value.is_resolvable` cannot be False, so
        # `assert item.resolvable` has no FAIL-ON path there. It is a
        # precondition, not this check's contract.
        assert item.resolvable, f"GPIO not resolvable: {item}"
        checked = ["resolvable"]
        observed_only = []
        for field in GPIO_SAMPLE_FIELDS + GPIO_VECTOR_FIELDS:
            probe = GPIO_FIELD_PROBES[field]
            label = GPIO_FIELD_SIGNALS[field]
            exp = getattr(item, "expect_" + field)
            refuse_expectation_on_unbackable(probe, label, exp, "SmcScoreboard._check_gpio")
            if probe in UNBACKABLE_PROBES:
                self.idle_legs_observed_only += 1
                self._unbackable_idle_legs[probe] = self._unbackable_idle_legs.get(probe, 0) + 1
                observed_only.append(f"{field}(unbackable)")
                continue
            if exp is None:
                observed_only.append(f"{field}(no stated expectation)")
                continue
            got = getattr(item, field)
            # Never weakened by the credit: the compare always runs. The credit
            # only decides whether the kept log may present it as checked.
            assert got == exp, (
                f"{label} expected {SmcGpioItem.fmt_vec(exp)}, got "
                f"{SmcGpioItem.fmt_vec(got)} ({item})"
            )
            # Do not book a pending idle leg: the compare already ran. A
            # check_phase raise for "compares did not happen" would be a false
            # diagnostic on a passing vector check, which is worse than leaving
            # the line OBSERVED-ONLY until prove_gpio_pad_bus_probe credits it.
            if probe_alive(probe):
                self.idle_legs_checked += 1
                checked.append(field)
            else:
                observed_only.append(f"{field}(compared; no liveness credit)")
        self.logger.info(
            "Scoreboard GPIO sample #%d: %s [checked: %s | OBSERVED-ONLY (NOT "
            "checked evidence): %s]",
            self.gpio_samples_seen,
            item,
            ", ".join(checked),
            ", ".join(observed_only) or "-",
        )
        self._cov(
            "gpio_state",
            (int(item.core2pad_any), int(item.core2pad_en_any), int(item.pad2core_en_any)),
        )

    def _check_axil(self, item):
        if item.op is not SmcAxilOp.SAMPLE:
            return
        self.axil_samples_seen += 1
        assert item.resolvable, f"AXIL not resolvable: {item}"
        # A stated expectation (expect_<field>, either level) is always
        # exact-compared. With no expectation the leg is the idle contract == 0,
        # a pure negative check that a stuck-at-0 / undriven / mis-tied probe
        # passes identically, so it is compared only when this run carries a
        # liveness credit for the same probe ([NEGATIVE-NEEDS-POSITIVE-CONTROL]).
        #
        # Credits available:
        #   efuse_bank_active   -- smc_efuse_vip_utils.prove_efuse_bank_axil_activity
        #   any_master_active   -- smc_diagnostic_vip_utils.prove_axil_any_master_activity
        #   external_active     -- smc_probe_positive_control.prove_axil_external_active_probe
        #                          (probe_positive_controls = ("axil_external_active",))
        #
        # dtp_csr_active is DIFFERENT and is never asserted: tb_top ties
        # axil_dtp_csr_resp = '0', so there is no responder and an access there
        # would wedge rather than complete. It is listed in
        # env.smc_probe_liveness.UNBACKABLE_PROBES: sampled and logged as
        # OBSERVED-ONLY, never checked evidence. Sequence-side idle helpers must
        # restrict themselves to AXIL_CHECKABLE_FIELDS for the same reason.
        #
        # The rail below enforces that structurally: `expect_<field>` is refused
        # for an unbackable probe BEFORE the compare branch, mirroring the
        # `credit_probe` refusal on the ledger side (env/smc_probe_liveness.py),
        # so a sequence setting `expect_dtp_csr_active` cannot silently
        # exact-compare a probe whose responder is tied to zero.
        checked = ["resolvable"]
        observed_only = []
        for field in AXIL_SAMPLE_FIELDS:
            got = getattr(item, field)
            refuse_expectation_on_unbackable(
                f"axil_{field}",
                f"tb_axil_{field}",
                getattr(item, "expect_" + field),
                "SmcScoreboard._check_axil",
            )
            if getattr(item, "expect_" + field) is not None:
                exp = item.expected(field)
                assert got == exp, f"tb_axil_{field} expected {exp}, got {got} ({item})"
                checked.append(field)
                continue
            verdict = self._idle_leg(f"axil_{field}", f"tb_axil_{field}", got, 0, item)
            if verdict == "checked":
                checked.append(field)
            else:
                observed_only.append(f"{field}({verdict})")
        self.logger.info(
            "Scoreboard AXIL sample #%d: %s [checked: %s | OBSERVED-ONLY (NOT "
            "checked evidence): %s]",
            self.axil_samples_seen,
            item,
            ", ".join(checked),
            ", ".join(observed_only) or "-",
        )
        self._cov("axil_master", tuple(int(getattr(item, f)) for f in AXIL_SAMPLE_FIELDS))

    def _resp_is_okay(self, item: SmcSysAxiItem) -> bool:
        """True only for AXI OKAY — not SLVERR/DECERR even if allow_error."""
        return (not item.timed_out) and item.resp_code == 0

    def _check_sys_axi(self, item):
        self.sys_axi_checks_seen += 1
        # Per-bus measured access tally. `bus_name` is stamped by the driver that
        # actually drove the item, so this counts accesses the DUT completed on a
        # named port -- not accesses a test says it issued. A timed-out access is
        # excluded: nothing was performed.
        bus = getattr(item, "bus_name", "") or "unknown"
        if not getattr(item, "timed_out", False):
            self.axi_accesses_by_bus[bus] = self.axi_accesses_by_bus.get(bus, 0) + 1
        self.logger.info(
            "Scoreboard SYS AXI check #%d [%s]: %s", self.sys_axi_checks_seen, bus, item
        )
        if getattr(item, "expect_error", False):
            # Negative-path probe (mirrors the SEP expect_error guard): a real
            # error response is the expected outcome. Two vacuous passes are
            # rejected structurally here, independent of the sequence's own
            # asserts: an OKAY response means the access was NOT blocked, and a
            # timeout means it wedged rather than returning an error.
            assert not item.timed_out, (
                f"SYS AXI {item.op.value} @ 0x{item.addr:014x} marked expect_error "
                f"but TIMED OUT (a blocked access must return an error, not wedge)"
            )
            assert item.resp_code is not None and item.resp_code > 1, (
                f"SYS AXI {item.op.value} @ 0x{item.addr:014x} marked expect_error "
                f"but returned resp={item.resp_code} (expected SLVERR/DECERR)"
            )
            # `expected_resp` is honoured on this early-return path too, so an
            # item declaring DECERR (3) is not satisfied by a SLVERR (2). The
            # "some error" guard above is the structural floor; this is the
            # exact expectation when the scenario states one
            # ([EXACT-EXPECTATION]).
            if item.expected_resp is not None:
                assert item.resp_code == item.expected_resp, (
                    f"SYS AXI {item.op.value} @ 0x{item.addr:014x} marked "
                    f"expect_error returned resp={item.resp_code}, but the "
                    f"scenario declared expected_resp={item.expected_resp} "
                    f"(an error response of the wrong kind is not the declared "
                    f"behaviour)"
                )
            self._cov("sys_axi", (item.op.value, item.addr >> 12))
            return
        assert item.resp_ok, f"SYS AXI {item.op.value} @ 0x{item.addr:014x} returned non-OKAY"
        if item.expected_resp is not None:
            assert item.resp_code == item.expected_resp, (
                f"SYS AXI {item.op.value} @ 0x{item.addr:014x} resp "
                f"{item.resp_code}, expected {item.expected_resp}"
            )
        self._cov("sys_axi", (item.op.value, item.addr >> 12))
        if item.op is SmcSysAxiOp.READ and item.expected is not None:
            # The mask spans the whole transfer, so a multi-beat burst read is
            # compared over every beat rather than only the first.
            mask = (1 << (item.transfer_bytes * 8)) - 1
            got = item.rdata & mask
            exp = item.expected & mask
            assert got == exp, f"SYS AXI read 0x{item.addr:014x} = 0x{got:x}, expected 0x{exp:x}"
            self.sys_axi_value_checks_seen += 1
        self._check_sys_axi_memory_model(item)

    def _check_sys_axi_memory_model(self, item: SmcSysAxiItem) -> None:
        """U1-3: update/compare TB-local SmcMemoryModel on OKAY fabric traffic."""
        if self.memory_model is None:
            return
        if item.update_golden:
            assert self._resp_is_okay(item), (
                f"SYS AXI golden update refused for non-OKAY "
                f"{item.op.value} @ 0x{item.addr:x} resp={item.resp_code}"
            )
            assert item.op is SmcSysAxiOp.WRITE, "update_golden is only valid for SYS AXI writes"
            region = self.memory_model.find_region(item.addr, item.length, item.memory_region)
            assert region is not None, (
                f"update_golden set but no memory region covers 0x{item.addr:x} "
                f"(region={item.memory_region!r})"
            )
            self.memory_model.write_int(
                item.addr,
                item.wdata,
                length=item.length,
                region=region.name,
            )
            self.memory_model_updates_seen += 1
            self._cov("memory_model", ("update", region.name, item.addr >> 3))
            self.logger.info(
                "Scoreboard memory-model UPDATE #%d: %s @ 0x%x <- 0x%x",
                self.memory_model_updates_seen,
                region.name,
                item.addr,
                item.wdata,
            )
        if item.check_golden:
            assert self._resp_is_okay(item), (
                f"SYS AXI golden check refused for non-OKAY "
                f"{item.op.value} @ 0x{item.addr:x} resp={item.resp_code}"
            )
            assert item.op is SmcSysAxiOp.READ, "check_golden is only valid for SYS AXI reads"
            region = self.memory_model.find_region(item.addr, item.length, item.memory_region)
            assert region is not None, (
                f"check_golden set but no memory region covers 0x{item.addr:x} "
                f"(region={item.memory_region!r})"
            )
            mask = (1 << (item.length * 8)) - 1
            exp = (
                self.memory_model.read_int(item.addr, length=item.length, region=region.name) & mask
            )
            got = item.rdata & mask
            assert got == exp, (
                f"SYS AXI memory-model mismatch @ 0x{item.addr:x} "
                f"region={region.name}: got 0x{got:x}, expected 0x{exp:x}"
            )
            self.memory_model_checks_seen += 1
            self._cov("memory_model", ("check", region.name, item.addr >> 3))
            self.logger.info(
                "Scoreboard memory-model CHECK #%d: %s @ 0x%x == 0x%x",
                self.memory_model_checks_seen,
                region.name,
                item.addr,
                got,
            )

    def _check_protocol_vip(self, item):
        assert item.scenario != "", "protocol VIP scenario name is empty"
        if item.auto_evidence:
            # An activity stamp: either the one smc_base_test.run_phase adds, or
            # a scenario that has no measured CSR traffic and no byte golden and
            # therefore routes its record here rather than claiming a check. It
            # carries only the SYS-AXI
            # transaction count the scoreboard itself observed, so it is booked
            # as an activity stamp: its own coverage bin, no protocol assert,
            # and it does NOT count toward protocol_vip_checks_seen or the
            # minimum-activity gate ([NO-ALWAYS-PASS-CHECKER] -- a record that
            # cannot fail must not be presented as a check).
            self.protocol_vip_auto_stamps_seen += 1
            self.logger.info(
                "Scoreboard protocol VIP AUTO-COVERAGE-STAMP #%d (activity "
                "record, NOT a check): %s",
                self.protocol_vip_auto_stamps_seen,
                item,
            )
            self._cov("protocol_vip_auto", (item.kind.value, item.scenario, item.csr_accesses > 0))
            return
        # ROOT GATE: a scenario-recorded item is bookable as a *check* only with
        # a meaningful stimulus floor. With min_csr_accesses == 0 every assert
        # below reduces to a constant (`N >= 0`, `0 <= N`, a non-empty literal
        # string) while the item is still logged as "protocol VIP check #k",
        # books a protocol_vip coverage bin, is counted in
        # protocol_vip_checks_seen and can single-handedly satisfy check_phase's
        # minimum-activity gate -- exactly the shape the auto_evidence branch
        # above exists to prevent ([NO-ALWAYS-PASS-CHECKER] /
        # [NO-ZERO-ACTIVITY-PASS]). Refusing it here, and not only at the
        # record_protocol_vip() call site, means no path can book one.
        assert not item.auto_evidence
        assert item.min_csr_accesses > 0 or item.expected_bytes is not None, (
            f"protocol VIP {item.scenario}: a scenario-recorded item was booked "
            f"with min_csr_accesses={item.min_csr_accesses} and no byte golden. "
            f"Every assert on such a record reduces to a constant, so it cannot "
            f"be presented as a protocol VIP check. Pass "
            f"min_csr_accesses=<stimulus floor > 0> to record_protocol_vip() "
            f"(or supply expected_bytes, which carries the fail-capability for "
            f"a scenario with no CSR traffic), or set auto_evidence=True to "
            f"book it in the protocol_vip_auto activity bin instead."
        )
        self.protocol_vip_checks_seen += 1
        self.logger.info(
            "Scoreboard protocol VIP check #%d: %s", self.protocol_vip_checks_seen, item
        )
        # A scenario-recorded item is an evidence record, not the protocol
        # verdict: the real protocol verification lives in sequence-body /
        # SYS-AXI scoreboard checks. The asserts below make the record itself
        # fail-capable — an empty or activity-short record is rejected instead of
        # logging false coverage.
        assert item.details != "", f"protocol VIP {item.scenario} recorded without evidence details"
        assert item.csr_accesses >= item.min_csr_accesses, (
            f"protocol VIP {item.scenario}: observed csr_accesses "
            f"({item.csr_accesses}) below the stimulus minimum "
            f"({item.min_csr_accesses}) -- the scenario did not run the traffic "
            f"this record claims"
        )
        assert item.fabric_accesses >= item.min_fabric_accesses, (
            f"protocol VIP {item.scenario}: observed "
            f"{item.fabric_access_label or 'non-CSR fabric'} accesses "
            f"({item.fabric_accesses}) below the stimulus minimum "
            f"({item.min_fabric_accesses})"
        )
        if item.timeouts is not None:
            # Every timeout counted by csr_read_bounded() is also an access, so
            # a recorded item must never report more timeouts than accesses.
            assert item.timeouts <= item.csr_accesses, (
                f"protocol VIP {item.scenario}: timeouts ({item.timeouts}) exceed "
                f"csr_accesses ({item.csr_accesses})"
            )
        # U6-3: optional byte-level golden — mismatch fails the test.
        if item.expected_bytes is not None:
            obs = item.observed_bytes if item.observed_bytes is not None else b""
            assert obs == item.expected_bytes, (
                f"protocol VIP {item.scenario} byte golden mismatch: "
                f"got {obs.hex()}, expected {item.expected_bytes.hex()}"
            )
        self._cov("protocol_vip", (item.kind.value, item.scenario, int(item.proxy)))

    def check_phase(self):
        # Resolve every deferred idle leg first: a positive control that ran
        # after a sample still turns that sample's leg into a real compare.
        self._resolve_pending_idle_legs()
        alive = alive_probes()
        self.logger.info(
            "Scoreboard probe liveness: proven-at-1 this run = %s; "
            "unbackable-by-TB = %s; idle legs checked=%d observed_only=%d",
            ", ".join(sorted(alive)) or "-",
            ", ".join(sorted(UNBACKABLE_PROBES)),
            self.idle_legs_checked,
            self.idle_legs_observed_only,
        )
        # Minimum-activity gate. Excludes
        # `protocol_vip_auto_stamps_seen` and `reset_raw_observations_seen`:
        # neither can fail, so neither may satisfy the gate on its own
        # ([NO-ZERO-ACTIVITY-PASS]).
        total = (
            self.i2c_samples_seen
            + self.reset_samples_seen
            + self.clk_samples_seen
            + self.irq_samples_seen
            + self.gpio_samples_seen
            + self.axil_samples_seen
            + self.sys_axi_checks_seen
            + self.protocol_vip_checks_seen
            + self.reset_raw_checks_seen
            + self.reset_wait_checks_seen
        )
        assert total > 0, "SmcScoreboard saw no SAMPLE items"
        self.logger.info(
            "Scoreboard activity: i2c=%d reset=%d(raw_chk=%d raw_obs=%d wait=%d) "
            "clk_setup=%d clk_dut=%d irq=%d gpio=%d axil=%d sys_axi=%d "
            "protocol_vip=%d(auto_stamps=%d)",
            self.i2c_samples_seen,
            self.reset_samples_seen,
            self.reset_raw_checks_seen,
            self.reset_raw_observations_seen,
            self.reset_wait_checks_seen,
            self.clk_setup_checks_seen,
            self.clk_dut_checks_seen,
            self.irq_samples_seen,
            self.gpio_samples_seen,
            self.axil_samples_seen,
            self.sys_axi_checks_seen,
            self.protocol_vip_checks_seen,
            self.protocol_vip_auto_stamps_seen,
        )
        self.logger.info(
            "Scoreboard measured AXI accesses per bus (completed, non-timeout): %s",
            ", ".join(f"{bus}={n}" for bus, n in sorted(self.axi_accesses_by_bus.items())) or "-",
        )
