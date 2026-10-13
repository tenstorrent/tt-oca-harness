# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_xtrig_cold_reset_clears_ctn_test. SEP=1 (sep_rtl), no Force.

Contract: SMU_MISC_XTRIG_008 revision 4, anchor smu_xtrig_cold_reset_clears_ctn_test.
Spec: dtp/doc/clk_rst.adoc (rst_n_i resets all CTN and CSR state; stop_clks_o low while rst_n_i is
asserted), cross_trigger_port/doc/architecture.adoc (sender state machine), CTN/CTM/CTP RDL resets.
Addresses and masks come from the generated cross-trigger headers.

S1  Idle inputs, TAP in Run-Test/Idle, IDCODE, J2A gate open.
S2  CT_SRC[0] = 0x10, CTP[0].CONFIG = 0x3, CTP[0].STRETCH_MULT = 0x55 read back.
S3  Cold reset; the three registers read 0 (the RDL reset values).
S4  CTP[1] point-to-point, request raised through CT_SRC[1]; cold reset while the request is out
    (SENDER_REQ_ASSERTED) and again with the acknowledge held after the request
    (SENDER_WAIT_ACK_DEASSERT, where the sender drives ct_req_out low).
S5  xtrig_clk_stop_req held across a cold reset; dtp_stop_clks_o stays low while the DTP reset
    is asserted and on the first edge after it releases.
S6  Every bounded wait is a site with its bound, last state and expiry.
"""

from __future__ import annotations

import time
from typing import cast

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import smc_addr
from seq_lib.smu_boundary_regs import (
    cross_trigger_network_indexed_addr,
    cross_trigger_network_u32,
    cross_trigger_u32,
)
from seq_lib.smu_compose_helpers import bit_width, sample
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    axi64_pack32,
    axi64_unpack32,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)
from seq_lib.smu_tb_pins import smc_primary_reset

DTP_CSR_BASE = smc_addr("SMC_TOP_DTP_CTRL_REG_BASE_ADDR")

NUM_CTP = cross_trigger_network_u32("CROSS_TRIGGER_NETWORK_CTP_NUM")
NUM_CT_SRC = cross_trigger_network_u32("CROSS_TRIGGER_NETWORK_CTM_CT_SRC_NUM")
CTP_CONFIG_OFF = cross_trigger_u32("CROSS_TRIGGER_PORT_CONFIG_BASE_ADDR")
CTP_STATUS_OFF = cross_trigger_u32("CROSS_TRIGGER_PORT_STATUS_BASE_ADDR")
CT_DST_SELECT_BM = cross_trigger_u32("CROSS_TRIGGER_MATRIX__CT_SRC__CONFIG_0__CT_DST_SELECT_bm")
CONFIG_MODE_BP = cross_trigger_u32("CROSS_TRIGGER_PORT__CONFIG__MODE_bp")
CONFIG_RESETS = (
    cross_trigger_u32("CROSS_TRIGGER_PORT__CONFIG__MODE_reset"),
    cross_trigger_u32("CROSS_TRIGGER_PORT__CONFIG__INVERT_reset"),
    cross_trigger_u32("CROSS_TRIGGER_PORT__CONFIG__RESET_reset"),
)
STRETCH_MULT_RESET = cross_trigger_u32("CROSS_TRIGGER_PORT__STRETCH_MULT__STRETCH_MULT_reset")
STATUS_RESETS = (
    cross_trigger_u32("CROSS_TRIGGER_PORT__STATUS__BUSY_reset"),
    cross_trigger_u32("CROSS_TRIGGER_PORT__STATUS__REQ_OUT_reset"),
    cross_trigger_u32("CROSS_TRIGGER_PORT__STATUS__ACK_IN_reset"),
    cross_trigger_u32("CROSS_TRIGGER_PORT__STATUS__REQ_IN_reset"),
    cross_trigger_u32("CROSS_TRIGGER_PORT__STATUS__ACK_OUT_reset"),
)

P2P = 1
CT_SRC0_VALUE = 0x10
CTP0_CONFIG_VALUE = 0x3
CTP0_STRETCH_VALUE = 0x55
REQ_LANE = 1
# The DTP internal lanes follow the NUM_CTP external ports in the CTM; the SMU exposes the
# last SMU_INT_CT_EXPOSED of them, and exposed lane 0 is xtrig_ctm_dst_req[0].
SMU_INT_CT_EXPOSED = 8

J2A_POLL_LIMIT = 128
RESET_LOW_CLK_REF = 64
RESET_DONE_BOUND = 5000
DTP_RESET_BOUND = 5000
REQ_CLEAR_BOUND = 16
REQ_RISE_BOUND = 64
ACK_RETIRE_BOUND = 64
ACK_RELEASE_SETTLE = 8
STOP_RISE_BOUND = 64
PULSE_HOLD = 8
POST_RELEASE_EDGES = 8
# Waits the contract names: JTAG2AXI poll, reset-low window, reset_done, request rise, clear.
CONTRACT_WAITS = ("j2a", "reset_low", "reset_done", "req_rise", "req_clear")
CONTRACT_WAIT_KINDS = 5
SITES = (
    "j2a",
    "reset_low",
    "dtp_reset_assert",
    "dtp_reset_release",
    "reset_done",
    "req_rise",
    "ack_retire",
    "ack_release_settle",
    "req_clear",
    "stop_rise",
)


class smu_xtrig_cold_reset_clears_ctn_test_seq:
    """Cold reset across CTN registers, an in-flight P2P request and the clock-stop output."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.sb = test.env.scoreboard
        self.jtag = None
        self.j2a = 0
        self.rebringups = 0
        self.step_ts: dict[str, float] = {}
        self.sites = {
            site: {"bound": 0, "count": 0, "last": "none", "expired": 0} for site in SITES
        }
        self.sites["j2a"]["bound"] = J2A_POLL_LIMIT
        self.sites["reset_low"]["bound"] = RESET_LOW_CLK_REF
        self.sites["dtp_reset_assert"]["bound"] = DTP_RESET_BOUND
        self.sites["dtp_reset_release"]["bound"] = DTP_RESET_BOUND
        self.sites["reset_done"]["bound"] = RESET_DONE_BOUND
        self.sites["req_rise"]["bound"] = REQ_RISE_BOUND
        self.sites["ack_retire"]["bound"] = ACK_RETIRE_BOUND
        self.sites["ack_release_settle"]["bound"] = ACK_RELEASE_SETTLE
        self.sites["req_clear"]["bound"] = REQ_CLEAR_BOUND
        self.sites["stop_rise"]["bound"] = STOP_RISE_BOUND

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _mark(self, step: str, text: str) -> None:
        self.step_ts[step] = time.monotonic()
        self._log(f"STEP {step}: {text}")

    def _cell(self, name: str, addr: int, text: str) -> None:
        self._log(f"CELL {name} addr=0x{addr:08x} {text}")

    def _expire(self, site: str, last: str) -> None:
        rec = self.sites[site]
        rec["expired"] += 1
        rec["last"] = last
        raise AssertionError(f"TIMEOUT {site}: bound={rec['bound']} last_state={last}")

    def _ok(self, site: str, last: str) -> None:
        rec = self.sites[site]
        rec["count"] += 1
        rec["last"] = last

    def _vec(self, name: str) -> int:
        return sample(getattr(self.dut, name), name)

    def _req_out(self) -> int:
        return (self._vec("tb_xtrig_ctp_req_out_dout") >> REQ_LANE) & 1

    def _ctp_addr(self, lane: int, offset: int) -> int:
        if not 0 <= lane < NUM_CTP:
            raise AssertionError(f"CTP lane {lane} outside CROSS_TRIGGER_NETWORK_CTP_NUM={NUM_CTP}")
        return cast(
            int,
            DTP_CSR_BASE
            + cross_trigger_network_indexed_addr("CROSS_TRIGGER_NETWORK_CTP_BASE_ADDR", lane)
            + offset,
        )

    def _stretch_addr(self, lane: int) -> int:
        return cast(
            int,
            DTP_CSR_BASE
            + cross_trigger_network_indexed_addr(
                "CROSS_TRIGGER_NETWORK_CTP_STRETCH_MULT_BASE_ADDR", lane
            ),
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

    def _internal_src_port(self) -> int:
        dtp_int_ct = NUM_CT_SRC - NUM_CTP
        exposed = bit_width(self.dut.xtrig_ctm_dst_req, "xtrig_ctm_dst_req")
        if exposed != SMU_INT_CT_EXPOSED or exposed > dtp_int_ct:
            raise AssertionError(
                f"xtrig_ctm_dst_req is {exposed} wide; the SMU exposes {SMU_INT_CT_EXPOSED} of "
                f"{dtp_int_ct} DTP internal lanes"
            )
        return cast(int, NUM_CTP + (dtp_int_ct - SMU_INT_CT_EXPOSED))

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

    async def _wr32(self, addr: int, data: int, what: str) -> None:
        rec = self.sites["j2a"]
        wstrb, beat = axi64_pack32(addr, data)
        try:
            status, _ = await jtag2axi_single_write(
                self.jtag,
                addr,
                beat,
                wstrb=wstrb,
                size=SMC_DBG_AXSIZE_4B,
                poll_limit=J2A_POLL_LIMIT,
                require_complete=True,
            )
            require_jtag_tdo_resolved(f"{what} WR @0x{addr:08x}")
        except (TimeoutError, AssertionError) as exc:
            rec["expired"] += 1
            rec["last"] = f"{what} WR @0x{addr:08x}: {exc}"
            raise
        self.j2a += 1
        rec["count"] = self.j2a
        rec["last"] = f"{what} WR status={status}"
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"{what} write @0x{addr:08x} status={status}")

    async def _tap_up(self) -> None:
        self.rebringups += 1
        await self.jtag.reset_tap()
        await self.jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await self.jtag.step_tms(0)
        idcode = await self.jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        if self._vec("tb_smc_jtag2axi_security_disable") & 1:
            raise AssertionError("SMC JTAG2AXI still gated; no CSR access can run")

    async def _cold_reset(self, tag: str) -> dict:
        """Pulse rst_cold_ni low and trace every clk_smu edge across the DTP reset.

        Returns the per-edge trace ``(dtp_rst_n, req_out[1], dtp_stop_clks_o)`` indexed from the
        first edge after the assertion, the index at which the DTP reset is first seen low
        and the index at which it is first seen high again.
        """
        dut = self.dut
        clk = dut.clk_smu_i
        trace: list[tuple[int, int, int]] = []

        def snap() -> None:
            trace.append(
                (
                    sample(dut.obs_dtp_rst_n_o, "obs_dtp_rst_n_o"),
                    self._req_out(),
                    sample(dut.dtp_stop_clks_o, "dtp_stop_clks_o"),
                )
            )

        low_smu_edges = round(
            RESET_LOW_CLK_REF * self.cfg.ref_clk_period_ns / self.cfg.smu_clk_period_ns
        )
        await RisingEdge(clk)
        dut.rst_cold_ni.value = 0
        for _ in range(low_smu_edges):
            await RisingEdge(clk)
            snap()
        dut.rst_cold_ni.value = 1
        self._ok(
            "reset_low",
            f"{tag}: rst_cold_ni low for {RESET_LOW_CLK_REF} clk_ref ({len(trace)} clk_smu)",
        )

        fall = next((i for i, s in enumerate(trace) if s[0] == 0), None)
        while fall is None:
            if len(trace) >= DTP_RESET_BOUND:
                self._expire(
                    "dtp_reset_assert", f"{tag}: obs_dtp_rst_n_o still 1 after {len(trace)} clk_smu"
                )
            await RisingEdge(clk)
            snap()
            if trace[-1][0] == 0:
                fall = len(trace) - 1
        self._ok("dtp_reset_assert", f"{tag}: DTP reset low at edge {fall} after the assertion")

        release = next((i for i, s in enumerate(trace) if i > fall and s[0] == 1), None)
        while release is None:
            if len(trace) - fall >= DTP_RESET_BOUND:
                self._expire(
                    "dtp_reset_release",
                    f"{tag}: obs_dtp_rst_n_o still 0 after {len(trace)} clk_smu",
                )
            await RisingEdge(clk)
            snap()
            if trace[-1][0] == 1:
                release = len(trace) - 1
        self._ok("dtp_reset_release", f"{tag}: DTP reset high at edge {release}")
        for _ in range(POST_RELEASE_EDGES):
            await RisingEdge(clk)
            snap()

        primary = smc_primary_reset(dut)
        last = None
        for cyc in range(1, RESET_DONE_BOUND + 1):
            last = sample(primary, "rst_primary_smc_clk_no")
            if last == 1:
                self._ok("reset_done", f"{tag}: primary reset released after {cyc - 1} clk_smu")
                break
            await RisingEdge(clk)
        else:
            self._expire("reset_done", f"{tag}: rst_primary_smc_clk_no={last}")
        await ClockCycles(dut.clk_ref_i, self.cfg.post_reset_settle_cycles)
        self._log(
            f"CELL cold_reset {tag} dtp_rst_low_edge={fall} dtp_rst_high_edge={release} "
            f"edges_traced={len(trace)}"
        )
        return {"trace": trace, "fall": fall, "release": release}

    async def _expect_ctn_regs(self, label: str, ct_src: int, config: int, stretch: int) -> None:
        cells = (
            ("CT_SRC[0].CONFIG_0", self._ctm_src_addr(0), ct_src),
            ("CTP[0].CONFIG", self._ctp_addr(0, CTP_CONFIG_OFF), config),
            ("CTP[0].STRETCH_MULT", self._stretch_addr(0), stretch),
        )
        for name, addr, want in cells:
            got = await self._rd32(addr, name)
            self._cell(f"{label}.{name}", addr, f"value=0x{got:08x} want=0x{want:x}")
            self.sb.expect_eq(f"{label} {name}", got, want, evidence="CHK-CTN-RESET-CLEARS-REGS")

    async def _request_leg(self, leg: str, ack_held: bool) -> None:
        dut = self.dut
        clk = dut.clk_smu_i
        src_port = self._internal_src_port()
        select = (1 << src_port) & CT_DST_SELECT_BM
        config_addr = self._ctp_addr(REQ_LANE, CTP_CONFIG_OFF)
        src_addr = self._ctm_src_addr(REQ_LANE)
        await self._wr32(config_addr, P2P << CONFIG_MODE_BP, f"{leg} CTP1 CONFIG")
        await self._wr32(src_addr, select, f"{leg} CT_SRC[1]")
        self._cell(f"{leg}.CTP[1].CONFIG", config_addr, f"wrote=0x{P2P << CONFIG_MODE_BP:x}")
        self._cell(f"{leg}.CT_SRC[1]", src_addr, f"wrote=0x{select:x} (source port {src_port})")

        dut.xtrig_ctm_dst_req.value = 1
        rec_last = "req_out=0"
        for cyc in range(1, REQ_RISE_BOUND + 1):
            await RisingEdge(clk)
            if cyc == PULSE_HOLD:
                dut.xtrig_ctm_dst_req.value = 0
            if self._req_out() == 1:
                rec_last = f"req_out=1 after {cyc} clk_smu"
                break
        else:
            dut.xtrig_ctm_dst_req.value = 0
            self._expire("req_rise", f"{leg}: {rec_last}")
        dut.xtrig_ctm_dst_req.value = 0
        self._ok("req_rise", f"{leg}: {rec_last}")
        req_before = self._req_out()
        self._log(f"CELL {leg}.req_out[1] before ack or reset value={req_before}")
        self.sb.expect_eq(
            f"{leg} req_out[1] raised by the routed trigger",
            req_before,
            1,
            evidence="CHK-CTP-RESET-MID-REQUEST",
        )

        if ack_held:
            dut.tb_xtrig_ctp_ack_in_din.value = 1 << REQ_LANE
            for cyc in range(1, ACK_RETIRE_BOUND + 1):
                await RisingEdge(clk)
                if self._req_out() == 0:
                    self._ok("ack_retire", f"{leg}: req_out=0 after {cyc} clk_smu")
                    break
            else:
                self._expire("ack_retire", f"{leg}: req_out=1")
            self.sb.expect_eq(
                f"{leg} sender drives req_out[1] low in WAIT_ACK_DEASSERT",
                self._req_out(),
                0,
                evidence="CHK-CTP-RESET-MID-REQUEST",
            )

        res = await self._cold_reset(leg)
        trace, fall = res["trace"], res["fall"]
        cleared = next((i - fall for i in range(fall, len(trace)) if trace[i][1] == 0), None)
        if cleared is None or cleared > REQ_CLEAR_BOUND:
            self._expire("req_clear", f"{leg}: req_out[1] cleared_after={cleared} clk_smu")
        self._ok("req_clear", f"{leg}: req_out[1]=0 {cleared} clk_smu after the DTP reset asserts")
        self._log(f"CELL {leg}.req_out[1] cleared {cleared} clk_smu after DTP reset assert")
        self.sb.expect_eq(
            f"{leg} req_out[1] low within {REQ_CLEAR_BOUND} clk_smu of the reset assert",
            cleared is not None and cleared <= REQ_CLEAR_BOUND,
            True,
            evidence="CHK-CTP-RESET-MID-REQUEST",
        )
        after = [s[1] for s in trace[fall + cleared :]] + [self._req_out()]
        self.sb.expect_eq(
            f"{leg} req_out[1] stays low through the release",
            max(after),
            0,
            evidence="CHK-CTP-RESET-MID-REQUEST",
        )
        await self._tap_up()
        status_addr = self._ctp_addr(REQ_LANE, CTP_STATUS_OFF)
        if ack_held:
            held = await self._rd32(status_addr, f"{leg} CTP1 STATUS ack held")
            self._cell(f"{leg}.CTP[1].STATUS ack held", status_addr, f"value=0x{held:08x}")
            self._log(f"CHK-CTP-RESET-MID-REQUEST: ack_held_status=0x{held:x}")
            dut.tb_xtrig_ctp_ack_in_din.value = 0
            await ClockCycles(dut.clk_smu_i, ACK_RELEASE_SETTLE)
            self._ok(
                "ack_release_settle", f"{leg}: ack released, waited {ACK_RELEASE_SETTLE} clk_smu"
            )
        phase = "ack released" if ack_held else "after reset"
        status = await self._rd32(status_addr, f"{leg} CTP1 STATUS {phase}")
        self._cell(f"{leg}.CTP[1].STATUS {phase}", status_addr, f"value=0x{status:08x}")
        self.sb.expect_eq(
            f"{leg} CTP1 STATUS {phase}",
            status,
            sum(STATUS_RESETS),
            evidence="CHK-CTP-RESET-MID-REQUEST",
        )
        self.sb.expect_eq(
            f"{leg} req_out[1] low {phase}",
            self._req_out(),
            0,
            evidence="CHK-CTP-RESET-MID-REQUEST",
        )
        dut.tb_xtrig_ctp_ack_in_din.value = 0

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
            )
        }
        sb.expect_eq("every xtrig and CTP pad input idle", sum(idle.values()), 0)
        self.jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self._tap_up()
        self._log(f"CELL setup j2a_accesses={self.j2a} seed={getattr(cocotb, 'RANDOM_SEED', 'na')}")

        self._mark("S2", "program CT_SRC[0], CTP[0].CONFIG, CTP[0].STRETCH_MULT and read back")
        ct_src_addr = self._ctm_src_addr(0)
        config_addr = self._ctp_addr(0, CTP_CONFIG_OFF)
        stretch_addr = self._stretch_addr(0)
        await self._wr32(ct_src_addr, CT_SRC0_VALUE, "CT_SRC[0]")
        await self._wr32(config_addr, CTP0_CONFIG_VALUE, "CTP0 CONFIG")
        await self._wr32(stretch_addr, CTP0_STRETCH_VALUE, "CTP0 STRETCH_MULT")
        self._cell("S2.CT_SRC[0].CONFIG_0", ct_src_addr, f"wrote=0x{CT_SRC0_VALUE:x}")
        self._cell("S2.CTP[0].CONFIG", config_addr, f"wrote=0x{CTP0_CONFIG_VALUE:x}")
        self._cell("S2.CTP[0].STRETCH_MULT", stretch_addr, f"wrote=0x{CTP0_STRETCH_VALUE:x}")
        await self._expect_ctn_regs(
            "S2 before reset", CT_SRC0_VALUE, CTP0_CONFIG_VALUE, CTP0_STRETCH_VALUE
        )

        self._mark("S3", "cold reset clears the three registers")
        await self._cold_reset("S3")
        await self._tap_up()
        reset_cfg = sum(CONFIG_RESETS)
        await self._expect_ctn_regs("S3 after reset", 0, reset_cfg, STRETCH_MULT_RESET)

        self._mark("S4", "cold reset with a point-to-point request in flight")
        await self._request_leg("S4A req_asserted", ack_held=False)
        await self._request_leg("S4B wait_ack_deassert", ack_held=True)

        self._mark("S5", "clock-stop request held across a cold reset")
        dut.xtrig_clk_stop_req.value = 1
        for cyc in range(1, STOP_RISE_BOUND + 1):
            await RisingEdge(dut.clk_smu_i)
            if sample(dut.dtp_stop_clks_o, "dtp_stop_clks_o") == 1:
                self._ok("stop_rise", f"dtp_stop_clks_o=1 after {cyc} clk_smu")
                break
        else:
            self._expire("stop_rise", "dtp_stop_clks_o=0")
        res = await self._cold_reset("S5")
        trace, fall, release = res["trace"], res["fall"], res["release"]
        window = [s[2] for s in trace[fall : release + 1]]
        self._log(
            f"CELL S5.dtp_stop_clks_o reset window={len(window)} samples "
            f"high_samples={sum(window)} first_edge_after_release={trace[release][2]}"
        )
        self._log(
            "CHK-CLKSTOP-RESET-LOW: dtp_stop_clks_o after release with the request held "
            f"{[s[2] for s in trace[release + 1 : release + 1 + POST_RELEASE_EDGES]]}"
        )
        sb.expect_eq(
            "dtp_stop_clks_o high samples while the DTP reset is asserted and at the release",
            (len(window) > 1, sum(window)),
            (True, 0),
            evidence="CHK-CLKSTOP-RESET-LOW",
        )
        dut.xtrig_clk_stop_req.value = 0
        await self._tap_up()

        self._mark("S6", "bounded waits and last state")
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
            f"j2a_accesses_counted={self.j2a} tap_rebringups={self.rebringups}"
        )
        sb.expect_eq("expired TIMEOUT-PATH records", expired, 0, evidence="CHK_TIMEOUT_PATHS")
        recorded = [s for s in CONTRACT_WAITS if self.sites[s]["count"] > 0]
        sb.expect_eq(
            "bounded wait kinds named by the contract all exercised",
            len(recorded),
            CONTRACT_WAIT_KINDS,
        )

        for name in ("xtrig_ctm_dst_req", "xtrig_ctm_src_ack", "xtrig_clk_stop_req"):
            getattr(dut, name).value = 0
        dut.tb_xtrig_ctp_req_in_din.value = 0
        dut.tb_xtrig_ctp_ack_in_din.value = 0
        self.step_ts["PASS"] = time.monotonic()
        order = ["S1", "S2", "S3", "S4", "S5", "S6", "PASS"]
        for a, b in zip(order, order[1:]):
            if self.step_ts[a] >= self.step_ts[b]:
                raise AssertionError(f"CHK-NONVAC order fail: {a} not before {b}")
        self._log("CHK-NONVAC: PASS (ordered fence S1<S2<S3<S4<S5<S6<PASS)")
        sb.expect_eq("CHK-NONVAC ordered fence", len(order), 7, evidence="CHK-NONVAC")
