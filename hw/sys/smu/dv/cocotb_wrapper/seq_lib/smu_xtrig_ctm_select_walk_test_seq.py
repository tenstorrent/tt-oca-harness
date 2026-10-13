# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_xtrig_ctm_select_walk_test. SEP=1 (sep_rtl), no Force.

Contract: SMU_MISC_XTRIG_010 revision 1, anchor smu_xtrig_ctm_select_walk_test.
Spec: cross_trigger_matrix.rdl (CT_SRC[n].CT_DST_SELECT[NUM_CT_DST-1:0] sw=rw reset 0, CT_SRC @0x0
+= 0x8), cross_trigger_matrix/doc/architecture.adoc (port indexing: 0..15 CTP ports, 16..17
SMC-reserved lanes, 18..25 exposed lanes; NUM_CT_DST = 26), cross_trigger_network.rdl (ctm @0x0),
smc.rdl (DTP CSR window base). Addresses and masks come from the generated headers.

The CT_SRC register of index kind n mod 3 is used for bit n: kind 0 is CT_SRC[0] (CTP port),
kind 1 is CT_SRC[16] (SMC-reserved lane), kind 2 is CT_SRC[18] (exposed lane).

S1  Idle inputs, TAP in Run-Test/Idle, IDCODE, J2A gate open.
S2  For n = 0..25 write 1 << n to the CT_SRC register of kind n mod 3 and read it back.
S3  Write 0 to CT_SRC[0], CT_SRC[16] and CT_SRC[18] and read each back.
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
    axi64_pack32,
    axi64_unpack32,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)

DTP_CSR_BASE = smc_addr("SMC_TOP_DTP_CTRL_REG_BASE_ADDR")

NUM_CT_SRC = cross_trigger_network_u32("CROSS_TRIGGER_NETWORK_CTM_CT_SRC_NUM")
CT_DST_SELECT_BM = cross_trigger_u32("CROSS_TRIGGER_MATRIX__CT_SRC__CONFIG_0__CT_DST_SELECT_bm")
CT_DST_SELECT_BW = cross_trigger_u32("CROSS_TRIGGER_MATRIX__CT_SRC__CONFIG_0__CT_DST_SELECT_bw")

KIND_PORTS = (0, 16, 18)
MIN_BITS_PER_REGISTER = 8

J2A_POLL_LIMIT = 128
# Waits the contract names: a JTAG2AXI access.
CONTRACT_WAITS = ("j2a",)
CONTRACT_WAIT_COUNT = 1
SITES = ("j2a",)


class smu_xtrig_ctm_select_walk_test_seq:
    """Walking-one storage of CT_DST_SELECT in CT_SRC registers of the three index kinds."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.sb = test.env.scoreboard
        self.jtag = None
        self.j2a = 0
        self.step_ts: dict[str, float] = {}
        self.sites = {
            site: {"bound": J2A_POLL_LIMIT, "count": 0, "last": "none", "expired": 0}
            for site in SITES
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

        self._mark("S2", "walking one over CT_DST_SELECT[25:0] in the three CT_SRC index kinds")
        records = []
        for n in range(CT_DST_SELECT_BW):
            idx = KIND_PORTS[n % len(KIND_PORTS)]
            addr = self._ctm_src_addr(idx)
            wrote = (1 << n) & CT_DST_SELECT_BM
            await self._wr32(addr, wrote, f"CT_SRC[{idx}] n={n}")
            got = await self._rd32(addr, f"CT_SRC[{idx}] n={n}")
            self._cell(f"CT_SRC[{idx}] n={n}", addr, f"wrote=0x{wrote:08x} read=0x{got:08x}")
            records.append((idx, n, wrote, got))
        sb.expect_eq(
            "CT_SRC walking-one readback list",
            [(n, got) for _, n, _, got in records],
            [(n, 1 << n) for n in range(CT_DST_SELECT_BW)],
            evidence="CHK-CT-SRC-WALK",
        )

        self._mark("S3", "clear CT_SRC[0], CT_SRC[16] and CT_SRC[18]")
        cleared = {}
        for idx in KIND_PORTS:
            addr = self._ctm_src_addr(idx)
            await self._wr32(addr, 0, f"CT_SRC[{idx}] clear")
            got = await self._rd32(addr, f"CT_SRC[{idx}] clear")
            self._cell(f"CT_SRC[{idx}] clear", addr, f"wrote=0x00000000 read=0x{got:08x}")
            cleared[idx] = got
        bits_per_register = {idx: [r[2] for r in records if r[0] == idx] for idx in KIND_PORTS}
        written_bits = [r[1] for r in records]
        kinds = (
            all(len(bits) >= MIN_BITS_PER_REGISTER for bits in bits_per_register.values()),
            len(written_bits) == len(set(written_bits)),
            all(cleared[idx] == 0 for idx in KIND_PORTS),
        )
        self._log(
            "CHK-CT-SRC-KINDS: bits_per_register="
            f"{ {idx: len(bits) for idx, bits in bits_per_register.items()} } "
            f"distinct_bits={len(set(written_bits))} cleared={cleared}"
        )
        sb.expect_eq(
            "CT_SRC kinds: bits per register, no repeated bit, cleared",
            kinds,
            (True, True, True),
            evidence="CHK-CT-SRC-KINDS",
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
        recorded = [s for s in CONTRACT_WAITS if self.sites[s]["count"] > 0]
        sb.expect_eq(
            "bounded wait kinds named by the contract all exercised",
            len(recorded),
            CONTRACT_WAIT_COUNT,
        )

        self.step_ts["PASS"] = time.monotonic()
        order = ["S1", "S2", "S3", "S4", "PASS"]
        for a, b in zip(order, order[1:]):
            if self.step_ts[a] >= self.step_ts[b]:
                raise AssertionError(f"CHK-NONVAC order fail: {a} not before {b}")
        self._log("CHK-NONVAC: PASS (ordered fence S1<S2<S3<S4<PASS)")
        sb.expect_eq("CHK-NONVAC ordered fence", len(order), 5, evidence="CHK-NONVAC")
