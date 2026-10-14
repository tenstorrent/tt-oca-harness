# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_xtrig_ctn_csr_rw_test. SEP=1 (sep_rtl), no Force.

Spec: cross_trigger_port.rdl (CONFIG.MODE, INVERT, RESET sw=rw; STATUS writes complete with OKAY
and leave the register unchanged; STRETCH_MULT[15:0] sw=rw; CONFIG @0x0, STATUS @0x4,
STRETCH_MULT @0x8),
cross_trigger_network.rdl (ctm @0x0, ctp[NUM_CTP] @0x200 += 0x10), cross_trigger_network/doc/
architecture.adoc (Address Map), cross_trigger_matrix.rdl (CT_SRC @0x0 += 0x8), smc.rdl (DTP CSR
window base). Addresses and masks come from the generated headers.

S1  Idle inputs, TAP in Run-Test/Idle, IDCODE, J2A gate open.
S2  Port 3 CONFIG 0x7 and 0x0, STRETCH_MULT 0, 1 and 0xFFFF each written and read back.
S3  Port 3 STATUS read, written 0xFFFF_FFFF, read again.
S4  STRETCH_MULT = 0x1000 + i written to ports 0..15 and read back; CONFIG 0x1 on port 0 and 0x6 on
    port 15; CONFIG and STRETCH_MULT of ports 0 and 15 read back.
S5  Interleaved CT_SRC[0] and port 0 STRETCH_MULT write-then-read over JTAG2AXI, alternating reads
    of CT_SRC[25], CTP[15], CT_SRC[0], CTP[0], then CT_SRC[0], CT_SRC[25] and CONFIG of ports 0
    and 15 cleared.
S6  Every bounded wait is a site with its bound, last state and expiry.
"""

from __future__ import annotations

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
CTP_STRETCH_OFF = cross_trigger_u32("CROSS_TRIGGER_PORT_STRETCH_MULT_BASE_ADDR")
MODE_BM = cross_trigger_u32("CROSS_TRIGGER_PORT__CONFIG__MODE_bm")
INVERT_BM = cross_trigger_u32("CROSS_TRIGGER_PORT__CONFIG__INVERT_bm")
RESET_BM = cross_trigger_u32("CROSS_TRIGGER_PORT__CONFIG__RESET_bm")
STRETCH_BM = cross_trigger_u32("CROSS_TRIGGER_PORT__STRETCH_MULT__STRETCH_MULT_bm")

CONFIG_ALL = MODE_BM | INVERT_BM | RESET_BM
PORT_LOW = 0
PORT_MID = 3
PORT_HIGH = NUM_CTP - 1
CT_SRC_FIRST = 0
CT_SRC_LAST = NUM_CT_SRC - 1
STRETCH_BASE = 0x1000
CONFIG_LOW = 0x1
CONFIG_HIGH = 0x6
STRETCH_SERIAL = 0x2A5A
CT_SRC_SET = 0x1

J2A_POLL_LIMIT = 128
# Bounded waits: a JTAG2AXI access.
EXPECTED_WAITS = ("j2a",)
EXPECTED_WAIT_COUNT = 1
SITES = ("j2a",)


class smu_xtrig_ctn_csr_rw_test_seq:
    """CTP CONFIG, STATUS and STRETCH_MULT access, window independence and serialised accesses."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.sb = test.env.scoreboard
        self.jtag = None
        self.j2a = 0
        self.sites = {
            site: {"bound": J2A_POLL_LIMIT, "count": 0, "last": "none", "expired": 0}
            for site in SITES
        }

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _mark(self, step: str, text: str) -> None:
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
        await self.jtag.reset_tap()
        await self.jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await self.jtag.step_tms(0)
        idcode = await self.jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        if self._vec("tb_smc_jtag2axi_security_disable") & 1:
            raise AssertionError("SMC JTAG2AXI still gated; no CSR access can run")

    async def _wr_rd(self, addr: int, data: int, what: str, log: list) -> int:
        await self._wr32(addr, data, what)
        got = await self._rd32(addr, what)
        self._cell(what, addr, f"wrote=0x{data:08x} read=0x{got:08x}")
        log.append((what, data, got))
        return got

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

        self._mark("S2", "CONFIG and STRETCH_MULT storage on port 3")
        cfg3 = self._ctp_addr(PORT_MID, CTP_CONFIG_OFF)
        str3 = self._ctp_addr(PORT_MID, CTP_STRETCH_OFF)
        s2: list = []
        for data in (CONFIG_ALL, 0):
            await self._wr_rd(cfg3, data, f"CTP[{PORT_MID}].CONFIG", s2)
        for data in (0, 1, STRETCH_BM):
            await self._wr_rd(str3, data, f"CTP[{PORT_MID}].STRETCH_MULT", s2)
        sb.expect_eq(
            "port 3 CONFIG and STRETCH_MULT readback list",
            [(what, got) for what, _, got in s2],
            [(what, wrote) for what, wrote, _ in s2],
            evidence="CHK-CTP-CFG-STRETCH-RW",
        )
        self._log(f"CHK-CTP-CFG-STRETCH-RW: readbacks={[hex(got) for _, _, got in s2]}")

        self._mark("S3", "STATUS write is acknowledged and leaves the register unchanged")
        sta3 = self._ctp_addr(PORT_MID, CTP_STATUS_OFF)
        before = await self._rd32(sta3, f"CTP[{PORT_MID}].STATUS before")
        await self._wr32(sta3, 0xFFFFFFFF, f"CTP[{PORT_MID}].STATUS write")
        after = await self._rd32(sta3, f"CTP[{PORT_MID}].STATUS after")
        self._cell(
            f"CTP[{PORT_MID}].STATUS",
            sta3,
            f"before=0x{before:08x} wrote=0xffffffff status=success after=0x{after:08x}",
        )
        sb.expect_eq(
            "STATUS after the write equals STATUS before it",
            after,
            before,
            evidence="CHK-CTP-STATUS-WRITE-IGNORED",
        )
        self._log(f"CHK-CTP-STATUS-WRITE-IGNORED: before=0x{before:08x} after=0x{after:08x}")

        self._mark("S4", "sixteen port windows hold distinct STRETCH_MULT and CONFIG values")
        for i in range(NUM_CTP):
            await self._wr32(self._ctp_addr(i, CTP_STRETCH_OFF), STRETCH_BASE + i, f"CTP[{i}] SM")
        stretch = []
        for i in range(NUM_CTP):
            addr = self._ctp_addr(i, CTP_STRETCH_OFF)
            got = await self._rd32(addr, f"CTP[{i}].STRETCH_MULT")
            self._cell(
                f"CTP[{i}].STRETCH_MULT", addr, f"wrote=0x{STRETCH_BASE + i:08x} read=0x{got:08x}"
            )
            stretch.append(got)
        cfg_low = self._ctp_addr(PORT_LOW, CTP_CONFIG_OFF)
        cfg_high = self._ctp_addr(PORT_HIGH, CTP_CONFIG_OFF)
        await self._wr32(cfg_low, CONFIG_LOW, f"CTP[{PORT_LOW}].CONFIG")
        await self._wr32(cfg_high, CONFIG_HIGH, f"CTP[{PORT_HIGH}].CONFIG")
        ends = {}
        for port in (PORT_LOW, PORT_HIGH):
            for reg, off in (("CONFIG", CTP_CONFIG_OFF), ("STRETCH_MULT", CTP_STRETCH_OFF)):
                addr = self._ctp_addr(port, off)
                ends[(port, reg)] = await self._rd32(addr, f"CTP[{port}].{reg}")
                self._cell(f"CTP[{port}].{reg}", addr, f"read=0x{ends[(port, reg)]:08x}")
        sb.expect_eq(
            "per-port STRETCH_MULT and end-port CONFIG readback",
            (stretch, ends),
            (
                [STRETCH_BASE + i for i in range(NUM_CTP)],
                {
                    (PORT_LOW, "CONFIG"): CONFIG_LOW,
                    (PORT_LOW, "STRETCH_MULT"): STRETCH_BASE + PORT_LOW,
                    (PORT_HIGH, "CONFIG"): CONFIG_HIGH,
                    (PORT_HIGH, "STRETCH_MULT"): STRETCH_BASE + PORT_HIGH,
                },
            ),
            evidence="CHK-CTP-WINDOW-INDEPENDENCE",
        )

        self._mark("S5", "interleaved CT_SRC and CTP accesses over JTAG2AXI")
        src_first = self._ctm_src_addr(CT_SRC_FIRST)
        src_last = self._ctm_src_addr(CT_SRC_LAST)
        str_low = self._ctp_addr(PORT_LOW, CTP_STRETCH_OFF)
        str_high = self._ctp_addr(PORT_HIGH, CTP_STRETCH_OFF)
        s5: list = []
        await self._wr_rd(src_first, CT_SRC_SET, f"CT_SRC[{CT_SRC_FIRST}]", s5)
        await self._wr_rd(str_low, STRETCH_SERIAL, f"CTP[{PORT_LOW}].STRETCH_MULT", s5)
        alternating = []
        for what, addr in (
            (f"CT_SRC[{CT_SRC_LAST}]", src_last),
            (f"CTP[{PORT_HIGH}].STRETCH_MULT", str_high),
            (f"CT_SRC[{CT_SRC_FIRST}]", src_first),
            (f"CTP[{PORT_LOW}].STRETCH_MULT", str_low),
        ):
            got = await self._rd32(addr, what)
            self._cell(what, addr, f"read=0x{got:08x}")
            alternating.append((what, got))
        await self._wr32(src_first, 0, f"CT_SRC[{CT_SRC_FIRST}] restore")
        await self._wr32(src_last, 0, f"CT_SRC[{CT_SRC_LAST}] restore")
        await self._wr32(cfg_low, 0, f"CTP[{PORT_LOW}].CONFIG restore")
        await self._wr32(cfg_high, 0, f"CTP[{PORT_HIGH}].CONFIG restore")
        sb.expect_eq(
            "pipelined write-read and alternating reads return the last written values",
            ([(w, g) for w, _, g in s5], alternating),
            (
                [
                    (f"CT_SRC[{CT_SRC_FIRST}]", CT_SRC_SET),
                    (f"CTP[{PORT_LOW}].STRETCH_MULT", STRETCH_SERIAL),
                ],
                [
                    (f"CT_SRC[{CT_SRC_LAST}]", 0),
                    (f"CTP[{PORT_HIGH}].STRETCH_MULT", STRETCH_BASE + PORT_HIGH),
                    (f"CT_SRC[{CT_SRC_FIRST}]", CT_SRC_SET),
                    (f"CTP[{PORT_LOW}].STRETCH_MULT", STRETCH_SERIAL),
                ],
            ),
            evidence="CHK-CTN-SERIALISED-ACCESS",
        )

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
            f"j2a_accesses_counted={self.j2a}"
        )
        sb.expect_eq("expired TIMEOUT-PATH records", expired, 0, evidence="CHK_TIMEOUT_PATHS")
        recorded = [s for s in EXPECTED_WAITS if self.sites[s]["count"] > 0]
        sb.expect_eq(
            "bounded wait kinds declared by the sequence all exercised",
            len(recorded),
            EXPECTED_WAIT_COUNT,
        )
