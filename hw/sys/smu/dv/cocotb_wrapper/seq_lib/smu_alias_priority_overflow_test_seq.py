# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Alias remap overlap, degenerate regions, offset arithmetic and field preservation on a hit.

Spec: hw/ip/axi_alias_remap/regs/alias_remap.rdl (REGION_START / REGION_END non-inclusive,
REGION_ATTRS offset added to address bits [55:12], valid) and hw/sys/smc/doc/fabric.adoc "Alias
Remapping" and "Protection Bit Pass-Through".

The JTAG2AXI bridge issues every access; the bench responder behind smu_axi_out holds the bytes and
a passive tap on the outbound interface captures the address phases. A miss reference is taken
first with every region at reset; the hit captures are compared with it field by field.

S1 setup, S2 miss reference, S3 overlap and hit, S4 preservation and narrow writes, S5 degenerate
regions, S6 offset arithmetic at the top and past it, S7 bounded waits.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import _REPO_ROOT, c_header_u32, smc_indexed_addr
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)

_ALIAS_REMAP_H = _REPO_ROOT / "hw/ip/axi_alias_remap/regs/gen/c/alias_remap.h"
# hw/ip/axi_alias_remap/regs/gen/c/alias_remap.h: REGION_ATTRS offset and valid fields.
OFFSET_BM = c_header_u32(_ALIAS_REMAP_H, "ALIAS_REMAP__REMAP_REGION__REGION_ATTRS__OFFSET_bm")
OFFSET_BP = c_header_u32(_ALIAS_REMAP_H, "ALIAS_REMAP__REMAP_REGION__REGION_ATTRS__OFFSET_bp")
VALID_BM = c_header_u32(_ALIAS_REMAP_H, "ALIAS_REMAP__REMAP_REGION__REGION_ATTRS__VALID_bm")
# hw/ip/axi_alias_remap/regs/alias_remap.rdl: addresses are 56 bits wide, fields start at bit 12.
ADDR_MASK56 = (1 << 56) - 1
PAGE = 1 << OFFSET_BP
LOW_MASK = PAGE - 1

_START = "SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_START_BASE_ADDR"
_END = "SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_END_BASE_ADDR"
_ATTRS = "SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_ATTRS_BASE_ADDR"

# Input pages outside the SMC and SEP apertures (hw/sys/smu/doc/index.adoc "AXI Crossbar").
PAGE_A = 0x8100_0000
PAGE_EQ = 0x8110_0000
PAGE_GT_END = 0x8120_0000
PAGE_GT_MID = 0x8124_0000
PAGE_GT_START = 0x8128_0000
PAGE_TOP = 0x8130_0000
PAGE_CARRY = 0x8140_0000
# Offsets in bytes added to bits [55:12] (alias_remap.rdl REGION_ATTRS offset).
OFFSET_0 = 0x0200_0000
OFFSET_1 = 0x0400_0000
OFFSET_EQ = 0x0600_0000
OFFSET_GT = 0x0800_0000
# Sum target 0xFF_FFFF_F000 and the page that bit 55 carry wraps to when the sum is truncated to 56
# bits (alias_remap.rdl addresses are [55:12]).
TOP_PAGE = 0xFF_FFFF_F000
CARRY_WRAP_PAGE = 0x0900_0000

LOW_BITS = 0x7F8
TOP_LOW_BITS = 0x238
CARRY_LOW_BITS = 0x240
EQ_LOW_BITS = 0x40
GT_LOW_BITS = 0x80
MISS_DATA = 0x1122_3344_5566_7788
HIT_DATA = 0x8877_6655_4433_2211
NARROW_PATTERN = HIT_DATA
FILL = 0xFF
SIZE_8B = 3
NARROW_BASE = 0x100
NARROW_STEP = 0x10
# (AxSIZE, byte offset inside the doubleword): one lane position per size.
NARROW = ((0, 3), (1, 2), (2, 4), (3, 0))

J2A_POLL_LIMIT = 128
OUT_OBS_BOUND_CYCLES = 2000
J2A_ACCESS_BUDGET = 33
STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")
ACCESS_STEPS = ("S2", "S3", "S4", "S5", "S6")
FIELDS = ("addr", "len", "size", "burst", "id", "prot", "lock", "cache", "qos", "region")
KEPT = ("prot", "len", "size", "id", "burst")
OBSERVED = ("cache", "lock", "qos", "region")


def _f(phase: tuple, *names: str) -> tuple:
    return tuple(phase[FIELDS.index(n)] for n in names)


def _region_reg(prefix: str, idx: int) -> int:
    return smc_indexed_addr(prefix, idx)


class _OutboundTap:
    """Every address phase on the outbound boundary interface."""

    def __init__(self, dut) -> None:
        self._if = dut.u_axi_out_if
        self._clk = dut.clk_smu_i
        self.aw: list[tuple] = []
        self.ar: list[tuple] = []
        self._task = cocotb.start_soon(self._watch())

    def _int(self, name: str) -> int:
        val = getattr(self._if, name).value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on u_axi_out_if.{name}: {val}")
        return int(val)

    def _phase(self, ch: str) -> tuple:
        return tuple(self._int(f"{ch}{f}") for f in FIELDS)

    async def _watch(self) -> None:
        while True:
            await RisingEdge(self._clk)
            if self._int("awvalid") and self._int("awready"):
                self.aw.append(self._phase("aw"))
            if self._int("arvalid") and self._int("arready"):
                self.ar.append(self._phase("ar"))

    def mark(self) -> tuple[int, int]:
        return len(self.aw), len(self.ar)

    def since(self, mark: tuple[int, int]) -> tuple[list[tuple], list[tuple]]:
        return self.aw[mark[0] :], self.ar[mark[1] :]

    def stop(self) -> None:
        if not self._task.done():
            self._task.cancel()


class smu_alias_priority_overflow_test_seq:
    """Alias regions 0..5 over JTAG2AXI, observed at the smu_axi_out responder."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.clk = self.dut.clk_smu_i
        self.jtag = None
        self.tap = None
        self.step = "S1"
        self.step_ts: dict[str, float] = {}
        self.step_access = {s: 0 for s in STEPS}
        self.j2a = 0
        self.j2a_last = "none"
        self.j2a_expired = 0
        self.obs_used_max = 0
        self.obs_count = 0
        self.obs_last = "none"
        self.obs_expired = 0

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    async def _mark(self, step: str, text: str) -> None:
        await RisingEdge(self.clk)
        self.step = step
        self.step_ts[step] = get_sim_time("ns")
        self._log(f"STEP {step}: {text}")

    def _chk(self, sb, chk: str, name: str, observed, expected, text: str) -> None:
        self._log(f"{chk}: {text} observed={observed} expected={expected}")
        sb.expect_eq(f"{chk} {name}", observed, expected, evidence=chk)

    async def _j2a(self, write: bool, addr: int, data: int = 0, *, size=SIZE_8B, wstrb=0xFF):
        kind = "WR" if write else "RD"
        try:
            if write:
                status, raw = await jtag2axi_single_write(
                    self.jtag,
                    addr,
                    data,
                    wstrb=wstrb,
                    size=size,
                    poll_limit=J2A_POLL_LIMIT,
                    require_complete=True,
                )
            else:
                status, raw = await jtag2axi_single_read(
                    self.jtag, addr, size=size, poll_limit=J2A_POLL_LIMIT, require_complete=True
                )
        except TimeoutError as exc:
            self.j2a_expired += 1
            self.j2a_last = f"EXPIRED {exc}"
            self._log(f"TIMEOUT-PATH j2a: bound={J2A_POLL_LIMIT} polls EXPIRED last={exc}")
            raise
        require_jtag_tdo_resolved(f"J2A {kind} @0x{addr:x}")
        self.j2a += 1
        self.step_access[self.step] += 1
        self.j2a_last = f"{kind} @0x{addr:x} status={status}"
        return status, int(raw)

    async def _program(self, idx: int, start: int, end: int, delta: int, label: str) -> None:
        for reg, value in (
            (_START, start & ADDR_MASK56 & ~LOW_MASK),
            (_END, end & ADDR_MASK56 & ~LOW_MASK),
            (_ATTRS, (delta & OFFSET_BM) | VALID_BM),
        ):
            status, _ = await self._j2a(True, _region_reg(reg, idx), value)
            if status != J2A_STATUS_SUCCESS:
                raise AssertionError(f"{label} region {idx} register write status={status}")
        self._log(
            f"CELL region {idx} {label} start=0x{start:x} end=0x{end:x} offset=0x{delta:x} "
            f"j2a_accesses={self.j2a}"
        )

    async def _access(self, write: bool, addr: int, tag: str, data: int = 0, **kw):
        """One bridge access; returns (status, read data, first AW or AR, count seen)."""
        mark = self.tap.mark()
        status, raw = await self._j2a(write, addr, data, **kw)
        used = 0
        while used < OUT_OBS_BOUND_CYCLES:
            aw, ar = self.tap.since(mark)
            if aw if write else ar:
                break
            await RisingEdge(self.clk)
            used += 1
        self.obs_count += 1
        self.obs_used_max = max(self.obs_used_max, used)
        seen = aw if write else ar
        self.obs_last = f"{tag} waited={used} cycles seen={len(seen)}"
        if not seen:
            self.obs_expired += 1
            self.obs_last = f"EXPIRED {tag} after {used} cycles"
            raise AssertionError(f"{tag}: no {'AW' if write else 'AR'} on smu_axi_out")
        return status, raw, seen[0], len(seen)

    def _fill_pages(self, *pages: int) -> None:
        for page in pages:
            self.cfg.axi_out_mem.write(page, bytes([FILL]) * PAGE)

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        dut = self.dut
        mem = self.cfg.axi_out_mem
        issued = PAGE_A + LOW_BITS

        await self._mark("S1", "SETUP: TAP, JTAG2AXI gate, responder pages filled with 0xFF")
        await self.cfg.reset_done.wait()
        await ClockCycles(self.clk, 16)
        self.jtag = jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        gate = dut.tb_smc_jtag2axi_security_disable.value
        if not gate.is_resolvable or int(gate) & 1:
            raise AssertionError(f"SMC J2A gated: security_disable={gate}")
        self.tap = _OutboundTap(dut)
        try:
            await self._body(sb, mem, issued)
        finally:
            self.tap.stop()

    async def _body(self, sb, mem, issued: int) -> None:
        cand = {0: issued + OFFSET_0, 1: issued + OFFSET_1}
        self._fill_pages(PAGE_A, PAGE_A + OFFSET_0, PAGE_A + OFFSET_1)
        self._log(f"CELL setup seed={getattr(cocotb, 'RANDOM_SEED', 'na')} issued=0x{issued:x}")

        await self._mark("S2", "miss reference: 8-byte write and read with every region at reset")
        _, _, miss_aw, _ = await self._access(True, issued, "miss write", MISS_DATA)
        _, miss_rd, miss_ar, _ = await self._access(False, issued, "miss read")
        self._log(f"CELL miss aw={miss_aw} ar={miss_ar} read=0x{miss_rd:x}")

        await self._mark("S3", "regions 0 and 1 valid over A; two writes and a read at A+0x7F8")
        await self._program(0, PAGE_A, PAGE_A + PAGE, OFFSET_0, "narrow")
        await self._program(1, PAGE_A, PAGE_A + 4 * PAGE, OFFSET_1, "wide")
        _, _, hit_aw1, n1 = await self._access(True, issued, "hit write 1", MISS_DATA)
        _, _, hit_aw2, n2 = await self._access(True, issued, "hit write 2", HIT_DATA)
        _, hit_rd, hit_ar, n3 = await self._access(False, issued, "hit read")
        wide_issued = PAGE_A + PAGE + LOW_BITS
        _, _, wide_aw, _ = await self._access(True, wide_issued, "region 1 only write", HIT_DATA)
        wide_hit = _f(wide_aw, "addr")[0]
        hits = [_f(hit_aw1, "addr")[0], _f(hit_aw2, "addr")[0], _f(hit_ar, "addr")[0]]
        winner = next((i for i, c in cand.items() if hits[0] == c), None)
        self._log(
            f"OBSERVATION winner region={winner} aw1=0x{hits[0]:x} aw2=0x{hits[1]:x} "
            f"ar=0x{hits[2]:x} phases={n1},{n2},{n3} measured and logged only"
        )
        self._chk(
            sb,
            "CHK-ALIASPRI-HIT-TRANSLATE",
            "hit leaves translated, low bits kept, AW equals AR",
            (
                _f(miss_aw, "addr")[0] == issued,
                _f(miss_ar, "addr")[0] == issued,
                [h != issued for h in hits],
                [h & LOW_MASK for h in hits],
                len(set(hits)) == 1,
            ),
            (True, True, [True] * 3, [LOW_BITS] * 3, True),
            f"issued=0x{issued:x} miss_aw=0x{_f(miss_aw, 'addr')[0]:x} "
            f"miss_ar=0x{_f(miss_ar, 'addr')[0]:x} hits={[hex(h) for h in hits]}",
        )
        self._chk(
            sb,
            "CHK-ALIASPRI-OVERLAP-WINNER",
            "exactly one translation applied, the same on AW and AR, read returns the last write",
            (sorted(set(hits)) in ([cand[0]], [cand[1]]), len(set(hits)), hit_rd, wide_hit),
            (True, 1, HIT_DATA, wide_issued + OFFSET_1),
            f"candidates={[hex(c) for c in cand.values()]} hits={[hex(h) for h in hits]} "
            f"winner_region={winner} read=0x{hit_rd:x}; region 1 only: issued=0x{wide_issued:x} "
            f"leaving=0x{wide_hit:x}",
        )
        offsets = {0: OFFSET_0, 1: OFFSET_1}
        diffs = [h - issued for h in hits]
        self._chk(
            sb,
            "CHK-ALIASPRI-OFFSET-LOWBITS",
            "leaving address minus issued address equals the winning offset",
            (winner is not None, diffs),
            (True, [offsets.get(winner, -1)] * 3),
            f"winner_region={winner} diffs={[hex(d) for d in diffs]} "
            f"offset_field_shift={OFFSET_BP}",
        )

        await self._mark("S4", "hit fields against the miss reference; narrow writes")
        hit_fields = (_f(hit_aw1, *KEPT), _f(hit_ar, *KEPT))
        miss_fields = (_f(miss_aw, *KEPT), _f(miss_ar, *KEPT))
        self._log(
            f"OBSERVATION cache/lock/qos/region miss aw={_f(miss_aw, *OBSERVED)} "
            f"hit aw={_f(hit_aw1, *OBSERVED)} measured and logged only"
        )
        self._chk(
            sb,
            "CHK-ALIASPRI-FIELDS-PRESERVED",
            "AxPROT, AxLEN, AxSIZE, AxID, AxBURST of the hit equal the miss reference",
            hit_fields,
            miss_fields,
            f"fields={KEPT} hit(aw,ar)={hit_fields} miss(aw,ar)={miss_fields}",
        )
        win_page = hits[0] & ~LOW_MASK
        other_page = cand[1 - winner] & ~LOW_MASK if winner is not None else PAGE_A
        got, want, sizes = {}, {}, {}
        for k, (size, off) in enumerate(NARROW):
            nbytes = 1 << size
            dw = PAGE_A + NARROW_BASE + NARROW_STEP * k
            value = NARROW_PATTERN & ((1 << (8 * nbytes)) - 1)
            _, _, aw, _ = await self._access(
                True,
                dw + off,
                f"narrow write size{size}",
                value << (8 * off),
                size=size,
                wstrb=((1 << nbytes) - 1) << off,
            )
            sizes[size] = _f(aw, "size")[0]
            lanes = bytearray([FILL]) * 16
            lanes[off : off + nbytes] = value.to_bytes(nbytes, "little")
            at = (win_page | (dw & LOW_MASK), other_page | (dw & LOW_MASK))
            got[size] = (mem.read(at[0], 16).hex(), mem.read(at[1], 16).hex())
            want[size] = (bytes(lanes).hex(), (bytes([FILL]) * 16).hex())
        self._log(
            f"OBSERVATION narrow write AxSIZE by issued size {sizes} measured and logged only"
        )
        self._chk(
            sb,
            "CHK-ALIASPRI-PAYLOAD-BYTES",
            "narrow writes leave exactly their bytes at the winning page",
            got,
            want,
            f"winning_page=0x{win_page:x} lanes={got}; AxSIZE measured={sizes} (measured and "
            "logged only)",
        )

        await self._mark("S5", "degenerate regions START == END and START > END")
        await self._program(2, PAGE_EQ, PAGE_EQ, OFFSET_EQ, "start-equals-end")
        eq_addr = PAGE_EQ + EQ_LOW_BITS
        _, _, eq_aw, _ = await self._access(True, eq_addr, "equal start page write", MISS_DATA)
        await self._program(3, PAGE_GT_START, PAGE_GT_END, OFFSET_GT, "start-above-end")
        mid_addr = PAGE_GT_MID + GT_LOW_BITS
        start_addr = PAGE_GT_START + GT_LOW_BITS
        _, _, mid_aw, _ = await self._access(True, mid_addr, "between end and start", MISS_DATA)
        _, _, gt_aw, _ = await self._access(True, start_addr, "start page write", MISS_DATA)
        self._chk(
            sb,
            "CHK-ALIASPRI-DEGEN-EQ",
            "START-equals-END region passes the START page write at the issued address",
            (_f(eq_aw, "addr")[0], hits[0] != issued),
            (eq_addr, True),
            f"issued=0x{eq_addr:x} leaving=0x{_f(eq_aw, 'addr')[0]:x}; positive control: the "
            f"overlap hit left translated (0x{hits[0]:x} for 0x{issued:x})",
        )
        self._chk(
            sb,
            "CHK-ALIASPRI-DEGEN-GT",
            "START-above-END region passes the writes between END and START and at START",
            (_f(mid_aw, "addr")[0], _f(gt_aw, "addr")[0], hits[0] != issued),
            (mid_addr, start_addr, True),
            f"between: issued=0x{mid_addr:x} leaving=0x{_f(mid_aw, 'addr')[0]:x}; start page: "
            f"issued=0x{start_addr:x} leaving=0x{_f(gt_aw, 'addr')[0]:x}; positive control as "
            "above",
        )

        await self._mark("S6", "offset arithmetic to 0xFF_FFFF_F000 and past bit 55")
        await self._program(4, PAGE_TOP, PAGE_TOP + PAGE, TOP_PAGE - PAGE_TOP, "to the top")
        top_issued = PAGE_TOP + TOP_LOW_BITS
        top_status, _, top_aw, _ = await self._access(True, top_issued, "top write", HIT_DATA)
        top_held = mem.read_int(TOP_PAGE + TOP_LOW_BITS, 8)
        self._chk(
            sb,
            "CHK-ALIASPRI-OFFSET-TOP",
            "the write leaves at 0xFF_FFFF_F000 plus its low 12 bits and the responder holds it",
            (top_status, _f(top_aw, "addr")[0], top_held),
            (J2A_STATUS_SUCCESS, TOP_PAGE + TOP_LOW_BITS, HIT_DATA),
            f"issued=0x{top_issued:x} leaving=0x{_f(top_aw, 'addr')[0]:x} held=0x{top_held:x}",
        )
        carry_delta = (1 << 56) + CARRY_WRAP_PAGE - PAGE_CARRY
        await self._program(5, PAGE_CARRY, PAGE_CARRY + PAGE, carry_delta, "past bit 55")
        carry_issued = PAGE_CARRY + CARRY_LOW_BITS
        carry_status, _, carry_aw, _ = await self._access(
            True, carry_issued, "carry write", HIT_DATA
        )
        carry_addr = _f(carry_aw, "addr")[0]
        self._log(
            f"OBSERVATION carry write issued=0x{carry_issued:x} leaving=0x{carry_addr:x} "
            f"page=0x{carry_addr & ~LOW_MASK:x} initiator_status={carry_status} "
            "measured and logged only"
        )
        self._chk(
            sb,
            "CHK-ALIASPRI-OVERFLOW-OBS",
            "the carry write keeps its low 12 bits",
            carry_addr & LOW_MASK,
            CARRY_LOW_BITS,
            f"issued=0x{carry_issued:x} leaving=0x{carry_addr:x}: the low 12 bits "
            f"0x{carry_addr & LOW_MASK:x} against 0x{CARRY_LOW_BITS:x}; the leaving page "
            f"0x{carry_addr & ~LOW_MASK:x} and initiator_status={carry_status} are measured "
            "and logged only",
        )

        await self._mark("S7", "TIMEOUT: bounded waits and last state")
        self._timeout_paths(sb)
        await ClockCycles(self.clk, 2)
        self.step_ts["PASS"] = get_sim_time("ns")
        order = [*STEPS, "PASS"]
        stamps = " ".join(f"{k}={self.step_ts[k]:.0f}ns" for k in order)
        counts = " ".join(f"{s}={self.step_access[s]}" for s in STEPS)
        increasing = all(self.step_ts[b] > self.step_ts[a] for a, b in zip(order, order[1:]))
        every_step = all(self.step_access[s] > 0 for s in ACCESS_STEPS)
        self._log(f"CHK-NONVAC: ordered fence {'<'.join(order)} {stamps}; j2a accesses {counts}")
        self._chk(
            sb,
            "CHK-NONVAC",
            "ordered fence",
            (increasing, every_step, self.j2a <= J2A_ACCESS_BUDGET),
            (True, True, True),
            f"stamps strictly increase to the pass point, the miss reference precedes the first "
            f"hit, S2..S6 each count an access, total {self.j2a} of {J2A_ACCESS_BUDGET}",
        )

    def _timeout_paths(self, sb) -> None:
        self._log(
            f"TIMEOUT-PATH j2a: bound={J2A_POLL_LIMIT} polls used: not measured "
            f"count={self.j2a} expired={self.j2a_expired} last={self.j2a_last}"
        )
        self._log(
            f"TIMEOUT-PATH out_obs: bound={OUT_OBS_BOUND_CYCLES} clk max_used={self.obs_used_max} "
            f"count={self.obs_count} expired={self.obs_expired} last={self.obs_last}"
        )
        expired = self.j2a_expired + self.obs_expired
        finite = 0 < J2A_POLL_LIMIT < 10**9 and 0 < OUT_OBS_BOUND_CYCLES < 10**9
        self._chk(
            sb,
            "CHK-TIMEOUT-PATHS",
            "bounded waits",
            (expired, finite, bool(self.j2a_last), bool(self.obs_last)),
            (0, True, True, True),
            f"sites=2 expired={expired} j2a_accesses={self.j2a} captures={self.obs_count}",
        )
