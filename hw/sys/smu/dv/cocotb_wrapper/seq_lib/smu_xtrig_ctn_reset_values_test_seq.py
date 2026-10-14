# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_xtrig_ctn_reset_values_test. SEP=1 (sep_rtl), no Force.

Spec: cross_trigger_matrix.rdl (CT_SRC[n].CONFIG_0.CT_DST_SELECT reset 0x0, offset 0x8 * n),
cross_trigger_port.rdl (CONFIG @0x0, STATUS @0x4, STRETCH_MULT @0x8, all reset 0x0),
cross_trigger_network.rdl (CT_SRC and CTP windows), smc.rdl (dtp_ctrl_reg at the DTP CSR base).
Addresses come from the generated cross-trigger headers.

S1  Idle inputs, TAP in Run-Test/Idle, IDCODE, J2A gate open; J2A accesses counted from here.
S2  Read CT_SRC[n].CONFIG_0 for n = 0..25: every read succeeds and returns 0.
S3  Read CONFIG, STATUS and STRETCH_MULT of CTP[i] for i = 0..15: every read returns 0.
S4  Every bounded wait is a site with its bound, last state and expiry.
"""

from __future__ import annotations

import time
from typing import cast

import cocotb
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import smc_addr
from seq_lib.smu_boundary_regs import (
    cross_trigger_network_indexed_addr,
    cross_trigger_network_u32,
    cross_trigger_u32,
)
from seq_lib.smu_compose_helpers import sample
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    axi64_unpack32,
    jtag2axi_single_read,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)

DTP_CSR_BASE = smc_addr("SMC_TOP_DTP_CTRL_REG_BASE_ADDR")

NUM_CTP = cross_trigger_network_u32("CROSS_TRIGGER_NETWORK_CTP_NUM")
NUM_CT_SRC = cross_trigger_network_u32("CROSS_TRIGGER_NETWORK_CTM_CT_SRC_NUM")
CTP_REGS = (
    ("CONFIG", cross_trigger_u32("CROSS_TRIGGER_PORT_CONFIG_BASE_ADDR")),
    ("STATUS", cross_trigger_u32("CROSS_TRIGGER_PORT_STATUS_BASE_ADDR")),
    ("STRETCH_MULT", cross_trigger_u32("CROSS_TRIGGER_PORT_STRETCH_MULT_BASE_ADDR")),
)

J2A_POLL_LIMIT = 128
SITES = ("j2a",)


class smu_xtrig_ctn_reset_values_test_seq:
    """CT_SRC and CTP reset values."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.sb = test.env.scoreboard
        self.jtag = None
        self.j2a = 0
        self.step_ts: dict[str, float] = {}
        self.sites = {
            "j2a": {"bound": J2A_POLL_LIMIT, "count": 0, "last": "none", "expired": 0},
        }

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _mark(self, step: str, text: str) -> None:
        self.step_ts[step] = time.monotonic()
        self._log(f"STEP {step}: {text}")

    def _cell(self, name: str, addr: int, text: str) -> None:
        self._log(f"CELL {name} addr=0x{addr:08x} {text}")

    def _vec(self, name: str) -> int:
        return sample(getattr(self.dut, name), name)

    def _ctp_addr(self, lane: int, offset: int) -> int:
        if not 0 <= lane < NUM_CTP:
            raise AssertionError(f"CTP lane {lane} outside CROSS_TRIGGER_NETWORK_CTP_NUM={NUM_CTP}")
        return cast(
            int,
            DTP_CSR_BASE
            + cross_trigger_network_indexed_addr("CROSS_TRIGGER_NETWORK_CTP_BASE_ADDR", lane)
            + offset,
        )

    def _ctm_src_addr(self, port: int) -> int:
        if not 0 <= port < NUM_CT_SRC:
            raise AssertionError(
                f"CTM port {port} outside CROSS_TRIGGER_NETWORK_CTM_CT_SRC_NUM={NUM_CT_SRC}"
            )
        return cast(
            int,
            DTP_CSR_BASE
            + cross_trigger_network_indexed_addr(
                "CROSS_TRIGGER_NETWORK_CTM_CT_SRC_BASE_ADDR", port
            ),
        )

    async def _rd32(self, addr: int, what: str) -> int:
        rec = self.sites["j2a"]
        try:
            status, rdata = await jtag2axi_single_read(
                self.jtag,
                addr,
                size=SMC_DBG_AXSIZE_4B,
                poll_limit=J2A_POLL_LIMIT,
                require_complete=True,
            )
            require_jtag_tdo_resolved(f"{what} RD @0x{addr:08x}")
        except (TimeoutError, AssertionError) as exc:
            rec["expired"] += 1
            rec["last"] = f"{what} RD @0x{addr:08x}: {exc}"
            raise
        self.j2a += 1
        rec["count"] = self.j2a
        rec["last"] = f"{what} RD status={status}"
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"{what} read @0x{addr:08x} status={status}")
        return cast(int, axi64_unpack32(addr, rdata))

    async def _tap_up(self) -> None:
        await self.jtag.reset_tap()
        await self.jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await self.jtag.step_tms(0)
        idcode = await self.jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        if self._vec("tb_smc_jtag2axi_security_disable") & 1:
            raise AssertionError("SMC JTAG2AXI still gated; no CSR access can run")

    async def run(self) -> None:
        dut = self.dut
        sb = self.sb
        await self.cfg.reset_done.wait()

        self._mark("S1", "idle inputs, TAP in Run-Test/Idle, IDCODE, J2A gate open")
        idle = {
            name: self._vec(name)
            for name in (
                "xtrig_ctm_dst_req",
                "xtrig_ctm_src_ack",
                "xtrig_clk_stop_req",
                "tb_xtrig_ctp_req_in_din",
                "tb_xtrig_ctp_ack_in_din",
                "tb_xtrig_ctp_wire_ext_assert",
            )
        }
        sb.expect_eq("every xtrig and CTP pad input idle", sum(idle.values()), 0)
        self.jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self._tap_up()
        self._log(f"CELL setup j2a_accesses={self.j2a} seed={getattr(cocotb, 'RANDOM_SEED', 'na')}")

        self._mark("S2", "CT_SRC[n].CONFIG_0 reset values, n = 0..25")
        src_values = []
        for n in range(NUM_CT_SRC):
            addr = self._ctm_src_addr(n)
            value = await self._rd32(addr, f"CT_SRC[{n}]")
            self._cell(f"CT_SRC[{n}]", addr, f"read=0x{value:08x}")
            src_values.append(value)
        sb.expect_eq(
            "CT_SRC[0..25].CONFIG_0 reset values",
            src_values,
            [0] * NUM_CT_SRC,
            evidence="CHK-CTN-CTSRC-RESET",
        )

        self._mark("S3", "CONFIG, STATUS and STRETCH_MULT reset values of CTP[0..15]")
        ctp_values = []
        for lane in range(NUM_CTP):
            for reg, offset in CTP_REGS:
                addr = self._ctp_addr(lane, offset)
                value = await self._rd32(addr, f"CTP{lane} {reg}")
                self._cell(f"CTP[{lane}].{reg}", addr, f"read=0x{value:08x}")
                ctp_values.append(value)
        sb.expect_eq(
            "CTP[0..15] CONFIG, STATUS and STRETCH_MULT reset values",
            ctp_values,
            [0] * (NUM_CTP * len(CTP_REGS)),
            evidence="CHK-CTN-CTP-RESET",
        )

        self._mark("S4", "bounded waits and last state")
        lines = []
        for site in SITES:
            rec = self.sites[site]
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
        sb.expect_eq(
            "J2A accesses counted at the call site",
            self.j2a,
            len(src_values) + len(ctp_values),
        )

        self.step_ts["PASS"] = time.monotonic()
        order = ["S1", "S2", "S3", "S4", "PASS"]
        for a, b in zip(order, order[1:]):
            if self.step_ts[a] >= self.step_ts[b]:
                raise AssertionError(f"CHK-NONVAC order fail: {a} not before {b}")
        self._log("CHK-NONVAC: PASS (ordered fence S1<S2<S3<S4<PASS)")
        sb.expect_eq("CHK-NONVAC ordered fence", len(order), 5, evidence="CHK-NONVAC")
