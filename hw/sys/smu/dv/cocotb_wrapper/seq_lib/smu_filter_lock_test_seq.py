# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Write-once filter entry lock on the inbound and outbound filters. SEP=1, no Force.

Spec: hw/ip/axi_filter/doc/index.adoc (Locking a Filter Entry, Match Then Permit, Blocked
Transactions), hw/ip/axi_filter/regs/filter_ctrl.rdl, hw/sys/smc/doc/fabric.adoc (filtering).
The BRESP of the write that sets locked is logged as CHK-LOCK-SET and never compared.
"""

from __future__ import annotations

import time

import cocotb
from cocotb.triggers import RisingEdge
from ocah_axi_vip import RESP_DECERR, RESP_OKAY, resp_name
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import (
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    INBOUND_FILTER_CONFIG_SYM,
    INBOUND_FILTER_END_SYM,
    INBOUND_FILTER_START_SYM,
    OUTBOUND_FILTER_CONFIG_SYM,
    OUTBOUND_FILTER_END_SYM,
    OUTBOUND_FILTER_START_SYM,
    SMC_CHIP_CONFIG_CHIP_ID,
    SMC_CHIP_CONFIG_VERSION_LO,
    SMC_CHIP_CONFIG_VERSION_LO_RESET,
    filter_ctrl_bm,
    filter_ctrl_field_reset_encode,
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
    SMC_APERTURE_GLOBAL_BASE_REG,
    SMC_APERTURE_LOCAL_BASE,
    page_align_window,
)
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_DECERR,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    SMC_DBG_AXSIZE_8B,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)
from seq_lib.smu_tb_pins import smc_primary_reset

_F_READ = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__READ_ALLOWED_bm")
_F_WRITE = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__WRITE_ALLOWED_bm")
_F_ENTRY = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm")
_F_ALLOW_NS = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__ALLOW_NS_bm")
_F_ALLOW_BURST = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__ALLOW_BURST_bm")
_F_BUS64 = filter_ctrl_field_reset_encode("DATA_BUS_WIDTH")
LOCKED = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__LOCKED_bm")

LOCKED_ENTRY = 5
NEIGHBOURS = (4, 6)
BAR_CONFIG = _F_READ | _F_WRITE | _F_ENTRY | _F_ALLOW_NS | _F_BUS64 | _F_ALLOW_BURST

# allow_burst = 1 makes the match granule 4 KB; START and END are granule aligned so the
# registers hold the written values.
VERSION_PAGE_START, VERSION_PAGE_END = page_align_window(
    SMC_CHIP_CONFIG_VERSION_LO, SMC_CHIP_CONFIG_CHIP_ID
)
OUT_PAGE_START = EXT_FABRIC_PROBE_ADDR & ~0xFFF
OUT_PAGE_END = OUT_PAGE_START | 0xFFF

# The inbound entry admits reads. The outbound entry blocks reads of its page; its allow_ns
# equals the AxPROT[1] the JTAG2AXI read carries on smu_axi_out so that the entry matches it.
OUTBOUND_BLOCK_BASE = _F_ENTRY | _F_BUS64 | _F_ALLOW_BURST
ENTRY_WINDOW = {
    "inbound": (VERSION_PAGE_START, VERSION_PAGE_END),
    "outbound": (OUT_PAGE_START, OUT_PAGE_END),
}
NEW_START = 0x0000_0000_5000_0000
NEW_END = 0x0000_0000_5000_0FFF
NEIGHBOUR_VALUES = {
    4: (0x0000_0000_4000_0000, 0x0000_0000_4000_0FFF, _F_READ | _F_ALLOW_BURST | _F_BUS64),
    6: (0x0000_0000_4010_0000, 0x0000_0000_4010_0FFF, _F_WRITE | _F_ALLOW_NS | _F_BUS64),
}

SYMS = {
    "inbound": (INBOUND_FILTER_CONFIG_SYM, INBOUND_FILTER_START_SYM, INBOUND_FILTER_END_SYM),
    "outbound": (OUTBOUND_FILTER_CONFIG_SYM, OUTBOUND_FILTER_START_SYM, OUTBOUND_FILTER_END_SYM),
}
INSTANCES = ("inbound", "outbound")
REGS = ("config", "start", "end")

_ENTRY_ADDRS = [
    smc_indexed_addr(sym, i) for syms in SYMS.values() for sym in syms for i in range(16)
]
BAR_START = min(_ENTRY_ADDRS)
BAR_END = max(_ENTRY_ADDRS) + 7

# 32-bit accesses per instance (a 64-bit register is two halves): writes are S2 eight, S3 four,
# S4 four, S6 twelve; reads are S2 two, S3 two, S4 four, S5 six, S6 twelve. JTAG2AXI accesses are
# the aperture write and read, three BAR writes and two outbound probes.
WANT_WR = 6 + 2 + 4 + 4 + 12
WANT_RD = 2 + 2 + 4 + 6 + 12
J2A_ACCESSES = 2 + 3 + 2
J2A_POLL_LIMIT = 128
OUT_OBS_BOUND_CYCLES = 2000
SITES = ("j2a", "wr", "rd", "probe", "out_obs")


class smu_filter_lock_test_seq:
    """Lock entry 5 on both filter instances and prove the frozen entry."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.done = False
        self.sites: dict[str, int] = {}
        self.last: dict[str, str] = {}
        self.step_ts: dict[str, float] = {}
        self.parity: dict[str, list] = {i: [] for i in INSTANCES}
        self.master = None
        self.expired: list[str] = []
        self.j2a = 0

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _mark(self, step: str, text: str) -> None:
        self.step_ts[step] = time.monotonic()
        self._log(f"STEP {step}: {text}")

    def _addr(self, inst: str, reg: str, entry: int) -> int:
        return smc_indexed_addr(SYMS[inst][REGS.index(reg)], entry)

    def _site(self, site: str, resp: int) -> None:
        self.sites[site] = self.sites.get(site, 0) + 1
        self.last[site] = resp_name(resp)

    def _expire(self, site: str, bound: str, exc: Exception) -> None:
        line = f"{site}: bound={bound} EXPIRED last={exc}"
        self.expired.append(line)
        self._log(f"TIMEOUT-PATH {line}")

    async def _axi_wr(self, site: str, addr: int, value: int, label: str) -> int:
        try:
            resp = await axi_write32_resp_bounded(self.master, addr, value, label=label)
        except AssertionError as exc:
            if "TIMEOUT" in str(exc):
                self._expire(site, f"{AXI_TIMEOUT_NS}ns", exc)
            raise
        self._site(site, resp)
        return resp

    async def _axi_rd(self, site: str, addr: int, label: str) -> tuple[int, int]:
        try:
            data, resp = await axi_read32_resp_bounded(self.master, addr, label=label)
        except AssertionError as exc:
            if "TIMEOUT" in str(exc):
                self._expire(site, f"{AXI_TIMEOUT_NS}ns", exc)
            raise
        self._site(site, resp)
        return int(data), resp

    async def _wr(self, addr: int, value: int, label: str) -> list[int]:
        resps = []
        for half in (0, 1):
            resps.append(
                await self._axi_wr(
                    "wr",
                    addr + 4 * half,
                    (value >> (32 * half)) & 0xFFFF_FFFF,
                    f"{label} half{half}",
                )
            )
        return resps

    async def _rd(self, addr: int, label: str) -> tuple[int, list[int]]:
        value = 0
        resps = []
        for half in (0, 1):
            data, resp = await self._axi_rd("rd", addr + 4 * half, f"{label} half{half}")
            resps.append(resp)
            value |= (int(data) & 0xFFFF_FFFF) << (32 * half)
        return value, resps

    def _cell(self, name: str, addr: int, resps: list[int], value: int | None = None) -> None:
        text = "/".join(resp_name(r) for r in resps)
        tail = "" if value is None else f" value=0x{value:016x}"
        self._log(f"CELL {name} addr=0x{addr:08x} resp={text}{tail}")

    async def _j2a(
        self, write: bool, addr: int, data: int = 0, *, size: int = SMC_DBG_AXSIZE_8B, wstrb=0xFF
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
            self._expire("j2a", f"{J2A_POLL_LIMIT} polls", exc)
            raise
        require_jtag_tdo_resolved(f"J2A {kind} @0x{addr:08x}")
        self.j2a += 1
        self.last["j2a"] = f"status={status}"
        return status, int(rdata)

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        dut = self.dut
        want = {i: {} for i in INSTANCES}

        self._mark(
            "S1", "SETUP: bring-up, aperture, IDCODE, BAR window, vip master, pre-lock probes"
        )
        self.jtag = jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        st, _ = await self._j2a(
            True,
            SMC_APERTURE_GLOBAL_BASE_REG,
            SMC_APERTURE_LOCAL_BASE,
            size=SMC_DBG_AXSIZE_4B,
            wstrb=0x0F,
        )
        sb.expect_eq("JTAG2AXI GLOBAL_BASE write", st, J2A_STATUS_SUCCESS)
        st, rb = await self._j2a(False, SMC_APERTURE_GLOBAL_BASE_REG, size=SMC_DBG_AXSIZE_4B)
        sb.expect_eq("JTAG2AXI GLOBAL_BASE read", st, J2A_STATUS_SUCCESS)
        sb.expect_eq(
            "SMC aperture GLOBAL_BASE=LOCAL_BASE", rb & 0xFFFF_FFFF, SMC_APERTURE_LOCAL_BASE
        )
        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        gate = dut.tb_smc_jtag2axi_security_disable.value
        if not gate.is_resolvable or int(gate) & 1:
            raise AssertionError(f"SMC J2A gated: security_disable={gate}")
        if not (SMC_APERTURE_LOCAL_BASE + 0x1_5000 <= BAR_START <= BAR_END):
            raise AssertionError(f"filter register span 0x{BAR_START:08x}..0x{BAR_END:08x}")
        for addr, data, name in (
            (INBOUND0_START, BAR_START, "BAR_START"),
            (INBOUND0_END, BAR_END, "BAR_END"),
            (INBOUND0_FILTER_CONFIG, BAR_CONFIG, "BAR_CONFIG"),
        ):
            st, _ = await self._j2a(True, addr, data)
            sb.expect_eq(f"JTAG2AXI {name} write", st, J2A_STATUS_SUCCESS)
        self._log(f"CELL bar addr=0x{BAR_START:08x}..0x{BAR_END:08x} j2a_accesses={self.j2a}")
        self.master = await make_smu_axi_master(dut, dut.clk_smu_i, smc_primary_reset(dut))

        out_if = dut.u_axi_out_if
        seen: list[tuple[int, int]] = []
        probing = [True]

        async def _watch_ar() -> None:
            while probing[0]:
                await RisingEdge(dut.clk_smu_i)
                if out_if.arvalid.value.is_resolvable and int(out_if.arvalid.value):
                    if out_if.arready.value.is_resolvable and int(out_if.arready.value):
                        seen.append((int(out_if.araddr.value), int(out_if.arprot.value)))

        tap = cocotb.start_soon(_watch_ar())
        try:
            pre_out, _ = await self._j2a(False, EXT_FABRIC_PROBE_ADDR, size=SMC_DBG_AXSIZE_4B)
        finally:
            probing[0] = False
        await tap
        probe_prot: list[int] = []
        waited = 0
        while waited < OUT_OBS_BOUND_CYCLES:
            probe_prot = [prot for addr, prot in seen if addr == EXT_FABRIC_PROBE_ADDR]
            if probe_prot:
                break
            await RisingEdge(dut.clk_smu_i)
            waited += 1
        self.last["out_obs"] = f"waited={waited} cycles phases_seen={len(seen)}"
        self.sites["out_obs"] = 1
        if len(probe_prot) != 1:
            self._expire("out_obs", f"{OUT_OBS_BOUND_CYCLES} clk", AssertionError(seen))
            raise AssertionError(f"outbound probe address phases on smu_axi_out: {seen}")
        self._log(
            f"CELL outbound.probe-prot addr=0x{EXT_FABRIC_PROBE_ADDR:08x} arprot={probe_prot[0]} "
            "stimulus calibration only"
        )
        self.locked_cfg = {
            "inbound": BAR_CONFIG,
            "outbound": OUTBOUND_BLOCK_BASE | (_F_ALLOW_NS if probe_prot[0] & 2 else 0),
        }
        self._log(f"CELL outbound.pre-probe addr=0x{EXT_FABRIC_PROBE_ADDR:08x} status={pre_out}")
        sb.expect_eq("outbound unmatched probe permitted", pre_out, J2A_STATUS_SUCCESS)
        _, pre_resp = await self._axi_rd(
            "probe", SMC_CHIP_CONFIG_VERSION_LO, "inbound pre-lock probe"
        )
        self._log(
            f"CELL inbound.pre-probe addr=0x{SMC_CHIP_CONFIG_VERSION_LO:08x} "
            f"resp={resp_name(pre_resp)}"
        )
        sb.expect_eq("inbound unmatched probe blocked", pre_resp, RESP_DECERR)

        self._mark("S2", "program entry 5, write locked=1, read FILTER_CONFIG")
        set_obs = {}
        set_exp = {}
        for inst in INSTANCES:
            cfg = self.locked_cfg[inst]
            start, end = ENTRY_WINDOW[inst]
            resps = []
            for reg, val in (("start", start), ("end", end), ("config", cfg)):
                addr = self._addr(inst, reg, LOCKED_ENTRY)
                r = await self._wr(addr, val, f"{inst} program {reg}")
                self._cell(f"{inst}.program-{reg}", addr, r)
                resps += r
            addr = self._addr(inst, "config", LOCKED_ENTRY)
            lock_resps = await self._wr(addr, cfg | LOCKED, f"{inst} lock")
            self._cell(f"{inst}.set-locked", addr, lock_resps)
            self._log(
                f"CHK-LOCK-SET: inst={inst} bresp={'/'.join(resp_name(r) for r in lock_resps)}"
            )
            got, rresps = await self._rd(addr, f"{inst} config after lock")
            self._cell(f"{inst}.config-after-lock", addr, rresps, got)
            set_obs[inst] = (resps, rresps, got >> 63, got & ~LOCKED)
            set_exp[inst] = ([RESP_OKAY] * 6, [RESP_OKAY] * 2, 1, cfg)
            want[inst]["config"] = cfg | LOCKED
            want[inst]["start"] = start
            want[inst]["end"] = end
            self.parity[inst].append(("S2", resps, rresps, got >> 63))
        sb.expect_eq("CHK-LOCK-SET locked reads 1", set_obs, set_exp, evidence="LOCK_SET")

        self._mark("S3", "FILTER_CONFIG writes to the locked entry")
        cfg_obs = {}
        cfg_exp = {}
        for inst in INSTANCES:
            addr = self._addr(inst, "config", LOCKED_ENTRY)
            cfg = self.locked_cfg[inst]
            new = (cfg & ~_F_ENTRY) | LOCKED
            r_new = await self._wr(addr, new, f"{inst} config new value")
            self._cell(f"{inst}.config-write-decerr", addr, r_new)
            r_unlock = await self._wr(addr, cfg, f"{inst} config locked=0")
            self._cell(f"{inst}.unlock-attempt", addr, r_unlock)
            got, rresps = await self._rd(addr, f"{inst} config after rejected writes")
            self._cell(f"{inst}.config-after-reject", addr, rresps, got)
            cfg_obs[inst] = (r_new, r_unlock, rresps, got)
            cfg_exp[inst] = (
                [RESP_DECERR] * 2,
                [RESP_DECERR] * 2,
                [RESP_OKAY] * 2,
                want[inst]["config"],
            )
            self.parity[inst].append(("S3", r_new, r_unlock, rresps, got >> 63))
        sb.expect_eq(
            "CHK-LOCK-CONFIG-DECERR rejected and frozen",
            cfg_obs,
            cfg_exp,
            evidence="LOCK_CONFIG_DECERR",
        )

        self._mark("S4", "START_ADDR and END_ADDR writes to the locked entry")
        addr_obs = {}
        addr_exp = {}
        for inst in INSTANCES:
            obs = []
            for reg, val in (("start", NEW_START), ("end", NEW_END)):
                addr = self._addr(inst, reg, LOCKED_ENTRY)
                r = await self._wr(addr, val, f"{inst} {reg} rejected")
                self._cell(f"{inst}.{reg}-write-decerr", addr, r)
                got, rresps = await self._rd(addr, f"{inst} {reg} after rejected write")
                self._cell(f"{inst}.{reg}-after-reject", addr, rresps, got)
                obs.append((reg, r, rresps, got))
                self.parity[inst].append(("S4", reg, r, rresps, got == want[inst][reg]))
            addr_obs[inst] = obs
            addr_exp[inst] = [
                (reg, [RESP_DECERR] * 2, [RESP_OKAY] * 2, want[inst][reg])
                for reg in ("start", "end")
            ]
        sb.expect_eq(
            "CHK-LOCK-ADDR-DECERR rejected and frozen",
            addr_obs,
            addr_exp,
            evidence="LOCK_ADDR_DECERR",
        )

        self._mark("S5", "read the three locked registers")
        rb_obs = {}
        rb_exp = {}
        for inst in INSTANCES:
            obs = []
            for reg in REGS:
                addr = self._addr(inst, reg, LOCKED_ENTRY)
                got, rresps = await self._rd(addr, f"{inst} {reg} readback")
                self._cell(f"{inst}.locked-readback-{reg}", addr, rresps, got)
                obs.append((reg, rresps, got))
                self.parity[inst].append(("S5", reg, rresps, got == want[inst][reg]))
            rb_obs[inst] = obs
            rb_exp[inst] = [(reg, [RESP_OKAY] * 2, want[inst][reg]) for reg in REGS]
        sb.expect_eq(
            "CHK-LOCK-READBACK locked configuration", rb_obs, rb_exp, evidence="LOCK_READBACK"
        )

        self._mark("S6", "entries 4 and 6 write and read back")
        iso_obs = {}
        iso_exp = {}
        for inst in INSTANCES:
            obs = []
            exp = []
            for entry in NEIGHBOURS:
                start, end, cfg = NEIGHBOUR_VALUES[entry]
                for reg, val in (("start", start), ("end", end), ("config", cfg)):
                    addr = self._addr(inst, reg, entry)
                    r = await self._wr(addr, val, f"{inst} entry{entry} {reg}")
                    got, rresps = await self._rd(addr, f"{inst} entry{entry} {reg}")
                    self._cell(f"{inst}.lock-isolation-e{entry}-{reg}", addr, r + rresps, got)
                    obs.append((entry, reg, r, rresps, got))
                    exp.append((entry, reg, [RESP_OKAY] * 2, [RESP_OKAY] * 2, val))
                    self.parity[inst].append(("S6", entry, reg, r, rresps, got))
            iso_obs[inst] = obs
            iso_exp[inst] = exp
        sb.expect_eq(
            "CHK-LOCK-ISOLATION neighbours writable", iso_obs, iso_exp, evidence="LOCK_ISOLATION"
        )

        self._mark("S7", "probe the page covered by locked entry 5")
        data, resp = await self._axi_rd(
            "probe", SMC_CHIP_CONFIG_VERSION_LO, "inbound locked-entry probe"
        )
        self._log(
            f"CELL inbound.locked-entry-still-filters addr=0x{SMC_CHIP_CONFIG_VERSION_LO:08x} "
            f"resp={resp_name(resp)} data=0x{int(data) & 0xFFFF_FFFF:08x}"
        )
        status, _ = await self._j2a(False, EXT_FABRIC_PROBE_ADDR, size=SMC_DBG_AXSIZE_4B)
        self._log(
            f"CELL outbound.locked-entry-still-filters addr=0x{EXT_FABRIC_PROBE_ADDR:08x} "
            f"status={status}"
        )
        sb.expect_eq(
            "CHK-LOCK-STILL-FILTERS locked entry admits inbound and blocks outbound",
            (resp, int(data) & 0xFFFF_FFFF, status),
            (RESP_OKAY, SMC_CHIP_CONFIG_VERSION_LO_RESET, J2A_STATUS_DECERR),
            evidence="LOCK_STILL_FILTERS",
        )

        self._mark("S8", "compare S2 to S6 between the instances")
        for inst in INSTANCES:
            self._log(f"CELL parity.{inst} records={len(self.parity[inst])}")
        sb.expect_eq(
            "CHK-LOCK-PARITY inbound equals outbound",
            self.parity["inbound"],
            self.parity["outbound"],
            evidence="LOCK_PARITY",
        )

        self._mark("S9", "TIMEOUT: bounded waits and last state")
        want_sites = {"wr": 2 * WANT_WR, "rd": 2 * WANT_RD, "probe": 2}
        bounds = {
            "j2a": f"{J2A_POLL_LIMIT} polls",
            "out_obs": f"{OUT_OBS_BOUND_CYCLES} clk",
        }
        paths = []
        for site in SITES:
            if site not in self.last:
                raise AssertionError(f"bounded wait site {site} never ran")
            bound = bounds.get(site, f"{AXI_TIMEOUT_NS}ns")
            count = self.j2a if site == "j2a" else self.sites[site]
            paths.append(f"{site}: bound={bound} ok accesses={count} last={self.last[site]}")
        for line in paths:
            self._log(f"TIMEOUT-PATH {line}")
        for site, count in want_sites.items():
            sb.expect_eq(f"axi accesses at site {site}", self.sites.get(site), count)
        sb.expect_eq("j2a accesses", self.j2a, J2A_ACCESSES)
        sb.expect_eq("j2a last status", self.last["j2a"], f"status={J2A_STATUS_DECERR}")
        sb.expect_eq("expired TIMEOUT-PATH records", self.expired, [])
        self._log(f"CHK-TIMEOUT-PATHS: sites={len(paths)} expired={len(self.expired)}")
        sb.expect_eq(
            "CHK-TIMEOUT-PATHS site count",
            len(paths),
            len(SITES),
            evidence="CHK_TIMEOUT_PATHS",
        )

        self.step_ts["PASS"] = time.monotonic()
        order = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "PASS"]
        for a, b in zip(order, order[1:]):
            if self.step_ts[a] >= self.step_ts[b]:
                raise AssertionError(f"CHK-NONVAC order fail: {a} not before {b}")
        self._log("CHK-NONVAC: PASS (ordered fence S1<S2<S3<S4<S5<S6<S7<S8<S9<PASS)")
        sb.expect_eq("CHK-NONVAC ordered fence", len(order), 10, evidence="CHK-NONVAC")
        self.done = True
