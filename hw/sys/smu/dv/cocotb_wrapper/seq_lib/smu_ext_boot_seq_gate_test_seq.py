# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_ext_boot_seq_gate_test (SMU_006).

Observes smc_fuse_reset_n_delayed_o — the RTL consumer gated by ext_boot_seq_done_i
(port_table: gates reset release). rst_primary_smc_clk_no is NOT gated by this pin
(negative control CHK-PRIMARY-NOT-GATED).
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
    )
    PRIMARY = "rst_primary_smc_clk_no"
    FUSE = "smc_fuse_reset_n_delayed_o"

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self._waits: list[_BoundedWait] = []
        #: Simulation time (ns) at which each tracked output is first sampled 1.
        self._first_high_ns: dict[str, float | None] = {self.PRIMARY: None, self.FUSE: None}
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
                self._first_high_ns[name] = get_sim_time("ns")
                return

    def _arm_trackers(self) -> None:
        self._trackers = [
            cocotb.start_soon(self._track_first_high(smc_primary_reset(self.dut), self.PRIMARY)),
            cocotb.start_soon(
                self._track_first_high(self.dut.smc_fuse_reset_n_delayed_o, self.FUSE)
            ),
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
    ) -> int:
        """Poll until expect or bound; return last sample (never raise on mismatch).

        Callers must sb.expect_eq the returned sample so the compare can fail.
        The wait is recorded in ``_waits`` for CHK-TIMEOUT-PATHS.
        """
        last = None
        for cycles in range(1, bound + 1):
            await RisingEdge(clk)
            last = self._sample(signal, label)
            if last == expect:
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
        )
        self._log(
            "CHK-PRIMARY-NOT-GATED: rst_primary_smc_clk_no releases to 1'b1 while "
            "ext_boot_seq_done_i=0; only fuse_reset_n_delayed_o is boot-gated "
            f"(primary={primary})"
        )
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
        )
        self._log(
            "CHK-BOOT-SEQ-GATE: with ext_boot_seq_done_i=0, smc_fuse_reset_n_delayed_o "
            f"remains 1'b0 across >={self.GATED_SAMPLES} samples; after "
            f"ext_boot_seq_done_i=1, smc_fuse_reset_n_delayed_o becomes 1'b1 within the "
            f"bounded release window (gated_samples={gated_samples} released={released})"
        )
        sb.expect_eq(
            "CHK-BOOT-SEQ-GATE fuse_reset released after ungate",
            released,
            1,
            evidence="CHK-BOOT-SEQ-GATE",
        )

        self._step("S5", "TIMEOUT: bounded sample waits with last reset/gate state")
        for wait in self._waits:
            self._log(
                f"TIMEOUT-PATH {wait.label}: bound={wait.bound} cycles={wait.cycles} "
                f"expired={wait.expired} last={wait.last}"
            )
        self._log(
            "CHK-TIMEOUT-PATHS: every bounded wait completed inside its bound "
            f"(waits={len(self._waits)} expect={len(self.WAIT_LABELS)})"
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
        self._log("SMU_006 sequence complete")
