# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seed-drawn address, size, strobe, payload and series cells of the three DTP JTAG2AXI bridges.

The SMC fabric bridge carries a 56-bit address and 64-bit data, and the two OTP bridges a 32-bit
address and 32-bit data (``hw/sys/dtp/doc/jtag.adoc``, the bridge table). A single operation
uses the effective size ``E = min(size, data_size)`` as AxSIZE and drives its strobe field on
WSTRB, and a completed operation reads op 0; a series write advances the address by ``2**E``
after each operation, and the series status is sticky until ``AXI_SERIES_CTRL.reset``
(``hw/ip/jtag/jtag_ptap/doc/architecture.adoc``, ``*_AXI_SINGLE_OP``, ``*_AXI_SERIES_CTRL``,
``*_AXI_SERIES_DATA_INCR``). An address between SMC unit apertures answers DECERR
(``hw/sys/smc/doc/memmap.adoc``).

S1: TAP reset, IDCODE, the fabric gate open, the capability data size, the lifecycle word that
    admits OTP reads, outbound filter entry 0 opened over the whole space, the draw.
S2: SPM cells: three words seeded, the drawn write, the drawn-size read at the issued address and
    the three words read back.
S3: SCRATCH_COLD cells inside one 32-bit register, restored afterwards.
S4: cells outside both apertures on ``u_axi_out_if`` (AxADDR, AxSIZE, WSTRB) and the responder.
S5: adopter window and DTP CSR window cells: a read and a zero-strobe write at the drawn offset,
    the address graded at the far-end link, the responses recorded.
S6: OTP bridge reads at drawn register words of the generated eFuse headers.
S7: series writes in an unclaimed span of the adopter window and outside both apertures.
S8: a failing series read at a drawn address between unit apertures, a series read of the SPM
    word the pinned full-strobe cell wrote (its response status and data graded), a second
    failing read at a second drawn address, then the reset.
S9: the series status reset.
S10: the PASS stamp, then the compares.

Pinned on every seed: each window and bridge, each size on the outbound tap, a full and a partial
strobe on the SPM, one series cell per tap.
"""

from __future__ import annotations

import importlib.util
import random
import re
from collections import Counter
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import _REPO_ROOT, c_header_u32, smc_addr, smc_indexed_addr
from seq_lib.smu_axi_helpers import AXI_TIMEOUT_NS
from seq_lib.smu_compose_helpers import hier, sample
from seq_lib.smu_filter_helpers import (
    OUTBOUND0_END,
    OUTBOUND0_FILTER_CONFIG,
    OUTBOUND0_START,
    PASS_ALL_END,
    PASS_RW_CONFIG,
    SMC_APERTURE_LOCAL_BASE,
)
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    DTP_IR_SMC_AXI_SERIES_DATA_INCR,
    DTP_IR_WIDTH,
    J2A_OP_NOP,
    J2A_OP_READ,
    J2A_OP_WRITE,
    J2A_STATUS_BUSY,
    J2A_STATUS_DECERR,
    J2A_STATUS_SUCCESS,
    JTAG2AXI_CAPS_DATA_SIZE_8B,
    JTAG2AXI_CAPS_DATA_SIZE_LSB,
    SMC_DBG_AXSIZE_4B,
    SMC_DBG_AXSIZE_8B,
    apply_axi_wstrb,
    dtp_ir_opcode,
    make_smu_jtag_tap,
    pack_otp_single_op,
    pack_single_op,
    pack_smc_series_ctrl,
    require_jtag_tdo_resolved,
    unpack_otp_single_op,
    unpack_single_op,
    unpack_smc_series_ctrl,
)
from seq_lib.smu_lifecycle_table import LC_STATE_NO_LCC
from seq_lib.smu_tb_pins import smu_scope

_SMC_C = _REPO_ROOT / "hw" / "sys" / "smc" / "regs" / "gen" / "c"
_SEP_C = _REPO_ROOT / "hw" / "sys" / "sep" / "regs" / "gen" / "c"
_EFUSE_C = _REPO_ROOT / "hw" / "ip" / "efuse" / "regs" / "gen" / "c"
_SMC_ADDR_H = _SMC_C / "smc_addr.h"
_SEP_ADDR_H = _SEP_C / "sep_addr.h"
_SMC_EFUSE_MAP_H = _SMC_C / "blocks" / "smc_efuse_map.h"
_SEP_EFUSE_MAP_H = _SEP_C / "blocks" / "sep_efuse_map.h"
_SMC_MEMORY_MAP_PY = _REPO_ROOT / "hw" / "sys" / "smc" / "regs" / "gen" / "py" / "smc_memory_map.py"

MASK64 = (1 << 64) - 1
MASK32 = (1 << 32) - 1
# hw/sys/dtp/doc/jtag.adoc, the bridge table: the SMC fabric bridge carries 64-bit data, so its
# data_size capability is 3 and the 2-bit size field takes 0 to 3.
DATA_SIZE = JTAG2AXI_CAPS_DATA_SIZE_8B
SIZES = (0, 1, 2, 3)
# A size inside one 32-bit word: the adopter and DTP CSR links are 32-bit AXI-Lite
# (doc/integrator/src/smu-smc.adoc, "Adopter Peripheral Window"), and SCRATCH_COLD is a bank of
# 32-bit registers (hw/sys/smc/regs/blocks/scratch/scratch.rdl).
WORD_SIZES = (0, 1, 2)

SPM_BASE = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR")
SPM_SIZE = smc_addr("SMC_TOP_SPM_MEMORY_SIZE")
SCRATCH_BASE = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_BASE_ADDR")
SCRATCH_SIZE = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SIZE")
EXT_BASE = smc_addr("SMC_TOP_SMC_EXTERNAL_BASE_ADDR")
EXT_SIZE = smc_addr("SMC_TOP_SMC_EXTERNAL_SIZE")
DTP_BASE = smc_addr("SMC_TOP_DTP_CTRL_REG_BASE_ADDR")
DTP_SIZE = smc_addr("SMC_TOP_DTP_CTRL_REG_SIZE")
# The far-end link address is compared modulo the window's power-of-two span, the window bases
# being aligned to it, as smu_dtp_jtag2axi_address_walk_test compares it.
EXT_SPAN_MASK = (1 << (EXT_SIZE - 1).bit_length()) - 1
DTP_SPAN_MASK = (1 << (DTP_SIZE - 1).bit_length()) - 1
# doc/integrator/src/smu-smc.adoc, "SHIM control address window": the eFuse SHIM range at the
# window base (SMU default size 0x4) leaves on efuse_bank_ctrl, every other offset on the
# external port.
_EXT_BLOCKS = (
    ("SMC_TOP_SMC_EXTERNAL_MANDATORY_EFUSE_SHIM_CTRL_BASE_ADDR", "_SIZE"),
    ("SMC_TOP_SMC_EXTERNAL_MANDATORY_GPIO_CTRL_BASE_ADDR", "_TOTAL_SIZE"),
    ("SMC_TOP_SMC_EXTERNAL_MANDATORY_SMC_PLL_WRAP_BASE_ADDR", "_SIZE"),
    ("SMC_TOP_SMC_EXTERNAL_MANDATORY_STRAPS_BASE_ADDR", "_SIZE"),
    ("SMC_TOP_SMC_EXTERNAL_SUPPLEMENTARY_CONTROLLER_WRAP_BASE_ADDR", "_SIZE"),
    ("SMC_TOP_SMC_EXTERNAL_SUPPLEMENTARY_GPIO_EXTRA_INTF_BASE_ADDR", "_SIZE"),
    ("SMC_TOP_SMC_EXTERNAL_SUPPLEMENTARY_GPIO_EXTRA_CTRL_BASE_ADDR", "_SIZE"),
    ("SMC_TOP_SMC_EXTERNAL_SUPPLEMENTARY_SMC_PVT_WRAP_BASE_ADDR", "_SIZE"),
)
# Outside both apertures: every cell lies at or above 4 GiB, above the SEP and SMC apertures the
# leaf reads from the boundary ports (guarded at S1), and below the 56-bit top.
OUTSIDE_FLOOR = 1 << 32
ADDR_TOP = 1 << 56
PAGE = 0x1000
SERIES_COUNTS = (2, 8)
EXTRA_CELLS = (2, 6)
STICKY_DRAW_BOUND = 64
# hw/sys/smc/doc/memmap.adoc: BASE + 0x001_7000 lies between unit apertures; it is the fixed
# address of the series contention cell, so the draw leaves its span out.
FIXED_GAP_OFFSET = 0x001_7000

ISSUE_GAP_CYCLES = 32
POLL_GAP_CYCLES = 16
SINGLE_POLL_LIMIT = 128
OTP_POLL_LIMIT = 64
SERIES_IDLE_TCKS = 64
# hw/ip/jtag/jtag_ptap/doc/architecture.adoc, *_AXI_SERIES_DATA_WITH_ERROR_STATUS: n + 1 bits for
# n = 8 * 2**E; the bit shifted out above the data reads 0 for a transaction that succeeded.
IR_SERIES_WES = dtp_ir_opcode("SMC_AXI_SERIES_DATA_WITH_ERROR_STATUS")
WES_DATA_BITS = 8 << SMC_DBG_AXSIZE_4B
WES_SUCCEEDED = 0
STEP_CLOCK_GAP = 2
STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10")
EXTRA_KINDS = (
    "spm",
    "scratch",
    "outside",
    "adopter",
    "dtp",
    "smc_otp",
    "sep_otp",
    "series_adopter",
    "series_outside",
)
# hw/ip/efuse/regs/efuse_mmr.rdl: TOKEN_EOP is write-only (sw = w), so no read verdict is
# stated for it.
WRITE_ONLY_WORDS = frozenset({c_header_u32(_SEP_ADDR_H, "SEP_TOP_EFUSE_MMR_TOKEN_EOP_BASE_ADDR")})

_STRUCT_MEMBER = re.compile(r"^\s*(\w+)\s+(\w+)(?:\[(\d+)\])?(?:\[(\d+)\])?;")
_INT_BYTES = {"uint32_t": 4, "uint64_t": 8}


def _struct_members(path: Path) -> list[tuple[str, int, int]]:
    """(name, byte offset, byte size) of each member of the packed register struct."""
    text = path.read_text(encoding="utf-8")
    body = text[text.index("typedef struct") : text.index("}", text.index("typedef struct"))]
    out, offset = [], 0
    for line in body.splitlines()[1:]:
        m = _STRUCT_MEMBER.match(line)
        if not m:
            continue
        nbytes = _INT_BYTES.get(m.group(1), 4)
        if m.group(4):
            # A two-dimensional member is an array of multi-word registers, element i named
            # with its index as the generated lock fields name it.
            each = nbytes * int(m.group(4))
            for i in range(int(m.group(3))):
                out.append((f"{m.group(2)}{i}", offset, each))
                offset += each
            continue
        count = int(m.group(3) or 1)
        out.append((m.group(2), offset, nbytes * count))
        offset += nbytes * count
    return out


def _block_words(header: Path, prefix: str, struct: Path | None) -> list[tuple[str, int]]:
    """Every 32-bit word of a block whose generated register struct tiles it exactly."""
    base = c_header_u32(header, f"{prefix}_BASE_ADDR")
    size = c_header_u32(header, f"{prefix}_SIZE")
    if struct is None:
        return [(f"{prefix}+0x{off:x}", base + off) for off in range(0, size, 4)]
    members = _struct_members(struct)
    if sum(m[2] for m in members) != size:
        raise RuntimeError(f"{struct.name} does not tile {prefix} (size 0x{size:x})")
    return [(name, base + off + w) for name, off, nbytes in members for w in range(0, nbytes, 4)]


def _image_words(path: str, count: int) -> list[int]:
    words = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        words.append(int(line, 16))
        if len(words) == count:
            break
    return words


def _read_locked(header: Path, register: str, locks: dict[str, int]) -> bool:
    """True when the image sets the generated read-lock bit that names ``register``.

    The lock registers carry no read lock; any other register without a lock symbol raises.
    """
    if register.upper() in locks:
        return False
    stem = header.stem.upper()
    found = False
    for lock_reg, value in locks.items():
        symbol = f"{stem}__{lock_reg}__{register.upper()}_READ_LOCK_bm"
        try:
            bit = c_header_u32(header, symbol)
        except KeyError:
            continue
        found = True
        if value & bit:
            return True
    if not found:
        raise RuntimeError(f"{header.name}: no read-lock symbol names {register}")
    return False


def smc_otp_words(image: str) -> list[tuple[str, int]]:
    """SMC OTP register words: the eFuse map and interface-control blocks of smc_addr.h.

    smc_efuse_map.rdl: a register whose read lock is set is not readable, with no response
    stated, so a word whose read lock the Run mode's shadow image sets is not drawn.
    """
    words = _block_words(_SMC_ADDR_H, "SMC_TOP_SMC_EFUSE_MAP", _SMC_EFUSE_MAP_H)
    lo, hi = _image_words(image, 2)
    locks = {"LOCKS": lo | (hi << 32)}
    words = [(n, a) for n, a in words if not _read_locked(_SMC_EFUSE_MAP_H, n, locks)]
    words += _block_words(_SMC_ADDR_H, "SMC_TOP_EFUSE_INTERFACE_CTRL", None)
    return words


def sep_otp_words(image: str) -> list[tuple[str, int]]:
    """SEP OTP register words: the eFuse map, interface-control and MMR blocks of sep_addr.h."""
    words = _block_words(_SEP_ADDR_H, "SEP_TOP_SEP_EFUSE_MAP", _SEP_EFUSE_MAP_H)
    w = _image_words(image, 3)
    locks = {"LOCKS": w[0] | (w[1] << 32), "LOCKS_SPARE": w[2]}
    words = [(n, a) for n, a in words if not _read_locked(_SEP_EFUSE_MAP_H, n, locks)]
    words += _block_words(_SEP_ADDR_H, "SEP_TOP_EFUSE_INTERFACE_CTRL", None)
    words += _block_words(_SEP_ADDR_H, "SEP_TOP_EFUSE_MMR", None)
    return [(n, a) for n, a in words if a not in WRITE_ONLY_WORDS]


def _load_memory_map():
    spec = importlib.util.spec_from_file_location("smc_memory_map", _SMC_MEMORY_MAP_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fabric_gaps() -> list[tuple[int, int]]:
    """Spans between unit apertures of the generated component map below the adopter window.

    hw/sys/smc/doc/memmap.adoc: a read between unit apertures answers DECERR. The span at
    BASE + FIXED_GAP_OFFSET is left out.
    """
    rows = sorted(
        (r["base"], r["end"])
        for r in _load_memory_map().VIEWS["smc-components"]["rows"]
        if r["end"] < EXT_BASE
    ) + [(EXT_BASE, EXT_BASE)]
    fixed = SMC_APERTURE_LOCAL_BASE + FIXED_GAP_OFFSET
    gaps = []
    for (_, end), (nxt, _) in zip(rows, rows[1:]):
        start = (end + 4) & ~3
        if start < nxt and not start <= fixed < nxt:
            gaps.append((start, nxt))
    return gaps


def adopter_spans() -> list[tuple[int, int]]:
    """Offsets of the adopter window that no block of the generated smc_external map owns."""
    blocks = []
    for base, suffix in _EXT_BLOCKS:
        size = smc_addr(base.replace("_BASE_ADDR", suffix))
        start = (
            smc_indexed_addr(base, 0) if suffix == "_TOTAL_SIZE" else smc_addr(base)
        ) - EXT_BASE
        blocks.append((start, start + size))
    blocks.sort()
    spans, cursor = [], 0
    for start, end in blocks:
        if start > cursor:
            spans.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < EXT_SIZE:
        spans.append((cursor, EXT_SIZE))
    return spans


def lanes(addr: int, size: int) -> list[int]:
    """Byte lanes of the 64-bit beat that size ``size`` at ``addr`` selects."""
    first = addr & 7
    last = ((addr & ~((1 << size) - 1)) & 7) + (1 << size)
    return list(range(first, last))


def lane_mask(lane_list: list[int]) -> int:
    return sum(0xFF << (8 * lane) for lane in lane_list)


def _strobe(rng: random.Random, lane_list: list[int], *, full=False, partial=False) -> int:
    if full:
        pick = (1 << len(lane_list)) - 1
    elif partial:
        pick = rng.randint(1, (1 << len(lane_list)) - 2)
    else:
        pick = rng.randint(1, (1 << len(lane_list)) - 1)
    return sum(1 << lane for i, lane in enumerate(lane_list) if (pick >> i) & 1)


def _single_cell(rng, kind: str, tag: str, *, size=None, full=False, partial=False) -> dict:
    cell = {"kind": kind, "tag": tag}
    if kind == "spm":
        size = rng.choice(SIZES) if size is None else size
        container = SPM_BASE + 8 * rng.randint(2, SPM_SIZE // 8 - 3)
        addr = container + (0 if full else rng.randint(0, 6) if partial else rng.randint(0, 7))
    elif kind == "scratch":
        size = rng.choice(WORD_SIZES)
        addr = SCRATCH_BASE + rng.randrange(0, SCRATCH_SIZE)
    elif kind == "outside":
        size = rng.choice(SIZES) if size is None else size
        container = 8 * rng.randint(OUTSIDE_FLOOR // 8 + 1, ADDR_TOP // 8 - 3)
        addr = container + rng.randint(0, 7)
    elif kind == "adopter":
        size = rng.choice(WORD_SIZES)
        addr = EXT_BASE + rng.randrange(0, EXT_SIZE)
    else:
        size = rng.choice(WORD_SIZES)
        addr = DTP_BASE + rng.randrange(0, DTP_SIZE)
    cell.update(addr=addr, size=size)
    if kind in ("spm", "scratch", "outside"):
        cell["strobe"] = _strobe(rng, lanes(addr, size), full=full, partial=partial)
        cell["payload"] = rng.getrandbits(64)
    return cell


def _series_cell(rng, kind: str, tag: str, spans) -> dict:
    count = rng.randint(*SERIES_COUNTS)
    if kind == "series_outside":
        e = rng.choice(SIZES)
        page = PAGE * rng.randint(OUTSIDE_FLOOR // PAGE, ADDR_TOP // PAGE - 1)
        addr = page + (rng.randint(0, PAGE // (1 << e) - count) << e)
    else:
        e = rng.choice(WORD_SIZES)
        fits = [(s, t) for s, t in spans if ((t >> e) - ((s + (1 << e) - 1) >> e)) >= count]
        start, end = rng.choice(fits)
        first = (start + (1 << e) - 1) >> e
        addr = EXT_BASE + ((rng.randint(first, (end >> e) - count)) << e)
    words = [rng.getrandbits(8 << e) for _ in range(count)]
    return {"kind": kind, "tag": tag, "addr": addr, "size": e, "count": count, "words": words}


def draw_plan(seed: int, smc_words, sep_words) -> dict:
    """Every cell of the run from the seed alone; pinned corners first, drawn cells after."""
    rng = random.Random(seed)
    spans, gaps = adopter_spans(), fabric_gaps()
    cells = [
        _single_cell(rng, "spm", "pinned full strobe", size=3, full=True),
        _single_cell(rng, "spm", "pinned partial strobe", size=3, partial=True),
        *(_single_cell(rng, "spm", f"pinned size {s}", size=s) for s in (2, 1, 0)),
        _single_cell(rng, "scratch", "pinned"),
        *(_single_cell(rng, "outside", f"pinned size {s}", size=s) for s in SIZES),
        _single_cell(rng, "adopter", "pinned"),
        _single_cell(rng, "dtp", "pinned"),
    ]
    for kind, words in (("smc_otp", smc_words), ("sep_otp", sep_words)):
        name, addr = rng.choice(words)
        cells.append({"kind": kind, "tag": "pinned", "addr": addr, "reg": name})
    cells.append(_series_cell(rng, "series_adopter", "pinned", spans))
    cells.append(_series_cell(rng, "series_outside", "pinned", spans))
    for i in range(rng.randint(*EXTRA_CELLS)):
        kind = rng.choice(EXTRA_KINDS)
        tag = f"drawn {i}"
        if kind in ("smc_otp", "sep_otp"):
            name, addr = rng.choice(smc_words if kind == "smc_otp" else sep_words)
            cells.append({"kind": kind, "tag": tag, "addr": addr, "reg": name})
        elif kind.startswith("series"):
            cells.append(_series_cell(rng, kind, tag, spans))
        else:
            cells.append(_single_cell(rng, kind, tag))
    start, end = rng.choice(gaps)
    first = start + 4 * rng.randrange(0, (end - start) // 4)
    second_draws = 0
    second = first
    while second == first:
        if second_draws >= STICKY_DRAW_BOUND:
            raise AssertionError(f"second sticky address draw bound {STICKY_DRAW_BOUND} reached")
        start, end = rng.choice(gaps)
        second = start + 4 * rng.randrange(0, (end - start) // 4)
        second_draws += 1
    for i, cell in enumerate(cells):
        cell["label"] = f"{cell['tag']} {cell['kind']} #{i}"
    # The succeeding sticky read targets the doubleword the pinned full-strobe SPM cell writes.
    return {
        "cells": cells,
        "sticky": (first, second),
        "sticky_ok": cells[0]["addr"],
        "second_draws": second_draws,
    }


def _merge(seed: int, beat: int, strobe: int) -> int:
    return apply_axi_wstrb(seed, beat, strobe, 8)


class _AxilTap:
    """Address handshakes on one AXI-Lite 32/32 link, in arrival order."""

    # AXI-Lite 32/32 request and response packing, LSB first.
    REQ_BITS = 111
    AR_VALID, AR_ADDR, AW_VALID, AW_ADDR = 1, 5, 75, 79
    AR_READY, AW_READY = 35, 40

    def __init__(self, req, resp, clk, seen: list) -> None:
        if len(req) != self.REQ_BITS:
            raise AssertionError(f"{req._path} is {len(req)} bits, not an AXI-Lite 32/32 request")
        self._req, self._resp, self._clk, self.seen = req, resp, clk, seen
        self._task = cocotb.start_soon(self._watch())

    async def _watch(self) -> None:
        while True:
            await RisingEdge(self._clk)
            req, resp = self._req.value, self._resp.value
            if not (req.is_resolvable and resp.is_resolvable):
                continue
            req, resp = int(req), int(resp)
            if (req >> self.AW_VALID) & 1 and (resp >> self.AW_READY) & 1:
                self.seen.append(("w", (req >> self.AW_ADDR) & 0xFFFF_FFFF))
            if (req >> self.AR_VALID) & 1 and (resp >> self.AR_READY) & 1:
                self.seen.append(("r", (req >> self.AR_ADDR) & 0xFFFF_FFFF))

    def stop(self) -> None:
        self._task.cancel()


class _OutTap:
    """AW (AxADDR, AxSIZE), W (WSTRB) and AR (AxADDR, AxSIZE) handshakes on u_axi_out_if."""

    def __init__(self, dut) -> None:
        self._if, self._clk = dut.u_axi_out_if, dut.clk_smu_i
        self.aw: list[tuple[int, int]] = []
        self.w: list[int] = []
        self.ar: list[tuple[int, int]] = []
        self._task = cocotb.start_soon(self._watch())

    def _int(self, name: str) -> int:
        val = getattr(self._if, name).value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on u_axi_out_if.{name}: {val}")
        return int(val)

    async def _watch(self) -> None:
        while True:
            await RisingEdge(self._clk)
            if self._int("awvalid") and self._int("awready"):
                self.aw.append((self._int("awaddr"), self._int("awsize")))
            if self._int("wvalid") and self._int("wready"):
                self.w.append(self._int("wstrb"))
            if self._int("arvalid") and self._int("arready"):
                self.ar.append((self._int("araddr"), self._int("arsize")))

    def mark(self) -> tuple[int, int, int]:
        return len(self.aw), len(self.w), len(self.ar)

    def since(self, mark):
        return self.aw[mark[0] :], self.w[mark[1] :], self.ar[mark[2] :]

    def stop(self) -> None:
        self._task.cancel()


class smu_jtag2axi_access_matrix_rand_test_seq:
    """Drawn single and series cells over the SMC fabric and both OTP JTAG2AXI bridges."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.sb = test.env.scoreboard
        self.clk = self.dut.clk_smu_i
        self.ext_bound_cycles = int(AXI_TIMEOUT_NS // self.cfg.smu_clk_period_ns)
        self.seed = test.random_seed()
        self.jtag = None
        self.mem = self.cfg.axi_out_mem
        self.stamp_ps: dict[str, int] = {}
        self.sites: list[dict] = []
        self.accesses: Counter = Counter()
        self.obs: dict[str, dict] = {k: {} for k in ("addr", "size", "wstrb", "data", "series")}
        self.want: dict[str, dict] = {k: {} for k in ("addr", "size", "wstrb", "data", "series")}
        self.graded: Counter = Counter()
        self.sizes_on_tap: set[int] = set()
        self.spm_model: dict[int, int] = {}
        self.done = False

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    async def _mark(self, step: str, text: str) -> None:
        await RisingEdge(self.clk)
        self.stamp_ps[step] = int(get_sim_time(unit="ps"))
        self._log(f"STEP {step} @{self.stamp_ps[step] / 1000:.3f}ns: {text}")

    def _site(
        self, kind: str, label: str, bound: int, unit: str, used: int, last: str, expired: bool
    ) -> None:
        self.sites.append(
            {
                "kind": kind,
                "label": label,
                "bound": bound,
                "unit": unit,
                "used": used,
                "last": last,
                "expired": int(expired),
            }
        )
        if expired:
            raise AssertionError(
                f"TIMEOUT {kind} {label}: bound={bound} {unit} used={used} {unit} last={last}"
            )

    def _record(self, check: str, key: str, got, want) -> None:
        self.obs[check][key] = got
        self.want[check][key] = want

    def _counts(self) -> tuple[int, int, int]:
        dut = self.dut
        return (
            sample(dut.dtp_smc_dbg_aw_count_o, "dtp_smc_dbg_aw_count_o"),
            sample(dut.dtp_smc_dbg_ar_count_o, "dtp_smc_dbg_ar_count_o"),
            sample(dut.dtp_smc_dbg_b_count_o, "dtp_smc_dbg_b_count_o"),
        )

    async def _single(
        self, op: int, addr: int, label: str, *, data=0, wstrb=0, size=SMC_DBG_AXSIZE_8B
    ) -> tuple[int, int]:
        """One fabric SINGLE_OP and its bounded status poll; returns (op, rdata)."""
        self.accesses["fabric_single"] += 1
        await self.jtag.write("SMC_AXI_SINGLE_OP", pack_single_op(op, addr, data, wstrb, size))
        require_jtag_tdo_resolved(f"SINGLE_OP issue {label}")
        await ClockCycles(self.clk, ISSUE_GAP_CYCLES)
        status, rdata, used = J2A_STATUS_BUSY, 0, 0
        while used < SINGLE_POLL_LIMIT:
            capt = await self.jtag.read("SMC_AXI_SINGLE_OP", shift_value=0)
            require_jtag_tdo_resolved(f"SINGLE_OP poll {label}")
            status, rdata = unpack_single_op(capt)
            used += 1
            if status != J2A_STATUS_BUSY:
                break
            await ClockCycles(self.clk, POLL_GAP_CYCLES)
        self._site(
            "single_op",
            label,
            SINGLE_POLL_LIMIT,
            "polls",
            used,
            f"op={status}",
            status == J2A_STATUS_BUSY,
        )
        return status, rdata

    async def _otp_read(self, tdr: str, addr: int, label: str) -> tuple[int, int]:
        self.accesses["otp_single"] += 1
        await self.jtag.write(tdr, pack_otp_single_op(J2A_OP_READ, addr))
        require_jtag_tdo_resolved(f"{tdr} issue {label}")
        await ClockCycles(self.clk, ISSUE_GAP_CYCLES)
        status, rdata, used = J2A_STATUS_BUSY, 0, 0
        while used < OTP_POLL_LIMIT:
            capt = await self.jtag.read(tdr, shift_value=0)
            require_jtag_tdo_resolved(f"{tdr} poll {label}")
            status, rdata = unpack_otp_single_op(capt)
            used += 1
            if status != J2A_STATUS_BUSY:
                break
            await ClockCycles(self.clk, POLL_GAP_CYCLES)
        self._site(
            "otp_op",
            label,
            OTP_POLL_LIMIT,
            "polls",
            used,
            f"op={status}",
            status == J2A_STATUS_BUSY,
        )
        return status, rdata

    async def _series_ctrl(self, op: int, addr: int, size: int, *, reset: int = 0) -> None:
        self.accesses["series_ctrl"] += 1
        word = pack_smc_series_ctrl(op, addr, pipeline_depth=0, size=size, reset=reset)
        await self.jtag.write("SMC_AXI_SERIES_CTRL", word)
        require_jtag_tdo_resolved(f"SERIES_CTRL op={op} reset={reset}")

    async def _series_status(self) -> int:
        self.accesses["series_ctrl"] += 1
        nop = pack_smc_series_ctrl(J2A_OP_NOP, 0, pipeline_depth=0, size=SMC_DBG_AXSIZE_4B)
        capt = await self.jtag.read("SMC_AXI_SERIES_CTRL", shift_value=nop)
        require_jtag_tdo_resolved("SERIES_CTRL status")
        return unpack_smc_series_ctrl(capt)[4]

    async def _series_data(self, word: int, size: int) -> int:
        self.accesses["series_data"] += 1
        await self.jtag.shift_ir(DTP_IR_SMC_AXI_SERIES_DATA_INCR, DTP_IR_WIDTH)
        capt = await self.jtag.shift_dr(word, 8 << size, back_to_rti=True)
        require_jtag_tdo_resolved("SERIES_DATA_INCR")
        for _ in range(SERIES_IDLE_TCKS):
            await self.jtag.step_tms(0)
        return int(capt)

    async def _series_wes(self, inc: int) -> tuple[int, int]:
        """One SERIES_DATA_WITH_ERROR_STATUS scan at E = 2; returns (data, status bit)."""
        self.accesses["series_data"] += 1
        await self.jtag.shift_ir(IR_SERIES_WES, DTP_IR_WIDTH)
        capt = await self.jtag.shift_dr(inc << WES_DATA_BITS, WES_DATA_BITS + 1, back_to_rti=True)
        require_jtag_tdo_resolved("SERIES_DATA_WITH_ERROR_STATUS")
        for _ in range(SERIES_IDLE_TCKS):
            await self.jtag.step_tms(0)
        capt = int(capt)
        return capt & MASK32, (capt >> WES_DATA_BITS) & 1

    async def _wait_count(self, index: int, base: tuple, want: int, kind: str, label: str) -> int:
        """Wait until the DTP-to-SMC debug counter ``index`` moved by ``want``; bounded."""
        used = 0
        delta = 0
        while used < self.ext_bound_cycles:
            delta = (self._counts()[index] - base[index]) & 0xFFFF_FFFF
            if delta >= want:
                break
            used += 1
            await ClockCycles(self.clk, 1)
        self._site(
            kind,
            label,
            self.ext_bound_cycles,
            "clk_smu_i cycles",
            used,
            f"delta={delta}",
            delta < want,
        )
        return delta

    async def run(self) -> None:
        await self._setup()
        await self._step_cells("S2", "spm", self._spm_cell, "SPM cells")
        await self._step_cells("S3", "scratch", self._scratch_cell, "SCRATCH_COLD cells")
        await self._step_cells("S4", "outside", self._outside_cell, "cells outside both apertures")
        await self._mark("S5", "adopter window and DTP CSR window cells")
        for cell in self._cells("adopter", "dtp"):
            await self._link_cell(cell)
        await self._mark("S6", "OTP bridge reads at drawn register words")
        for cell in self._cells("smc_otp", "sep_otp"):
            await self._otp_cell(cell)
        await self._mark("S7", "series writes in the adopter window and outside both apertures")
        for cell in self._cells("series_adopter", "series_outside"):
            await self._series_cell(cell)
        await self._mark("S8", "failing, succeeding and failing series reads, then the reset")
        sticky = await self._sticky()
        await self._mark("S9", "series status reset after the cells")
        await self._series_ctrl(J2A_OP_NOP, 0, SMC_DBG_AXSIZE_4B, reset=1)
        await ClockCycles(self.clk, STEP_CLOCK_GAP)
        self.stamp_ps["S10"] = int(get_sim_time(unit="ps"))
        self._log(f"STEP S10 @{self.stamp_ps['S10'] / 1000:.3f}ns: PASS stamp")
        for tap in self.taps:
            tap.stop()
        self.out_tap.stop()
        self._check(sticky)
        self.done = True

    def _cells(self, *kinds: str) -> list[dict]:
        return [c for c in self.plan["cells"] if c["kind"] in kinds]

    async def _step_cells(self, step: str, kind: str, fn, text: str) -> None:
        await self._mark(step, text)
        for cell in self._cells(kind):
            await fn(cell)

    async def _setup(self) -> None:
        dut = self.dut
        self.jtag = jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        await self._mark("S1", "TAP reset, gate, capability, lifecycle word, filter, draw")
        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        if sample(dut.tb_smc_jtag2axi_security_disable, "tb_smc_jtag2axi_security_disable"):
            raise AssertionError("the SMC fabric JTAG2AXI gate is closed")
        caps = int(await jtag.read("SMC_JTAG2AXI_CAPS"))
        require_jtag_tdo_resolved("SMC_JTAG2AXI_CAPS")
        if (caps >> JTAG2AXI_CAPS_DATA_SIZE_LSB) & 0x7 != DATA_SIZE:
            raise AssertionError(f"SMC_JTAG2AXI_CAPS 0x{caps:x}: data_size is not {DATA_SIZE}")
        lc_state = sample(dut.lc_state_o, "lc_state_o")
        if lc_state != LC_STATE_NO_LCC:
            raise AssertionError(
                f"lc_state_o 0x{lc_state:02x}: the OTP reads need the TEST_DEV word "
                f"0x{LC_STATE_NO_LCC:02x} of the Run mode's image"
            )
        smc_image = str(cocotb.plusargs["smc_shadow_reg_preload"])
        sep_image = str(cocotb.plusargs["sep_shadow_reg_preload"])
        self.plan = draw_plan(self.seed, smc_otp_words(smc_image), sep_otp_words(sep_image))
        self._log(f"SEED: RANDOM_SEED={self.seed} {self._draw_text()}")
        apertures = []
        for base, size in (
            ("smc_global_base_o", "smc_region_size_o"),
            ("sep_global_base_o", "sep_region_size_o"),
        ):
            b = sample(getattr(dut, base), base)
            apertures.append((b, b + sample(getattr(dut, size), size)))
        for cell in self._cells("outside", "series_outside"):
            lo = (cell["addr"] & ~7) - 8
            hi = cell["addr"] + 16 + 8 * cell.get("count", 0)
            for a_lo, a_hi in apertures:
                if lo < a_hi and a_lo < hi:
                    raise AssertionError(f"{cell['label']} meets an aperture [{a_lo:x},{a_hi:x})")
        for addr, data in (
            (OUTBOUND0_START, 0),
            (OUTBOUND0_END, PASS_ALL_END),
            (OUTBOUND0_FILTER_CONFIG, PASS_RW_CONFIG),
        ):
            status, _ = await self._single(J2A_OP_WRITE, addr, f"filter 0x{addr:x}", data=data)
            if status != J2A_STATUS_SUCCESS:
                raise AssertionError(f"outbound filter write 0x{addr:x} op={status}")
        smu = smu_scope(dut)
        self.ext_seen: list = []
        self.dtp_seen: list = []
        self.otp_seen: dict[str, list] = {"smc_otp": [], "sep_otp": []}
        self.taps = [
            _AxilTap(
                dut.u_dut.smc_external_req, dut.u_dut.smc_external_resp, self.clk, self.ext_seen
            ),
            _AxilTap(
                dut.u_dut.smc_efuse_bank_ctrl_req,
                dut.u_dut.smc_efuse_bank_ctrl_resp,
                self.clk,
                self.ext_seen,
            ),
            _AxilTap(
                hier(smu, "smc_axil_dtp_csr_req"),
                hier(smu, "smc_axil_dtp_csr_resp"),
                self.clk,
                self.dtp_seen,
            ),
            _AxilTap(
                hier(smu, "dtp_axil_smc_otp_jtag_req"),
                hier(smu, "dtp_axil_smc_otp_jtag_resp"),
                self.clk,
                self.otp_seen["smc_otp"],
            ),
            _AxilTap(
                hier(smu, "dtp_axil_sep_otp_jtag_req"),
                hier(smu, "dtp_axil_sep_otp_jtag_resp"),
                self.clk,
                self.otp_seen["sep_otp"],
            ),
        ]
        self.out_tap = _OutTap(dut)
        self._log(
            "CONTROL the fixed cells CHK-J2A-WALK-EXTERNAL, CHK-J2A-WALK-DTP-CSR, "
            "CHK-J2A-WALK-SMC-OTP, CHK-J2A-WALK-SEP-OTP (smu_dtp_jtag2axi_address_walk_test), "
            "CHK-J2A-WSTRB-WIDTH and CHK-J2A-RW-MATRIX (smu_dtp_jtag2axi_smc_rw_matrix_test), "
            "CHK-J2A-WSTRB-NBR (smu_dtp_jtag2axi_wstrb_partial_sticky_test) and "
            "CHK-DBG-J2A-SERIES-INCR (smu_dtp_jtag2axi_series_contention_test) are those "
            "entries' and are not graded here"
        )

    def _draw_text(self) -> str:
        parts = []
        for c in self.plan["cells"]:
            if c["kind"].startswith("series"):
                parts.append(f"{c['label']} A=0x{c['addr']:x} E={c['size']} n={c['count']}")
            elif c["kind"].endswith("otp"):
                parts.append(f"{c['label']} {c['reg']} 0x{c['addr']:x}")
            else:
                extra = f" wstrb=0x{c['strobe']:02x}" if "strobe" in c else ""
                parts.append(f"{c['label']} 0x{c['addr']:x} size={c['size']}{extra}")
        first, second = self.plan["sticky"]
        parts.append(
            f"sticky 0x{first:x} 0x{second:x} second address draws={self.plan['second_draws']} "
            f"succeeding read 0x{self.plan['sticky_ok']:x}"
        )
        return "drawn " + "; ".join(parts)

    async def _spm_cell(self, cell: dict) -> None:
        addr, size, strobe, beat = cell["addr"], cell["size"], cell["strobe"], cell["payload"]
        container = addr & ~7
        seed = ~beat & MASK64
        label = cell["label"]
        for a in (container - 8, container, container + 8):
            st, _ = await self._single(J2A_OP_WRITE, a, f"{label} seed", data=seed, wstrb=0xFF)
            if st != J2A_STATUS_SUCCESS:
                raise AssertionError(f"{label}: seed write 0x{a:x} op={st}")
        op_wr, _ = await self._single(
            J2A_OP_WRITE, addr, f"{label} write", data=beat, wstrb=strobe, size=size
        )
        op_rd, rdata = await self._single(J2A_OP_READ, addr, f"{label} read", size=size)
        words = []
        for a in (container - 8, container, container + 8):
            _, word = await self._single(J2A_OP_READ, a, f"{label} readback")
            words.append(word & MASK64)
        merged = _merge(seed, beat, strobe)
        self.spm_model.update({container - 8: seed, container: merged, container + 8: seed})
        mask = lane_mask(lanes(addr, size))
        key = f"{label} 0x{addr:x} size={size} wstrb=0x{strobe:02x}"
        self._record("addr", key, (op_wr, words[1]), (J2A_STATUS_SUCCESS, merged))
        self._record("wstrb", key, tuple(words), (seed, merged, seed))
        self._record(
            "data",
            key,
            (op_wr, op_rd, rdata & mask, words[1]),
            (J2A_STATUS_SUCCESS, J2A_STATUS_SUCCESS, merged & mask, merged),
        )
        self.graded["spm"] += 1

    async def _scratch_cell(self, cell: dict) -> None:
        addr, size, strobe, beat = cell["addr"], cell["size"], cell["strobe"], cell["payload"]
        word_addr = addr & ~3
        shift = 8 * (word_addr & 4)
        word_strobe = 0xF << (word_addr & 4)
        label = cell["label"]
        _, orig = await self._single(J2A_OP_READ, word_addr, f"{label} original", size=2)
        orig = (orig >> shift) & 0xFFFF_FFFF
        seed32 = (~beat >> shift) & 0xFFFF_FFFF
        st, _ = await self._single(
            J2A_OP_WRITE,
            word_addr,
            f"{label} seed",
            data=seed32 << shift,
            wstrb=word_strobe,
            size=2,
        )
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(f"{label}: seed write op={st}")
        op_wr, _ = await self._single(
            J2A_OP_WRITE, addr, f"{label} write", data=beat, wstrb=strobe, size=size
        )
        op_rd, rdata = await self._single(J2A_OP_READ, addr, f"{label} read", size=size)
        _, word = await self._single(J2A_OP_READ, word_addr, f"{label} readback", size=2)
        word = (word >> shift) & 0xFFFF_FFFF
        st, _ = await self._single(
            J2A_OP_WRITE,
            word_addr,
            f"{label} restore",
            data=orig << shift,
            wstrb=word_strobe,
            size=2,
        )
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(f"{label}: restore write op={st}")
        merged_beat = _merge(seed32 << shift, beat, strobe)
        merged = (merged_beat >> shift) & 0xFFFF_FFFF
        mask = lane_mask(lanes(addr, size))
        key = f"{label} 0x{addr:x} size={size} wstrb=0x{strobe:02x}"
        self._log(f"OBSERVATION {key} original word 0x{orig:08x} restored")
        self._record("addr", key, (op_wr, word), (J2A_STATUS_SUCCESS, merged))
        self._record(
            "data",
            key,
            (op_wr, op_rd, rdata & mask, word),
            (J2A_STATUS_SUCCESS, J2A_STATUS_SUCCESS, merged_beat & mask, merged),
        )
        self.graded["scratch"] += 1

    async def _outside_cell(self, cell: dict) -> None:
        addr, size, strobe, beat = cell["addr"], cell["size"], cell["strobe"], cell["payload"]
        container = addr & ~7
        seed = ~beat & MASK64
        for a in (container - 8, container, container + 8):
            self.mem.write_int(a, seed, 8)
        label = cell["label"]
        mark = self.out_tap.mark()
        op_wr, _ = await self._single(
            J2A_OP_WRITE, addr, f"{label} write", data=beat, wstrb=strobe, size=size
        )
        op_rd, rdata = await self._single(J2A_OP_READ, addr, f"{label} read", size=size)
        aw, w, ar = self.out_tap.since(mark)
        held = [self.mem.read_int(a, 8) for a in (container - 8, container, container + 8)]
        merged = _merge(seed, beat, strobe)
        mask = lane_mask(lanes(addr, size))
        eff = min(size, DATA_SIZE)
        key = f"{label} 0x{addr:014x} size={size} wstrb=0x{strobe:02x}"
        self._record("addr", key, ([a for a, _ in aw], [a for a, _ in ar]), ([addr], [addr]))
        self._record("size", key, ([s for _, s in aw], [s for _, s in ar]), ([eff], [eff]))
        self._record("wstrb", key, (w, held[0], held[2]), ([strobe], seed, seed))
        self._record(
            "data",
            key,
            (op_wr, op_rd, rdata & mask, held[1]),
            (J2A_STATUS_SUCCESS, J2A_STATUS_SUCCESS, merged & mask, merged),
        )
        self.sizes_on_tap.add(size)
        self.graded["outside"] += 1

    async def _link_cell(self, cell: dict) -> None:
        addr, size, label = cell["addr"], cell["size"], cell["label"]
        seen, base, span = (
            (self.ext_seen, EXT_BASE, EXT_SPAN_MASK)
            if cell["kind"] == "adopter"
            else (self.dtp_seen, DTP_BASE, DTP_SPAN_MASK)
        )
        mark = len(seen)
        op_rd, rdata = await self._single(J2A_OP_READ, addr, f"{label} read", size=size)
        op_wr, _ = await self._single(J2A_OP_WRITE, addr, f"{label} write", wstrb=0, size=size)
        arrived = [(ch, a & span) for ch, a in seen[mark:]]
        offset = addr - base
        key = f"{label} offset 0x{offset:x} size={size}"
        self._log(
            f"OBSERVATION {key} responses read op={op_rd} data=0x{rdata:x} zero-strobe write "
            f"op={op_wr}; the target is the integration's, recorded and not graded"
        )
        self._record("addr", key, arrived, [("r", offset), ("w", offset)])
        self.graded[cell["kind"]] += 1

    async def _otp_cell(self, cell: dict) -> None:
        tdr = "SMC_OTP_AXI_SINGLE_OP" if cell["kind"] == "smc_otp" else "SEP_OTP_AXI_SINGLE_OP"
        seen = self.otp_seen[cell["kind"]]
        mark = len(seen)
        status, rdata = await self._otp_read(tdr, cell["addr"], cell["label"])
        key = f"{cell['label']} {cell['reg']} 0x{cell['addr']:08x}"
        self._log(f"OBSERVATION {key} read data 0x{rdata:08x}; the image word, not graded")
        self._record(
            "addr", key, (status, seen[mark:]), (J2A_STATUS_SUCCESS, [("r", cell["addr"])])
        )
        self.graded[cell["kind"]] += 1

    async def _series_cell(self, cell: dict) -> None:
        addr, e, count, words = cell["addr"], cell["size"], cell["count"], cell["words"]
        label = cell["label"]
        await self._series_ctrl(J2A_OP_NOP, 0, e, reset=1)
        before = await self._series_status()
        outside = cell["kind"] == "series_outside"
        step = 1 << e
        if outside:
            for k in range(count):
                self.mem.write_int(addr + k * step, ~words[k] & ((1 << (8 << e)) - 1), step)
            mark = self.out_tap.mark()
        else:
            ext_mark = len(self.ext_seen)
        base = self._counts()
        await self._series_ctrl(J2A_OP_WRITE, addr, e)
        for word in words:
            await self._series_data(word, e)
        b_delta = await self._wait_count(2, base, count, "b_count", label)
        after = await self._series_status()
        key = f"{label} A=0x{addr:x} E={e} n={count}"
        if outside:
            aw, _, _ = self.out_tap.since(mark)
            held = [self.mem.read_int(addr + k * step, step) for k in range(count)]
            self._record(
                "series",
                key,
                (before, aw, b_delta, held, after),
                (
                    J2A_STATUS_SUCCESS,
                    [(addr + k * step, e) for k in range(count)],
                    count,
                    words,
                    J2A_STATUS_SUCCESS,
                ),
            )
        else:
            arrived = [(ch, a & EXT_SPAN_MASK) for ch, a in self.ext_seen[ext_mark:]]
            offset = addr - EXT_BASE
            self._log(
                f"OBSERVATION {key} SERIES_CTRL.op after the writes {after}; the integration's "
                "response at an unclaimed offset, recorded and not graded"
            )
            self._record(
                "series",
                key,
                (before, arrived, b_delta),
                (J2A_STATUS_SUCCESS, [("w", offset + k * step) for k in range(count)], count),
            )
        await self._series_ctrl(J2A_OP_NOP, 0, e, reset=1)
        self.graded[cell["kind"]] += 1

    async def _sticky(self) -> tuple:
        """Status after the reset, a failure, a succeeding read, a second failure, the reset.

        The succeeding read takes two SERIES_DATA_WITH_ERROR_STATUS scans without increment: the
        second captures the first read's data and its status bit (and issues a second read of
        the same doubleword).
        """
        first, second = self.plan["sticky"]
        good = self.plan["sticky_ok"]
        await self._series_ctrl(J2A_OP_NOP, 0, SMC_DBG_AXSIZE_4B, reset=1)
        codes = [await self._series_status()]
        ok_read = None
        for n, addr in enumerate((first, good, second)):
            base = self._counts()
            await self._series_ctrl(J2A_OP_READ, addr, SMC_DBG_AXSIZE_4B)
            label = f"sticky read {n} 0x{addr:x}"
            if n == 1:
                capt, _ = await self._series_wes(0)
                await self._wait_count(1, base, 1, "ar_count", label)
                data, status = await self._series_wes(0)
                ok_read = (status, data)
                await self._wait_count(1, base, 2, "ar_count", f"{label} second scan")
            else:
                capt = await self._series_data(0, SMC_DBG_AXSIZE_4B)
                await self._wait_count(1, base, 1, "ar_count", label)
            for _ in range(SERIES_IDLE_TCKS):
                await self.jtag.step_tms(0)
            codes.append(await self._series_status())
            self._log(
                f"OBSERVATION {label} first data scan capture 0x{capt:x} (not the read's data: "
                "the read is issued at that scan's Update-DR)"
            )
        await self._series_ctrl(J2A_OP_NOP, 0, SMC_DBG_AXSIZE_4B, reset=1)
        codes.append(await self._series_status())
        return first, good, second, tuple(codes), ok_read

    def _check(self, sticky) -> None:
        sb = self.sb
        drawn = f"seed {self.seed}"
        for check, chk in (
            ("addr", "CHK-J2AMX-ADDR"),
            ("size", "CHK-J2AMX-SIZE"),
            ("wstrb", "CHK-J2AMX-WSTRB"),
            ("data", "CHK-J2AMX-DATA"),
            ("series", "CHK-J2AMX-SERIES"),
        ):
            self._log(f"{chk}: {len(self.obs[check])} cells {self.obs[check]}")
        name = f"drawn and pinned cells ({drawn})"
        sb.expect_eq(
            f"CHK-J2AMX-ADDR {name}", self.obs["addr"], self.want["addr"], evidence="CHK-J2AMX-ADDR"
        )
        sb.expect_eq(
            f"CHK-J2AMX-SIZE {name}", self.obs["size"], self.want["size"], evidence="CHK-J2AMX-SIZE"
        )
        sb.expect_eq(
            f"CHK-J2AMX-WSTRB {name}",
            self.obs["wstrb"],
            self.want["wstrb"],
            evidence="CHK-J2AMX-WSTRB",
        )
        sb.expect_eq(
            f"CHK-J2AMX-DATA {name}", self.obs["data"], self.want["data"], evidence="CHK-J2AMX-DATA"
        )
        sb.expect_eq(
            f"CHK-J2AMX-SERIES {name}",
            self.obs["series"],
            self.want["series"],
            evidence="CHK-J2AMX-SERIES",
        )
        first, good, second, codes, ok_read = sticky
        want = (
            J2A_STATUS_SUCCESS,
            J2A_STATUS_DECERR,
            J2A_STATUS_DECERR,
            J2A_STATUS_DECERR,
            J2A_STATUS_SUCCESS,
        )
        want_ok = (WES_SUCCEEDED, self.spm_model[good] & MASK32)
        self._log(
            f"CHK-J2AMX-STICKY-DRAWN drawn 0x{first:x} 0x{second:x}, SPM 0x{good:x}: status "
            f"after reset, first failure, succeeding read, second failure, reset = {codes}; "
            f"succeeding read (status bit, data) = {ok_read}, model {want_ok}; the fixed-address "
            "cell is smu_dtp_jtag2axi_series_contention_test's"
        )
        sb.expect_eq(
            f"CHK-J2AMX-STICKY-DRAWN drawn 0x{first:x} 0x{second:x}, succeeding read 0x{good:x}",
            (codes, ok_read),
            (want, want_ok),
            evidence="CHK-J2AMX-STICKY-DRAWN",
        )

        for rec in self.sites:
            self._log(
                f"TIMEOUT-PATH {rec['kind']} {rec['label']}: bound={rec['bound']} {rec['unit']} "
                f"used={rec['used']} {rec['unit']} {'EXPIRED' if rec['expired'] else 'ok'} "
                f"last={rec['last']}"
            )
        kinds = dict(Counter(rec["kind"] for rec in self.sites))
        expired = sum(rec["expired"] for rec in self.sites)
        expect_kinds = expected_site_kinds(self.plan)
        self._log(
            f"CHK-TIMEOUT-PATHS: sites={len(self.sites)} kinds={kinds} expected={expect_kinds} "
            f"expired={expired}; accesses={dict(self.accesses)}"
        )
        sb.expect_eq(
            "CHK-TIMEOUT-PATHS bounded waits per kind, none expired",
            (kinds, expired),
            (expect_kinds, 0),
            evidence="CHK-TIMEOUT-PATHS",
        )

        fence = "<".join(f"{s}@{self.stamp_ps[s] / 1000:.1f}" for s in STEPS)
        bridges = {
            "fabric": sum(self.graded[k] for k in ("spm", "scratch", "outside", "adopter", "dtp")),
            "smc_otp": self.graded["smc_otp"],
            "sep_otp": self.graded["sep_otp"],
        }
        self._log(f"OBSERVATION step fence {fence} (logged, not compared)")
        self._log(
            f"CHK-NONVAC: graded={dict(self.graded)} bridges={bridges} "
            f"sizes_on_tap={sorted(self.sizes_on_tap)} seed={self.seed}"
        )
        sb.expect_eq(
            "CHK-NONVAC a graded cell per bridge and window, every size on the tap",
            (
                min(bridges.values()) >= 1,
                min(self.graded[k] for k in EXTRA_KINDS) >= 1,
                sorted(self.sizes_on_tap),
            ),
            (True, True, list(SIZES)),
            evidence="CHK-NONVAC",
        )


def expected_site_kinds(plan: dict) -> dict[str, int]:
    """Bounded wait sites the plan makes, per kind."""
    singles = {"spm": 8, "scratch": 6, "outside": 2, "adopter": 2, "dtp": 2}
    kinds: Counter = Counter({"single_op": 3})
    for cell in plan["cells"]:
        kind = cell["kind"]
        if kind in singles:
            kinds["single_op"] += singles[kind]
        elif kind.endswith("otp"):
            kinds["otp_op"] += 1
        else:
            kinds["b_count"] += 1
    kinds["ar_count"] += 4
    return dict(kinds)
