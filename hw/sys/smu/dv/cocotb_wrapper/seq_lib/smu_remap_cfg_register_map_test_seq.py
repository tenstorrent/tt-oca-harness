# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Alias remap and output remap register map over smu_axi_in. SEP=1, no Force.

Spec: hw/ip/axi_alias_remap/regs/alias_remap.rdl, hw/ip/output_remap/regs/output_remap.rdl,
hw/sys/smc/regs/smc.rdl (array bases and strides), doc/trm/src/memory_map.adoc.
Bits the RDL defines no field for are logged as CHK-CFG-UNDEF-BITS and never compared.
"""

from __future__ import annotations

from pathlib import Path

import cocotb
from ocah_axi_vip import RESP_OKAY, resp_name
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import (
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    c_header_u32,
    smc_indexed_addr,
)
from seq_lib.smu_axi_helpers import (
    AXI_TIMEOUT_NS,
    axi_read32_resp_bounded,
    axi_write32_resp_bounded,
    make_smu_axi_master,
)
from seq_lib.smu_filter_helpers import (
    PASS_RW_CONFIG,
    SMC_APERTURE_GLOBAL_BASE_REG,
    SMC_APERTURE_LOCAL_BASE,
    page_align_window,
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

_START = "SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_START_BASE_ADDR"
_END = "SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_END_BASE_ADDR"
_ATTRS = "SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_ATTRS_BASE_ADDR"
_MMODE = "SMC_TOP_SMC_MMODE_REMAP_REGION_REGION_ATTRS_BASE_ADDR"
_XVISOR = "SMC_TOP_SMC_XVISOR_REMAP_REGION_REGION_ATTRS_BASE_ADDR"

NUM_REGIONS = 8
ALIAS_BASE = SMC_APERTURE_LOCAL_BASE + 0x1_2000
ALIAS_STRIDE = 0x20
MMODE_BASE = SMC_APERTURE_LOCAL_BASE + 0x1_3000
XVISOR_BASE = SMC_APERTURE_LOCAL_BASE + 0x1_4000
OREMAP_STRIDE = 0x8
ALIAS_REG_OFFS = (("start", 0x0), ("end", 0x8), ("attrs", 0x10))

_IP = Path(__file__).resolve().parents[6] / "hw" / "ip"
_ALIAS_REMAP_H = _IP / "axi_alias_remap" / "regs" / "gen" / "c" / "alias_remap.h"
_OUTPUT_REMAP_H = _IP / "output_remap" / "regs" / "gen" / "c" / "output_remap.h"


def _alias_bm(reg_field: str) -> int:
    return c_header_u32(_ALIAS_REMAP_H, f"ALIAS_REMAP__REMAP_REGION__{reg_field}_bm")


def _oremap_bm(reg_field: str) -> int:
    return c_header_u32(_OUTPUT_REMAP_H, f"OUTPUT_REMAP__OUTPUT_REMAP_REGION__{reg_field}_bm")


ADDR_FIELD = _alias_bm("REGION_START__START_ADDR")
CACHEABLE_FIELD = _alias_bm("REGION_ATTRS__CACHEABLE")
VALID = _alias_bm("REGION_ATTRS__VALID")
ALL_ONES = (1 << 64) - 1
ALIAS_MASKS = {
    "start": ADDR_FIELD,
    "end": _alias_bm("REGION_END__END_ADDR"),
    "attrs": _alias_bm("REGION_ATTRS__OFFSET") | CACHEABLE_FIELD | VALID,
}
OREMAP_OFFSET = _oremap_bm("REGION_ATTRS__OFFSET")
OREMAP_MASK = OREMAP_OFFSET | _oremap_bm("REGION_ATTRS__VALID")

# START above END selects no input address.
NO_MATCH_START = 0x0000_0010_0000_0000
NO_MATCH_END = 0x0000_0001_0000_0000

WINDOW_START = ALIAS_BASE
WINDOW_END = XVISOR_BASE + (NUM_REGIONS - 1) * OREMAP_STRIDE + 7

# smu_axi_in waits per site, two 32-bit halves per 64-bit register access; J2A accesses:
# aperture write+readback, three BAR writes.
J2A_POLL_LIMIT = 128
S4_WALK_BITS_START = 44
S4_WALK_BITS_ATTRS = 44 + 4 + 1
S4_LOW12 = 12
S5_WALK_BITS = 56 + 1 + 7


def _alias_value(reg: str, i: int) -> int:
    k = i * 3 + [r for r, _ in ALIAS_REG_OFFS].index(reg)
    if reg == "attrs":
        return ((0x5A0_0000 + k * 0x137) << 12) | (((k % 15) + 1) << 56)
    return (0x0A5_0000_0000 + (k + 1) * 0x1357) << 12 & ADDR_FIELD


def _oremap_value(j: int) -> int:
    return 0x00A5_0000_0000_0000 | ((j + 1) * 0x1357_9BDF_0123)


def _alias_mask(addr: int) -> int:
    off = (addr - ALIAS_BASE) % ALIAS_STRIDE
    return ALIAS_MASKS[{0x0: "start", 0x8: "end", 0x10: "attrs"}[off]]


class smu_remap_cfg_register_map_test_seq:
    """Reset, placement and mask proof of the remap register blocks."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.done = False
        self.sites: dict[str, int] = {}
        self.last_resp: dict[str, str] = {}
        self.expired: list[str] = []
        self.j2a_ops = 0
        self.j2a_last = None

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _mark(self, step: str, text: str) -> None:
        self._log(f"STEP {step}: {text}")

    def _expire(self, site: str, exc: Exception) -> None:
        if "TIMEOUT" in str(exc):
            line = f"{site}: bound={AXI_TIMEOUT_NS}ns EXPIRED last={exc}"
            self.expired.append(line)
            self._log(f"TIMEOUT-PATH {line}")

    async def _j2a(self, jtag, write: bool, addr: int, data: int, *, size=None, wstrb=0xFF) -> int:
        kind = "WR" if write else "RD"
        try:
            if write:
                status, rdata = await jtag2axi_single_write(
                    jtag,
                    addr,
                    data,
                    wstrb=wstrb,
                    size=size if size is not None else 3,
                    poll_limit=J2A_POLL_LIMIT,
                    require_complete=True,
                )
            else:
                status, rdata = await jtag2axi_single_read(
                    jtag,
                    addr,
                    size=size if size is not None else 3,
                    poll_limit=J2A_POLL_LIMIT,
                    require_complete=True,
                )
        except TimeoutError as exc:
            line = f"j2a: bound={J2A_POLL_LIMIT} polls EXPIRED last={exc}"
            self.expired.append(line)
            self._log(f"TIMEOUT-PATH {line}")
            raise
        require_jtag_tdo_resolved(f"J2A {kind} @0x{addr:08x}")
        self.j2a_ops += 1
        self.j2a_last = status
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A {kind} @0x{addr:08x} status={status}")
        return int(rdata)

    async def _rd(self, site: str, addr: int, label: str) -> int:
        value = 0
        for half in (0, 1):
            try:
                data, resp = await axi_read32_resp_bounded(
                    self.master, addr + 4 * half, label=f"{label} half{half}"
                )
            except AssertionError as exc:
                self._expire(site, exc)
                raise
            self.sites[site] = self.sites.get(site, 0) + 1
            self.last_resp[site] = resp_name(resp)
            if resp != RESP_OKAY:
                raise AssertionError(f"{label} addr=0x{addr + 4 * half:08x} resp={resp_name(resp)}")
            value |= (int(data) & 0xFFFF_FFFF) << (32 * half)
        return value

    async def _wr(self, site: str, addr: int, value: int, label: str) -> None:
        for half in (0, 1):
            try:
                resp = await axi_write32_resp_bounded(
                    self.master,
                    addr + 4 * half,
                    (value >> (32 * half)) & 0xFFFF_FFFF,
                    label=f"{label} half{half}",
                )
            except AssertionError as exc:
                self._expire(site, exc)
                raise
            self.sites[site] = self.sites.get(site, 0) + 1
            self.last_resp[site] = resp_name(resp)
            if resp != RESP_OKAY:
                raise AssertionError(f"{label} addr=0x{addr + 4 * half:08x} resp={resp_name(resp)}")

    def _undef(self, reg: str, mask: int, read: int) -> None:
        self._log(f"CHK-CFG-UNDEF-BITS: reg={reg} mask=0x{mask:016x} read=0x{read & mask:016x}")

    def _alias_addr(self, reg: str, i: int) -> int:
        off = dict(ALIAS_REG_OFFS)[reg]
        addr = ALIAS_BASE + i * ALIAS_STRIDE + off
        sym = {"start": _START, "end": _END, "attrs": _ATTRS}[reg]
        if smc_indexed_addr(sym, i) != addr:
            raise AssertionError(f"alias {reg}[{i}] header 0x{smc_indexed_addr(sym, i):08x} != RDL")
        return addr

    def _oremap_addr(self, kind: str, i: int) -> int:
        base, sym = (MMODE_BASE, _MMODE) if kind == "mmode" else (XVISOR_BASE, _XVISOR)
        addr = base + i * OREMAP_STRIDE
        if smc_indexed_addr(sym, i) != addr:
            raise AssertionError(f"{kind}[{i}] header 0x{smc_indexed_addr(sym, i):08x} != RDL")
        return addr

    async def _walk(
        self, site: str, reg: str, addr: int, bits: list[int], mask: int, obs: list, exp: list
    ) -> None:
        for b in bits:
            value = 1 << b
            await self._wr(f"{site}.wr", addr, value, f"{reg} walk bit{b}")
            got = await self._rd(f"{site}.rd", addr, f"{reg} walk bit{b}")
            obs.append((reg, b, got & mask))
            exp.append((reg, b, value & mask))

    async def _observe_undef(self, site: str, reg: str, addr: int, bits: list[int]) -> None:
        for b in bits:
            await self._wr(f"{site}.wr", addr, 1 << b, f"{reg} undef bit{b}")
            got = await self._rd(f"{site}.rd", addr, f"{reg} undef bit{b}")
            self._undef(f"{reg}.bit{b}", 1 << b, got)

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        dut = self.dut
        page_lo, page_hi = page_align_window(WINDOW_START, WINDOW_END)

        self._mark("S1", "SETUP: JTAG bring-up, aperture, IDCODE, BAR window, vip master")
        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        await self._j2a(
            jtag,
            True,
            SMC_APERTURE_GLOBAL_BASE_REG,
            SMC_APERTURE_LOCAL_BASE,
            size=SMC_DBG_AXSIZE_4B,
            wstrb=0x0F,
        )
        rb = (
            await self._j2a(jtag, False, SMC_APERTURE_GLOBAL_BASE_REG, 0, size=SMC_DBG_AXSIZE_4B)
        ) & 0xFFFF_FFFF
        sb.expect_eq("SMC aperture GLOBAL_BASE=LOCAL_BASE", rb, SMC_APERTURE_LOCAL_BASE)
        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        gate = dut.tb_smc_jtag2axi_security_disable.value
        if not gate.is_resolvable or int(gate) & 1:
            raise AssertionError(f"SMC J2A gated: security_disable={gate}")
        for addr, data in (
            (INBOUND0_START, WINDOW_START),
            (INBOUND0_END, WINDOW_END),
            (INBOUND0_FILTER_CONFIG, PASS_RW_CONFIG),
        ):
            await self._j2a(jtag, True, addr, data)
        self._log(f"CELL bar addr=0x{page_lo:08x}..0x{page_hi:08x} j2a_accesses={self.j2a_ops}")
        self.master = await make_smu_axi_master(dut, dut.clk_smu_i, smc_primary_reset(dut))

        self._mark("S2", "reset reads before any write")
        alias_reset_obs = []
        for i in range(NUM_REGIONS):
            for reg, _ in ALIAS_REG_OFFS:
                addr = self._alias_addr(reg, i)
                val = await self._rd("s2.rd", addr, f"alias{i}.{reg}")
                alias_reset_obs.append(val)
                self._log(f"CELL region{i}.reset.{reg} addr=0x{addr:08x} value=0x{val:016x}")
        oremap_reset_obs = []
        for kind in ("mmode", "xvisor"):
            for i in range(NUM_REGIONS):
                addr = self._oremap_addr(kind, i)
                val = await self._rd("s2.rd", addr, f"{kind}{i}.attrs")
                oremap_reset_obs.append(val)
                self._log(f"CELL {kind}.reset{i} addr=0x{addr:08x} value=0x{val:016x}")
        sb.expect_eq(
            "CHK-ALIAS-REGS-RESET all 24 registers read 0",
            alias_reset_obs,
            [0] * (3 * NUM_REGIONS),
            evidence="ALIAS_REGS_RESET",
        )
        sb.expect_eq(
            "CHK-OREMAP-REGS-RESET all 16 registers read 0",
            oremap_reset_obs,
            [0] * (2 * NUM_REGIONS),
            evidence="OREMAP_REGS_RESET",
        )

        self._mark("S3", "unique value per register, read all back, then clear")
        alias_exp = {}
        for i in range(NUM_REGIONS):
            for reg, _ in ALIAS_REG_OFFS:
                alias_exp[self._alias_addr(reg, i)] = _alias_value(reg, i)
        oremap_exp = {}
        for kind_idx, kind in enumerate(("mmode", "xvisor")):
            for i in range(NUM_REGIONS):
                oremap_exp[self._oremap_addr(kind, i)] = _oremap_value(kind_idx * NUM_REGIONS + i)
        if len(set(alias_exp.values())) != len(alias_exp) or len(set(oremap_exp.values())) != len(
            oremap_exp
        ):
            raise AssertionError("placement values are not unique")
        for addr, val in {**alias_exp, **oremap_exp}.items():
            if val & VALID:
                raise AssertionError(f"placement value 0x{val:x} sets valid")
            await self._wr("s3.wr", addr, val, "placement write")
        alias_got = {a: await self._rd("s3.rd", a, "alias placement") for a in alias_exp}
        oremap_got = {a: await self._rd("s3.rd", a, "oremap placement") for a in oremap_exp}
        for i in range(NUM_REGIONS):
            for reg, _ in ALIAS_REG_OFFS:
                addr = self._alias_addr(reg, i)
                self._log(
                    f"CELL region{i}.{reg} addr=0x{addr:08x} value=0x{alias_got[addr]:016x} "
                    f"want=0x{alias_exp[addr]:016x}"
                )
        for addr in oremap_exp:
            self._log(
                f"CELL oremap addr=0x{addr:08x} value=0x{oremap_got[addr]:016x} "
                f"want=0x{oremap_exp[addr]:016x}"
            )
        sb.expect_eq(
            "CHK-ALIAS-REGS-PLACEMENT value at own address only",
            {a: alias_got[a] & _alias_mask(a) for a in alias_got},
            {a: alias_exp[a] & _alias_mask(a) for a in alias_exp},
            evidence="ALIAS_REGS_PLACEMENT",
        )
        sb.expect_eq(
            "CHK-OREMAP-REGS-PLACEMENT value at own address only",
            {a: oremap_got[a] & OREMAP_MASK for a in oremap_got},
            {a: oremap_exp[a] & OREMAP_MASK for a in oremap_exp},
            evidence="OREMAP_REGS_PLACEMENT",
        )
        for addr in list(alias_exp) + list(oremap_exp):
            await self._wr("s3.clr", addr, 0, "placement clear")

        self._mark("S4", "alias masks on region 3")
        r = 3
        a_start = self._alias_addr("start", r)
        a_end = self._alias_addr("end", r)
        a_attrs = self._alias_addr("attrs", r)
        masks_obs: list = []
        masks_exp: list = []
        await self._wr("s4.wr", a_start, NO_MATCH_START, "no-match START")
        await self._wr("s4.wr", a_end, NO_MATCH_END, "no-match END")
        await self._wr("s4.wr", a_attrs, ALL_ONES, "ATTRS all ones")
        got = await self._rd("s4.rd", a_attrs, "ATTRS all ones")
        masks_obs.append(("attrs", "ones", got & ALIAS_MASKS["attrs"]))
        masks_exp.append(("attrs", "ones", ALIAS_MASKS["attrs"]))
        self._undef("attrs.all_ones", ~ALIAS_MASKS["attrs"] & ALL_ONES, got)
        await self._wr("s4.wr", a_attrs, 0, "ATTRS clear")
        for reg, addr in (("start", a_start), ("end", a_end)):
            await self._wr("s4.wr", addr, ALL_ONES, f"{reg} all ones")
            got = await self._rd("s4.rd", addr, f"{reg} all ones")
            masks_obs.append((reg, "ones", got & ADDR_FIELD))
            masks_exp.append((reg, "ones", ADDR_FIELD))
            self._undef(f"{reg}.all_ones", ~ADDR_FIELD & ALL_ONES, got)
        await self._walk(
            "s4", "start", a_start, list(range(12, 56)), ADDR_FIELD, masks_obs, masks_exp
        )
        self._log(f"CELL start-mask addr=0x{a_start:08x} bits=12..55")
        await self._walk("s4", "end", a_end, list(range(12, 56)), ADDR_FIELD, masks_obs, masks_exp)
        self._log(f"CELL end-mask addr=0x{a_end:08x} bits=12..55")
        await self._wr("s4.wr", a_start, NO_MATCH_START, "no-match START")
        await self._wr("s4.wr", a_end, NO_MATCH_END, "no-match END")
        attrs_mask = ALIAS_MASKS["attrs"]
        await self._walk(
            "s4", "attrs.offset", a_attrs, list(range(12, 56)), attrs_mask, masks_obs, masks_exp
        )
        self._log(f"CELL attrs-offset-mask addr=0x{a_attrs:08x} bits=12..55")
        await self._walk(
            "s4", "attrs.cacheable", a_attrs, list(range(56, 60)), attrs_mask, masks_obs, masks_exp
        )
        self._log(f"CELL attrs-cacheable-mask addr=0x{a_attrs:08x} bits=56..59")
        await self._walk("s4", "attrs.valid", a_attrs, [63], attrs_mask, masks_obs, masks_exp)
        await self._wr("s4.wr", a_attrs, 0, "ATTRS clear")
        self._log(f"CELL attrs-valid-mask addr=0x{a_attrs:08x} bit=63")
        for reg, addr in (("start", a_start), ("end", a_end), ("attrs", a_attrs)):
            await self._observe_undef("s4.low12", f"{reg}", addr, list(range(12)))
        self._log(f"CELL low12-bits addr=0x{a_start:08x},0x{a_end:08x},0x{a_attrs:08x} bits=0..11")
        for addr in (a_start, a_end, a_attrs):
            await self._wr("s4.wr", addr, 0, "region clear")
        sb.expect_eq(
            "CHK-ALIAS-REGS-MASKS defined fields store and read back",
            masks_obs,
            masks_exp,
            evidence="ALIAS_REGS_MASKS",
        )

        self._mark("S5", "output remap masks on mmode[2] and xvisor[5]")
        o_obs: list = []
        o_exp: list = []
        for kind, idx in (("mmode", 2), ("xvisor", 5)):
            addr = self._oremap_addr(kind, idx)
            await self._walk(
                "s5", f"{kind}.offset", addr, list(range(56)), OREMAP_MASK, o_obs, o_exp
            )
            self._log(f"CELL offset-walk addr=0x{addr:08x} bits=0..55")
            await self._walk("s5", f"{kind}.valid", addr, [63], OREMAP_MASK, o_obs, o_exp)
            await self._wr("s5.wr", addr, 0, f"{kind} clear")
            self._log(f"CELL valid-bit addr=0x{addr:08x} bit=63")
            await self._observe_undef("s5.undef", kind, addr, list(range(56, 63)))
            self._log(f"CELL bits-62-56 addr=0x{addr:08x} bits=56..62")
            await self._wr("s5.wr", addr, 0, f"{kind} clear")
        sb.expect_eq(
            "CHK-OREMAP-REGS-MASKS defined fields store and read back",
            o_obs,
            o_exp,
            evidence="OREMAP_REGS_MASKS",
        )

        self._mark("S6", "TIMEOUT: bounded waits and last state")
        want_sites = {
            k: 2 * v
            for k, v in {
                "s2.rd": 40,
                "s3.wr": 40,
                "s3.rd": 40,
                "s3.clr": 40,
                "s4.wr": 6 + 2 * S4_WALK_BITS_START + 2 + S4_WALK_BITS_ATTRS + 1 + 3,
                "s4.rd": 1 + 2 + 2 * S4_WALK_BITS_START + S4_WALK_BITS_ATTRS,
                "s4.low12.wr": 3 * S4_LOW12,
                "s4.low12.rd": 3 * S4_LOW12,
                "s5.wr": 2 * (56 + 1 + 1 + 1),
                "s5.rd": 2 * (56 + 1),
                "s5.undef.wr": 2 * 7,
                "s5.undef.rd": 2 * 7,
            }.items()
        }
        paths = [
            f"j2a: bound={J2A_POLL_LIMIT} polls ok accesses={self.j2a_ops} "
            f"last_status={self.j2a_last}"
        ]
        for site in sorted(self.sites):
            paths.append(
                f"{site}: bound={AXI_TIMEOUT_NS}ns ok accesses={self.sites[site]} "
                f"last={self.last_resp[site]}"
            )
        for line in paths:
            self._log(f"TIMEOUT-PATH {line}")
        for site, want in want_sites.items():
            sb.expect_eq(
                f"axi accesses at site {site}",
                self.sites.get(site),
                want,
                evidence="CHK_TIMEOUT_PATHS",
            )
        sb.expect_eq("J2A accesses issued", self.j2a_ops, 5)
        sb.expect_eq("J2A last status", self.j2a_last, J2A_STATUS_SUCCESS)
        sb.expect_eq("expired TIMEOUT-PATH records", self.expired, [])
        self._log(f"CHK-TIMEOUT-PATHS: sites={len(paths)} expired={len(self.expired)}")
        sb.expect_eq("bounded wait sites recorded", len(paths), 1 + len(want_sites))
        self.done = True
