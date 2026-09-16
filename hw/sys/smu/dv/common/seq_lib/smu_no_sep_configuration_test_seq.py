# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_no_sep_configuration_test (SMU_005).

Proves that on SEP=0 lc_state_o carries the no-LCC word of
``seq_lib.smu_lifecycle_table`` and nothing else. The direct SMN→SMC path is
not covered: SYS_IN BlockByDefault + gated JTAG2AXI prevent a frontdoor SMC
hit under SEP=0.
"""

from __future__ import annotations

import time

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from seq_lib.smu_lifecycle_table import LC_STATE_NO_LCC


class smu_no_sep_configuration_test_seq:
    """SMU_005: SEP=0 lc_state composition."""

    LC_STABLE_CYCLES = 16
    EXPECTED_TIMEOUT_PATHS = 1

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

    async def run(self) -> None:
        dut = self.dut
        sb = self.test.env.scoreboard

        await self.cfg.reset_done.wait()
        await ClockCycles(dut.clk_smu_i, 16)

        self._mark_step(
            "S1",
            "PRELOAD build/run with SEP=0; clocks/resets valid; SEP aperture tie-off",
        )
        sep_base = self._sample(dut.sep_global_base_o, "sep_global_base_o")
        sep_size = self._sample(dut.sep_region_size_o, "sep_region_size_o")
        if sep_base != 0 or sep_size != 0:
            raise AssertionError(
                f"SEP=0 aperture not tied off: base=0x{sep_base:x} size=0x{sep_size:x}"
            )

        self._mark_step(
            "S2",
            f"LC STATE: sample lc_state_o == 0x{LC_STATE_NO_LCC:02x} for >=16 clk_smu cycles",
        )
        stable = 0
        for _ in range(self.LC_STABLE_CYCLES):
            await RisingEdge(dut.clk_smu_i)
            last_lc = self._sample(dut.lc_state_o, "lc_state_o") & 0xFF
            if last_lc != LC_STATE_NO_LCC:
                self._timeout_paths.append(
                    f"s2_lc_stable: bound={self.LC_STABLE_CYCLES} EXPIRED last=0x{last_lc:02x}"
                )
                raise AssertionError(
                    f"lc_state_o != 0x{LC_STATE_NO_LCC:02x} at stable sample {stable}: "
                    f"0x{last_lc:02x}"
                )
            stable += 1
        self._timeout_paths.append(
            f"s2_lc_stable: bound={self.LC_STABLE_CYCLES} ok last=0x{LC_STATE_NO_LCC:02x}"
        )
        chk_lc = (
            f"CHK-SEP0-LC: lc_state_o == 0x{LC_STATE_NO_LCC:02x} sampled stable for "
            f">={self.LC_STABLE_CYCLES} clk_smu_i cycles (samples={stable})"
        )
        self._log(chk_lc)
        sb.expect_eq("CHK-SEP0-LC stable", stable, self.LC_STABLE_CYCLES, evidence="CHK-SEP0-LC")

        self._mark_step("S3", "TIMEOUT: bounded sample waits with last state")
        for line in self._timeout_paths:
            self._log(f"TIMEOUT-PATH {line}")
        n_paths = len(self._timeout_paths)
        if n_paths != self.EXPECTED_TIMEOUT_PATHS:
            raise AssertionError(
                f"CHK-TIMEOUT-PATHS count mismatch: got {n_paths} "
                f"expect {self.EXPECTED_TIMEOUT_PATHS}"
            )
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
        self._log("SMU_005 sequence complete (PASS term recorded for NONVAC fence)")

        # Ordered-fence pairs from the measured step timestamps.
        order = ["S1", "S2", "PASS"]
        pairs_ok = sum(
            1
            for a, b in zip(order, order[1:])
            if a in self._step_ts and b in self._step_ts and self._step_ts[a] < self._step_ts[b]
        )
        chk_nonvac = (
            f"CHK-NONVAC: ordered fence S1<S2<PASS (pairs_ok={pairs_ok} expect={len(order) - 1})"
        )
        self._log(chk_nonvac)
        sb.expect_eq(
            "CHK-NONVAC ordered fence",
            pairs_ok,
            len(order) - 1,
            evidence="CHK-NONVAC",
        )
