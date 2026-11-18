# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_ext_boot_seq_gate_test (SMU_006).

Observes smc_fuse_reset_n_delayed_o — the RTL consumer gated by ext_boot_seq_done_i
(port_table: gates reset release). rst_primary_smc_clk_no is NOT gated by this pin
(negative control CHK-PRIMARY-NOT-GATED).

S6 lowers ext_boot_seq_done_i again and pulses the cold reset: the gate holds the
fuse reset asserted across the new release, and raising the gate releases it
(CHK-BOOT-SEQ-REGATE).

The pin is qualified inside the SMC and fanned to the SEP (hw/sys/smu/doc/port_table.adoc
``ext_boot_seq_done_i``; doc/integrator/src/smu-composition.adoc, "DFT Signals":
``ext_boot_seq_done_qual_o`` drives the SEP's ``ext_boot_seq_done_i``), and the SEP qualifies
its reset release with ``ext_boot_seq_done_i`` asserted (hw/sys/sep/doc/clk_rst.adoc, the OTP
controller release; hw/sys/sep/doc/port_table.adoc ``ext_boot_seq_done_i``). With the pin low
``sep_reset_n_o`` reads 0 on every gated sample, and it rises only after the pin, in S4
and again across the S6 cold reset (CHK-BOOT-SEQ-GATE-SEP). The sense-done level during
the gated window is logged: this leaf runs with the sense skipped.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time

from seq_lib.smu_tb_pins import smc_primary_reset


@dataclass
class _BoundedWait:
    """One bounded poll: how long it ran, whether it expired, and its last sample."""

    label: str
    bound: int
    cycles: int
    expired: bool
    last: int


class smu_ext_boot_seq_gate_test_seq:
    """SMU_006: ext_boot_seq_done_i gates fuse_reset release."""

    GATED_SAMPLES = 64
    RELEASE_BOUND = 2000
    SETTLE_REF_CYCLES = 500
    #: Bounded waits this sequence performs, in program order.
    WAIT_LABELS = (
        "primary_released_while_boot_gated",
        "fuse_reset_n_delayed_after_ungate",
        "sep_reset_n_after_ungate",
    )
    PRIMARY = "rst_primary_smc_clk_no"
    FUSE = "smc_fuse_reset_n_delayed_o"
    SEP = "sep_reset_n_o"

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self._waits: list[_BoundedWait] = []
        #: Simulation time (ns) at which each tracked output is first sampled 1.
        self._first_high_ns: dict[str, float | None] = {
            self.PRIMARY: None,
            self.FUSE: None,
            self.SEP: None,
        }
        self._trackers: list = []

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _step(self, step_id: str, detail: str) -> None:
        self._log(f"STEP {step_id}: {detail}")

    def _sample(self, signal, name: str) -> int:
        val = signal.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z sample on {name}: {val}")
        return int(val)

    async def _track_first_high(self, signal, name: str) -> None:
        """Stamp the first clk_smu_i edge at which ``signal`` samples 1."""
        while True:
            await RisingEdge(self.dut.clk_smu_i)
            if self._sample(signal, name) == 1:
                if self._first_high_ns[name] is None:
                    self._first_high_ns[name] = get_sim_time("ns")
                return

    def _arm_trackers(self) -> None:
        self._trackers = [
            cocotb.start_soon(self._track_first_high(smc_primary_reset(self.dut), self.PRIMARY)),
            cocotb.start_soon(
                self._track_first_high(self.dut.smc_fuse_reset_n_delayed_o, self.FUSE)
            ),
            cocotb.start_soon(self._track_first_high(self.dut.sep_reset_n_o, self.SEP)),
        ]

    def _stop_trackers(self) -> None:
        for task in self._trackers:
            task.kill()
        self._trackers.clear()

    async def _wait_eq(
        self,
        signal,
        expect: int,
        *,
        clk,
        bound: int,
        label: str,
        first_high: str | None = None,
    ) -> int:
        """Poll until expect or bound; return last sample (never raise on mismatch).

        Callers must sb.expect_eq the returned sample so the compare can fail.
        The wait is recorded in ``_waits`` for CHK-TIMEOUT-PATHS. ``first_high``
        names the edge tracker whose signal this is: the tracker and this poll
        sample the same clock edge, and the caller's compare can run before the
        tracker task resumes, so the poll stamps the edge itself when it is the
        first to see the 1.
        """
        last = None
        for cycles in range(1, bound + 1):
            await RisingEdge(clk)
            last = self._sample(signal, label)
            if last == expect:
                if first_high is not None and last == 1 and self._first_high_ns[first_high] is None:
                    self._first_high_ns[first_high] = get_sim_time("ns")
                self._waits.append(_BoundedWait(label, bound, cycles, False, last))
                return last
        last = last if last is not None else -1
        self._waits.append(_BoundedWait(label, bound, bound, True, last))
        return last

    async def run(self) -> None:
        dut = self.dut
        sb = self.test.env.scoreboard

        dut.ext_boot_seq_done_i.value = 0
        dut.powergood_i.value = 1
        dut.rst_cold_ni.value = 0
        await ClockCycles(dut.clk_ref_i, 64)
        dut.rst_cold_ni.value = 1
        dut.jtag_trst.value = 1
        await ClockCycles(dut.clk_ref_i, self.SETTLE_REF_CYCLES)

        self._step(
            "S1",
            "PRELOAD clocks running; ext_boot_seq_done_i=0; cold released; "
            "powergood=1 (fuse_reset gated)",
        )
        self._arm_trackers()
        try:
            await self._body(sb)
        finally:
            self._stop_trackers()

    async def _body(self, sb) -> None:
        dut = self.dut

        self._step(
            "S2",
            "GATED: ext_boot_seq_done_i=0 holds smc_fuse_reset_n_delayed_o low",
        )
        gated_samples = 0
        sep_low_gated = 0
        sense_done_gated = 0
        for _ in range(self.GATED_SAMPLES):
            await RisingEdge(dut.clk_smu_i)
            fuse = self._sample(dut.smc_fuse_reset_n_delayed_o, self.FUSE)
            gate = self._sample(dut.ext_boot_seq_done_i, "ext_boot_seq_done_i")
            if gate != 0:
                raise AssertionError(f"ext_boot_seq_done_i not 0 during S2: {gate}")
            if fuse != 0:
                raise AssertionError(
                    f"smc_fuse_reset_n_delayed_o released while gated at sample {gated_samples}"
                )
            gated_samples += 1
            sep_low_gated += self._sample(dut.sep_reset_n_o, self.SEP) == 0
            sense_done_gated += self._sample(dut.smc_fuse_sense_done_o, "smc_fuse_sense_done_o")
        t_gated_end = get_sim_time("ns")

        self._step(
            "S3",
            "NEGATIVE CONTROL: rst_primary_smc_clk_no still releases while boot-gated",
        )
        primary = await self._wait_eq(
            smc_primary_reset(dut),
            1,
            clk=dut.clk_smu_i,
            bound=self.RELEASE_BOUND,
            label=self.WAIT_LABELS[0],
            first_high=self.PRIMARY,
        )
        self._log(f"CHK-PRIMARY-NOT-GATED observed rst_primary_smc_clk_no={primary}")
        sb.expect_eq(
            "CHK-PRIMARY-NOT-GATED primary released while gated",
            primary,
            1,
            evidence="CHK-PRIMARY-NOT-GATED",
        )

        self._step(
            "S4",
            "UNGATE: drive ext_boot_seq_done_i=1; fuse_reset release permitted",
        )
        dut.ext_boot_seq_done_i.value = 1
        t_ungate = get_sim_time("ns")
        released = await self._wait_eq(
            dut.smc_fuse_reset_n_delayed_o,
            1,
            clk=dut.clk_smu_i,
            bound=self.RELEASE_BOUND,
            label=self.WAIT_LABELS[1],
            first_high=self.FUSE,
        )
        self._log(
            f"CHK-BOOT-SEQ-GATE observed gated_samples={gated_samples} of "
            f">={self.GATED_SAMPLES} and smc_fuse_reset_n_delayed_o={released} after the ungate"
        )
        sb.expect_eq(
            "CHK-BOOT-SEQ-GATE fuse_reset released after ungate",
            released,
            1,
            evidence="CHK-BOOT-SEQ-GATE",
        )
        sep_released = await self._wait_eq(
            dut.sep_reset_n_o,
            1,
            clk=dut.clk_smu_i,
            bound=self.RELEASE_BOUND,
            label=self.WAIT_LABELS[2],
            first_high=self.SEP,
        )
        t_sep = self._first_high_ns[self.SEP]
        self._log(
            f"OBS smc_fuse_sense_done_o=1 on {sense_done_gated}/{gated_samples} gated samples "
            "(supplied by the skipped sense, logged only)"
        )
        self._log(
            f"CHK-BOOT-SEQ-GATE-SEP sep_reset_n_o low on {sep_low_gated}/{gated_samples} gated "
            f"samples; sep_reset_n_o={sep_released} after the ungate, first rise {t_sep}ns, "
            f"ungate {t_ungate}ns"
        )
        sb.expect_eq(
            "CHK-BOOT-SEQ-GATE-SEP with ext_boot_seq_done_i low sep_reset_n_o reads 0 on every "
            "gated sample, and sep_reset_n_o first rises within the bound and only after the pin "
            "rises",
            (sep_low_gated, sep_released, t_sep is not None and t_sep > t_ungate),
            (self.GATED_SAMPLES, 1, True),
            evidence="CHK-BOOT-SEQ-GATE-SEP",
        )

        self._step("S5", "TIMEOUT: bounded sample waits with last reset/gate state")
        for wait in self._waits:
            self._log(
                f"TIMEOUT-PATH {wait.label}: bound={wait.bound} cycles={wait.cycles} "
                f"expired={wait.expired} last={wait.last}"
            )
        self._log(
            f"CHK-TIMEOUT-PATHS observed waits={len(self._waits)} expected={len(self.WAIT_LABELS)}"
        )
        sb.expect_eq(
            "CHK-TIMEOUT-PATHS every bounded wait completed inside its bound",
            [(wait.label, wait.expired, wait.bound) for wait in self._waits],
            [(label, False, self.RELEASE_BOUND) for label in self.WAIT_LABELS],
            evidence="CHK-TIMEOUT-PATHS",
        )

        # Ordering from DUT edges, not from the order the steps ran in: the
        # primary reset must release before the ungate stimulus, and the fuse
        # reset must first rise only after the gated window and after the
        # ungate. A fuse release inside the S3 wait, which S2 does not sample,
        # fails the second and third clauses.
        t_primary = self._first_high_ns[self.PRIMARY]
        t_fuse = self._first_high_ns[self.FUSE]
        fence = (
            ("S3<S4 primary_release<ungate", t_primary is not None and t_primary < t_ungate),
            ("S2<S4 gated_window_end<fuse_release", t_fuse is not None and t_gated_end < t_fuse),
            ("S4 ungate<fuse_release", t_fuse is not None and t_ungate < t_fuse),
        )
        self._log(
            "CHK-NONVAC: ordered fence from DUT edges "
            f"(gated_window_end={t_gated_end}ns primary_release={t_primary}ns "
            f"ungate={t_ungate}ns fuse_release={t_fuse}ns; "
            + ", ".join(f"{name}={ok}" for name, ok in fence)
            + ")"
        )
        sb.expect_eq(
            "CHK-NONVAC ordered fence from DUT edges",
            [ok for _, ok in fence],
            [True] * len(fence),
            evidence="CHK-NONVAC",
        )
        self._step("S6", "RE-GATE: ext_boot_seq_done_i=0 across a cold reset")
        dut.ext_boot_seq_done_i.value = 0
        dut.rst_cold_ni.value = 0
        await ClockCycles(dut.clk_ref_i, 64)
        dut.rst_cold_ni.value = 1
        await ClockCycles(dut.clk_ref_i, self.SETTLE_REF_CYCLES)
        held = 0
        sep_held = 0
        for _ in range(self.GATED_SAMPLES):
            await RisingEdge(dut.clk_smu_i)
            held += self._sample(dut.smc_fuse_reset_n_delayed_o, self.FUSE) == 0
            sep_held += self._sample(dut.sep_reset_n_o, self.SEP) == 0
        dut.ext_boot_seq_done_i.value = 1
        rereleased = 0
        sep_rereleased = 0
        for _ in range(self.RELEASE_BOUND):
            await RisingEdge(dut.clk_smu_i)
            rereleased |= self._sample(dut.smc_fuse_reset_n_delayed_o, self.FUSE)
            sep_rereleased |= self._sample(dut.sep_reset_n_o, self.SEP)
            if rereleased and sep_rereleased:
                break
        self._log(f"CHK-BOOT-SEQ-REGATE held={held}/{self.GATED_SAMPLES} released={rereleased}")
        sb.expect_eq(
            "CHK-BOOT-SEQ-REGATE the gate holds the fuse reset across a cold reset and releases it",
            (held, rereleased),
            (self.GATED_SAMPLES, 1),
            evidence="CHK-BOOT-SEQ-REGATE",
        )
        self._log(
            f"CHK-BOOT-SEQ-GATE-SEP across the second cold reset sep_reset_n_o low on "
            f"{sep_held}/{self.GATED_SAMPLES} gated samples, released={sep_rereleased}"
        )
        sb.expect_eq(
            "CHK-BOOT-SEQ-GATE-SEP across a cold reset with the pin low sep_reset_n_o reads 0 on "
            "every gated sample and rises within the bound after the pin",
            (sep_held, sep_rereleased),
            (self.GATED_SAMPLES, 1),
            evidence="CHK-BOOT-SEQ-GATE-SEP",
        )
        # The poll sees the release on the edge that made it; the cov/sv monitors
        # sample it on the next one, which the simulation has to reach.
        await ClockCycles(self.dut.clk_smu_i, 2)
        self._log("SMU_006 sequence complete")
