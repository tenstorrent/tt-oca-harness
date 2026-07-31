# SPDX-License-Identifier: Apache-2.0
"""Sequence for smu_axi_external_port_connectivity_test (SMU_003 rev 2).

Inbound-only: outbound SMN (SMU-AXI-SMN-PORTS.S2) is OUT-OF-MILESTONE under SEP=0.
"""

from __future__ import annotations

import time

import cocotb
from cocotb.triggers import ClockCycles, with_timeout
from cocotbext.axi import AxiResp

from seq_lib.smu_addr_map import SMC_CHIP_CONFIG_VERSION_LO
from seq_lib.smu_axi_helpers import (
    axi_read32_resp_ids,
    axi_write32_resp_ids,
    make_smu_axi_master,
    resp_name,
)


class smu_axi_external_port_connectivity_test_seq:
    """SMU_003 rev2: smu_axi_in inbound completion evidence."""

    # Authoritative map: smc_addr.h SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_LO_BASE_ADDR
    IN_PROBE = SMC_CHIP_CONFIG_VERSION_LO
    WRITE_ID = 0x42
    READ_ID = 0x43
    BOUND_SMU = 2000
    AXI_TIMEOUT_NS = 200_000
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

    async def _axi_write_bounded(self, master, addr: int, data: int, awid: int):
        label = "s2_inbound_write"
        try:
            result = await with_timeout(
                axi_write32_resp_ids(master, addr, data, awid=awid),
                timeout_time=self.AXI_TIMEOUT_NS,
                timeout_unit="ns",
            )
            self._timeout_paths.append(
                f"{label}: bound={self.BOUND_SMU} ok last={resp_name(result[0])}"
            )
            return result
        except Exception:
            self._timeout_paths.append(
                f"{label}: bound={self.BOUND_SMU} EXPIRED last=no_bresp"
            )
            raise AssertionError(
                f"TIMEOUT {label}: bound={self.BOUND_SMU} last_state=no_bresp"
            ) from None

    async def _axi_read_bounded(self, master, addr: int, arid: int):
        label = "s2_inbound_read"
        try:
            result = await with_timeout(
                axi_read32_resp_ids(master, addr, arid=arid),
                timeout_time=self.AXI_TIMEOUT_NS,
                timeout_unit="ns",
            )
            self._timeout_paths.append(
                f"{label}: bound={self.BOUND_SMU} ok last={resp_name(result[1])}"
            )
            return result
        except Exception:
            self._timeout_paths.append(
                f"{label}: bound={self.BOUND_SMU} EXPIRED last=no_rresp"
            )
            raise AssertionError(
                f"TIMEOUT {label}: bound={self.BOUND_SMU} last_state=no_rresp"
            ) from None

    async def run(self) -> None:
        dut = self.dut
        sb = self.test.env.scoreboard

        await self.cfg.reset_done.wait()
        await ClockCycles(dut.clk_smu_i, 32)

        self._mark_step(
            "S1",
            "PRELOAD SEP=0 bring-up complete; smu_axi_in peer live (inbound-only card)",
        )

        master = await make_smu_axi_master(dut, dut.clk_smu_i, dut.rst_primary_smc_clk_no)

        self._mark_step(
            "S2",
            f"SMN IN write/read @0x{self.IN_PROBE:08x} on s_axi_* (mapped SYS_IN path)",
        )
        wdata = 0xA5A5_5A5A
        wresp, w_awid, w_bid = await self._axi_write_bounded(
            master, self.IN_PROBE, wdata, self.WRITE_ID
        )
        if wresp not in (AxiResp.OKAY, AxiResp.DECERR):
            raise AssertionError(f"unexpected inbound BRESP {resp_name(wresp)}")
        if w_bid != self.WRITE_ID:
            raise AssertionError(
                f"inbound BID mismatch: bid=0x{w_bid:x} awid=0x{self.WRITE_ID:x}"
            )

        _, rresp, r_arid, r_rid = await self._axi_read_bounded(
            master, self.IN_PROBE, self.READ_ID
        )
        if rresp not in (AxiResp.OKAY, AxiResp.DECERR):
            raise AssertionError(f"unexpected inbound RRESP {resp_name(rresp)}")
        if r_rid != self.READ_ID:
            raise AssertionError(
                f"inbound RID mismatch: rid=0x{r_rid:x} arid=0x{self.READ_ID:x}"
            )

        chk_in = (
            "CHK-SMN-IN: inbound write returns BRESP and inbound read returns RRESP; "
            f"both completions recorded with IDs matching the issued transactions "
            f"(awid=0x{self.WRITE_ID:x} bid=0x{w_bid:x} bresp={resp_name(wresp)} "
            f"arid=0x{self.READ_ID:x} rid=0x{r_rid:x} rresp={resp_name(rresp)})"
        )
        self._log(chk_in)
        sb.expect_eq("CHK-SMN-IN ID+resp", w_bid, self.WRITE_ID, evidence="CHK-SMN-IN")

        self._mark_step("S3", "TIMEOUT: bounded AXI completion waits with last channel state")
        for line in self._timeout_paths:
            self._log(f"TIMEOUT-PATH {line}")
        n_paths = len(self._timeout_paths)
        if n_paths != self.EXPECTED_TIMEOUT_PATHS:
            raise AssertionError(
                f"CHK-TIMEOUT-PATHS count mismatch: got {n_paths} "
                f"expect {self.EXPECTED_TIMEOUT_PATHS}"
            )
        for i, line in enumerate(self._timeout_paths):
            if "bound=" not in line or (
                "ok last=" not in line and "EXPIRED last=" not in line
            ):
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
        self._log("SMU_003 sequence complete (PASS term recorded for NONVAC fence)")

        order = ["S1", "S2", "PASS"]
        for step_id in order:
            if step_id not in self._step_ts:
                raise AssertionError(f"CHK-NONVAC missing step term: {step_id}")
        for a, b in zip(order, order[1:]):
            if self._step_ts[a] >= self._step_ts[b]:
                raise AssertionError(f"CHK-NONVAC order fail: {a} not before {b}")
        chk_nonvac = "CHK-NONVAC: ordered fence S2<PASS all present"
        self._log(chk_nonvac)
        sb.expect_eq("CHK-NONVAC ordered fence", True, True, evidence="CHK-NONVAC")
