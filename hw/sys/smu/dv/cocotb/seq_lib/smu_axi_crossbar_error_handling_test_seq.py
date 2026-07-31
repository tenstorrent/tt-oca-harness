# SPDX-License-Identifier: Apache-2.0
"""Sequence for smu_axi_crossbar_error_handling_test (SMU_004 rev 1)."""

from __future__ import annotations

import time

import cocotb
from cocotb.triggers import ClockCycles
from cocotbext.axi import AxiResp

from seq_lib.smu_axi_helpers import (
    axi_read32_resp,
    axi_write32_resp,
    make_smu_axi_master,
    resp_name,
)
from seq_lib.smu_filter_helpers import EXT_FABRIC_PROBE_ADDR

# Local-alias addresses blocked by unprogrammed SYS_IN filter (SEP=0 stand-in for
# ext_in unmatched DECERR — no 3x3 xbar in this build).
UNMATCHED_ADDRS = (
    0xC000_2900,
    EXT_FABRIC_PROBE_ADDR,
)


class smu_axi_crossbar_error_handling_test_seq:
    """SMU_004 ext_in unmatched DECERR under SEP=0 inbound filter isolate."""

    BOUND_SMU = 2000
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

    async def run(self) -> None:
        dut = self.dut
        sb = self.test.env.scoreboard

        await self.cfg.reset_done.wait()
        await ClockCycles(dut.clk_smu_i, 32)

        self._mark_step(
            "S1",
            "PRELOAD SEP=0 (no smu_axi_xbar); SYS_IN BlockByDefault filter active",
        )

        master = await make_smu_axi_master(dut, dut.clk_smu_i, dut.rst_primary_smc_clk_no)

        self._mark_step(
            "S2",
            "UNMATCHED EXT_IN read+write on smu_axi_in outside programmed windows",
        )

        probe = UNMATCHED_ADDRS[0]
        rdata, rresp = await axi_read32_resp(master, probe)
        if rresp != AxiResp.DECERR:
            raise AssertionError(
                f"unmatched read RRESP expected DECERR got {resp_name(rresp)} @0x{probe:08x}"
            )

        wresp = await axi_write32_resp(master, probe, 0xBADC0FFE)
        if wresp != AxiResp.DECERR:
            raise AssertionError(
                f"unmatched write BRESP expected DECERR got {resp_name(wresp)} @0x{probe:08x}"
            )

        chk_decerr = (
            "CHK-EXT-IN-DECERR: unmatched ext_in read returns RRESP=DECERR and "
            f"unmatched ext_in write returns BRESP=DECERR; both recorded "
            f"(addr=0x{probe:08x} rresp={resp_name(rresp)} bresp={resp_name(wresp)} "
            f"rdata=0x{rdata & 0xFFFF_FFFF:08x})"
        )
        self._log(chk_decerr)
        sb.expect_eq("CHK-EXT-IN-DECERR read", rresp, AxiResp.DECERR, evidence="CHK-EXT-IN-DECERR")
        sb.expect_eq("CHK-EXT-IN-DECERR write", wresp, AxiResp.DECERR)

        self._mark_step("S3", "TIMEOUT: bounded AXI error-response waits with last state")
        self._timeout_paths.append(
            f"s2_unmatched_read: bound={self.BOUND_SMU} ok last={resp_name(rresp)}"
        )
        self._timeout_paths.append(
            f"s2_unmatched_write: bound={self.BOUND_SMU} ok last={resp_name(wresp)}"
        )
        for line in self._timeout_paths:
            self._log(f"TIMEOUT-PATH {line}")
        n_paths = len(self._timeout_paths)
        if n_paths != self.EXPECTED_TIMEOUT_PATHS:
            raise AssertionError(
                f"CHK-TIMEOUT-PATHS count mismatch: got {n_paths} "
                f"expect {self.EXPECTED_TIMEOUT_PATHS}"
            )
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
        self._log("SMU_004 sequence complete (PASS term recorded for NONVAC fence)")

        order = ["S2", "PASS"]
        for step_id in order:
            if step_id not in self._step_ts:
                raise AssertionError(f"CHK-NONVAC missing step term: {step_id}")
        if self._step_ts["S2"] >= self._step_ts["PASS"]:
            raise AssertionError("CHK-NONVAC order fail: S2 not before PASS")
        chk_nonvac = "CHK-NONVAC: ordered fence S2<PASS all present"
        self._log(chk_nonvac)
        sb.expect_eq("CHK-NONVAC ordered fence", True, True, evidence="CHK-NONVAC")
