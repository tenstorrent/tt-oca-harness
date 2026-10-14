# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC base-configuration register state and the region-size pin at boot.

Spec: smc_base_config.rdl (GLOBAL_BASE, LOCAL_BASE, REGION_SIZE, CLOCK_GATE_CONTROL and
HANG_DET_* resets); smc.rdl (smc_base_config at SMC base + 0x1_0000); port_table.adoc
(smc_region_size_o).

The JTAG2AXI bridge reads the registers without writing anything and smc_region_size_o is
sampled on clk_smu_i. GLOBAL_BASE, LOCAL_BASE, REGION_SIZE and CLOCK_GATE_CONTROL are 64-bit
registers read with 8-byte accesses. The HANG_DET_* control and threshold registers declare no
regwidth, so the RDL makes them 32 bits wide at 8-byte spacing; each is read with a 4-byte
access and its 32-bit lane compared, with the same expected values the test steps list.
"""

from __future__ import annotations

from pathlib import Path

import cocotb
from cocotb.triggers import RisingEdge, with_timeout
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import c_header_u32, smc_addr
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    SMC_DBG_AXSIZE_8B,
    axi64_unpack32,
    jtag2axi_single_read,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)

_BASE_CONFIG_H = (
    Path(__file__).resolve().parents[6] / "hw/sys/smc/regs/gen/c/blocks/smc_base_config.h"
)
_CGC = "SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__"

ADDR_GLOBAL_BASE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_GLOBAL_BASE_BASE_ADDR")
ADDR_LOCAL_BASE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_LOCAL_BASE_BASE_ADDR")
ADDR_REGION_SIZE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
ADDR_CLOCK_GATE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
HANG_DET_CTRL = (
    ("SYS_AXI", smc_addr("SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SYS_AXI_CTRL_BASE_ADDR")),
    ("SEP_AXI", smc_addr("SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SEP_AXI_CTRL_BASE_ADDR")),
    ("DATA_ACCEL", smc_addr("SMC_TOP_SMC_BASE_CONFIG_HANG_DET_DATA_ACCEL_CTRL_BASE_ADDR")),
)
HANG_DET_THRESHOLD = (
    ("SYS_AXI", smc_addr("SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SYS_AXI_TIMEOUT_THRESHOLD_BASE_ADDR")),
    ("SEP_AXI", smc_addr("SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SEP_AXI_TIMEOUT_THRESHOLD_BASE_ADDR")),
    (
        "DATA_ACCEL",
        smc_addr("SMC_TOP_SMC_BASE_CONFIG_HANG_DET_DATA_ACCEL_TIMEOUT_THRESHOLD_BASE_ADDR"),
    ),
)

GLOBAL_BASE_RESET = c_header_u32(_BASE_CONFIG_H, "SMC_BASE_CONFIG__GLOBAL_BASE__BASE_reset")
LOCAL_BASE_RESET = c_header_u32(_BASE_CONFIG_H, "SMC_BASE_CONFIG__LOCAL_BASE__BASE_reset")
REGION_SIZE_BM = c_header_u32(_BASE_CONFIG_H, "SMC_BASE_CONFIG__REGION_SIZE__SIZE_bm")
REGION_SIZE_RESET = c_header_u32(_BASE_CONFIG_H, "SMC_BASE_CONFIG__REGION_SIZE__SIZE_reset")
CG_HYST_BP = c_header_u32(_BASE_CONFIG_H, f"{_CGC}CG_HYSTERESIS_bp")
CG_HYST_RESET = c_header_u32(_BASE_CONFIG_H, f"{_CGC}CG_HYSTERESIS_reset")
CLOCK_GATE_RESET_WORD = CG_HYST_RESET << CG_HYST_BP
THRESHOLD_RESET = c_header_u32(
    _BASE_CONFIG_H, "SMC_BASE_CONFIG__HANG_DET_TIMEOUT_THRESHOLD__VALUE_reset"
)

J2A_POLL_LIMIT = 128
RESET_DONE_BOUND_NS = 200000
EXPECTED_WAIT_KINDS = 2


class smu_smc_base_config_state_test_seq:
    """Reset-state reads of the SMC base-configuration block and the region-size pin."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.done = False
        self.jtag = None
        self.j2a = 0
        self.sites = {
            "reset_done": {
                "bound": f"{RESET_DONE_BOUND_NS} ns",
                "count": 0,
                "last": "none",
                "expired": 0,
            },
            "j2a": {"bound": f"{J2A_POLL_LIMIT} polls", "count": 0, "last": "none", "expired": 0},
        }

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _mark(self, step: str, text: str) -> None:
        self._log(f"STEP {step}: {text}")

    async def _wait_reset_done(self) -> None:
        rec = self.sites["reset_done"]
        try:
            await with_timeout(self.cfg.reset_done.wait(), RESET_DONE_BOUND_NS, "ns")
        except TimeoutError as exc:
            rec["expired"] += 1
            rec["last"] = f"EXPIRED reset_done not set {exc}"
            self._log(f"TIMEOUT-PATH reset_done: bound={rec['bound']} EXPIRED last={exc}")
            raise
        rec["count"] += 1
        rec["last"] = "reset_done set"

    async def _j2a_rd(self, addr: int, size: int, label: str) -> int:
        """One counted JTAG2AXI read; an expiry is recorded and re-raised."""
        rec = self.sites["j2a"]
        try:
            status, rdata = await jtag2axi_single_read(
                self.jtag, addr, size=size, poll_limit=J2A_POLL_LIMIT, require_complete=True
            )
        except TimeoutError as exc:
            rec["expired"] += 1
            rec["last"] = f"EXPIRED {label} {exc}"
            self._log(f"TIMEOUT-PATH j2a: bound={rec['bound']} EXPIRED last={exc}")
            raise
        require_jtag_tdo_resolved(f"J2A RD {label} @0x{addr:08x}")
        self.j2a += 1
        rec["count"] = self.j2a
        rec["last"] = f"{label} status={status}"
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A RD {label} @0x{addr:08x} status={status}")
        return int(rdata)

    async def _j2a_rd32(self, addr: int, label: str) -> int:
        raw = await self._j2a_rd(addr, SMC_DBG_AXSIZE_4B, label)
        return axi64_unpack32(addr, raw)

    def _pin(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on this tb_top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val)

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        dut = self.dut

        self._mark("S1", "SETUP: reset_done, TAP reset, IDCODE, J2A gate open")
        await self._wait_reset_done()
        self.jtag = jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:08x} got 0x{idcode:08x}")
        gate = dut.tb_smc_jtag2axi_security_disable.value
        if not gate.is_resolvable or int(gate) & 1:
            raise AssertionError(f"SMC J2A gated: security_disable={gate}")
        self._log(f"CELL setup idcode=0x{idcode:08x} security_disable={int(gate)}")

        self._mark("S2", "read GLOBAL_BASE, LOCAL_BASE, REGION_SIZE")
        global_raw = await self._j2a_rd(ADDR_GLOBAL_BASE, SMC_DBG_AXSIZE_8B, "GLOBAL_BASE")
        self._log(f"CELL global_base addr=0x{ADDR_GLOBAL_BASE:08x} raw=0x{global_raw:016x}")
        local_raw = await self._j2a_rd(ADDR_LOCAL_BASE, SMC_DBG_AXSIZE_8B, "LOCAL_BASE")
        self._log(f"CELL local_base addr=0x{ADDR_LOCAL_BASE:08x} raw=0x{local_raw:016x}")
        size_raw = await self._j2a_rd(ADDR_REGION_SIZE, SMC_DBG_AXSIZE_8B, "REGION_SIZE")
        size = size_raw & REGION_SIZE_BM
        self._log(
            f"CELL region_size addr=0x{ADDR_REGION_SIZE:08x} raw=0x{size_raw:016x} size=0x{size:x}"
        )
        sb.expect_eq(
            "CHK-BOOT-BASECFG-APERTURE GLOBAL_BASE, LOCAL_BASE, REGION_SIZE reset values",
            (global_raw, local_raw, size),
            (GLOBAL_BASE_RESET, LOCAL_BASE_RESET, REGION_SIZE_RESET),
            evidence="BOOT_BASECFG_APERTURE",
        )

        self._mark("S3", "sample smc_region_size_o")
        await RisingEdge(dut.clk_smu_i)
        pin = self._pin("smc_region_size_o")
        self._log(f"CELL region_size_port smc_region_size_o=0x{pin:08x}")
        sb.expect_eq(
            "CHK-BOOT-BASECFG-REGION-PORT smc_region_size_o vs reset and REGION_SIZE",
            (pin, pin),
            (REGION_SIZE_RESET, size),
            evidence="BOOT_BASECFG_REGION_PORT",
        )

        self._mark("S4", "read CLOCK_GATE_CONTROL and the hang-detector registers")
        cg_raw = await self._j2a_rd(ADDR_CLOCK_GATE, SMC_DBG_AXSIZE_8B, "CLOCK_GATE_CONTROL")
        self._log(f"CELL clock_gate_control addr=0x{ADDR_CLOCK_GATE:08x} raw=0x{cg_raw:016x}")
        ctrl = []
        for name, addr in HANG_DET_CTRL:
            val = await self._j2a_rd32(addr, f"HANG_DET_{name}_CTRL")
            self._log(f"CELL hang_det_ctrl addr=0x{addr:08x} value=0x{val:x}")
            ctrl.append(val)
        thr = []
        for name, addr in HANG_DET_THRESHOLD:
            val = await self._j2a_rd32(addr, f"HANG_DET_{name}_TIMEOUT_THRESHOLD")
            self._log(f"CELL hang_det_threshold addr=0x{addr:08x} value=0x{val:x}")
            thr.append(val)
        sb.expect_eq(
            "CHK-BOOT-BASECFG-CG-HANG CLOCK_GATE_CONTROL and hang-detector reset values",
            (cg_raw, *ctrl, *thr),
            (CLOCK_GATE_RESET_WORD, 0, 0, 0, THRESHOLD_RESET, THRESHOLD_RESET, THRESHOLD_RESET),
            evidence="BOOT_BASECFG_CG_HANG",
        )

        self._mark("S5", "TIMEOUT: bounded waits and last state")
        lines = []
        for site, rec in self.sites.items():
            state = "EXPIRED" if rec["expired"] else "ok"
            lines.append(
                f"{site}: bound={rec['bound']} {state} count={rec['count']} last={rec['last']}"
            )
        for line in lines:
            self._log(f"TIMEOUT-PATH {line}")
        expired = sum(rec["expired"] for rec in self.sites.values())
        self._log(
            f"CHK-TIMEOUT-PATHS: sites={len(lines)} expired={expired} "
            f"j2a_accesses_counted={self.j2a}"
        )
        sb.expect_eq("expired TIMEOUT-PATH records", expired, 0, evidence="CHK_TIMEOUT_PATHS")
        sb.expect_eq("bounded wait kinds named by the test steps", len(lines), EXPECTED_WAIT_KINDS)
        self.done = True
