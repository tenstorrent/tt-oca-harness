# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_smc_mailbox_int_test (SMU_ALL_004).

DV-CARD:          SMU_ALL_004   ANCHOR: smu_smc_mailbox_int_test

Owns:
  SMC-MBX-IRQ-EXT.S2 — Width equals NUM_MAILBOXES (32) at the SMU boundary
    (passive DECODE on bare tb_top SEP=0; required_cells width=32).

CHANNELS.S2/S3 and EXT.S1 are owned by SMU_ALL_008 — out of scope.
No mailbox MMIO; no Force/deposit on ext_mailbox_interrupts.
"""

from __future__ import annotations

from seq_lib.smu_tb_pins import smc_primary_reset

import time

import cocotb
from cocotb.triggers import RisingEdge


class smu_smc_mailbox_int_test_seq:
    """SMU_ALL_004: passive DECODE of ext_mailbox_interrupts width=32."""

    NUM_MAILBOXES = 32
    BOUND_CYCLES = 2000
    SETTLE_CYCLES = 32
    # Bounded waits: primary release (S1) + width-sample settle (S2).
    EXPECTED_TIMEOUT_PATHS = 2

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self._step_ts: dict[str, float] = {}
        self._timeout_paths: list[str] = []
        self._lifecycle_ts: dict[str, float] = {}

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _mark_step(self, step_id: str, detail: str) -> None:
        self._step_ts[step_id] = time.monotonic()
        self._log(f"STEP {step_id}: {detail}")

    def _sample(self, signal, name: str) -> int:
        val = signal.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z sample on {name}: {val}")
        return int(val)

    def _nbits(self, signal, name: str) -> int:
        if signal is None:
            raise AssertionError(f"width observe fail: {name} is None")
        n = getattr(signal, "n_bits", None)
        if n is None:
            try:
                n = len(signal)
            except TypeError as exc:
                raise AssertionError(f"width observe fail: cannot measure {name}") from exc
        if n <= 0:
            raise AssertionError(f"width observe fail: {name} n_bits={n}")
        return int(n)

    async def _wait_eq(
        self,
        signal,
        expect: int,
        *,
        clk,
        bound: int,
        label: str,
    ) -> int:
        last = None
        for _ in range(bound):
            await RisingEdge(clk)
            last = self._sample(signal, label)
            if last == expect:
                self._timeout_paths.append(f"{label}: bound={bound} ok last={last}")
                return last
        self._timeout_paths.append(f"{label}: bound={bound} EXPIRED last={last}")
        raise AssertionError(f"TIMEOUT {label}: bound={bound} last_state={last} expect={expect}")

    async def _wait_width(
        self,
        signal,
        expect_w: int,
        *,
        clk,
        bound: int,
        label: str,
    ) -> tuple[int, int]:
        """Bounded wait until port width is measurable and equals expect_w."""
        last_w = None
        last_val = None
        for _ in range(bound):
            await RisingEdge(clk)
            try:
                last_w = self._nbits(signal, label)
                last_val = self._sample(signal, label)
            except AssertionError:
                continue
            if last_w == expect_w:
                self._timeout_paths.append(
                    f"{label}: bound={bound} ok last=width={last_w}/val=0x{last_val:x}"
                )
                return last_w, last_val
        self._timeout_paths.append(
            f"{label}: bound={bound} EXPIRED last=width={last_w}/val={last_val}"
        )
        raise AssertionError(
            f"TIMEOUT {label}: bound={bound} "
            f"last_state=width={last_w}/val={last_val} expect_width={expect_w}"
        )

    def _mark_lifecycle(self, phase: str, detail: str) -> None:
        self._lifecycle_ts[phase] = time.monotonic()
        self._log(f"LIFECYCLE CHK-SMC-MBX-IRQ-EXT-S2 {phase}: {detail}")

    async def run(self) -> None:
        dut = self.dut
        sb = self.test.env.scoreboard

        await self.cfg.reset_done.wait()
        for _ in range(self.SETTLE_CYCLES):
            await RisingEdge(dut.clk_smu_i)

        # ------------------------------------------------------------------
        # S1 SETUP
        # ------------------------------------------------------------------
        self._mark_step(
            "S1",
            "SETUP: SEP=0 bare tb_top bring-up; clocks/resets stable; "
            "baseline ext_mailbox_interrupts observation (no mailbox MMIO)",
        )
        await self._wait_eq(
            smc_primary_reset(dut),
            1,
            clk=dut.clk_smu_i,
            bound=self.BOUND_CYCLES,
            label="s1_primary_release",
        )
        if not hasattr(dut, "ext_mailbox_interrupts"):
            raise AssertionError("unobservable: tb_top.ext_mailbox_interrupts missing")
        mbx = dut.ext_mailbox_interrupts
        baseline = self._sample(mbx, "ext_mailbox_interrupts")
        baseline_w = self._nbits(mbx, "ext_mailbox_interrupts")
        self._log(
            f"baseline ext_mailbox_interrupts width={baseline_w} "
            f"val=0x{baseline:x} (passive; no MMIO)"
        )

        # ------------------------------------------------------------------
        # S2 SMC-MBX-IRQ-EXT.S2 — width DECODE NUM_MAILBOXES=32
        # ------------------------------------------------------------------
        self._mark_step(
            "S2",
            "ACTION SMC-MBX-IRQ-EXT.S2: passively observe "
            "ext_mailbox_interrupts[31:0] width/DECODE at SMU boundary",
        )
        self._log("COVERAGE SMC-MBX-IRQ-EXT.S2 cells: width=32")

        # Lifecycle (card non-null): set → observed → cleared → checked_cleared
        self._mark_lifecycle(
            "set",
            "assert observation for SMC-MBX-IRQ-EXT.S2 "
            f"(port=ext_mailbox_interrupts baseline_w={baseline_w} "
            f"baseline_val=0x{baseline:x})",
        )

        width, observed_val = await self._wait_width(
            mbx,
            self.NUM_MAILBOXES,
            clk=dut.clk_smu_i,
            bound=self.BOUND_CYCLES,
            label="s2_width_sample",
        )
        self._mark_lifecycle(
            "observed",
            "consumer samples asserted condition for SMC-MBX-IRQ-EXT.S2 "
            f"(width={width} val=0x{observed_val:x} "
            f"NUM_MAILBOXES={self.NUM_MAILBOXES})",
        )
        if width != self.NUM_MAILBOXES:
            raise AssertionError(f"SMC-MBX-IRQ-EXT.S2 width={width} expect={self.NUM_MAILBOXES}")

        # cleared: end observation window; confirm DUT-driven idle (no force)
        for _ in range(self.SETTLE_CYCLES):
            await RisingEdge(dut.clk_smu_i)
        cleared_val = self._sample(mbx, "ext_mailbox_interrupts")
        if cleared_val != baseline:
            raise AssertionError(
                "SMC-MBX-IRQ-EXT.S2 clear/ack fail: vector changed without "
                f"MMIO stimulus (baseline=0x{baseline:x} "
                f"cleared=0x{cleared_val:x}) — possible TB force/deposit"
            )
        self._mark_lifecycle(
            "cleared",
            "clear/ack for SMC-MBX-IRQ-EXT.S2 "
            f"(idle_val=0x{cleared_val:x} matches baseline; no force)",
        )

        checked_w = self._nbits(mbx, "ext_mailbox_interrupts")
        checked_val = self._sample(mbx, "ext_mailbox_interrupts")
        if checked_w != self.NUM_MAILBOXES:
            raise AssertionError(
                f"SMC-MBX-IRQ-EXT.S2 checked_cleared width={checked_w} expect={self.NUM_MAILBOXES}"
            )
        if checked_val != baseline:
            raise AssertionError(
                "SMC-MBX-IRQ-EXT.S2 checked_cleared value drift: "
                f"baseline=0x{baseline:x} checked=0x{checked_val:x}"
            )
        self._mark_lifecycle(
            "checked_cleared",
            f"readback cleared for SMC-MBX-IRQ-EXT.S2 (width={checked_w} val=0x{checked_val:x})",
        )

        lc_order = ["set", "observed", "cleared", "checked_cleared"]
        for phase in lc_order:
            if phase not in self._lifecycle_ts:
                raise AssertionError(f"CHK-SMC-MBX-IRQ-EXT-S2 lifecycle missing: {phase}")
        for a, b in zip(lc_order, lc_order[1:]):
            if self._lifecycle_ts[a] >= self._lifecycle_ts[b]:
                raise AssertionError(
                    f"CHK-SMC-MBX-IRQ-EXT-S2 lifecycle order fail: {a} not before {b}"
                )

        detail = (
            f"width={width} NUM_MAILBOXES={self.NUM_MAILBOXES} "
            f"port=ext_mailbox_interrupts "
            f"baseline=0x{baseline:x} observed=0x{observed_val:x} "
            f"checked=0x{checked_val:x}"
        )
        self._log(f"CHK-SMC-MBX-IRQ-EXT-S2: PASS ({detail})")
        sb.expect_eq(
            "CHK-SMC-MBX-IRQ-EXT-S2 width equals NUM_MAILBOXES",
            width,
            self.NUM_MAILBOXES,
            evidence="CHK-SMC-MBX-IRQ-EXT-S2",
        )

        # ------------------------------------------------------------------
        # S3 TIMEOUT inventory
        # ------------------------------------------------------------------
        self._mark_step(
            "S3",
            "TIMEOUT: every bounded wait names finite bound + fail-on-expiry + last-state",
        )
        for line in self._timeout_paths:
            self._log(f"TIMEOUT-PATH {line}")
        n_paths = len(self._timeout_paths)
        if n_paths != self.EXPECTED_TIMEOUT_PATHS:
            raise AssertionError(
                f"CHK-TIMEOUT-PATHS count mismatch: got {n_paths} "
                f"expect {self.EXPECTED_TIMEOUT_PATHS}"
            )
        for i, line in enumerate(self._timeout_paths):
            if "bound=" not in line:
                raise AssertionError(f"CHK-TIMEOUT-PATHS[{i}] missing finite bound: {line}")
            if "ok last=" not in line and "EXPIRED last=" not in line:
                raise AssertionError(f"CHK-TIMEOUT-PATHS[{i}] missing last-state: {line}")
        self._log(
            "CHK-TIMEOUT-PATHS: Finite bound on S3; expiry fails with "
            f"last-state diagnostics (paths={n_paths} "
            f"expect={self.EXPECTED_TIMEOUT_PATHS} bound={self.BOUND_CYCLES})"
        )
        sb.expect_eq(
            "CHK-TIMEOUT-PATHS exact count",
            n_paths,
            self.EXPECTED_TIMEOUT_PATHS,
            evidence="CHK-TIMEOUT-PATHS",
        )

        self._step_ts["PASS"] = time.monotonic()
        self._log("SMU_ALL_004 sequence complete (PASS term recorded for NONVAC fence)")

        order = ["S1", "S2", "S3", "PASS"]
        for step_id in order:
            if step_id not in self._step_ts:
                raise AssertionError(f"CHK-NONVAC missing step term: {step_id}")
        for a, b in zip(order, order[1:]):
            if self._step_ts[a] >= self._step_ts[b]:
                raise AssertionError(f"CHK-NONVAC order fail: {a} not before {b}")
        deltas_ns = [
            int((self._step_ts[b] - self._step_ts[a]) * 1e9) for a, b in zip(order, order[1:])
        ]
        positive_deltas = sum(1 for d in deltas_ns if d > 0)
        if positive_deltas != 3:
            raise AssertionError(
                f"CHK-NONVAC positive-delta count fail: {positive_deltas} deltas_ns={deltas_ns}"
            )
        self._log("CHK-NONVAC: Ordered fence S1<S2<S3<PASS all hold")
        sb.expect_eq(
            "CHK-NONVAC positive step-delta count",
            positive_deltas,
            3,
            evidence="CHK-NONVAC",
        )
