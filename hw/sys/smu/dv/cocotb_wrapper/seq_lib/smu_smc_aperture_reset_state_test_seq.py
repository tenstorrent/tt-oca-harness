# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC aperture CSRs, region-size pin and peripheral clock-gate enables at reset.

Spec: smc_base_config.rdl (GLOBAL_BASE, LOCAL_BASE, REGION_SIZE, CLOCK_GATE_CONTROL resets);
smc.rdl (smc_base_config at SMC base + 0x1_0000); port_table.adoc (smc_region_size_o).

The JTAG2AXI bridge reads the three 64-bit aperture registers and CLOCK_GATE_CONTROL without
writing anything, and smc_region_size_o is sampled on clk_smu_i.
"""

from __future__ import annotations

import time
from pathlib import Path

import cocotb
from cocotb.triggers import RisingEdge
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import c_header_u32, smc_addr
from seq_lib.smu_jtag_helpers import (
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    SMC_DBG_AXSIZE_8B,
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

GLOBAL_BASE_BM = c_header_u32(_BASE_CONFIG_H, "SMC_BASE_CONFIG__GLOBAL_BASE__BASE_bm")
GLOBAL_BASE_RESET = c_header_u32(_BASE_CONFIG_H, "SMC_BASE_CONFIG__GLOBAL_BASE__BASE_reset")
LOCAL_BASE_BM = c_header_u32(_BASE_CONFIG_H, "SMC_BASE_CONFIG__LOCAL_BASE__BASE_bm")
LOCAL_BASE_RESET = c_header_u32(_BASE_CONFIG_H, "SMC_BASE_CONFIG__LOCAL_BASE__BASE_reset")
REGION_SIZE_BM = c_header_u32(_BASE_CONFIG_H, "SMC_BASE_CONFIG__REGION_SIZE__SIZE_bm")
REGION_SIZE_RESET = c_header_u32(_BASE_CONFIG_H, "SMC_BASE_CONFIG__REGION_SIZE__SIZE_reset")

CG_EN_FIELDS = ("I3C", "AVS", "I2C", "UART", "TELEMETRY")
CG_EN_BM = {f: c_header_u32(_BASE_CONFIG_H, f"{_CGC}{f}_CG_EN_bm") for f in CG_EN_FIELDS}
CG_EN_RESET = {f: c_header_u32(_BASE_CONFIG_H, f"{_CGC}{f}_CG_EN_reset") for f in CG_EN_FIELDS}
CG_HYST_BM = c_header_u32(_BASE_CONFIG_H, f"{_CGC}CG_HYSTERESIS_bm")
CG_HYST_BP = c_header_u32(_BASE_CONFIG_H, f"{_CGC}CG_HYSTERESIS_bp")
CG_HYST_RESET = c_header_u32(_BASE_CONFIG_H, f"{_CGC}CG_HYSTERESIS_reset")

J2A_POLL_LIMIT = 128
CONTRACT_WAIT_KINDS = 1


class smu_smc_aperture_reset_state_test_seq:
    """Reset-state reads of the SMC aperture CSRs, the region-size pin and the clock gates."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.done = False
        self.jtag = None
        self.j2a = 0
        self.step_ts: dict[str, float] = {}
        self.sites = {
            "j2a": {"bound": f"{J2A_POLL_LIMIT} polls", "count": 0, "last": "none", "expired": 0},
        }

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _mark(self, step: str, text: str) -> None:
        self.step_ts[step] = time.monotonic()
        self._log(f"STEP {step}: {text}")

    def _cell(self, name: str, addr: int, text: str) -> None:
        self._log(f"CELL {name} addr=0x{addr:08x} {text}")

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

        self._mark("S1", "SETUP: bring-up, IDCODE, J2A gate open")
        self.jtag = jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        idcode = await jtag.read_idcode()
        if idcode != 0x1:
            raise AssertionError(f"IDCODE want 0x1 got 0x{idcode:08x}")
        gate = dut.tb_smc_jtag2axi_security_disable.value
        if not gate.is_resolvable or int(gate) & 1:
            raise AssertionError(f"SMC J2A gated: security_disable={gate}")
        self._log(f"CELL setup idcode=0x{idcode:08x} security_disable={int(gate)}")

        self._mark("S2", "read GLOBAL_BASE, LOCAL_BASE, REGION_SIZE")
        observed = []
        for name, addr, bm in (
            ("GLOBAL_BASE", ADDR_GLOBAL_BASE, GLOBAL_BASE_BM),
            ("LOCAL_BASE", ADDR_LOCAL_BASE, LOCAL_BASE_BM),
            ("REGION_SIZE", ADDR_REGION_SIZE, REGION_SIZE_BM),
        ):
            raw = await self._j2a_rd(addr, SMC_DBG_AXSIZE_8B, name)
            field = raw & bm
            self._cell(name, addr, f"raw=0x{raw:016x} field=0x{field:x}")
            observed.append(field)
        self._log(
            f"CHK-APRT-BASES: global=0x{observed[0]:x} local=0x{observed[1]:x} "
            f"region_size=0x{observed[2]:x}"
        )
        for name, got, want in zip(
            ("GLOBAL_BASE", "LOCAL_BASE", "REGION_SIZE"),
            observed,
            (GLOBAL_BASE_RESET, LOCAL_BASE_RESET, REGION_SIZE_RESET),
        ):
            sb.expect_eq(f"CHK-APRT-BASES {name} reset", got, want, evidence="APRT_BASES")

        self._mark("S3", "sample smc_region_size_o")
        await RisingEdge(dut.clk_smu_i)
        pin = self._pin("smc_region_size_o")
        self._cell("smc_region_size_o", 0, f"value=0x{pin:08x}")
        self._log(f"CHK-APRT-REGION-PIN: smc_region_size_o=0x{pin:08x}")
        sb.expect_eq(
            "CHK-APRT-REGION-PIN smc_region_size_o",
            pin,
            REGION_SIZE_RESET,
            evidence="APRT_REGION_PIN",
        )

        self._mark("S4", "read CLOCK_GATE_CONTROL")
        raw = await self._j2a_rd(ADDR_CLOCK_GATE, SMC_DBG_AXSIZE_4B, "CLOCK_GATE_CONTROL")
        word = raw & 0xFFFF_FFFF
        self._log(f"CHK-APRT-CLOCK-GATES: cg_en_word=0x{word:08x}")
        got = {f: int(bool(word & bm)) for f, bm in CG_EN_BM.items()}
        hyst = (word & CG_HYST_BM) >> CG_HYST_BP
        for f in CG_EN_FIELDS:
            self._cell(f"{f.lower()}_cg_en", ADDR_CLOCK_GATE, f"value={got[f]}")
        self._cell("cg_hysteresis", ADDR_CLOCK_GATE, f"value=0x{hyst:x}")
        sb.expect_eq(
            "CHK-APRT-CLOCK-GATES cg_en bits and cg_hysteresis",
            (got, hyst),
            ({f: CG_EN_RESET[f] for f in CG_EN_FIELDS}, CG_HYST_RESET),
            evidence="APRT_CLOCK_GATES",
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
            f"j2a_accesses_counted={self.j2a} (counted at the call sites of this seq)"
        )
        sb.expect_eq("expired TIMEOUT-PATH records", expired, 0, evidence="CHK_TIMEOUT_PATHS")
        sb.expect_eq("bounded wait kinds declared by the sequence", len(lines), CONTRACT_WAIT_KINDS)

        self.step_ts["PASS"] = time.monotonic()
        order = ["S1", "S2", "S3", "S4", "S5", "PASS"]
        for a, b in zip(order, order[1:]):
            if self.step_ts[a] >= self.step_ts[b]:
                raise AssertionError(f"CHK-NONVAC order fail: {a} not before {b}")
        self._log("CHK-NONVAC: PASS (ordered fence S1<S2<S3<S4<S5<PASS)")
        sb.expect_eq("CHK-NONVAC ordered fence", len(order), 6, evidence="CHK-NONVAC")
        self.done = True
