# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Responder SLVERR and DECERR on smu_axi_out returned to the SMC and SEP initiators.

The crossbar routes a ``smc_out`` or ``sep_out`` request that matches neither aperture to
``ext_out``, generates every DECERR of its own for a request that reaches no subordinate, and
answers an ``ext_in`` request outside both apertures with DECERR because ``ext_in`` is not
connected to ``ext_out`` (``hw/sys/smu/doc/index.adoc``, "AXI Crossbar"). A request the bench
responder answers has therefore reached ``ext_out``, and the code it returns is the response of
that request at its initiator. The SMC fabric JTAG2AXI bridge reports SLVERR as op 1 and DECERR
as op 2 (``hw/ip/jtag/jtag_ptap/doc/architecture.adoc``, ``AXI_SINGLE_OP``). The SEP debug
module's system bus reports a failed access as a non-zero ``sbcs.sberror`` (RISC-V Debug
Specification 0.13, ``sbcs``); neither that specification nor a document or RDL in this tree maps
an AXI SLVERR or DECERR to a value of the field, so a SEP cell grades ``sberror`` non-zero and logs
the value it reads as an observation. The iDMA (``hw/sys/smc/doc/dma.adoc``) exposes no error
status; its outcome after an errored beat is logged only.

Every cell is a control access with the hook disarmed, the same access with a one-shot code
armed through ``inject_error`` of the responder at the 8-byte word of the chosen beat (the
responder keys a read inject per R beat word and a write inject per W beat word, answers the
errored write burst's one B with the code and does not store the errored write beat), and a
recovery write and read at that word. Eight cells are pinned on every seed (both codes, both
directions, the bridge, the SEP system bus and the first, middle and last beat of an iDMA read
burst and the last beat of an iDMA write burst) and two more are drawn from the seed. An iDMA
cell's burst is the first INCR burst of three or more beats the disarmed copy issues on the
cell's side: with the ``CONFIG`` this test writes, no burst crosses a 2 KiB-aligned boundary and
read and write bursts are formed in lockstep (``dma_ctrl.rdl`` ``CONFIG``), so a block that
straddles such a boundary is issued as two or three bursts and the first can be one beat. Every
address is drawn on its own 4 KiB page of the SEP's SMU aperture outside the SMC and SEP
apertures. One ``ext_in`` read outside both apertures with a read inject armed at its own word
leaves the inject armed; the next bridge read consumes it.

S1 setup and draw; per cell CTRL, ERR, REC; INB the ext_in leg; SEP the SEP bring-up; PASS.
"""

from __future__ import annotations

import random
from collections import Counter

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from ocah_axi_vip import RESP_DECERR, RESP_OKAY, RESP_SLVERR, resp_name
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import c_header_u32
from seq_lib.smu_axi_helpers import (
    AXI_TIMEOUT_NS,
    axi_read32_resp_ids_bounded,
    make_smu_axi_master,
)
from seq_lib.smu_axi_out_addr_len_size_test_seq import (
    DMA_CONFIG,
    DMA_CONFIG_ENABLE_ND,
    DMA_DONE_0,
    DMA_DONE_POLLS,
    DMA_DST_HI,
    DMA_DST_LO,
    DMA_DST_STRIDE_HI,
    DMA_DST_STRIDE_LO,
    DMA_LEN_HI,
    DMA_LEN_LO,
    DMA_NEXT_ID_0,
    DMA_POLL_CYCLES,
    DMA_REPS_HI,
    DMA_REPS_LO,
    DMA_SRC_HI,
    DMA_SRC_LO,
    DMA_SRC_STRIDE_HI,
    DMA_SRC_STRIDE_LO,
    DMA_STATUS_0,
)
from seq_lib.smu_compose_helpers import sample
from seq_lib.smu_dtp_sep_dm_dmi_test_seq import (
    DMI_OP_READ,
    DMI_OP_WRITE,
    pack_dmi,
    smu_dtp_sep_dm_dmi_test_seq,
)
from seq_lib.smu_dtp_sep_dm_sba_test_seq import (
    _SEP_CPU_CTRL_H,
    OUTBOUND_CFG_OPEN,
    OUTBOUND_END_ADDR,
    OUTBOUND_FILTER_CONFIG,
    OUTBOUND_START_ADDR,
    SBA_POLLS,
    SBADDRESS0_ADDR,
    SBCS_ADDR,
    SBCS_SBBUSY,
    SBCS_SBBUSYERROR,
    SBCS_SBERROR_MASK,
    SBCS_SBERROR_SHIFT,
    SBCS_SBERROR_W1C,
    SBCS_SBREADONADDR,
    SBDATA0_ADDR,
    SBDATA1_ADDR,
    smu_dtp_sep_dm_sba_test_seq,
)
from seq_lib.smu_filter_helpers import (
    OUTBOUND0_END,
    OUTBOUND0_FILTER_CONFIG,
    OUTBOUND0_START,
    PASS_ALL_END,
    PASS_RW_CONFIG,
    SMC_APERTURE_GLOBAL_BASE_REG,
    SMC_APERTURE_LOCAL_BASE,
)
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_BUSY,
    J2A_STATUS_DECERR,
    J2A_STATUS_SLVERR,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    SMC_DBG_AXSIZE_8B,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)
from seq_lib.smu_lc_export_seq import _ReadCounter
from seq_lib.smu_sep_sba_fabric_sweep_test_seq import (
    ADDR_MASK,
    OUTBOUND_CFG_SECURE,
    SECURE_END_ADDR,
    SECURE_FILTER_CONFIG,
    SECURE_START_ADDR,
)
from seq_lib.smu_tb_pins import smc_primary_reset

# The SEP's SMU aperture (sep_cpu_ctrl.rdl reset values): a SEP address there goes to the SEP
# outbound filter and the SMN, and it lies outside the SMC and SEP apertures of the crossbar.
SMU_BASE = c_header_u32(_SEP_CPU_CTRL_H, "SEP_CPU_CTRL__SMU_GLOBAL_BASE_ADDR__ADDR_reset")
SMU_SIZE = c_header_u32(_SEP_CPU_CTRL_H, "SEP_CPU_CTRL__SMU_REGION_SIZE__SIZE_reset")
PAGE_BYTES = 0x1000
# Pages drawn from the upper three quarters of the SMU aperture, clear of the firmware console
# word the bench snoops at the aperture base.
PAGE_LO = (SMU_BASE + SMU_SIZE // 4) // PAGE_BYTES
PAGE_HI = (SMU_BASE + SMU_SIZE) // PAGE_BYTES
# The responder keys one-shot injects per 8-byte bus word (64-bit smu_axi_out).
WORD_BYTES = 8
# iDMA copy length: one page-resident INCR burst of 8-byte beats has 32 beats.
COPY_LENGTH = 256
COPY_BEATS = COPY_LENGTH // WORD_BYTES
AXI_BURST_INCR = 1
# The beat classes need distinct first, middle and last beats. CONFIG is written with ENABLED_ND
# only: DECOUPLE_RW 0 forms read and write bursts in lockstep, and SRC_REDUCE_LEN and
# DST_REDUCE_LEN 0 keep every burst inside a 2 KiB-aligned block (dma_ctrl.rdl CONFIG). A 256-byte
# copy therefore crosses at most one such boundary per side and splits into at most three bursts,
# one of which has at least eleven beats.
PLACE_MIN_BEATS = 3

SLVERR, DECERR = "SLVERR", "DECERR"
CODE_RESP = {SLVERR: RESP_SLVERR, DECERR: RESP_DECERR}
# architecture.adoc AXI_SINGLE_OP op field.
CODE_J2A = {SLVERR: J2A_STATUS_SLVERR, DECERR: J2A_STATUS_DECERR}
# RISC-V Debug Specification 0.13, sbcs.sberror: 0 is no error.
SB_NO_ERROR = 0
SB_ACCESS_64 = 3

BRIDGE, IDMA, SEP = "bridge", "idma", "sep"
READ, WRITE = "r", "w"
SINGLE, FIRST, MIDDLE, LAST = "single", "first", "middle", "last"
# (initiator, direction, code, beat class) issued on every seed beside the drawn cells.
PINNED_CELLS = (
    (BRIDGE, READ, SLVERR, SINGLE),
    (BRIDGE, WRITE, DECERR, SINGLE),
    (IDMA, READ, SLVERR, FIRST),
    (IDMA, READ, DECERR, MIDDLE),
    (IDMA, READ, SLVERR, LAST),
    (IDMA, WRITE, DECERR, LAST),
    (SEP, READ, DECERR, SINGLE),
    (SEP, WRITE, SLVERR, SINGLE),
)
DRAWN_CELLS = 2
# Draws of one page, one payload or one copy image before the run fails.
REDRAW_BOUND = 32

J2A_POLL_LIMIT = 128
STEP_CLOCK_GAP = 2
INBOUND_ARID = 0x2A


def _initiator_beats(initiator: str) -> tuple[str, ...]:
    return (FIRST, MIDDLE, LAST) if initiator == IDMA else (SINGLE,)


def _pages_needed(initiator: str) -> int:
    return 2 if initiator == IDMA else 1


def draw_plan(seed: int) -> tuple[list[dict], dict]:
    """The pinned and drawn cells and the ext_in leg, a pure function of ``seed``."""
    rng = random.Random(seed)
    used_pages: set[int] = set()
    used_words: set[int] = {0}

    def page() -> int:
        for _ in range(REDRAW_BOUND):
            candidate = rng.randrange(PAGE_LO, PAGE_HI)
            if candidate not in used_pages:
                used_pages.add(candidate)
                return candidate * PAGE_BYTES
        raise AssertionError(f"no unused page after {REDRAW_BOUND} draws")

    def word() -> int:
        for _ in range(REDRAW_BOUND):
            value = rng.getrandbits(64)
            if value not in used_words:
                used_words.add(value)
                return value
        raise AssertionError(f"no unused payload after {REDRAW_BOUND} draws")

    def image() -> bytes:
        for _ in range(REDRAW_BOUND):
            data = rng.randbytes(COPY_LENGTH)
            words = {
                int.from_bytes(data[i : i + WORD_BYTES], "little")
                for i in range(0, COPY_LENGTH, WORD_BYTES)
            }
            if len(words) == COPY_BEATS and not words & used_words:
                used_words.update(words)
                return data
        raise AssertionError(f"no copy image with distinct non-zero words after {REDRAW_BOUND}")

    kinds = [("pinned", cell) for cell in PINNED_CELLS]
    for _ in range(DRAWN_CELLS):
        initiator = rng.choice((BRIDGE, IDMA, SEP))
        kinds.append(
            (
                "drawn",
                (
                    initiator,
                    rng.choice((READ, WRITE)),
                    rng.choice((SLVERR, DECERR)),
                    rng.choice(_initiator_beats(initiator)),
                ),
            )
        )
    plan = []
    for index, (origin, (initiator, direction, code, beat)) in enumerate(kinds, start=1):
        cell = {
            "index": index,
            "origin": origin,
            "initiator": initiator,
            "direction": direction,
            "code": code,
            "beat": beat,
            "mid": rng.randint(1, COPY_BEATS - 2) if origin == "drawn" else 0,
        }
        if initiator == IDMA:
            span = PAGE_BYTES - COPY_LENGTH + WORD_BYTES
            cell["src"] = page() + rng.randrange(0, span, WORD_BYTES)
            cell["dst"] = page() + rng.randrange(0, span, WORD_BYTES)
            cell["image"] = image()
        else:
            cell["addr"] = page() + rng.randrange(0, PAGE_BYTES, WORD_BYTES)
            cell["ctrl"] = word()
        cell["rec"] = word()
        plan.append(cell)
    inbound = {
        "addr": page() + rng.randrange(0, PAGE_BYTES, WORD_BYTES),
        "code": rng.choice((SLVERR, DECERR)),
        "data": word(),
    }
    for cell in plan:
        assert cell["beat"] in _initiator_beats(cell["initiator"]), cell
    assert {c["code"] for c in plan} == {SLVERR, DECERR}
    assert len(used_pages) == sum(_pages_needed(c["initiator"]) for c in plan) + 1
    return plan, inbound


def cell_label(cell: dict) -> str:
    where = (
        f"src=0x{cell['src']:x} dst=0x{cell['dst']:x}"
        if cell["initiator"] == IDMA
        else f"addr=0x{cell['addr']:x}"
    )
    return (
        f"{cell['origin']} cell {cell['index']} {cell['initiator']}/{cell['direction']}/"
        f"{cell['code']}/{cell['beat']} {where}"
    )


class _BeatTap:
    """Address phases and response beats of the outbound boundary interface, in order."""

    def __init__(self, dut) -> None:
        self._if = dut.u_axi_out_if
        self._clk = dut.clk_smu_i
        self.aw: list[tuple[int, int, int, int]] = []
        self.ar: list[tuple[int, int, int, int]] = []
        self.r: list[tuple[int, int]] = []
        self.b: list[int] = []
        self._task = cocotb.start_soon(self._watch())

    def _int(self, name: str) -> int:
        val = getattr(self._if, name).value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on u_axi_out_if.{name}: {val}")
        return int(val)

    def _fire(self, ch: str) -> bool:
        return bool(self._int(f"{ch}valid") and self._int(f"{ch}ready"))

    def _phase(self, ch: str) -> tuple[int, int, int, int]:
        return tuple(self._int(f"{ch}{f}") for f in ("addr", "len", "size", "burst"))

    async def _watch(self) -> None:
        while True:
            await RisingEdge(self._clk)
            if self._fire("aw"):
                self.aw.append(self._phase("aw"))
            if self._fire("ar"):
                self.ar.append(self._phase("ar"))
            if self._fire("r"):
                self.r.append((self._int("rresp"), self._int("rlast")))
            if self._fire("b"):
                self.b.append(self._int("bresp"))

    def mark(self) -> tuple[int, int, int, int]:
        return len(self.aw), len(self.ar), len(self.r), len(self.b)

    def reads(self, mark) -> list[tuple[tuple[int, int, int, int], list[int]]]:
        """Each AR since ``mark`` with the R codes of its burst so far (no read interleaving)."""
        groups: list[list[int]] = [[]]
        for resp, last in self.r[mark[2] :]:
            groups[-1].append(resp)
            if last:
                groups.append([])
        ars = self.ar[mark[1] :]
        return [(ar, groups[i] if i < len(groups) else []) for i, ar in enumerate(ars)]

    def writes(self, mark) -> list[tuple[tuple[int, int, int, int], int | None]]:
        """Each AW since ``mark`` with its B code, or None before the B."""
        bs = self.b[mark[3] :]
        return [(aw, bs[i] if i < len(bs) else None) for i, aw in enumerate(self.aw[mark[0] :])]

    def idle(self) -> bool:
        return sum(last for _, last in self.r) == len(self.ar) and len(self.b) == len(self.aw)

    def stop(self) -> None:
        if not self._task.done():
            self._task.cancel()


def _beats(phase: tuple[int, int, int, int]) -> list[int]:
    """The 8-byte bus word of each beat of an INCR burst."""
    addr, length, size, _ = phase
    nbytes = 1 << size
    first = addr - addr % nbytes
    return [((first + k * nbytes) // WORD_BYTES) * WORD_BYTES for k in range(length + 1)]


def placement_burst(bursts) -> int | None:
    """Index of the first INCR burst of ``PLACE_MIN_BEATS`` or more beats, None if there is none."""
    for index, (_, length, _, burst) in enumerate(bursts):
        if burst == AXI_BURST_INCR and length + 1 >= PLACE_MIN_BEATS:
            return index
    return None


def _covered(phases, lo: int, hi: int) -> int:
    return sum((p[1] + 1) << p[2] for p in phases if lo <= p[0] < hi)


class smu_ext_in_error_inject_rand_test_seq(smu_dtp_sep_dm_sba_test_seq):
    """Responder codes on drawn beats reach the bridge and the SEP bus; the iDMA is logged."""

    def __init__(self, test) -> None:
        super().__init__(test)
        self.mem = self.cfg.axi_out_mem
        self.clk = self.dut.clk_smu_i
        self.period_ps = round(self.cfg.smu_clk_period_ns * 1000)
        self.ext_bound = AXI_TIMEOUT_NS * 1000 // self.period_ps
        self.seed = test.random_seed()
        self.plan, self.inbound = draw_plan(self.seed)
        self.sites: list[dict] = []
        self.order: list[str] = []
        self.stamp_ps: dict[str, int] = {}
        self.injected: list[str] = []
        self.cells_done = 0
        self.j2a_tap = None
        self.tap: _BeatTap | None = None
        self._sbcs: int | None = None
        self.done = False

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _now(self) -> int:
        return int(get_sim_time(unit="ps"))

    async def _mark(self, step: str, text: str) -> None:
        await RisingEdge(self.clk)
        self.stamp_ps[step] = self._now()
        self.order.append(step)
        self._log(f"STEP {step} @{self.stamp_ps[step] / 1000:.3f}ns: {text}")

    def _site(self, kind: str, label: str, bound: int, unit: str, used: int, last: str, done: bool):
        """One wait record; ``used`` is in the bound's unit and the wait expired unless done."""
        self.sites.append(
            {
                "kind": kind,
                "label": label,
                "bound": bound,
                "unit": unit,
                "used": used,
                "last": last,
                "expired": int(not done),
            }
        )
        if not done and kind != "dma_obs":
            raise AssertionError(
                f"TIMEOUT {kind} {label}: bound={bound} {unit} used={used} {unit} last={last}"
            )

    # JTAG2AXI bridge ------------------------------------------------------------------------

    async def _j2a(self, op: str, addr: int, data: int = 0, *, size: int, wstrb: int = 0):
        tap = _ReadCounter(self.j2a_tap)
        if op == WRITE:
            st, rdata = await jtag2axi_single_write(
                tap, addr, data, wstrb=wstrb, size=size, poll_limit=J2A_POLL_LIMIT
            )
        else:
            st, rdata = await jtag2axi_single_read(tap, addr, size=size, poll_limit=J2A_POLL_LIMIT)
        require_jtag_tdo_resolved(f"J2A {op} @0x{addr:x}")
        self._site(
            "j2a",
            f"{op}@0x{addr:x}",
            J2A_POLL_LIMIT,
            "polls",
            tap.reads,
            f"op={st}",
            st != J2A_STATUS_BUSY,
        )
        return st, int(rdata)

    async def _j2a_wr32(self, addr: int, value: int) -> None:
        word = int(value) & 0xFFFF_FFFF
        packed, wstrb = (word << 32, 0xF0) if addr & 0x4 else (word, 0x0F)
        st, _ = await self._j2a(WRITE, addr, packed, size=SMC_DBG_AXSIZE_4B, wstrb=wstrb)
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A write 0x{addr:x} op={st}")

    async def _j2a_rd32(self, addr: int) -> int:
        st, raw = await self._j2a(READ, addr, size=SMC_DBG_AXSIZE_4B)
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A read 0x{addr:x} op={st}")
        return (raw >> 32) & 0xFFFF_FFFF if addr & 0x4 else raw & 0xFFFF_FFFF

    async def _j2a_wr64(self, addr: int, value: int) -> None:
        st, _ = await self._j2a(WRITE, addr, value, size=SMC_DBG_AXSIZE_8B, wstrb=0xFF)
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A write 0x{addr:x} op={st}")

    # SEP debug system bus -------------------------------------------------------------------

    async def _post(self, jtag, addr: int, data: int) -> None:
        await self._dmi_scan(jtag, pack_dmi(addr, data, op=DMI_OP_WRITE))

    async def _sb(self, jtag, addr: int, size: int, data: int | None = None) -> tuple[int, int]:
        """One system-bus access of 2**size bytes; returns (sberror, read data)."""
        sbcs = (size << 17) | (SBCS_SBREADONADDR if data is None else 0)
        if sbcs != self._sbcs:
            await self._post(jtag, SBCS_ADDR, sbcs)
            self._sbcs = sbcs
        if data is not None and size == SB_ACCESS_64:
            await self._post(jtag, SBDATA1_ADDR, (data >> 32) & 0xFFFF_FFFF)
        await self._post(jtag, SBADDRESS0_ADDR, addr)
        if data is not None:
            await self._post(jtag, SBDATA0_ADDR, data & 0xFFFF_FFFF)
        status = SBCS_SBBUSY
        polls = 0
        while polls < SBA_POLLS and status & SBCS_SBBUSY:
            status = await self._dmi(jtag, SBCS_ADDR, 0, DMI_OP_READ)
            polls += 1
        self._site(
            "sba",
            f"0x{addr:x}",
            SBA_POLLS,
            "polls",
            polls,
            f"sbcs=0x{status:08x}",
            not status & SBCS_SBBUSY,
        )
        if status & SBCS_SBBUSYERROR:
            raise AssertionError(f"system-bus access 0x{addr:08x}: sbbusyerror")
        err = (status >> SBCS_SBERROR_SHIFT) & SBCS_SBERROR_MASK
        if err:
            await self._dmi(jtag, SBCS_ADDR, sbcs | SBCS_SBERROR_W1C, DMI_OP_WRITE)
            return err, 0
        if data is not None:
            return 0, 0
        value = await self._dmi(jtag, SBDATA0_ADDR, 0, DMI_OP_READ)
        if size == SB_ACCESS_64:
            value |= (await self._dmi(jtag, SBDATA1_ADDR, 0, DMI_OP_READ)) << 32
        return 0, value

    async def _sb_ok(self, jtag, addr: int, size: int, data: int) -> None:
        err, _ = await self._sb(jtag, addr, size, data)
        if err:
            raise AssertionError(f"system-bus write 0x{addr:08x}: sberror={err}")

    # Outbound tap ---------------------------------------------------------------------------

    async def _await_tap(self, kind: str, label: str, done) -> None:
        used = 0
        while not done() and used < self.ext_bound:
            await RisingEdge(self.clk)
            used += 1
        tap = self.tap
        last = f"aw={len(tap.aw)} ar={len(tap.ar)} r={len(tap.r)} b={len(tap.b)}"
        self._site(kind, label, self.ext_bound, "clk_smu_i cycles", used, last, done())

    def _armed(self) -> tuple[int, int]:
        backend = self.mem.backend
        return len(backend.read_errors), len(backend.write_errors)

    # Single-access cells (bridge, SEP) ------------------------------------------------------

    async def _single(self, cell: dict, direction: str, data: int) -> int | tuple[int, int]:
        addr = cell["addr"]
        if cell["initiator"] == BRIDGE:
            st, rdata = await self._j2a(direction, addr, data, size=SMC_DBG_AXSIZE_8B, wstrb=0xFF)
            return st if direction == WRITE else (st, rdata)
        err, rdata = await self._sb(
            self.jtag, addr, SB_ACCESS_64, data if direction == WRITE else None
        )
        return err if direction == WRITE else (err, rdata)

    async def _single_access(self, cell: dict, direction: str, data: int, tag: str):
        mark = self.tap.mark()
        result = await self._single(cell, direction, data)
        if direction == READ:
            await self._await_tap(
                "ext_resp",
                f"{tag} read 0x{cell['addr']:x}",
                lambda: len(self.tap.reads(mark)) == 1 and len(self.tap.reads(mark)[0][1]) == 1,
            )
            phases = [(p[0], codes) for p, codes in self.tap.reads(mark)]
        else:
            await self._await_tap(
                "ext_resp",
                f"{tag} write 0x{cell['addr']:x}",
                lambda: len(self.tap.writes(mark)) == 1 and self.tap.writes(mark)[0][1] is not None,
            )
            phases = [(p[0], [code]) for p, code in self.tap.writes(mark)]
        return result, phases

    async def _cell_single(self, sb, cell: dict) -> None:
        label = cell_label(cell)
        addr, direction = cell["addr"], cell["direction"]
        okay = J2A_STATUS_SUCCESS if cell["initiator"] == BRIDGE else SB_NO_ERROR
        if direction == READ:
            self.mem.write_int(addr, cell["ctrl"], WORD_BYTES)
        result, phases = await self._single_access(cell, direction, cell["ctrl"], "ctrl")
        held = self.mem.read_int(addr, WORD_BYTES)
        got = (result, phases, held)
        want = (
            (okay, cell["ctrl"]) if direction == READ else okay,
            [(addr, [RESP_OKAY])],
            cell["ctrl"],
        )
        self._log(f"CHK-EXTERR-NOXBAR control {label}: got={got}")
        sb.expect_eq(
            f"CHK-EXTERR-NOXBAR the disarmed access answers OKAY with the bytes {label}",
            got,
            want,
            evidence="CHK-EXTERR-NOXBAR",
        )
        await self._mark(f"C{cell['index']}-CTRL", f"control {label}")

        code = cell["code"]
        self.mem.inject_error(
            addr, CODE_RESP[code], read=direction == READ, write=direction == WRITE
        )
        armed = self._armed()
        result, phases = await self._single_access(cell, direction, cell["ctrl"], "err")
        status = result[0] if direction == READ else result
        consumed = self._armed()
        self.injected.append(code)
        if cell["initiator"] == BRIDGE:
            want_status = CODE_J2A[code]
            self._log(
                f"CHK-EXTERR-RESP {label}: initiator={status} want={want_status} tap={phases} "
                f"armed={armed} after={consumed}"
            )
            sb.expect_eq(
                f"CHK-EXTERR-RESP the responder {code} reaches the bridge as op {want_status} "
                f"{label}",
                status,
                want_status,
                evidence="CHK-EXTERR-RESP",
            )
        else:
            self._log(
                f"CHK-EXTERR-RESP {label}: sberror={status} want!={SB_NO_ERROR} tap={phases} "
                f"armed={armed} after={consumed}"
            )
            self._log(f"OBSERVATION sberror code for the responder {code} {label}: {status}")
            sb.expect_true(
                f"CHK-EXTERR-RESP the responder {code} reaches the SEP system bus as a "
                f"non-zero sberror {label}",
                status != SB_NO_ERROR,
                evidence="CHK-EXTERR-RESP",
            )
        sb.expect_eq(
            f"CHK-EXTERR-BEAT the tap shows the one {direction.upper()} beat at the armed word "
            f"carrying {code} and the inject consumed {label}",
            (phases, armed != (0, 0), consumed),
            ([(addr, [CODE_RESP[code]])], True, (0, 0)),
            evidence="CHK-EXTERR-BEAT",
        )
        await self._mark(f"C{cell['index']}-ERR", f"inject {label} status={status}")

        await self._recover(sb, cell, addr, cell["initiator"])

    async def _recover(self, sb, cell: dict, word: int, initiator: str) -> None:
        label = cell_label(cell)
        self.mem.clear_errors()
        probe = dict(cell, initiator=initiator, addr=word)
        wres, wph = await self._single_access(probe, WRITE, cell["rec"], "rec")
        rres, rph = await self._single_access(probe, READ, 0, "rec")
        okay = J2A_STATUS_SUCCESS if initiator == BRIDGE else SB_NO_ERROR
        got = (wres, rres, wph + rph, self.mem.read_int(word, WORD_BYTES))
        want = (okay, (okay, cell["rec"]), [(word, [RESP_OKAY])] * 2, cell["rec"])
        self._log(f"CHK-EXTERR-RECOVER {label} word=0x{word:x} via {initiator}: got={got}")
        sb.expect_eq(
            f"CHK-EXTERR-RECOVER the next write and read at the word answer OKAY with the "
            f"bytes written, via the {initiator} {label}",
            got,
            want,
            evidence="CHK-EXTERR-RECOVER",
        )
        await self._mark(f"C{cell['index']}-REC", f"recovery {label}")
        self.cells_done += 1

    # iDMA cells -----------------------------------------------------------------------------

    async def _dma_launch(self) -> tuple[int, int]:
        baseline = await self._j2a_rd32(DMA_DONE_0)
        # Reading NEXT_ID_0 submits the programmed copy (dma.adoc); it is read once per copy.
        launched = await self._j2a_rd32(DMA_NEXT_ID_0)
        return baseline, launched

    async def _dma_poll(self, kind: str, label: str, launched: int) -> int:
        done, used = -1, 0
        while used < DMA_DONE_POLLS and done != launched:
            await ClockCycles(self.clk, DMA_POLL_CYCLES)
            done = await self._j2a_rd32(DMA_DONE_0)
            used += 1
        self._site(kind, label, DMA_DONE_POLLS, "polls", used, f"DONE_0={done}", done == launched)
        return done

    async def _cell_idma(self, sb, cell: dict) -> None:
        label = cell_label(cell)
        src, dst, image = cell["src"], cell["dst"], cell["image"]
        self.mem.write(src, image)
        self.mem.write(dst, bytes(COPY_LENGTH))
        for addr, value in (
            (DMA_SRC_LO, src & 0xFFFF_FFFF),
            (DMA_SRC_HI, src >> 32),
            (DMA_DST_LO, dst & 0xFFFF_FFFF),
            (DMA_DST_HI, dst >> 32),
        ):
            await self._j2a_wr32(addr, value)
        mark = self.tap.mark()
        _, launched = await self._dma_launch()
        done = await self._dma_poll("dma_done", f"control {label}", launched)
        await self._await_tap("ext_resp", f"ctrl copy {label}", self.tap.idle)
        reads = [(p, c) for p, c in self.tap.reads(mark) if src <= p[0] < src + COPY_LENGTH]
        writes = [(p, c) for p, c in self.tap.writes(mark) if dst <= p[0] < dst + COPY_LENGTH]
        got = (
            done == launched,
            self.mem.read(dst, COPY_LENGTH).hex(),
            _covered([p for p, _ in reads], src, src + COPY_LENGTH),
            _covered([p for p, _ in writes], dst, dst + COPY_LENGTH),
            sorted({c for _, codes in reads for c in codes} | {c for _, c in writes}),
        )
        want = (True, image.hex(), COPY_LENGTH, COPY_LENGTH, [RESP_OKAY])
        self._log(
            f"CHK-EXTERR-NOXBAR control {label}: launched={launched} done={done} "
            f"ar={[(hex(p[0]), p[1], p[2]) for p, _ in reads]} "
            f"aw={[(hex(p[0]), p[1], p[2]) for p, _ in writes]}"
        )
        sb.expect_eq(
            f"CHK-EXTERR-NOXBAR the disarmed copy retires its id with the bytes and OKAY beats "
            f"{label}",
            got,
            want,
            evidence="CHK-EXTERR-NOXBAR",
        )
        await self._mark(f"C{cell['index']}-CTRL", f"control {label}")

        direction, code = cell["direction"], cell["code"]
        bursts = [p for p, _ in (reads if direction == READ else writes)]
        place = placement_burst(bursts)
        if place is None:
            raise AssertionError(
                f"{label}: no INCR burst of {PLACE_MIN_BEATS} or more beats among {bursts}, "
                "so the first, middle and last beat classes cannot be placed"
            )
        target = bursts[place]
        beats = _beats(target)
        k = {
            FIRST: 0,
            LAST: len(beats) - 1,
            MIDDLE: (1 + (cell["mid"] - 1) % (len(beats) - 2)) if cell["mid"] else len(beats) // 2,
        }[cell["beat"]]
        word = beats[k]
        self.mem.inject_error(
            word, CODE_RESP[code], read=direction == READ, write=direction == WRITE
        )
        armed = self._armed()
        mark = self.tap.mark()
        _, launched = await self._dma_launch()
        hit: list = []

        def target_done() -> bool:
            items = self.tap.reads(mark) if direction == READ else self.tap.writes(mark)
            for phase, resp in items:
                if word in _beats(phase):
                    complete = len(resp) == phase[1] + 1 if direction == READ else resp is not None
                    if complete:
                        hit[:] = [(phase, resp)]
                    return complete
            return False

        await self._await_tap("ext_resp", f"err copy {label}", target_done)
        consumed = self._armed()
        self.injected.append(code)
        phase, resp = hit[0]
        k_seen = _beats(phase).index(word)
        if direction == READ:
            want_codes = [RESP_OKAY] * (phase[1] + 1)
            want_codes[k] = CODE_RESP[code]
            got = (k_seen, resp, armed != (0, 0), consumed)
            want = (k, want_codes, True, (0, 0))
        else:
            got = (k_seen, phase[0] == target[0], resp, armed != (0, 0), consumed)
            want = (k, True, CODE_RESP[code], True, (0, 0))
        self._log(
            f"CHK-EXTERR-BEAT {label}: burst {place + 1} of {len(bursts)} "
            f"(0x{phase[0]:x},len={phase[1]},size={phase[2]}) "
            f"word=0x{word:x} beat={k_seen} codes={resp} armed={armed} after={consumed}"
        )
        sb.expect_eq(
            f"CHK-EXTERR-BEAT {code} on the {cell['beat']} {direction.upper()} beat {k} of the "
            f"first iDMA burst of {PLACE_MIN_BEATS} or more beats and OKAY elsewhere, inject "
            f"consumed {label}",
            got,
            want,
            evidence="CHK-EXTERR-BEAT",
        )
        retired = await self._dma_poll("dma_obs", f"err copy {label}", launched)
        status = await self._j2a_rd32(DMA_STATUS_0)
        await self._await_tap("tap_idle", f"after err copy {label}", self.tap.idle)
        self._log(
            f"OBSERVATION iDMA after the {code} beat {label}: launched={launched} "
            f"DONE_0={retired} STATUS_0=0x{status:x} dst_matches_image="
            f"{self.mem.read(dst, COPY_LENGTH) == image}; no cited document states the iDMA "
            "outcome of an error beat, logged only"
        )
        await self._mark(f"C{cell['index']}-ERR", f"inject {label} beat {k}")

        await self._recover(sb, cell, word, BRIDGE)

    # ext_in control leg ---------------------------------------------------------------------

    async def _inbound(self, sb, master) -> None:
        leg = self.inbound
        addr, code = leg["addr"], leg["code"]
        self.mem.write_int(addr, leg["data"], WORD_BYTES)
        self.mem.inject_error(addr, CODE_RESP[code], read=True, write=False)
        mark = self.tap.mark()
        start = self._now()
        rdata, rresp, _, rid = await axi_read32_resp_ids_bounded(
            master, addr, arid=INBOUND_ARID, label="ext_in_unmatched_read"
        )
        used_ns = (self._now() - start) // 1000
        self._site(
            "axi_in",
            f"ext_in read 0x{addr:x}",
            AXI_TIMEOUT_NS,
            "ns",
            used_ns,
            resp_name(rresp),
            used_ns <= AXI_TIMEOUT_NS,
        )
        armed_after = addr in self.mem.backend.read_errors
        ar_delta = len(self.tap.ar) - mark[1]
        self._log(
            f"OBSERVATION ext_in read 0x{addr:x}: rresp={resp_name(rresp)} rid=0x{rid:x} "
            f"rdata=0x{rdata:x} outbound AR={ar_delta}; the DECERR is the cell of "
            "smu_xbar_connectivity_matrix_test, logged as the control"
        )
        cell = {"initiator": BRIDGE, "addr": addr}
        (status, _), phases = await self._single_access(cell, READ, 0, "inb")
        consumed = addr not in self.mem.backend.read_errors
        self.mem.clear_errors()
        got = (armed_after, status, phases, consumed)
        want = (True, CODE_J2A[code], [(addr, [CODE_RESP[code]])], True)
        self._log(f"CHK-EXTERR-INBOUND drawn addr=0x{addr:x} code={code}: got={got}")
        sb.expect_eq(
            f"CHK-EXTERR-INBOUND the armed {code} at 0x{addr:x} survives the ext_in read and is "
            "consumed by the next bridge read",
            got,
            want,
            evidence="CHK-EXTERR-INBOUND",
        )
        await self._mark("INB", f"ext_in leg addr=0x{addr:x} code={code}")

    # Run ------------------------------------------------------------------------------------

    async def _setup_smc(self) -> None:
        dut = self.dut
        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        if sample(dut.tb_smc_jtag2axi_security_disable, "tb_smc_jtag2axi_security_disable"):
            raise AssertionError("SMC JTAG2AXI still gated after TCK sync")
        self.j2a_tap = jtag
        await self._j2a_wr32(SMC_APERTURE_GLOBAL_BASE_REG, SMC_APERTURE_LOCAL_BASE)
        for addr, value in (
            (OUTBOUND0_START, 0),
            (OUTBOUND0_END, PASS_ALL_END),
            (OUTBOUND0_FILTER_CONFIG, PASS_RW_CONFIG),
        ):
            await self._j2a_wr64(addr, value)
        for addr, value in (
            (DMA_CONFIG, DMA_CONFIG_ENABLE_ND),
            (DMA_LEN_LO, COPY_LENGTH),
            (DMA_LEN_HI, 0),
            (DMA_DST_STRIDE_LO, 0),
            (DMA_DST_STRIDE_HI, 0),
            (DMA_SRC_STRIDE_LO, 0),
            (DMA_SRC_STRIDE_HI, 0),
            (DMA_REPS_LO, 1),
            (DMA_REPS_HI, 0),
        ):
            await self._j2a_wr32(addr, value)

    def _check_apertures(self) -> None:
        dut = self.dut
        windows = [
            (
                sample(dut.sep_global_base_o, "sep_global_base_o"),
                sample(dut.sep_region_size_o, "sep_region_size_o"),
            ),
            (
                sample(dut.smc_global_base_o, "smc_global_base_o"),
                sample(dut.smc_region_size_o, "smc_region_size_o"),
            ),
        ]
        addrs = [self.inbound["addr"]]
        for cell in self.plan:
            if cell["initiator"] == IDMA:
                addrs += [cell["src"], cell["src"] + COPY_LENGTH - 1]
                addrs += [cell["dst"], cell["dst"] + COPY_LENGTH - 1]
            else:
                addrs.append(cell["addr"])
        inside = [a for a in addrs for base, size in windows if base <= a < base + size]
        if inside:
            raise AssertionError(f"drawn addresses inside an aperture {windows}: {inside}")
        self._log(f"apertures (base, size) sep/smc={windows}; every drawn address outside both")

    async def _setup_sep(self) -> None:
        await smu_dtp_sep_dm_dmi_test_seq.run(self)
        if not (self.s1_ok and self.s2_ok and self.s3_ok):
            raise AssertionError("SEP debug bring-up incomplete")
        jtag = self.jtag
        await self._sb_ok(jtag, OUTBOUND_START_ADDR, SB_ACCESS_64, 0)
        await self._sb_ok(jtag, OUTBOUND_END_ADDR, SB_ACCESS_64, ADDR_MASK)
        await self._sb_ok(jtag, OUTBOUND_FILTER_CONFIG, 2, OUTBOUND_CFG_OPEN)
        await self._sb_ok(jtag, SECURE_START_ADDR, SB_ACCESS_64, 0)
        await self._sb_ok(jtag, SECURE_END_ADDR, SB_ACCESS_64, ADDR_MASK)
        await self._sb_ok(jtag, SECURE_FILTER_CONFIG, 2, OUTBOUND_CFG_SECURE)

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        drawn = "; ".join(cell_label(c) for c in self.plan if c["origin"] == "drawn")
        self._log(
            f"SEED: RANDOM_SEED={self.seed} drawn {drawn}; drawn middle positions "
            f"{[c['mid'] for c in self.plan if c['origin'] == 'drawn']}; ext_in leg "
            f"addr=0x{self.inbound['addr']:x} code={self.inbound['code']}; pinned "
            + "; ".join(cell_label(c) for c in self.plan if c["origin"] == "pinned")
        )
        await self.cfg.reset_done.wait()
        self.tap = _BeatTap(self.dut)
        try:
            await self._setup_smc()
            self._check_apertures()
            master = await make_smu_axi_master(self.dut, self.clk, smc_primary_reset(self.dut))
            # smu_ext_in_error_cg samples the cells, the ext_in leg and the SEP cells only.
            self.dut.tb_fcov_gate.value = 1
            await self._mark("S1", "TAP, aperture alias, outbound entry 0, iDMA and AXI master")
            for cell in self.plan:
                if cell["initiator"] == IDMA:
                    await self._cell_idma(sb, cell)
                elif cell["initiator"] == BRIDGE:
                    await self._cell_single(sb, cell)
            await self._inbound(sb, master)
            await self._setup_sep()
            await self._mark("SEP", "SEP debug module and system bus ready, entries 1 and 2 open")
            for cell in self.plan:
                if cell["initiator"] == SEP:
                    await self._cell_single(sb, cell)
            await ClockCycles(self.clk, STEP_CLOCK_GAP)
            self.stamp_ps["PASS"] = self._now()
            self.order.append("PASS")
            self._log(f"STEP PASS @{self.stamp_ps['PASS'] / 1000:.3f}ns: PASS stamp")
            self._check_integrity(sb)
        finally:
            self.dut.tb_fcov_gate.value = 0
            self.tap.stop()
        self.done = True

    def _check_integrity(self, sb) -> None:
        for rec in self.sites:
            self._log(
                f"TIMEOUT-PATH {rec['kind']} {rec['label']}: bound={rec['bound']} {rec['unit']} "
                f"used={rec['used']} {rec['unit']} {'EXPIRED' if rec['expired'] else 'ok'} "
                f"last={rec['last']}"
            )
        kinds = Counter(rec["kind"] for rec in self.sites)
        expired = sum(rec["expired"] for rec in self.sites if rec["kind"] != "dma_obs")
        idma = sum(1 for c in self.plan if c["initiator"] == IDMA)
        bridge_or_sep = len(self.plan) - idma
        sep = sum(1 for c in self.plan if c["initiator"] == SEP)
        # Four tap waits per cell (control, error, recovery write and read) and the
        # bridge read of the ext_in leg.
        got = (
            expired,
            kinds["ext_resp"],
            kinds["dma_done"],
            kinds["dma_obs"],
            kinds["tap_idle"],
            kinds["axi_in"],
            kinds["j2a"] > 0,
            kinds["sba"] > 0,
        )
        want = (0, 4 * len(self.plan) + 1, idma, idma, idma, 1, True, sep > 0)
        self._log(
            f"CHK-TIMEOUT-PATHS: sites={len(self.sites)} kinds={dict(kinds)} expired={expired} "
            f"cells idma={idma} bridge/sep={bridge_or_sep}; dma_obs is the logged window after "
            "an errored copy, its expiry not a failure"
        )
        sb.expect_eq(
            "CHK-TIMEOUT-PATHS no bounded wait expired, tap/iDMA/ext_in waits per cell",
            got,
            want,
            evidence="CHK-TIMEOUT-PATHS",
        )

        stamps = [self.stamp_ps[s] for s in self.order]
        fence = "<".join(f"{s}@{t / 1000:.1f}" for s, t in zip(self.order, stamps))
        want_order = ["S1"]
        for c in self.plan:
            if c["initiator"] != SEP:
                want_order += [f"C{c['index']}-{s}" for s in ("CTRL", "ERR", "REC")]
        want_order += ["INB", "SEP"]
        for c in self.plan:
            if c["initiator"] == SEP:
                want_order += [f"C{c['index']}-{s}" for s in ("CTRL", "ERR", "REC")]
        want_order.append("PASS")
        self._log(f"OBSERVATION sim-time fence {fence} (logged, not compared)")
        self._log(
            f"CHK-NONVAC: step order {self.order} injected={Counter(self.injected)} "
            f"cells={self.cells_done}"
        )
        sb.expect_eq(
            "CHK-NONVAC step order of the plan, every cell injected and recovered, both codes",
            (self.order, sorted(set(self.injected)), self.cells_done),
            (want_order, [DECERR, SLVERR], len(self.plan)),
            evidence="CHK-NONVAC",
        )
