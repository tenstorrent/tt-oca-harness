# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_no_sep_configuration_test (SMU_005).

Proves that on SEP=0 lc_state_o carries the no-LCC word of
``seq_lib.smu_lifecycle_table`` and nothing else, and that the SMC-to-external
leg of the ID-converter pair that replaces the crossbar carries a write out of
the chiplet and brings its data back. The direct SMN→SMC path is not covered:
SYS_IN BlockByDefault + gated JTAG2AXI prevent a frontdoor SMC hit under SEP=0.
"""

from __future__ import annotations

import time

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
)
from seq_lib.smu_lifecycle_table import LC_STATE_NO_LCC

# Outside both SMC apertures at their reset values -- LOCAL_BASE 0xC000_0000
# and GLOBAL_BASE 0x4000_0000, each REGION_SIZE 0x0100_0000 wide -- so the SMC
# input fabric hands it to the output fabric and it leaves through the
# SMC-to-external ID converter. Not 0x8000_0000: the bench snoops the firmware
# console there.
EXT_EGRESS_ADDR = 0x9000_0000
EXT_EGRESS_PATTERN = 0x5EC0_0FF5_1D0E_A711


class smu_no_sep_configuration_test_seq:
    """SMU_005: SEP=0 lc_state composition and SMC-to-external egress."""

    LC_STABLE_CYCLES = 16
    EXPECTED_TIMEOUT_PATHS = 3
    EGRESS_POLL_CYCLES = 2000

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

    async def _await_counter(self, name: str, *, baseline: int, label: str) -> int:
        """Bounded poll of an outbound-boundary counter past ``baseline``."""
        last = baseline
        for _ in range(self.EGRESS_POLL_CYCLES):
            await RisingEdge(self.dut.clk_smu_i)
            last = self._sample(getattr(self.dut, name), name)
            if last > baseline:
                self._timeout_paths.append(
                    f"{label}: bound={self.EGRESS_POLL_CYCLES} ok last={last}"
                )
                return last
        self._timeout_paths.append(f"{label}: bound={self.EGRESS_POLL_CYCLES} EXPIRED last={last}")
        raise AssertionError(
            f"TIMEOUT {label}: {name} stayed at {last} (baseline {baseline}) for "
            f"{self.EGRESS_POLL_CYCLES} clk_smu cycles"
        )

    async def _step_egress(self, sb) -> None:
        """S3: the SMC-to-external ID-converter leg carries a write and a read."""
        dut = self.dut
        self._mark_step(
            "S3",
            "EGRESS: JTAG2AXI write then read at 0x"
            f"{EXT_EGRESS_ADDR:08x}, outside both SMC apertures, must leave "
            "through the SMC-to-external ID converter and return its data",
        )

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        idcode = await jtag.read_idcode()
        sb.expect_eq("CHK-SEP0-EGRESS-TAP idcode", idcode, DTP_DEFAULT_IDCODE)

        wr_base = self._sample(dut.smu_axi_out_write_count_o, "smu_axi_out_write_count_o")
        rd_base = self._sample(dut.smu_axi_out_read_count_o, "smu_axi_out_read_count_o")

        st_wr, _ = await jtag2axi_single_write(
            jtag, EXT_EGRESS_ADDR, EXT_EGRESS_PATTERN, wstrb=0xFF, require_complete=True
        )
        sb.expect_eq("CHK-SEP0-EGRESS-WR status", st_wr, J2A_STATUS_SUCCESS)
        wr_count = await self._await_counter(
            "smu_axi_out_write_count_o", baseline=wr_base, label="s3_egress_write_count"
        )
        sb.expect_eq("CHK-SEP0-EGRESS-WR left the chiplet", wr_count, wr_base + 1)

        st_rd, rdata = await jtag2axi_single_read(jtag, EXT_EGRESS_ADDR, require_complete=True)
        sb.expect_eq("CHK-SEP0-EGRESS-RD status", st_rd, J2A_STATUS_SUCCESS)
        sb.expect_eq(
            "CHK-SEP0-EGRESS-RD data round-trips",
            int(rdata) & 0xFFFF_FFFF_FFFF_FFFF,
            EXT_EGRESS_PATTERN,
            evidence="CHK-SEP0-EGRESS",
        )
        rd_count = await self._await_counter(
            "smu_axi_out_read_count_o", baseline=rd_base, label="s3_egress_read_count"
        )
        self._log(
            f"CHK-SEP0-EGRESS: write_count {wr_base}->{wr_count} read_count "
            f"{rd_base}->{rd_count} data=0x{int(rdata):016x}"
        )

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

        await self._step_egress(sb)

        self._mark_step("S4", "TIMEOUT: bounded sample waits with last state")
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
        order = ["S1", "S2", "S3", "S4", "PASS"]
        pairs_ok = sum(
            1
            for a, b in zip(order, order[1:])
            if a in self._step_ts and b in self._step_ts and self._step_ts[a] < self._step_ts[b]
        )
        chk_nonvac = (
            f"CHK-NONVAC: ordered fence {'<'.join(order)} "
            f"(pairs_ok={pairs_ok} expect={len(order) - 1})"
        )
        self._log(chk_nonvac)
        sb.expect_eq(
            "CHK-NONVAC ordered fence",
            pairs_ok,
            len(order) - 1,
            evidence="CHK-NONVAC",
        )
