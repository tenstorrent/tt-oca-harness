# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Alias remap AxCACHE on a hit, AxCACHE measured on a miss, transparent reset state.

Spec: alias_remap.rdl (REGION_START/END/ATTRS: offset[55:12], cacheable[59:56], valid[63]);
fabric.adoc Alias Remapping, Traffic Managers, Outbound Filtering;
sep-smc-common.adoc Global Aperture and Address Remapping.

The JTAG2AXI bridge issues every access; its own AxCACHE on smu_axi_out is measured while no
alias region is valid, and an alias hit must carry the programmed cacheable value on both the
AW and the AR. Alias region 0 is programmed over smu_axi_in once the inbound filter admits it.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from ocah_axi_vip import RESP_OKAY, resp_name
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import (
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    SMC_CHIP_CONFIG_VERSION_LO,
    SMC_CHIP_CONFIG_VERSION_LO_RESET,
    smc_indexed_addr,
)
from seq_lib.smu_axi_helpers import (
    AXI_TIMEOUT_NS,
    axi_read32_resp_bounded,
    axi_write32_resp_bounded,
    make_smu_axi_master,
)
from seq_lib.smu_filter_helpers import (
    EXT_FABRIC_PROBE_ADDR,
    PASS_RW_CONFIG,
    SMC_APERTURE_GLOBAL_BASE_REG,
    SMC_APERTURE_LOCAL_BASE,
)
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)
from seq_lib.smu_tb_pins import smc_primary_reset

ADDR_MASK56 = (1 << 56) - 1
PAGE_MASK = ADDR_MASK56 & ~0xFFF
ATTRS_VALID = 1 << 63
ATTRS_CACHEABLE_SHIFT = 56
ATTRS_HI_MASK = 0x8FFF_FFFF

_START = "SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_START_BASE_ADDR"
_END = "SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_END_BASE_ADDR"
_ATTRS = "SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_ATTRS_BASE_ADDR"
REGION_START = smc_indexed_addr(_START, 0)
REGION_END = smc_indexed_addr(_END, 0)
REGION_ATTRS = smc_indexed_addr(_ATTRS, 0)

BAR_START = REGION_START & ~0xFFF
BAR_END = BAR_START + 0xFFF
IW = 0xC050_0000
IW_SIZE = 0x1000
OA = EXT_FABRIC_PROBE_ADDR
OA_MISS = OA + 0x10_0000
WDATA = 0x5A5A_1234

J2A_POLL_LIMIT = 128
OUT_WATCH_BOUND_CYCLES = 1_000_000
OUT_OBS_BOUND_CYCLES = 2000
TAKE_EFFECT_POLLS = 64
TAKE_EFFECT_CLK = 4
SITES = ("j2a", "axi_in", "take_effect", "out_obs")


def _attrs_value(offset_delta: int, cacheable: int, *, valid: bool) -> int:
    val = (offset_delta & PAGE_MASK) | ((cacheable & 0xF) << ATTRS_CACHEABLE_SHIFT)
    return val | (ATTRS_VALID if valid else 0)


class _Capture:
    """Address phases seen on smu_axi_out while one JTAG2AXI access runs."""

    def __init__(self) -> None:
        self.aw: list[tuple[int, int]] = []
        self.ar: list[tuple[int, int]] = []
        self.stop = False
        self.cycles = 0
        self.bound_hit = False


class smu_alias_cache_reset_test_seq:
    """Alias region 0 cacheable sweep, miss and reset transparency over JTAG2AXI."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.done = False
        self.jtag = None
        self.master = None
        self.j2a = 0
        self.sites = {
            "j2a": {"bound": f"{J2A_POLL_LIMIT} polls", "count": 0, "last": "none", "expired": 0},
            "axi_in": {"bound": f"{AXI_TIMEOUT_NS} ns", "count": 0, "last": "none", "expired": 0},
            "take_effect": {
                "bound": f"{TAKE_EFFECT_POLLS} polls of {TAKE_EFFECT_CLK} clk",
                "count": 0,
                "last": "none",
                "expired": 0,
            },
            "out_obs": {
                "bound": f"{OUT_OBS_BOUND_CYCLES} clk (watch {OUT_WATCH_BOUND_CYCLES} clk)",
                "count": 0,
                "last": "none",
                "expired": 0,
            },
        }

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _mark(self, step: str, text: str) -> None:
        self._log(f"STEP {step}: {text}")

    def _expire(self, site: str, exc: Exception) -> None:
        rec = self.sites[site]
        rec["expired"] += 1
        rec["last"] = f"EXPIRED {exc}"
        self._log(f"TIMEOUT-PATH {site}: bound={rec['bound']} EXPIRED last={exc}")

    async def _j2a(
        self, write: bool, addr: int, data: int = 0, *, size: int = SMC_DBG_AXSIZE_4B, wstrb=0x0F
    ) -> tuple[int, int]:
        kind = "WR" if write else "RD"
        try:
            if write:
                status, rdata = await jtag2axi_single_write(
                    self.jtag,
                    addr,
                    data,
                    wstrb=wstrb,
                    size=size,
                    poll_limit=J2A_POLL_LIMIT,
                    require_complete=True,
                )
            else:
                status, rdata = await jtag2axi_single_read(
                    self.jtag,
                    addr,
                    size=size,
                    poll_limit=J2A_POLL_LIMIT,
                    require_complete=True,
                )
        except TimeoutError as exc:
            self._expire("j2a", exc)
            raise
        require_jtag_tdo_resolved(f"J2A {kind} @0x{addr:08x}")
        self.j2a += 1
        self.sites["j2a"]["count"] = self.j2a
        self.sites["j2a"]["last"] = f"status={status}"
        return status, int(rdata)

    async def _j2a_wr64(self, addr: int, data: int) -> int:
        st, _ = await self._j2a(True, addr, data, size=3, wstrb=0xFF)
        return st

    async def _j2a_rd32(self, addr: int) -> tuple[int, int]:
        st, raw = await self._j2a(False, addr)
        return st, ((raw >> 32) if addr & 0x4 else raw) & 0xFFFF_FFFF

    async def _axi_wr(self, addr: int, value: int, label: str) -> int:
        try:
            resp = await axi_write32_resp_bounded(self.master, addr, value, label=label)
        except AssertionError as exc:
            if "TIMEOUT" in str(exc):
                self._expire("axi_in", exc)
            raise
        self.sites["axi_in"]["count"] += 1
        self.sites["axi_in"]["last"] = resp_name(resp)
        return resp

    async def _axi_rd(self, addr: int, label: str) -> tuple[int, int]:
        try:
            data, resp = await axi_read32_resp_bounded(self.master, addr, label=label)
        except AssertionError as exc:
            if "TIMEOUT" in str(exc):
                self._expire("axi_in", exc)
            raise
        self.sites["axi_in"]["count"] += 1
        self.sites["axi_in"]["last"] = resp_name(resp)
        return int(data) & 0xFFFF_FFFF, resp

    async def _vip_wr64(self, addr: int, value: int, label: str) -> None:
        for half in (0, 1):
            resp = await self._axi_wr(
                addr + 4 * half, (value >> (32 * half)) & 0xFFFF_FFFF, f"{label} half{half}"
            )
            if resp != RESP_OKAY:
                raise AssertionError(f"{label} half{half} resp={resp_name(resp)} want OKAY")

    async def _vip_wr_hi(self, addr: int, value: int, label: str) -> None:
        resp = await self._axi_wr(addr + 4, (value >> 32) & 0xFFFF_FFFF, f"{label} half1")
        if resp != RESP_OKAY:
            raise AssertionError(f"{label} half1 resp={resp_name(resp)} want OKAY")

    async def _await_attrs_hi(self, attrs: int, label: str) -> None:
        want = (attrs >> 32) & ATTRS_HI_MASK
        rec = self.sites["take_effect"]
        got = None
        for poll in range(TAKE_EFFECT_POLLS):
            data, resp = await self._axi_rd(REGION_ATTRS + 4, f"{label} take-effect")
            got = data & ATTRS_HI_MASK
            rec["count"] += 1
            rec["last"] = f"poll={poll + 1} hi=0x{got:08x} want=0x{want:08x} resp={resp_name(resp)}"
            if resp == RESP_OKAY and got == want:
                return
            await ClockCycles(self.dut.clk_smu_i, TAKE_EFFECT_CLK)
        exc = AssertionError(f"{label} ATTRS hi last=0x{got:08x} want=0x{want:08x}")
        self._expire("take_effect", exc)
        raise exc

    async def _watch(self, cap: _Capture) -> None:
        out_if = self.dut.u_axi_out_if
        clk = self.dut.clk_smu_i

        def _int(name: str) -> int:
            val = getattr(out_if, name).value
            if not val.is_resolvable:
                raise AssertionError(f"X/Z on u_axi_out_if.{name}: {val}")
            return int(val)

        for n in range(OUT_WATCH_BOUND_CYCLES):
            if cap.stop:
                cap.cycles = n
                return
            await RisingEdge(clk)
            if _int("awvalid") and _int("awready"):
                cap.aw.append((_int("awaddr"), _int("awcache")))
            if _int("arvalid") and _int("arready"):
                cap.ar.append((_int("araddr"), _int("arcache")))
        cap.cycles = OUT_WATCH_BOUND_CYCLES
        cap.bound_hit = True

    async def _probe(
        self, write: bool, addr: int, want_out: int, name: str
    ) -> tuple[int, int, int, int]:
        """One JTAG2AXI access; returns (status, captured outbound address and AxCACHE, data)."""
        cap = _Capture()
        task = cocotb.start_soon(self._watch(cap))
        status, raw = 0, 0
        try:
            if write:
                status, _ = await self._j2a(True, addr, WDATA)
            else:
                status, raw = await self._j2a_rd32(addr)
        finally:
            seen: list[tuple[int, int]] = []
            waited = 0
            while waited < OUT_OBS_BOUND_CYCLES:
                seen = [p for p in (cap.aw if write else cap.ar) if p[0] == want_out]
                if seen:
                    break
                await RisingEdge(self.dut.clk_smu_i)
                waited += 1
            cap.stop = True
            await task
        rec = self.sites["out_obs"]
        rec["count"] += 1
        rec["last"] = f"{name} waited={waited} cycles seen={len(seen)} watch_cycles={cap.cycles}"
        if cap.bound_hit or len(seen) != 1:
            self._expire(
                "out_obs",
                AssertionError(f"{name} want_out=0x{want_out:x} aw={cap.aw} ar={cap.ar}"),
            )
            raise AssertionError(
                f"{name}: smu_axi_out phases at 0x{want_out:x}: {seen} aw={cap.aw} ar={cap.ar}"
            )
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"{name} J2A status={status} want SUCCESS")
        return status, seen[0][0], seen[0][1], raw

    def _cell(self, name: str, addr: int, text: str) -> None:
        self._log(f"CELL {name} addr=0x{addr:08x} {text}")

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        dut = self.dut

        self._mark("S1", "SETUP: bring-up, aperture, IDCODE, vip master")
        self.jtag = jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        st, _ = await self._j2a(True, SMC_APERTURE_GLOBAL_BASE_REG, SMC_APERTURE_LOCAL_BASE)
        sb.expect_eq("JTAG2AXI GLOBAL_BASE write", st, J2A_STATUS_SUCCESS)
        st, rb = await self._j2a_rd32(SMC_APERTURE_GLOBAL_BASE_REG)
        sb.expect_eq("JTAG2AXI GLOBAL_BASE read", st, J2A_STATUS_SUCCESS)
        sb.expect_eq("SMC aperture GLOBAL_BASE=LOCAL_BASE", rb, SMC_APERTURE_LOCAL_BASE)
        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        gate = dut.tb_smc_jtag2axi_security_disable.value
        if not gate.is_resolvable or int(gate) & 1:
            raise AssertionError(f"SMC J2A gated: security_disable={gate}")
        self.master = await make_smu_axi_master(dut, dut.clk_smu_i, smc_primary_reset(dut))
        self._log(f"CELL setup j2a_accesses={self.j2a} seed={getattr(cocotb, 'RANDOM_SEED', 'na')}")

        self._mark("S2", "alias regions at reset: outbound address and AxCACHE, local alias read")
        _, aw_addr, init_aw, _ = await self._probe(True, OA, OA, "reset write")
        _, ar_addr, init_ar, _ = await self._probe(False, OA, OA, "reset read")
        self._cell("reset.address-unchanged", OA, f"aw=0x{aw_addr:x} ar=0x{ar_addr:x}")
        self._cell("reset.axcache-unchanged", OA, f"initiator_awcache={init_aw} arcache={init_ar}")
        vst, vdata = await self._j2a_rd32(SMC_CHIP_CONFIG_VERSION_LO)
        self._cell(
            "reset.local-alias-reachable",
            SMC_CHIP_CONFIG_VERSION_LO,
            f"status={vst} data=0x{vdata:08x}",
        )
        self._log(
            f"initiator_axcache aw={init_aw} ar={init_ar} on smu_axi_out (measured, not compared)"
        )
        sb.expect_eq(
            "CHK-ALIAS-RESET-TRANSPARENT address, status, VERSION_LO",
            (aw_addr, ar_addr, vst, vdata),
            (OA, OA, J2A_STATUS_SUCCESS, SMC_CHIP_CONFIG_VERSION_LO_RESET),
            evidence="ALIAS_RESET_TRANSPARENT",
        )

        self._mark("S3", "open the bar: inbound entry 0 over the alias register page")
        for addr, data, name in (
            (INBOUND0_START, BAR_START, "BAR_START"),
            (INBOUND0_END, BAR_END, "BAR_END"),
            (INBOUND0_FILTER_CONFIG, PASS_RW_CONFIG, "BAR_CONFIG"),
        ):
            st = await self._j2a_wr64(addr, data)
            sb.expect_eq(f"JTAG2AXI {name} write", st, J2A_STATUS_SUCCESS)
        st, cfg_rb = await self._j2a_rd32(INBOUND0_FILTER_CONFIG)
        sb.expect_eq("JTAG2AXI BAR_CONFIG read", st, J2A_STATUS_SUCCESS)
        sb.expect_eq("BAR_CONFIG readback", cfg_rb, PASS_RW_CONFIG & 0xFFFF_FFFF)
        self._cell("bar", BAR_START, f"end=0x{BAR_END:08x} j2a_accesses={self.j2a}")

        self._mark("S4", "cacheable 0..15: J2A write and read at the alias window")
        delta = (OA - IW) & ADDR_MASK56
        await self._vip_wr64(REGION_ATTRS, 0, "ALIAS0_ATTRS_CLR")
        await self._vip_wr64(REGION_START, IW & PAGE_MASK, "ALIAS0_START")
        await self._vip_wr64(REGION_END, (IW + IW_SIZE) & PAGE_MASK, "ALIAS0_END")
        observed: list[tuple[int, int]] = []
        expected: list[tuple[int, int]] = []
        for cacheable in range(16):
            attrs = _attrs_value(delta, cacheable, valid=True)
            if cacheable == 0:
                await self._vip_wr64(REGION_ATTRS, attrs, "ALIAS0_ATTRS")
            else:
                await self._vip_wr_hi(REGION_ATTRS, attrs, "ALIAS0_ATTRS")
            await self._await_attrs_hi(attrs, f"cacheable={cacheable}")
            _, _, aw_cache, _ = await self._probe(True, IW, OA, f"hit write c={cacheable}")
            _, _, ar_cache, _ = await self._probe(False, IW, OA, f"hit read c={cacheable}")
            self._cell(f"write.cacheable-{cacheable}", IW, f"out=0x{OA:x} awcache={aw_cache}")
            self._cell(f"read.cacheable-{cacheable}", IW, f"out=0x{OA:x} arcache={ar_cache}")
            observed.append((aw_cache, ar_cache))
            expected.append((cacheable, cacheable))
        values = [c for c, _ in expected]
        self._log(
            f"CHK-ALIAS-CACHE-HIT seed={getattr(cocotb, 'RANDOM_SEED', 'na')} values={values}"
        )
        sb.expect_eq(
            "CHK-ALIAS-CACHE-HIT (awcache, arcache) per cacheable value",
            observed,
            expected,
            evidence="ALIAS_CACHE_HIT",
        )

        self._mark("S5", "cacheable 0 against the initiator AxCACHE")
        self._log(
            f"cacheable=0 observed={observed[0]} initiator_axcache aw={init_aw} ar={init_ar} "
            "(measured, not compared)"
        )

        self._mark("S6", "region 0 invalid; access that misses every region")
        await self._vip_wr_hi(REGION_ATTRS, 0, "ALIAS0_ATTRS_INVALID")
        await self._await_attrs_hi(0, "invalid")
        _, _, miss_aw, _ = await self._probe(True, OA_MISS, OA_MISS, "miss write")
        _, _, miss_ar, _ = await self._probe(False, OA_MISS, OA_MISS, "miss read")
        self._cell("miss.axcache", OA_MISS, f"awcache={miss_aw} arcache={miss_ar}")
        self._log(
            f"miss axcache aw={miss_aw} ar={miss_ar} initiator aw={init_aw} ar={init_ar} "
            "(measured, not compared)"
        )
        await self._vip_wr64(REGION_ATTRS, 0, "ALIAS0_ATTRS_RESTORE")
        await self._vip_wr64(REGION_START, 0, "ALIAS0_START_RESTORE")
        await self._vip_wr64(REGION_END, 0, "ALIAS0_END_RESTORE")

        self._mark("S7", "TIMEOUT: bounded waits and last state")
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
            f"j2a_accesses_counted={self.j2a} (counted at the call sites of this seq)"
        )
        sb.expect_eq("expired TIMEOUT-PATH records", expired, 0, evidence="CHK_TIMEOUT_PATHS")
        self.done = True
