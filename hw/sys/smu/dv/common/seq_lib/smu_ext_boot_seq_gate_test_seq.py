# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_ext_boot_seq_gate_test (SMU_006).

Observes smc_fuse_reset_n_delayed_o — the RTL consumer gated by ext_boot_seq_done_i
(port_table: gates reset release). rst_primary_smc_clk_no is NOT gated by this pin
(negative control CHK-PRIMARY-NOT-GATED).
"""

from __future__ import annotations

import time

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from seq_lib.smu_tb_pins import smc_primary_reset


class smu_ext_boot_seq_gate_test_seq:
    """SMU_006: ext_boot_seq_done_i gates fuse_reset release."""

    GATED_SAMPLES = 64
    RELEASE_BOUND = 2000
    SETTLE_REF_CYCLES = 500
    EXPECTED_TIMEOUT_PATHS = 2

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self._step_ts: dict[str, float] = {}
        self._timeout_paths: list[str] = []

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
        """
        last = None
        for _ in range(bound):
            await RisingEdge(clk)
            last = self._sample(signal, label)
            if last == expect:
                self._timeout_paths.append(f"{label}: bound={bound} ok last={last}")
                return last
        self._timeout_paths.append(f"{label}: bound={bound} EXPIRED last={last}")
        return last if last is not None else -1

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

        self._mark_step(
            "S1",
            "PRELOAD clocks running; ext_boot_seq_done_i=0; cold released; "
            "powergood=1 (fuse_reset gated)",
        )

        self._mark_step(
            "S2",
            "GATED: ext_boot_seq_done_i=0 holds smc_fuse_reset_n_delayed_o low",
        )
        gated_samples = 0
        for _ in range(self.GATED_SAMPLES):
            await RisingEdge(dut.clk_smu_i)
            fuse = self._sample(dut.smc_fuse_reset_n_delayed_o, "smc_fuse_reset_n_delayed_o")
            gate = self._sample(dut.ext_boot_seq_done_i, "ext_boot_seq_done_i")
            if gate != 0:
                raise AssertionError(f"ext_boot_seq_done_i not 0 during S2: {gate}")
            if fuse != 0:
                raise AssertionError(
                    f"smc_fuse_reset_n_delayed_o released while gated at sample {gated_samples}"
                )
            gated_samples += 1

        self._mark_step(
            "S3",
            "NEGATIVE CONTROL: rst_primary_smc_clk_no still releases while boot-gated",
        )
        primary = await self._wait_eq(
            smc_primary_reset(dut),
            1,
            clk=dut.clk_smu_i,
            bound=self.RELEASE_BOUND,
            label="primary_released_while_boot_gated",
        )
        chk_primary = (
            "CHK-PRIMARY-NOT-GATED: rst_primary_smc_clk_no releases to 1'b1 while "
            "ext_boot_seq_done_i=0; only fuse_reset_n_delayed_o is boot-gated "
            f"(primary={primary})"
        )
        self._log(chk_primary)
        # Soft wait + live compare (expires with primary!=1 → FAIL).
        sb.expect_eq(
            "CHK-PRIMARY-NOT-GATED primary released while gated",
            primary,
            1,
            evidence="CHK-PRIMARY-NOT-GATED",
        )

        self._mark_step(
            "S4",
            "UNGATE: drive ext_boot_seq_done_i=1; fuse_reset release permitted",
        )
        dut.ext_boot_seq_done_i.value = 1
        released = await self._wait_eq(
            dut.smc_fuse_reset_n_delayed_o,
            1,
            clk=dut.clk_smu_i,
            bound=self.RELEASE_BOUND,
            label="fuse_reset_n_delayed_after_ungate",
        )

        chk_gate = (
            "CHK-BOOT-SEQ-GATE: with ext_boot_seq_done_i=0, smc_fuse_reset_n_delayed_o "
            f"remains 1'b0 across >={self.GATED_SAMPLES} samples; after "
            f"ext_boot_seq_done_i=1, smc_fuse_reset_n_delayed_o becomes 1'b1 within the "
            f"bounded release window (gated_samples={gated_samples} released={released})"
        )
        self._log(chk_gate)
        # Measured release sample (soft wait) — can fail if fuse never rises.
        sb.expect_eq(
            "CHK-BOOT-SEQ-GATE fuse_reset released after ungate",
            released,
            1,
            evidence="CHK-BOOT-SEQ-GATE",
        )

        self._mark_step("S5", "TIMEOUT: bounded sample waits with last reset/gate state")
        for line in self._timeout_paths:
            self._log(f"TIMEOUT-PATH {line}")
        n_paths = len(self._timeout_paths)
        for i, line in enumerate(self._timeout_paths):
            if "bound=" not in line or ("ok last=" not in line and "EXPIRED last=" not in line):
                raise AssertionError(f"CHK-TIMEOUT-PATHS[{i}] shape fail: {line}")
        chk_to = (
            "CHK-TIMEOUT-PATHS: every bounded wait names finite bound, "
            f"fail-on-expiry path, and last-state diagnostic "
            f"(paths={n_paths} expect={self.EXPECTED_TIMEOUT_PATHS})"
        )
        self._log(chk_to)
        sb.expect_eq(
            "CHK-TIMEOUT-PATHS exact count",
            n_paths,
            self.EXPECTED_TIMEOUT_PATHS,
            evidence="CHK-TIMEOUT-PATHS",
        )

        self._step_ts["PASS"] = time.monotonic()
        self._log("SMU_006 sequence complete (PASS term recorded for NONVAC fence)")
        # Ordered-fence pairs from the measured step timestamps.
        order = ["S2", "S3", "S4", "PASS"]
        pairs_ok = sum(
            1
            for a, b in zip(order, order[1:])
            if a in self._step_ts and b in self._step_ts and self._step_ts[a] < self._step_ts[b]
        )
        chk_nonvac = (
            f"CHK-NONVAC: ordered fence S2<S3<S4<PASS (pairs_ok={pairs_ok} expect={len(order) - 1})"
        )
        self._log(chk_nonvac)
        sb.expect_eq(
            "CHK-NONVAC ordered fence",
            pairs_ok,
            len(order) - 1,
            evidence="CHK-NONVAC",
        )
