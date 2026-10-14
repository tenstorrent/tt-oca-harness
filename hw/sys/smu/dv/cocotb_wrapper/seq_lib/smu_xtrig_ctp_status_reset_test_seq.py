# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_xtrig_ctp_status_reset_test. SEP=1 (sep_rtl), no Force.

Spec: cross_trigger_port.rdl (CONFIG.MODE, INVERT, RESET; STATUS.BUSY, REQ_OUT, ACK_IN, REQ_IN and
ACK_OUT with INVERT undone, REQ_OUT and ACK_OUT read 0 in wire-OR mode),
cross_trigger_port/doc/architecture.adoc (sender and receiver state machines, RESET),
cross_trigger_matrix.rdl (CT_SRC[n].CT_DST_SELECT bit k routes port k into port n),
cross_trigger_network.rdl. Addresses and masks come from the generated cross-trigger headers.

S1  Idle inputs, TAP in Run-Test/Idle, IDCODE, J2A gate open.
S2  CTP[2].CONFIG = MODE and CT_SRC[2] = 1 << 4 (port 4 into port 2), read back.
S3  A chiplet pull of port 4's wire raises a request on port 2: BUSY reads 1; the acknowledge
    in completes it; BUSY polls back to 0.
S4  STATUS level fields on port 2 at INVERT 0 and INVERT 1 (request out, acknowledge in held,
    request in held, acknowledge out) and on wire-OR port 3 during an assertion.
S5  A stuck request is dropped by CONFIG.RESET, a trigger while RESET = 1 is discarded (no request
    while RESET = 1 nor in a window after RESET clears with the wire released), and the first
    trigger after RESET clears starts a new handshake.
S6  With RESET = 1 a request in is acknowledged and holds BUSY until it is released.
S7  Every bounded wait is a site with its bound, last state and expiry.
"""

from __future__ import annotations

from typing import cast

import cocotb
from cocotb.triggers import ClockCycles
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
    axi64_pack32,
    axi64_unpack32,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)

DTP_CSR_BASE = smc_addr("SMC_TOP_DTP_CTRL_REG_BASE_ADDR")

NUM_CTP = cross_trigger_network_u32("CROSS_TRIGGER_NETWORK_CTP_NUM")
NUM_CT_SRC = cross_trigger_network_u32("CROSS_TRIGGER_NETWORK_CTM_CT_SRC_NUM")
CTP_CONFIG_OFF = cross_trigger_u32("CROSS_TRIGGER_PORT_CONFIG_BASE_ADDR")
CTP_STATUS_OFF = cross_trigger_u32("CROSS_TRIGGER_PORT_STATUS_BASE_ADDR")
CT_DST_SELECT_BM = cross_trigger_u32("CROSS_TRIGGER_MATRIX__CT_SRC__CONFIG_0__CT_DST_SELECT_bm")
MODE_BM = cross_trigger_u32("CROSS_TRIGGER_PORT__CONFIG__MODE_bm")
INVERT_BM = cross_trigger_u32("CROSS_TRIGGER_PORT__CONFIG__INVERT_bm")
RESET_BM = cross_trigger_u32("CROSS_TRIGGER_PORT__CONFIG__RESET_bm")
BUSY_BM = cross_trigger_u32("CROSS_TRIGGER_PORT__STATUS__BUSY_bm")
REQ_OUT_BM = cross_trigger_u32("CROSS_TRIGGER_PORT__STATUS__REQ_OUT_bm")
ACK_IN_BM = cross_trigger_u32("CROSS_TRIGGER_PORT__STATUS__ACK_IN_bm")
REQ_IN_BM = cross_trigger_u32("CROSS_TRIGGER_PORT__STATUS__REQ_IN_bm")
ACK_OUT_BM = cross_trigger_u32("CROSS_TRIGGER_PORT__STATUS__ACK_OUT_bm")

P2P_LANE = 2
WIRE_OR_STATUS_LANE = 3
WIRE_LANE = 4
CONFIG_WIRE_OR = 0
CONFIG_P2P = MODE_BM
CONFIG_P2P_INVERT = MODE_BM | INVERT_BM
CONFIG_P2P_RESET = MODE_BM | RESET_BM

J2A_POLL_LIMIT = 128
PAD_BOUND = 64
DISCARD_WINDOW = 64
BUSY_POLL_BOUND = 4
# Bounded waits: a JTAG2AXI access and a handshake settle before a STATUS read.
EXPECTED_WAITS = ("j2a", "settle")
EXPECTED_WAIT_KINDS = 2
SITES = ("j2a", "settle", "discard_window", "busy_poll")


class smu_xtrig_ctp_status_reset_test_seq:
    """CTP STATUS levels and CONFIG.RESET recovery."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.sb = test.env.scoreboard
        self.jtag = None
        self.j2a = 0
        bounds = {
            "j2a": J2A_POLL_LIMIT,
            "settle": PAD_BOUND,
            "discard_window": DISCARD_WINDOW,
            "busy_poll": BUSY_POLL_BOUND,
        }
        self.sites = {
            site: {"bound": bounds[site], "count": 0, "last": "none", "expired": 0}
            for site in SITES
        }

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _mark(self, step: str, text: str) -> None:
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

    def _bit(self, name: str, lane: int) -> int:
        return (self._vec(name) >> lane) & 1

    def _drive(self, name: str, lane: int, level: int) -> None:
        cur = self._vec(name)
        new = (cur & ~(1 << lane)) | (level << lane)
        getattr(self.dut, name).value = new

    def _pull(self, lane: int, on: int) -> None:
        self._drive("tb_xtrig_ctp_wire_ext_assert", lane, on)

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

    async def _wait_bit(self, name: str, lane: int, want: int, label: str) -> int:
        for cyc in range(PAD_BOUND + 1):
            if self._bit(name, lane) == want:
                self._ok("settle", f"{label}: {name}[{lane}]={want} after {cyc} clk_smu")
                return cyc
            await ClockCycles(self.dut.clk_smu_i, 1)
        self._expire("settle", f"{label}: {name}[{lane}]={1 - want} after {PAD_BOUND} clk_smu")
        return -1

    async def _status(self, lane: int, label: str) -> int:
        addr = self._ctp_addr(lane, CTP_STATUS_OFF)
        value = await self._rd32(addr, f"CTP{lane} STATUS {label}")
        self._cell(f"CTP[{lane}].STATUS {label}", addr, f"value=0x{value:08x}")
        return value

    async def _poll_busy_clear(self, lane: int, label: str, evidence: str) -> None:
        for n in range(1, BUSY_POLL_BOUND + 1):
            value = await self._status(lane, f"{label} poll {n}")
            if not value & BUSY_BM:
                self._ok("busy_poll", f"{label}: BUSY=0 after {n} reads")
                self.sb.expect_eq(
                    f"{label} STATUS.BUSY clear", int(bool(value & BUSY_BM)), 0, evidence=evidence
                )
                return
        self._expire("busy_poll", f"{label}: BUSY=1 after {BUSY_POLL_BOUND} reads")

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

    async def _config(self, lane: int, value: int, label: str) -> None:
        addr = self._ctp_addr(lane, CTP_CONFIG_OFF)
        await self._wr32(addr, value, f"CTP{lane} CONFIG {label}")
        self._cell(f"CTP[{lane}].CONFIG {label}", addr, f"wrote=0x{value:x}")

    async def _trigger(self, label: str, asserted: int) -> None:
        """Pull port 4's wire and wait for the request out on port 2 at its asserted level."""
        self._pull(WIRE_LANE, 1)
        await self._wait_bit("tb_xtrig_ctp_req_out_dout", P2P_LANE, asserted, label)

    async def _release_wire(self, label: str) -> None:
        """Release port 4's wire and wait for it to rest at its INVERT 0 pull-up level."""
        self._pull(WIRE_LANE, 0)
        await self._wait_bit("tb_xtrig_ctp_req_out_din", WIRE_LANE, 1, label)

    async def _ack_cycle(self, label: str, asserted: int) -> None:
        """Hold ack_in at its asserted level until the request out drops, then lower it."""
        self._drive("tb_xtrig_ctp_ack_in_din", P2P_LANE, asserted)
        await self._wait_bit("tb_xtrig_ctp_req_out_dout", P2P_LANE, 1 - asserted, label)

    async def _level_cells(self, invert: int) -> None:
        """S4 cells on port 2 for one polarity.

        The asserted pad level is 1 at INVERT 0 and 0 at INVERT 1.
        """
        asserted = 1 - invert
        tag = f"invert={invert}"
        self.sb.expect_eq(
            f"{tag} req_out_dout[2] idle level before the trigger",
            self._bit("tb_xtrig_ctp_req_out_dout", P2P_LANE),
            1 - asserted,
            evidence="CHK-STATUS-LEVELS",
        )
        await self._trigger(f"S4 {tag} request out", asserted)
        value = await self._status(P2P_LANE, f"{tag} request outstanding")
        self.sb.expect_eq(
            f"{tag} STATUS.REQ_OUT with a request outstanding",
            int(bool(value & REQ_OUT_BM)),
            1,
            evidence="CHK-STATUS-LEVELS",
        )
        await self._ack_cycle(f"S4 {tag} ack in retires", asserted)
        value = await self._status(P2P_LANE, f"{tag} ack_in held")
        self.sb.expect_eq(
            f"{tag} STATUS.ACK_IN with the acknowledge pad held",
            int(bool(value & ACK_IN_BM)),
            1,
            evidence="CHK-STATUS-LEVELS",
        )
        self._drive("tb_xtrig_ctp_ack_in_din", P2P_LANE, 1 - asserted)
        await self._release_wire(f"S4 {tag} wire release")

        self.sb.expect_eq(
            f"{tag} ack_out_dout[2] idle level before the request in",
            self._bit("tb_xtrig_ctp_ack_out_dout", P2P_LANE),
            1 - asserted,
            evidence="CHK-STATUS-LEVELS",
        )
        self._drive("tb_xtrig_ctp_req_in_din", P2P_LANE, asserted)
        await self._wait_bit("tb_xtrig_ctp_ack_out_dout", P2P_LANE, asserted, f"S4 {tag} ack out")
        value = await self._status(P2P_LANE, f"{tag} req_in held")
        self.sb.expect_eq(
            f"{tag} STATUS.REQ_IN with the request pad held",
            int(bool(value & REQ_IN_BM)),
            1,
            evidence="CHK-STATUS-LEVELS",
        )
        self.sb.expect_eq(
            f"{tag} STATUS.ACK_OUT with the acknowledge raised",
            int(bool(value & ACK_OUT_BM)),
            1,
            evidence="CHK-STATUS-LEVELS",
        )
        self._drive("tb_xtrig_ctp_req_in_din", P2P_LANE, 1 - asserted)
        await self._wait_bit(
            "tb_xtrig_ctp_ack_out_dout", P2P_LANE, 1 - asserted, f"S4 {tag} ack out release"
        )

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

        self._mark("S2", "CTP[2] point-to-point, CT_SRC[2] = 1 << 4, read back")
        config_addr = self._ctp_addr(P2P_LANE, CTP_CONFIG_OFF)
        src_addr = self._ctm_src_addr(P2P_LANE)
        select = (1 << WIRE_LANE) & CT_DST_SELECT_BM
        await self._config(P2P_LANE, CONFIG_P2P, "S2")
        await self._wr32(src_addr, select, "CT_SRC[2]")
        self._cell("S2.CT_SRC[2]", src_addr, f"wrote=0x{select:x}")
        got = await self._rd32(config_addr, "CTP2 CONFIG")
        self._cell("S2.CTP[2].CONFIG readback", config_addr, f"value=0x{got:08x}")
        sb.expect_eq("CTP[2].CONFIG holds MODE", got & (MODE_BM | INVERT_BM | RESET_BM), CONFIG_P2P)
        got = await self._rd32(src_addr, "CT_SRC[2]")
        self._cell("S2.CT_SRC[2] readback", src_addr, f"value=0x{got:08x}")
        sb.expect_eq("CT_SRC[2] holds the port 4 select", got & CT_DST_SELECT_BM, select)

        self._mark("S3", "port 4 wire pull raises a request on port 2; BUSY follows")
        before = await self._status(P2P_LANE, "idle")
        sb.expect_eq(
            "STATUS.BUSY before the trigger",
            int(bool(before & BUSY_BM)),
            0,
            evidence="CHK-STATUS-BUSY",
        )
        await self._trigger("S3 request out", 1)
        value = await self._status(P2P_LANE, "request outstanding")
        sb.expect_eq(
            "STATUS.BUSY while the request is outstanding",
            int(bool(value & BUSY_BM)),
            1,
            evidence="CHK-STATUS-BUSY",
        )
        await self._ack_cycle("S3 ack in retires", 1)
        self._drive("tb_xtrig_ctp_ack_in_din", P2P_LANE, 0)
        await self._release_wire("S3 wire release")
        await self._poll_busy_clear(P2P_LANE, "S3 after completion", "CHK-STATUS-BUSY")

        self._mark("S4", "STATUS level fields at INVERT 0 and INVERT 1 and in wire-OR mode")
        await self._level_cells(0)
        self._pull(WIRE_OR_STATUS_LANE, 1)
        await self._wait_bit(
            "tb_xtrig_ctp_req_out_din", WIRE_OR_STATUS_LANE, 0, "S4 port 3 assertion"
        )
        value = await self._status(WIRE_OR_STATUS_LANE, "wire-OR assertion")
        sb.expect_eq(
            "wire-OR STATUS.REQ_OUT reads 0",
            int(bool(value & REQ_OUT_BM)),
            0,
            evidence="CHK-STATUS-LEVELS",
        )
        sb.expect_eq(
            "wire-OR STATUS.ACK_OUT reads 0",
            int(bool(value & ACK_OUT_BM)),
            0,
            evidence="CHK-STATUS-LEVELS",
        )
        self._log(
            "CHK-STATUS-LEVELS: wire_or_ack_in="
            f"{int(bool(value & ACK_IN_BM))} wire_or_req_in={int(bool(value & REQ_IN_BM))}"
        )
        self._pull(WIRE_OR_STATUS_LANE, 0)
        await self._wait_bit(
            "tb_xtrig_ctp_req_out_din", WIRE_OR_STATUS_LANE, 1, "S4 port 3 release"
        )

        await self._config(P2P_LANE, CONFIG_WIRE_OR, "to wire-OR")
        self._drive("tb_xtrig_ctp_req_in_din", P2P_LANE, 1)
        self._drive("tb_xtrig_ctp_ack_in_din", P2P_LANE, 1)
        await self._config(P2P_LANE, CONFIG_P2P_INVERT, "invert")
        got = await self._rd32(config_addr, "CTP2 CONFIG invert")
        sb.expect_eq(
            "CTP[2].CONFIG holds MODE and INVERT",
            got & (MODE_BM | INVERT_BM | RESET_BM),
            CONFIG_P2P_INVERT,
        )
        await self._level_cells(1)
        await self._config(P2P_LANE, CONFIG_WIRE_OR, "back to wire-OR")
        self._drive("tb_xtrig_ctp_req_in_din", P2P_LANE, 0)
        self._drive("tb_xtrig_ctp_ack_in_din", P2P_LANE, 0)
        await self._config(P2P_LANE, CONFIG_P2P, "restore")

        self._mark("S5", "CONFIG.RESET drops a stuck request, discards and re-arms")
        await self._trigger("S5 stuck request", 1)
        value = await self._status(P2P_LANE, "stuck request")
        sb.expect_eq(
            "stuck request STATUS.REQ_OUT",
            int(bool(value & REQ_OUT_BM)),
            1,
            evidence="CHK-HS-RESET-RECOVER",
        )
        await self._config(P2P_LANE, CONFIG_P2P_RESET, "RESET")
        await self._wait_bit("tb_xtrig_ctp_req_out_dout", P2P_LANE, 0, "S5 reset drops req_out")
        sb.expect_eq(
            "RESET lowers req_out_dout[2]",
            self._bit("tb_xtrig_ctp_req_out_dout", P2P_LANE),
            0,
            evidence="CHK-HS-RESET-RECOVER",
        )
        value = await self._status(P2P_LANE, "after RESET")
        sb.expect_eq(
            "RESET clears STATUS.REQ_OUT",
            int(bool(value & REQ_OUT_BM)),
            0,
            evidence="CHK-HS-RESET-RECOVER",
        )
        await self._release_wire("S5 wire release before the discarded trigger")
        self._pull(WIRE_LANE, 1)
        high = 0
        for cyc in range(DISCARD_WINDOW):
            high |= self._bit("tb_xtrig_ctp_req_out_dout", P2P_LANE)
            await ClockCycles(dut.clk_smu_i, 1)
        self._ok(
            "discard_window", f"req_out_dout[2] high_seen={high} over {DISCARD_WINDOW} clk_smu"
        )
        sb.expect_eq(
            "a trigger while RESET = 1 raises no request", high, 0, evidence="CHK-HS-RESET-DISCARD"
        )
        await self._release_wire("S5 wire release after the discarded trigger")
        await self._config(P2P_LANE, CONFIG_P2P, "RESET cleared")
        high = 0
        for _ in range(DISCARD_WINDOW):
            high |= self._bit("tb_xtrig_ctp_req_out_dout", P2P_LANE)
            await ClockCycles(dut.clk_smu_i, 1)
        self._ok(
            "discard_window",
            f"after RESET cleared req_out_dout[2] high_seen={high} over {DISCARD_WINDOW} clk_smu",
        )
        sb.expect_eq(
            "no request after RESET clears with the wire released",
            high,
            0,
            evidence="CHK-HS-RESET-DISCARD",
        )
        await self._trigger("S5 trigger after reset cleared", 1)
        sb.expect_eq(
            "the first trigger after RESET clears raises a new request",
            self._bit("tb_xtrig_ctp_req_out_dout", P2P_LANE),
            1,
            evidence="CHK-HS-RESET-RECOVER",
        )
        await self._ack_cycle("S5 ack in retires the new handshake", 1)
        self._drive("tb_xtrig_ctp_ack_in_din", P2P_LANE, 0)
        await self._release_wire("S5 final wire release")

        self._mark("S6", "request in with RESET = 1 is acknowledged and holds BUSY")
        await self._config(P2P_LANE, CONFIG_P2P_RESET, "RESET for receive")
        self._drive("tb_xtrig_ctp_req_in_din", P2P_LANE, 1)
        await self._wait_bit("tb_xtrig_ctp_ack_out_dout", P2P_LANE, 1, "S6 ack out")
        sb.expect_eq(
            "ack_out_dout[2] rises with RESET = 1",
            self._bit("tb_xtrig_ctp_ack_out_dout", P2P_LANE),
            1,
            evidence="CHK-HS-RESET-RX",
        )
        value = await self._status(P2P_LANE, "req_in held under RESET")
        sb.expect_eq(
            "STATUS.BUSY while the far end holds req_in",
            int(bool(value & BUSY_BM)),
            1,
            evidence="CHK-HS-RESET-RX",
        )
        self._drive("tb_xtrig_ctp_req_in_din", P2P_LANE, 0)
        await self._wait_bit("tb_xtrig_ctp_ack_out_dout", P2P_LANE, 0, "S6 ack out release")
        sb.expect_eq(
            "ack_out_dout[2] falls when req_in is released",
            self._bit("tb_xtrig_ctp_ack_out_dout", P2P_LANE),
            0,
            evidence="CHK-HS-RESET-RX",
        )
        await self._poll_busy_clear(P2P_LANE, "S6 req_in released", "CHK-HS-RESET-RX")
        await self._config(P2P_LANE, CONFIG_WIRE_OR, "restore wire-OR")
        await self._wr32(src_addr, 0, "CT_SRC[2] restore")

        self._mark("S7", "bounded waits and last state")
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
        self._log(
            "CHK-STATUS-BUSY: BUSY rises two clk_i cycles after a state machine leaves IDLE and "
            "falls two clk_i cycles after both return to IDLE (architecture.adoc); "
            "the delay is neither measured nor compared"
        )
        sb.expect_eq("expired TIMEOUT-PATH records", expired, 0, evidence="CHK_TIMEOUT_PATHS")
        recorded = [s for s in EXPECTED_WAITS if self.sites[s]["count"] > 0]
        sb.expect_eq(
            "bounded wait kinds declared by the sequence all exercised",
            len(recorded),
            EXPECTED_WAIT_KINDS,
        )

        for name in (
            "tb_xtrig_ctp_req_in_din",
            "tb_xtrig_ctp_ack_in_din",
            "tb_xtrig_ctp_wire_ext_assert",
        ):
            getattr(dut, name).value = 0
