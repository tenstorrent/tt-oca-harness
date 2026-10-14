# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Filter control register map of the inbound and outbound filters over smu_axi_in. SEP=1, no Force.

Spec: hw/ip/axi_filter/regs/filter_ctrl.rdl (field positions, access, resets),
hw/ip/axi_filter/doc/index.adoc (Address Range Granule, Locking),
hw/sys/smc/regs/smc.rdl (instance bases, stride 0x20).
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
    INBOUND_FILTER_CONFIG_SYM,
    INBOUND_FILTER_END_SYM,
    INBOUND_FILTER_START_SYM,
    OUTBOUND_FILTER_CONFIG_SYM,
    OUTBOUND_FILTER_END_SYM,
    OUTBOUND_FILTER_START_SYM,
    c_header_u32,
    filter_ctrl_bm,
    filter_ctrl_field_reset_encode,
    smc_indexed_addr,
    smc_indexed_stride,
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
)
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    SMC_DBG_AXSIZE_8B,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)
from seq_lib.smu_tb_pins import smc_primary_reset

_FIELDS = (
    "READ_ALLOWED",
    "WRITE_ALLOWED",
    "ENTRY_ENABLED",
    "ALLOW_NS",
    "DATA_BUS_WIDTH",
    "SRC_ID",
    "GROUP_ID",
    "ALLOW_BURST",
    "LOCKED",
)
_BM = {f: filter_ctrl_bm(f"FILTER_CTRL__FILTER_CONFIG__{f}_bm") for f in _FIELDS}
DEFINED_MASK = 0
for _m in _BM.values():
    DEFINED_MASK |= _m
GAP_MASK = ~DEFINED_MASK & ((1 << 64) - 1)
DBW_RESET = filter_ctrl_field_reset_encode("DATA_BUS_WIDTH")
LOCKED = _BM["LOCKED"]
CONFIG_RESET = DBW_RESET
_FILTER_CTRL_H = (
    Path(__file__).resolve().parents[6] / "hw" / "ip" / "axi_filter" / "regs" / "gen" / "c"
) / "filter_ctrl.h"
START_RESET = c_header_u32(_FILTER_CTRL_H, "FILTER_CTRL__START_ADDR__START_ADDR_reset")
END_RESET = c_header_u32(_FILTER_CTRL_H, "FILTER_CTRL__END_ADDR__END_ADDR_reset")
ADDR_MASK = (1 << 56) - 1
ALL56 = ADDR_MASK
RW_BITS = [
    1 << b
    for f in ("READ_ALLOWED", "WRITE_ALLOWED", "ENTRY_ENABLED", "ALLOW_NS")
    for b in range(64)
    if (_BM[f] >> b) & 1
] + [1 << b for f in ("SRC_ID", "GROUP_ID", "ALLOW_BURST") for b in range(64) if (_BM[f] >> b) & 1]
GROUP_ID_A = 0xA << ((_BM["GROUP_ID"] & -_BM["GROUP_ID"]).bit_length() - 1)

INSTANCES = ("inbound", "outbound")
SYMS = {
    "inbound": (INBOUND_FILTER_CONFIG_SYM, INBOUND_FILTER_START_SYM, INBOUND_FILTER_END_SYM),
    "outbound": (OUTBOUND_FILTER_CONFIG_SYM, OUTBOUND_FILTER_START_SYM, OUTBOUND_FILTER_END_SYM),
}
REGS = ("config", "start", "end")
REG_OFFSET = {"config": 0x0, "start": 0x8, "end": 0x10}
INST_BASE = {
    "inbound": SMC_APERTURE_LOCAL_BASE + 0x1_5000,
    "outbound": SMC_APERTURE_LOCAL_BASE + 0x1_6000,
}
ENTRY_STRIDE = 0x20
NUM_ENTRIES = 16
BAR_START = INST_BASE["inbound"]
BAR_END = INST_BASE["outbound"] + 0xFFF
BAR_ENTRY = 0
LOCK_ENTRY = 14
SCRATCH_ENTRY = 13
J2A_POLL_LIMIT = 128
J2A_BUDGET = 60


def _unique(inst_idx: int, reg: str, entry: int) -> int:
    if reg == "config":
        return (
            (entry & 1)
            | (((entry >> 1) & 1) << 1)
            | (inst_idx << 8)
            | (entry << 16)
            | ((15 - entry) << 20)
        )
    top = 0xA0 + inst_idx * 0x10 + entry
    if reg == "start":
        return (top << 40) | 0x1234_5678
    return ((top + 0x40) << 40) | 0xABCD_EF08


class smu_filter_cfg_register_map_test_seq:
    """Reset, field, stride and half-word proof of the filter control registers."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.done = False
        self.expired: list[str] = []
        self.j2a_ops = 0
        self.j2a_last = None
        self.axi_rd = 0
        self.axi_wr = 0
        self.axi_last = None
        self.jtag = None
        self.master = None

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _mark(self, step: str, text: str) -> None:
        self._log(f"STEP {step}: {text}")

    def _addr(self, inst: str, reg: str, entry: int) -> int:
        addr = smc_indexed_addr(SYMS[inst][REGS.index(reg)], entry)
        want = INST_BASE[inst] + entry * ENTRY_STRIDE + REG_OFFSET[reg]
        if addr != want:
            raise AssertionError(f"{inst}.{reg}[{entry}] header 0x{addr:08x} != RDL 0x{want:08x}")
        return addr

    def _expire(self, site: str, bound: str, exc: Exception) -> None:
        line = f"{site}: bound={bound} EXPIRED last={exc}"
        self.expired.append(line)
        self._log(f"TIMEOUT-PATH {line}")

    async def _j2a(
        self, write: bool, addr: int, data: int = 0, *, size=SMC_DBG_AXSIZE_8B, wstrb=0xFF
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
        self.j2a_ops += 1
        self.j2a_last = status
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A {kind} @0x{addr:08x} status={status}")
        return status, int(rdata)

    async def _wr_half(self, addr: int, value: int, label: str, *, strict: bool = True) -> int:
        try:
            resp = await axi_write32_resp_bounded(self.master, addr, value, label=label)
        except AssertionError as exc:
            if "TIMEOUT" in str(exc):
                self._expire("axi", f"{AXI_TIMEOUT_NS}ns", exc)
            raise
        self.axi_wr += 1
        self.axi_last = resp_name(resp)
        if strict and resp != RESP_OKAY:
            raise AssertionError(f"{label} addr=0x{addr:08x} resp={resp_name(resp)}")
        return resp

    async def _rd_half(self, addr: int, label: str) -> int:
        try:
            data, resp = await axi_read32_resp_bounded(self.master, addr, label=label)
        except AssertionError as exc:
            if "TIMEOUT" in str(exc):
                self._expire("axi", f"{AXI_TIMEOUT_NS}ns", exc)
            raise
        self.axi_rd += 1
        self.axi_last = resp_name(resp)
        if resp != RESP_OKAY:
            raise AssertionError(f"{label} addr=0x{addr:08x} resp={resp_name(resp)}")
        return int(data) & 0xFFFF_FFFF

    async def _wr(self, addr: int, value: int, label: str) -> None:
        for half in (0, 1):
            await self._wr_half(
                addr + 4 * half, (value >> (32 * half)) & 0xFFFF_FFFF, f"{label} half{half}"
            )

    async def _rd2(self, addr: int, label: str) -> tuple[int, int]:
        lo = await self._rd_half(addr, f"{label} lo")
        hi = await self._rd_half(addr + 4, f"{label} hi")
        return lo, hi

    async def _rd(self, addr: int, label: str) -> int:
        lo, hi = await self._rd2(addr, label)
        return (hi << 32) | lo

    def _undef(self, reg: str, mask: int, read: int) -> None:
        self._log(f"CHK-CFG-UNDEF-BITS: reg={reg} mask=0x{mask:016x} read=0x{read & mask:016x}")

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        dut = self.dut

        self._mark("S1", "SETUP: bring-up, aperture, entry 0 reset reads, BAR window, vip master")
        self.jtag = jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        await self._j2a(
            True,
            SMC_APERTURE_GLOBAL_BASE_REG,
            SMC_APERTURE_LOCAL_BASE,
            size=SMC_DBG_AXSIZE_4B,
            wstrb=0x0F,
        )
        _, rb = await self._j2a(False, SMC_APERTURE_GLOBAL_BASE_REG, size=SMC_DBG_AXSIZE_4B)
        sb.expect_eq(
            "SMC aperture GLOBAL_BASE=LOCAL_BASE", rb & 0xFFFF_FFFF, SMC_APERTURE_LOCAL_BASE
        )
        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        gate = dut.tb_smc_jtag2axi_security_disable.value
        if not gate.is_resolvable or int(gate) & 1:
            raise AssertionError(f"SMC J2A gated: security_disable={gate}")
        if smc_indexed_stride(INBOUND_FILTER_CONFIG_SYM) != ENTRY_STRIDE:
            raise AssertionError("filter entry stride header != RDL 0x20")
        entry0_reset = {}
        for reg, addr in (
            ("config", INBOUND0_FILTER_CONFIG),
            ("start", INBOUND0_START),
            ("end", INBOUND0_END),
        ):
            _, entry0_reset[reg] = await self._j2a(False, addr)
            self._log(
                f"CELL inbound.reset-j2a.{reg} addr=0x{addr:08x} value=0x{entry0_reset[reg]:016x}"
            )
        for addr, data in (
            (INBOUND0_START, BAR_START),
            (INBOUND0_END, BAR_END),
            (INBOUND0_FILTER_CONFIG, PASS_RW_CONFIG),
        ):
            await self._j2a(True, addr, data)
        _, bar_cfg = await self._j2a(False, INBOUND0_FILTER_CONFIG)
        sb.expect_eq("INBOUND0 FILTER_CONFIG bar readback", bar_cfg, PASS_RW_CONFIG)
        self._log(f"CELL bar addr=0x{BAR_START:08x}..0x{BAR_END:08x} j2a_accesses={self.j2a_ops}")
        self.master = await make_smu_axi_master(dut, dut.clk_smu_i, smc_primary_reset(dut))

        self._mark("S2", "reset reads of every entry of both instances")
        cfg_obs = []
        rng_obs = []
        for inst in INSTANCES:
            for entry in range(NUM_ENTRIES):
                vals = {}
                for reg in REGS:
                    addr = self._addr(inst, reg, entry)
                    if inst == "inbound" and entry == BAR_ENTRY:
                        vals[reg] = entry0_reset[reg]
                    else:
                        vals[reg] = await self._rd(addr, f"{inst}[{entry}].{reg} reset")
                    self._log(
                        f"CELL {inst}.reset.{reg}[{entry}] addr=0x{addr:08x} "
                        f"value=0x{vals[reg]:016x}"
                    )
                cfg_obs.append((inst, entry, vals["config"]))
                rng_obs.append((inst, entry, vals["start"], vals["end"]))
        sb.expect_eq(
            "CHK-CFG-RESET-CONFIG FILTER_CONFIG of 32 entries",
            cfg_obs,
            [(i, e, CONFIG_RESET) for i in INSTANCES for e in range(NUM_ENTRIES)],
            evidence="CFG_RESET_CONFIG",
        )
        sb.expect_eq(
            "CHK-CFG-RESET-RANGE START_ADDR and END_ADDR of 32 entries",
            rng_obs,
            [(i, e, START_RESET, END_RESET) for i in INSTANCES for e in range(NUM_ENTRIES)],
            evidence="CFG_RESET_RANGE",
        )

        self._mark("S3", f"field walk, data_bus_width and locked on entry {LOCK_ENTRY}")
        walk_obs = []
        walk_exp = []
        dbw_obs = []
        dbw_exp = []
        lock_obs = []
        for inst in INSTANCES:
            cfg = self._addr(inst, "config", LOCK_ENTRY)
            start = self._addr(inst, "start", LOCK_ENTRY)
            end = self._addr(inst, "end", LOCK_ENTRY)
            await self._wr(start, 0x2000, f"{inst} no-match START")
            await self._wr(end, 0x1000, f"{inst} no-match END")
            for value in RW_BITS:
                await self._wr(cfg, value, f"{inst} walk 0x{value:x}")
                got = await self._rd(cfg, f"{inst} walk 0x{value:x}")
                self._log(
                    f"CELL {inst}.rw-walk addr=0x{cfg:08x} wrote=0x{value:016x} read=0x{got:016x}"
                )
                walk_obs.append((inst, value, got & DEFINED_MASK))
                walk_exp.append((inst, value, value | DBW_RESET))
            await self._wr(cfg, _BM["DATA_BUS_WIDTH"], f"{inst} dbw all ones")
            got = await self._rd(cfg, f"{inst} dbw all ones")
            self._log(f"CELL {inst}.data-bus-width-ro addr=0x{cfg:08x} read=0x{got:016x}")
            dbw_obs.append((inst, got & _BM["DATA_BUS_WIDTH"]))
            dbw_exp.append((inst, DBW_RESET))
            await self._wr(cfg, 0, f"{inst} config clear")
            await self._wr(start, START_RESET, f"{inst} START restore")
            await self._wr(end, END_RESET, f"{inst} END restore")
            lo_resp = await self._wr_half(cfg, 0, f"{inst} lock lo", strict=False)
            hi_resp = await self._wr_half(cfg + 4, LOCKED >> 32, f"{inst} lock hi", strict=False)
            self._log(f"CHK-LOCK-SET: inst={inst} bresp={resp_name(lo_resp)}/{resp_name(hi_resp)}")
            got = await self._rd(cfg, f"{inst} config after lock")
            self._log(f"CELL {inst}.set-locked addr=0x{cfg:08x} read=0x{got:016x}")
            lock_obs.append((inst, got >> 63))
        sb.expect_eq(
            "CHK-CFG-DBW-RO data_bus_width after all-ones write",
            dbw_obs,
            dbw_exp,
            evidence="CFG_DBW_RO",
        )
        sb.expect_eq(
            "CHK-CFG-RW-FIELDS one-hot walk and locked",
            (walk_obs, lock_obs),
            (walk_exp, [(i, 1) for i in INSTANCES]),
            evidence="CFG_RW_FIELDS",
        )

        self._mark("S4", f"START_ADDR and END_ADDR bit walk on entry {SCRATCH_ENTRY}")
        addr_obs = []
        addr_exp = []
        for inst in INSTANCES:
            cfg = self._addr(inst, "config", SCRATCH_ENTRY)
            start = self._addr(inst, "start", SCRATCH_ENTRY)
            end = self._addr(inst, "end", SCRATCH_ENTRY)

            async def chk(reg, addr, value, label, _inst=inst):
                await self._wr(addr, value, f"{_inst} {reg} {label}")
                got = await self._rd(addr, f"{_inst} {reg} {label}")
                self._log(
                    f"CELL {_inst}.addr-56.{reg} addr=0x{addr:08x} wrote=0x{value:016x} "
                    f"read=0x{got:016x}"
                )
                addr_obs.append((_inst, reg, label, got & ADDR_MASK))
                addr_exp.append((_inst, reg, label, value & ADDR_MASK))
                return got

            await chk("start", start, ALL56, "all56")
            got = await chk("start", start, (1 << 64) - 1, "all64")
            self._undef(f"{inst}.start.all64", ~ADDR_MASK & ((1 << 64) - 1), got)
            await self._wr(start, START_RESET, f"{inst} START clear")
            await chk("end", end, ALL56, "all56")
            got = await chk("end", end, (1 << 64) - 1, "all64")
            self._undef(f"{inst}.end.all64", ~ADDR_MASK & ((1 << 64) - 1), got)
            for b in range(56):
                await chk("start", start, 1 << b, f"bit{b}")
            await self._wr(start, START_RESET, f"{inst} START clear")
            await self._wr(end, 1 << 55, f"{inst} END step")
            await self._wr(start, ALL56, f"{inst} START high")
            for b in range(56):
                await chk("end", end, 1 << b, f"bit{b}")
            await self._wr(start, START_RESET, f"{inst} START restore")
            await self._wr(end, END_RESET, f"{inst} END restore")
            await self._wr(cfg, GAP_MASK, f"{inst} gap bits")
            got = await self._rd(cfg, f"{inst} gap bits")
            self._undef(f"{inst}.config.gap", GAP_MASK, got)
            await self._wr(cfg, 0, f"{inst} config clear")
        sb.expect_eq(
            "CHK-CFG-ADDR-56 START_ADDR and END_ADDR bits [55:0]",
            addr_obs,
            addr_exp,
            evidence="CFG_ADDR_56",
        )

        self._mark("S5", "entry stride and half-word access across all entries")
        want: dict[tuple[str, str, int], int] = {}
        for ii, inst in enumerate(INSTANCES):
            for entry in range(NUM_ENTRIES):
                for reg in REGS:
                    want[(inst, reg, entry)] = {
                        "config": CONFIG_RESET,
                        "start": START_RESET,
                        "end": END_RESET,
                    }[reg]
                    if (inst, entry) == ("inbound", BAR_ENTRY):
                        want[(inst, reg, entry)] = {
                            "config": PASS_RW_CONFIG,
                            "start": BAR_START,
                            "end": BAR_END,
                        }[reg]
                    elif entry == LOCK_ENTRY:
                        if reg == "config":
                            want[(inst, reg, entry)] = CONFIG_RESET | LOCKED
                    else:
                        want[(inst, reg, entry)] = _unique(ii, reg, entry) | (
                            DBW_RESET if reg == "config" else 0
                        )
        writable = [
            (ii, inst, entry)
            for ii, inst in enumerate(INSTANCES)
            for entry in range(NUM_ENTRIES)
            if entry != LOCK_ENTRY and (inst, entry) != ("inbound", BAR_ENTRY)
        ]
        stride_obs = {}
        half_obs = {}
        for reg in ("start", "config", "end"):
            for ii, inst, entry in writable:
                await self._wr(
                    self._addr(inst, reg, entry), _unique(ii, reg, entry), f"{inst}[{entry}].{reg}"
                )
            for inst in INSTANCES:
                for entry in range(NUM_ENTRIES):
                    addr = self._addr(inst, reg, entry)
                    lo, hi = await self._rd2(addr, f"{inst}[{entry}].{reg} readback")
                    stride_obs[(inst, reg, entry)] = (hi << 32) | lo
                    half_obs[(inst, reg, entry)] = (lo, hi)
                    self._log(
                        f"CELL {inst}.stride.{reg}[{entry}] addr=0x{addr:08x} "
                        f"value=0x{(hi << 32) | lo:016x}"
                    )
        sb.expect_eq(
            "CHK-CFG-ENTRY-STRIDE unique value at own entry address only",
            stride_obs,
            want,
            evidence="CFG_ENTRY_STRIDE",
        )
        narrow_obs = []
        narrow_exp = []
        for inst in INSTANCES:
            start = self._addr(inst, "start", SCRATCH_ENTRY)
            old_lo, old_hi = (
                want[(inst, "start", SCRATCH_ENTRY)] & 0xFFFF_FFFF,
                (want[(inst, "start", SCRATCH_ENTRY)] >> 32),
            )
            new_lo, new_hi = 0x1357_9BDF, 0x00CA_FE01
            await self._wr_half(start, new_lo, f"{inst} START low half only")
            lo, hi = await self._rd2(start, f"{inst} START after low half write")
            narrow_obs.append((inst, "lo-only", lo, hi))
            narrow_exp.append((inst, "lo-only", new_lo, old_hi))
            await self._wr_half(start + 4, new_hi, f"{inst} START high half only")
            lo, hi = await self._rd2(start, f"{inst} START after high half write")
            narrow_obs.append((inst, "hi-only", lo, hi))
            narrow_exp.append((inst, "hi-only", new_lo, new_hi))
            self._log(f"CELL {inst}.half-word-write addr=0x{start:08x} old_lo=0x{old_lo:08x}")
        sb.expect_eq(
            "CHK-CFG-HALF-WORD halves of every register and narrow writes",
            (half_obs, narrow_obs),
            ({k: (v & 0xFFFF_FFFF, v >> 32) for k, v in want.items()}, narrow_exp),
            evidence="CFG_HALF_WORD",
        )
        restored = {}
        for ii, inst, entry in writable:
            await self._wr(self._addr(inst, "config", entry), 0, f"{inst}[{entry}] config restore")
            await self._wr(self._addr(inst, "start", entry), START_RESET, f"{inst}[{entry}] START")
            await self._wr(self._addr(inst, "end", entry), END_RESET, f"{inst}[{entry}] END")
        for ii, inst, entry in writable:
            for reg in REGS:
                restored[(inst, reg, entry)] = await self._rd(
                    self._addr(inst, reg, entry), f"{inst}[{entry}].{reg} restored"
                )
        sb.expect_eq(
            "entries restored to reset values",
            restored,
            {
                (inst, reg, entry): {
                    "config": CONFIG_RESET,
                    "start": START_RESET,
                    "end": END_RESET,
                }[reg]
                for _, inst, entry in writable
                for reg in REGS
            },
        )

        self._mark("S6", f"group_id = 0xA on entry {SCRATCH_ENTRY}")
        gid_obs = []
        gid_exp = []
        for inst in INSTANCES:
            cfg = self._addr(inst, "config", SCRATCH_ENTRY)
            await self._wr(cfg, GROUP_ID_A, f"{inst} group_id write")
            got = await self._rd(cfg, f"{inst} group_id read")
            self._log(f"CELL {inst}.group-id-readback addr=0x{cfg:08x} read=0x{got:016x}")
            gid_obs.append((inst, got & _BM["GROUP_ID"], got & DEFINED_MASK))
            gid_exp.append((inst, GROUP_ID_A, GROUP_ID_A | DBW_RESET))
            await self._wr(cfg, 0, f"{inst} config restore")
            sb.expect_eq(
                f"{inst} entry {SCRATCH_ENTRY} FILTER_CONFIG restored",
                await self._rd(cfg, f"{inst} config restored"),
                CONFIG_RESET,
            )
        sb.expect_eq(
            "CHK-CFG-GROUPID-RB group_id reads 0xA", gid_obs, gid_exp, evidence="CFG_GROUPID_RB"
        )

        self._mark("S7", "TIMEOUT: bounded waits and last state")
        state = "EXPIRED" if self.expired else "ok"
        paths = [
            f"j2a: bound={J2A_POLL_LIMIT} polls {state} accesses={self.j2a_ops} "
            f"last_status={self.j2a_last}",
            f"axi: bound={AXI_TIMEOUT_NS}ns {state} reads={self.axi_rd} writes={self.axi_wr} "
            f"last={self.axi_last}",
        ]
        for line in paths:
            self._log(f"TIMEOUT-PATH {line}")
        if not 0 < self.j2a_ops <= J2A_BUDGET:
            raise AssertionError(f"J2A accesses {self.j2a_ops} outside budget {J2A_BUDGET}")
        sb.expect_eq("J2A last status", self.j2a_last, J2A_STATUS_SUCCESS)
        sb.expect_eq("axi last response", self.axi_last, resp_name(RESP_OKAY))
        self._log(f"CHK-TIMEOUT-PATHS: sites={len(paths)} expired={len(self.expired)}")
        sb.expect_eq(
            "CHK-TIMEOUT-PATHS expired waits", len(self.expired), 0, evidence="CHK_TIMEOUT_PATHS"
        )
        self.done = True
