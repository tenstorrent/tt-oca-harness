# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CPU-path TCM ECC: the correctable counters raise MCEIP at the threshold, uncorrectable DCCM accesses trap, and no PIC source moves.

Firmware ``tcm_ecc_cpu_trap_test`` runs from the ICCM. This test draws the
threshold exponent t (0 to 5), the arming order of the DCCM correctable leg,
the flipped words and bits, the DCCM data words and the store byte from the run
seed. Before reset release it patches the parameter block, loads the data
words and the DCCM vector table into a reserved DCCM window that the image
leaves unused (``env/sep_dtcm_param_patch``), and writes the time-0 flip list
of the TCM bit-flip hook (``env/sep_tcm_flip``, ``+sep_tcm_flip_list``):
2^t + 1 single-bit flips in the ICCM straight-line block and in the DCCM
window, and three double-bit flips in the DCCM (the load word, the store word
and the vector-table word of PIC source 2). It follows the console
(``env/sep_fw_console``: graded window on ``M G`` / ``M C``), samples the CPU
trace, ``ext_debug_bus_o[367:364]`` and ``sep_internal_interrupts_probe_o`` on
every ``clk_i`` edge, and grades from the firmware CSR reads, the trap records,
the trace events and the pulse counts:

* CHK-TCM-CE      the counters read 0 after reset; MCEIP is set exactly when
                  the count field reaches 2^t (DCCM in every sample, ICCM at the
                  sample before the block and the quiescent sample after it);
                  every flipped DCCM load raises MDCCMECT; each arming that finds
                  MCEIP set traps once with mcause 0x8000_001E, an arming below
                  2^t does not.
* CHK-TCM-SILENT  with mie[30] clear the errors count with no trap and no trace
                  interrupt event, also at a count at or above 2^t.
* CHK-TCM-CLAMP   the exponent 31 reads back 26 in both counters; t reads back t.
* CHK-TCM-UE      the DCCM load traps with mcause 5, the byte store with mcause
                  7, both with mscause 1 and one trace exception event; the clean
                  neighbour of each returns its data or lands its byte.
* CHK-TCM-NMI     the vector-table read of source 2 ends in the NMI at the
                  programmed SEP_NMI_VEC with mcause 0xF000_1000.
* CHK-TCM-DBG     each access pulses its own debug-bus bit (ICCM single 367,
                  DCCM single 365, DCCM double 364) inside its markers, one
                  clock wide, and no other of the three bits.
* CHK-TCM-NO-PIC  the meip words equal their baseline and MICECT reads 0 after
                  the correctable leg and after each uncorrectable trap; the PIC
                  vector does not move around a correctable pulse.

Log only: ``OBS-TCM-INCR`` (corrections per access), ``OBS-TCM-DBG366``.
Expected values come from the cited interrupt chapter, the draws and the image
layout (the firmware symbol listing), never from a DUT read. cpu run mode,
``+skip_fuse_sense``, Verilator and VCS.
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass, field
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import ReadOnly, RisingEdge
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_dtcm_param_patch import parse_hex_cells, patch_param_block, place_words
from env.sep_fcov_gate import close_graded_window
from env.sep_fw_console import ConsoleRec, SepFwConsole, parse_kv
from env.sep_seeded_rng import SepSeededRng
from env.sep_tcm_flip import DCCM_BASE, DCCM_BYTES, ICCM_BASE, WORD_BITS, bit_mask, write_flip_list
from sep_base_test import sep_base_test

TEST = "sep_tcm_ecc_cpu_trap_test"
_FW = "tcm_ecc_cpu_trap_test"
_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", _FW)
_ITCM_HEX = os.path.join(_FW_DIR, f"{_FW}.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, f"{_FW}.dtcm.hex")
_BANNER = "SEP TCM ECC CPU trap test"
_FLIP_LIST = "sep_tcm_ecc_flips.txt"  # the +sep_tcm_flip_list of the testlist entry
_MAX_RUN_CYCLES = 20_000_000
_NO_BOOT_CYCLES = 80_000
_M32 = 0xFFFF_FFFF

# Parameter block (fw/tests/tcm_ecc_cpu_trap_test, enum P_*).
P_MAGIC = 0x3526EC0D
NFLIP_MAX = 33
P_WAIT = 20000
P_HOLD = 200

# Reserved DCCM window: data words, then the 1 KiB-aligned vector table.
WIN_BASE = 0xC005_0000
WIN_WORDS = 1024
TBL_BASE = WIN_BASE + 4 * WIN_WORDS
TBL_WORDS = 256
STACK_RESERVE = 0x1000  # bytes kept free below the stack top (environment choice)

# ICCM block: slot i is the word 0xE1C00037 + (i << 12) (lui x0, 0xE1C00 + i).
NSLOT = 33

# hw/sys/sep/doc/interrupts.adoc: MCEIP cause, uncorrectable traps, NMI cause.
MCAUSE_MCEIP = 0x8000_001E
MCAUSE_EXT = 0x8000_000B
MCAUSE_LOAD_FAULT = 5
MCAUSE_STORE_FAULT = 7
MSCAUSE_ECC = 1
MCAUSE_NMI_ECC = 0xF000_1000
CNT_MASK = 0x07FF_FFFF
CLAMP_MAX = 26
MIP_MCEIP = 1 << 30
MIE_MCEIE = 1 << 30
PIC_SRC = 2  # mailbox interrupt 1; vector bit PIC_SRC - 1

# ext_debug_bus_o[367:364] (hw/sys/sep/doc/interrupts.adoc, Debug bus mirror).
BIT_I_SB, BIT_I_DB, BIT_D_SB, BIT_D_DB = 367, 366, 365, 364
DBG_BITS = (BIT_I_SB, BIT_I_DB, BIT_D_SB, BIT_D_DB)
VEC_WINDOW = 4  # clocks around a correctable pulse (environment choice)


def load_symbols(fw_dir: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for path in glob.glob(os.path.join(fw_dir, f"{_FW}*.sym")):
        with open(path) as fh:
            for line in fh:
                parts = line.split()
                if len(parts) == 3:
                    try:
                        out[parts[2]] = int(parts[0], 16)
                    except ValueError:
                        continue
    return out


def slot_offsets(itcm_hex: str) -> list[int]:
    """ICCM byte offset of each block slot word, found by its unique encoding."""
    cells = parse_hex_cells(itcm_hex)
    words: dict[int, list[int]] = {}
    for off in range(0, max(cells) + 1, 4):
        w = sum(cells.get(off + b, 0) << (8 * b) for b in range(4))
        words.setdefault(w, []).append(off)
    out = []
    for i in range(NSLOT):
        hits = words.get((0xE1C0_0037 + (i << 12)) & _M32, [])
        if len(hits) != 1:
            raise AssertionError(f"ICCM block slot {i} found {len(hits)} times in the image")
        out.append(hits[0])
    return out


@dataclass
class TcmCfg:
    """The seeded stimulus. A pure function of the run seed."""

    seed: int
    t: int = 0
    order: int = 0  # 0 miss first, 1 reach first
    islots: list[int] = field(default_factory=list)
    ibits: list[int] = field(default_factory=list)
    data: list[int] = field(default_factory=list)
    singles: list[int] = field(default_factory=list)  # window word indices, access order
    sbits: list[int] = field(default_factory=list)
    ld: int = 0
    ld_nbr: int = 0
    st: int = 0
    st_nbr: int = 0
    ld_bits: tuple[int, int] = (0, 1)
    st_bits: tuple[int, int] = (0, 1)
    tbl_bits: tuple[int, int] = (0, 1)
    lane: int = 0
    byte: int = 0

    @property
    def n(self) -> int:
        return (1 << self.t) + 1

    @property
    def thr(self) -> int:
        return 1 << self.t

    @classmethod
    def from_seed(cls, seed: int) -> "TcmCfg":
        rng = SepSeededRng(seed)
        c = cls(seed)
        c.t = rng.randrange(0, 6)
        c.order = rng.randrange(0, 2)
        c.islots = sorted(rng.sample(range(NSLOT), c.n))
        c.ibits = [rng.randrange(WORD_BITS) for _ in range(c.n)]
        for _ in range(WIN_WORDS):
            w = 0
            while w == 0:
                w = rng.getrandbits(32)
            c.data.append(w)
        c.ld = rng.randrange(2, WIN_WORDS - 2)
        c.st = c.ld
        while abs(c.st - c.ld) <= 3:
            c.st = rng.randrange(2, WIN_WORDS - 2)
        c.ld_nbr = c.ld + (1 if rng.randrange(2) else -1)
        c.st_nbr = c.st + (1 if rng.randrange(2) else -1)
        busy = {c.ld - 1, c.ld, c.ld + 1, c.st - 1, c.st, c.st + 1}
        c.singles = rng.sample([i for i in range(1, WIN_WORDS - 1) if i not in busy], c.n)
        c.sbits = [rng.randrange(WORD_BITS) for _ in range(c.n)]
        c.ld_bits = tuple(rng.sample(range(WORD_BITS), 2))
        c.st_bits = tuple(rng.sample(range(WORD_BITS), 2))
        c.tbl_bits = tuple(rng.sample(range(WORD_BITS), 2))
        c.lane = rng.randrange(4)
        c.byte = rng.randrange(256)
        return c

    def addr(self, idx: int) -> int:
        return WIN_BASE + 4 * idx

    def st_nbr_exp(self) -> int:
        sh = 8 * self.lane
        return (self.data[self.st_nbr] & ~(0xFF << sh) | (self.byte << sh)) & _M32

    def words(self) -> list[int]:
        out = [
            P_MAGIC,
            self.seed & _M32,
            self.t,
            self.order,
            self.n,
            P_WAIT,
            P_HOLD,
            self.addr(self.ld),
            self.addr(self.ld_nbr),
            self.data[self.ld],
            self.data[self.ld_nbr],
            self.addr(self.st),
            self.addr(self.st_nbr),
            self.data[self.st],
            self.st_nbr_exp(),
            self.lane,
            self.byte,
            TBL_BASE,
        ]
        out += [self.addr(i) for i in self.singles]
        out += [0] * (NFLIP_MAX - len(self.singles))
        return out

    def flips(self, slots: list[int]) -> list[tuple[int, int, str]]:
        out = []
        for s, b in zip(self.islots, self.ibits, strict=True):
            out.append((ICCM_BASE + slots[s], bit_mask(b), f"iccm_slot{s}"))
        for i, b in zip(self.singles, self.sbits, strict=True):
            out.append((self.addr(i), bit_mask(b), f"dccm_single{i}"))
        out.append((self.addr(self.ld), bit_mask(*self.ld_bits), "dccm_load"))
        out.append((self.addr(self.st), bit_mask(*self.st_bits), "dccm_store"))
        out.append((TBL_BASE + 4 * PIC_SRC, bit_mask(*self.tbl_bits), "vector_table_src2"))
        return out

    def draw_lines(self) -> list[str]:
        return [
            f"DRAW t={self.t} order={'miss_first' if self.order == 0 else 'reach_first'} "
            f"flips_per_memory={self.n}",
            f"DRAW iccm_slots={self.islots} iccm_bits={self.ibits}",
            "DRAW dccm_singles="
            + ",".join(f"0x{self.addr(i):08x}" for i in self.singles)
            + f" dccm_bits={self.sbits}",
            f"DRAW dccm_load=0x{self.addr(self.ld):08x} bits={list(self.ld_bits)} "
            f"neighbour=0x{self.addr(self.ld_nbr):08x} dccm_store=0x{self.addr(self.st):08x} "
            f"bits={list(self.st_bits)} neighbour=0x{self.addr(self.st_nbr):08x} "
            f"lane={self.lane} byte=0x{self.byte:02x} vector_table_bits={list(self.tbl_bits)}",
        ]


@dataclass
class Pulse:
    clk: int
    nl: int
    bit: int
    width: int = 1


@pyuvm.test()
class sep_tcm_ecc_cpu_trap_test(sep_base_test):
    """CPU-path TCM ECC counters, MCEIP delivery, uncorrectable traps, NMI and debug-bus pulses."""

    build_env = False
    required_evidence = (
        "CHK-TCM-CE",
        "CHK-TCM-SILENT",
        "CHK-TCM-CLAMP",
        "CHK-TCM-UE",
        "CHK-TCM-NMI",
        "CHK-TCM-DBG",
        "CHK-TCM-NO-PIC",
    )

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    # ---- per-clock sampler ----
    async def _sample(self) -> None:
        dut = cocotb.top
        clk = 0
        level = dict.fromkeys(DBG_BITS, 0)
        open_p: dict[int, Pulse] = {}
        prev_vec = None
        while True:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            clk += 1
            self.clk = clk
            nl = len(self.con.lines)
            bus = str(dut.ext_debug_bus_o.value)
            top = len(bus) - 1
            for b in DBG_BITS:
                ch = bus[top - b]
                if ch not in "01":
                    raise AssertionError(f"ext_debug_bus_o[{b}] is {ch} at clk={clk}")
                v = int(ch)
                if v and not level[b]:
                    p = Pulse(clk, nl, b)
                    open_p[b] = p
                    self.pulses.append(p)
                elif v and level[b]:
                    open_p[b].width += 1
                level[b] = v
            vec = str(dut.sep_internal_interrupts_probe_o.value)
            if vec != prev_vec:
                self.vec_changes.append((clk, nl, prev_vec, vec))
                prev_vec = vec
            if int(dut.cpu_trace_valid_o.value):
                self.trace.append(
                    (
                        clk,
                        nl,
                        int(dut.cpu_trace_addr_o.value) & _M32,
                        int(dut.dbg_cpu_trace_exc_o.value),
                        int(dut.cpu_trace_interrupt_o.value),
                        int(dut.cpu_trace_ecause_o.value),
                    )
                )

    # ---- console helpers ----
    def _recs(self, prefix: str) -> list[ConsoleRec]:
        out = []
        for i, (_clk, text) in enumerate(self.con.lines):
            if text.split(" ", 1)[0] == prefix:
                out.append(ConsoleRec(i, prefix, "LOG", parse_kv(text), text))
        return out

    def _line_idx(self, text_prefix: str, after: int = 0) -> int:
        for i in range(after, len(self.con.lines)):
            if self.con.lines[i][1].startswith(text_prefix):
                return i
        raise AssertionError(f"console has no line '{text_prefix}' after line {after}")

    def _window(self, tag: str, k: int = 0) -> tuple[int, int]:
        """(first, last) line counts of the events between ``B <tag>`` and ``E <tag>``."""
        b = self._line_idx(f"B {tag} k=0x{k:08x}")
        e = self._line_idx(f"E {tag} k=0x{k:08x}", b)
        return b + 1, e

    def _leg(self, leg: str) -> tuple[int, int]:
        """(first, last) line counts of the events of the leg that ``M G|C <leg>`` opens."""
        i = None
        for j, (_c, text) in enumerate(self.con.lines):
            if text in (f"M G {leg}", f"M C {leg}"):
                i = j
                break
        if i is None:
            raise AssertionError(f"console has no marker of leg {leg}")
        nxt = len(self.con.lines)
        for j in range(i + 1, len(self.con.lines)):
            if self.con.lines[j][1].startswith("M "):
                nxt = j
                break
        return i + 1, nxt

    def _pulses_in(self, win: tuple[int, int]) -> dict[int, list[Pulse]]:
        out: dict[int, list[Pulse]] = {b: [] for b in DBG_BITS}
        for p in self.pulses:
            if win[0] <= p.nl <= win[1]:
                out[p.bit].append(p)
        return out

    def _trace_in(self, win: tuple[int, int]) -> list[tuple]:
        return [r for r in self.trace if win[0] <= r[1] <= win[1]]

    def _traps(self, tag: str | None = None) -> list[dict]:
        out = [r.kv for r in self._recs("TRAP")]
        return [kv for kv in out if tag is None or kv.get("tag") == tag]

    # ---- checks ----
    def _chk_clamp(self) -> int:
        cfg = self.tcfg
        rec = self._recs("CLAMP")
        if len(rec) != 1:
            raise AssertionError(f"CHK-TCM-CLAMP FAIL: {len(rec)} CLAMP lines")
        kv = rec[0].kv
        n = 0
        for reg, k31, kt in (("MICCMECT", "ic31", "ict"), ("MDCCMECT", "dc31", "dct")):
            r31, rt = int(kv[k31]), int(kv[kt])
            body = (
                f"reg={reg} wrote=31 readback={r31 >> 27} control_t={cfg.t} "
                f"control_readback={rt >> 27} count_fields=0x{r31 & CNT_MASK:x}/0x{rt & CNT_MASK:x}"
            )
            if r31 >> 27 != CLAMP_MAX or rt >> 27 != cfg.t or r31 & CNT_MASK or rt & CNT_MASK:
                raise AssertionError(f"CHK-TCM-CLAMP FAIL: {body} expected readback={CLAMP_MAX}")
            self.logger.info("CHK-TCM-CLAMP PASS: %s", body)
            n += 1
        return n

    def _samples(self, leg: str) -> list[dict]:
        return [r.kv for r in self._recs("SAMPLE") if r.kv.get("leg") == leg]

    def _intr_events(self, win: tuple[int, int], ecause: int | None = None) -> list[tuple]:
        return [r for r in self._trace_in(win) if r[4] and (ecause is None or r[5] == ecause)]

    def _chk_ce_silent(self) -> int:
        cfg = self.tcfg
        thr = cfg.thr
        order = "miss_first" if cfg.order == 0 else "reach_first"
        n = 0
        csr0 = self._recs("CSR0")
        if len(csr0) != 1 or int(csr0[0].kv["ic"]) or int(csr0[0].kv["dc"]):
            raise AssertionError(
                f"CHK-TCM-CE FAIL: counters after reset {csr0[0].text if csr0 else None}, expected 0x0"
            )
        mceip_traps = [kv for kv in self._traps() if int(kv["mcause"]) == MCAUSE_MCEIP]
        other_irq = [
            kv
            for kv in self._traps()
            if int(kv["mcause"]) & 0x8000_0000 and int(kv["mcause"]) != MCAUSE_MCEIP
        ]
        if other_irq:
            raise AssertionError(f"CHK-TCM-CE FAIL: interrupt traps other than MCEIP: {other_irq}")

        # ICCM leg: the sample before the block and the quiescent sample.
        isamp = {kv["tag"]: kv for kv in self._samples("iccm")}
        bef, qui, rew = isamp["before"], isamp["quiet"], isamp["rewrite"]
        for tag, kv, want in (("before", bef, 0), ("quiet", qui, 1)):
            cnt = int(kv["ic"]) & CNT_MASK
            mceip = (int(kv["mip"]) & MIP_MCEIP) >> 30
            other = int(kv["dc"]) & CNT_MASK
            ok = (cnt == 0 if want == 0 else cnt >= thr) and mceip == want and other == 0
            body = (
                f"mem=ICCM order={order} t={cfg.t} sample={tag} counter={cnt} mceip={mceip} "
                f"mcause=none other_counter={other} reset_ic=0x0 reset_dc=0x0"
            )
            if not ok:
                raise AssertionError(f"CHK-TCM-CE FAIL: {body}")
            self.logger.info("CHK-TCM-CE PASS: %s", body)
            n += 1
        arm = [r.kv for r in self._recs("ARM") if r.kv.get("kind") == "iccm"]
        itraps = self._traps("iccm_arm")
        win = self._window("iccm_arm")
        ev = self._intr_events(win, 0x1E)
        cnt = int(arm[0]["ic"]) & CNT_MASK if arm else -1
        ntr = int(arm[0]["traps_after"]) - int(arm[0]["traps_before"]) if arm else -1
        body = (
            f"mem=ICCM order={order} t={cfg.t} arming=after_block counter={cnt} "
            f"mceip_at_arming=1 traps={ntr} mcause="
            + ",".join(f"0x{int(kv['mcause']):08x}" for kv in itraps)
            + f" trace_ecause_0x1e={len(ev)} rewrite_counter={int(rew['ic']) & CNT_MASK} "
            f"rewrite_mceip={(int(rew['mip']) & MIP_MCEIP) >> 30}"
        )
        if (
            ntr != 1
            or len(itraps) != 1
            or int(itraps[0]["mcause"]) != MCAUSE_MCEIP
            or len(ev) != 1
            or int(rew["ic"]) & CNT_MASK
            or int(rew["mip"]) & MIP_MCEIP
        ):
            raise AssertionError(f"CHK-TCM-CE FAIL: {body}")
        self.logger.info("CHK-TCM-CE PASS: %s", body)
        n += 1
        iccm_trap_ok = True

        # ICCM silent: the block runs with mie[30] clear.
        bwin = self._window("iccm_block")
        bev = self._intr_events(bwin)
        qcnt = int(qui["ic"]) & CNT_MASK
        body = (
            f"mie30=0 mem=ICCM accesses={cfg.n} counter={qcnt} "
            f"traps={int(qui['traps']) - int(bef['traps'])} trace_irq_events={len(bev)} "
            f"mceip={(int(qui['mip']) & MIP_MCEIP) >> 30} control_trap_at_arming={int(iccm_trap_ok)}"
        )
        if (
            int(qui["traps"]) != int(bef["traps"])
            or bev
            or qcnt < thr
            or int(bef["mie"]) & MIE_MCEIE
        ):
            raise AssertionError(f"CHK-TCM-SILENT FAIL: {body}")
        self.logger.info("CHK-TCM-SILENT PASS: %s", body)
        n += 1
        # Per-slot ICCM samples: logged, not graded.
        slots = {int(r.kv["k"]): r.kv for r in self._recs("ISLOT")}
        prev = 0
        for s in cfg.islots:
            cur = int(slots[s]["ic"]) & CNT_MASK
            self.logger.info(
                "OBS-TCM-INCR LOG mem=ICCM access=slot%d counter_before=%d counter_after=%d",
                s,
                prev,
                cur,
            )
            prev = cur

        # DCCM leg.
        ds = self._samples("dccm")
        form = self._recs("FORM")
        fkv = form[0].kv
        realized = "miss_first" if int(fkv["form"]) == 0 else "reach_first"
        if int(fkv["order"]) != cfg.order:
            raise AssertionError(f"firmware ran order {fkv['order']}, drew {cfg.order}")
        if realized != order:
            self.logger.info(
                "OBS-TCM-INCR LOG order=miss_first skipped the readback %d (count %d): "
                "the leg runs in the reach-first form",
                thr - 1,
                int(fkv["cnt"]),
            )
        bad = []
        prev_cnt = None
        accesses = 0
        last_below = first_at = None
        for kv in ds:
            cnt = int(kv["dc"]) & CNT_MASK
            mceip = (int(kv["mip"]) & MIP_MCEIP) >> 30
            if mceip != int(cnt >= thr):
                bad.append(f"sample {kv['tag']} k={kv['k']} counter={cnt} mceip={mceip}")
            if int(kv["ic"]) & CNT_MASK:
                bad.append(f"sample {kv['tag']} MICCMECT count {int(kv['ic']) & CNT_MASK}")
            if kv["tag"] in ("silent", "cross", "post"):
                accesses += 1
                self.logger.info(
                    "OBS-TCM-INCR LOG mem=DCCM access=%d counter_before=%s counter_after=%d",
                    int(kv["k"]),
                    prev_cnt,
                    cnt,
                )
                if prev_cnt is None or cnt < prev_cnt + 1:
                    bad.append(f"access k={kv['k']} counter {prev_cnt} -> {cnt}")
            if cnt < thr:
                last_below = (cnt, mceip)
            elif first_at is None:
                first_at = (cnt, mceip, kv["tag"])
            prev_cnt = cnt
        if accesses != cfg.n:
            bad.append(f"{accesses} flipped DCCM loads, expected {cfg.n}")
        if bad or last_below is None or first_at is None:
            raise AssertionError(
                f"CHK-TCM-CE FAIL: mem=DCCM order={order} t={cfg.t}: {bad} "
                f"last_below={last_below} first_at={first_at}"
            )
        dtrap = self._traps("dccm_cross" if realized == "miss_first" else "dccm_reach")
        dmc = ",".join(f"0x{int(kv['mcause']):08x}" for kv in dtrap) or "none"
        self.logger.info(
            "CHK-TCM-CE PASS: mem=DCCM order=%s t=%d counter=%d mceip=%d mcause=none",
            order,
            cfg.t,
            last_below[0],
            last_below[1],
        )
        self.logger.info(
            "CHK-TCM-CE PASS: mem=DCCM order=%s t=%d counter=%d mceip=%d mcause=%s sample=%s",
            order,
            cfg.t,
            first_at[0],
            first_at[1],
            dmc if first_at[2] == "cross" else "none",
            first_at[2],
        )
        n += 2
        # One line for each arming of the DCCM leg.
        arms = {r.kv["kind"]: r.kv for r in self._recs("ARM") if r.kv.get("leg") == "dccm"}
        zero = arms["zero"]
        zw = self._window("dccm_zero")
        zero_ok = (
            int(zero["traps_after"]) == int(zero["traps_before"])
            and int(zero["dc"]) & CNT_MASK == 0
            and not int(zero["mip"]) & MIP_MCEIP
            and not self._intr_events(zw)
        )
        zbody = (
            f"mem=DCCM order={order} t={cfg.t} arming=count0 counter={int(zero['dc']) & CNT_MASK} "
            f"mceip={(int(zero['mip']) & MIP_MCEIP) >> 30} "
            f"traps={int(zero['traps_after']) - int(zero['traps_before'])} mcause=none"
        )
        if not zero_ok:
            raise AssertionError(f"CHK-TCM-CE FAIL: {zbody}")
        self.logger.info("CHK-TCM-CE PASS: %s", zbody)
        n += 1
        if realized == "miss_first":
            miss, cross = arms["miss"], arms["cross"]
            b = self._line_idx("B dccm_miss_arm")
            e = self._line_idx("SAMPLE leg=dccm tag=cross", b)
            ev = self._intr_events((b + 1, e), 0x1E)
            mbody = (
                f"mem=DCCM order={order} t={cfg.t} arming=miss counter={int(miss['dc']) & CNT_MASK} "
                f"mceip={(int(miss['mip']) & MIP_MCEIP) >> 30} "
                f"traps={int(miss['traps_after']) - int(miss['traps_before'])} mcause=none"
            )
            if (
                int(miss["traps_after"]) != int(miss["traps_before"])
                or int(miss["dc"]) & CNT_MASK != thr - 1
                or int(miss["mip"]) & MIP_MCEIP
            ):
                raise AssertionError(f"CHK-TCM-CE FAIL: {mbody}")
            self.logger.info("CHK-TCM-CE PASS: %s", mbody)
            ntr = int(cross["traps_after"]) - int(cross["traps_before"])
            cbody = (
                f"mem=DCCM order={order} t={cfg.t} arming=miss_then_cross "
                f"counter={int(cross['dc']) & CNT_MASK} traps={ntr} mcause={dmc} "
                f"trace_ecause_0x1e={len(ev)}"
            )
            if (
                ntr != 1
                or len(dtrap) != 1
                or int(dtrap[0]["mcause"]) != MCAUSE_MCEIP
                or len(ev) != 1
            ):
                raise AssertionError(f"CHK-TCM-CE FAIL: {cbody}")
            self.logger.info("CHK-TCM-CE PASS: %s", cbody)
            n += 2
        else:
            reach = arms["reach"]
            ev = self._intr_events(self._window("dccm_reach_arm"), 0x1E)
            ntr = int(reach["traps_after"]) - int(reach["traps_before"])
            rbody = (
                f"mem=DCCM order={order} t={cfg.t} arming=reach counter="
                f"{int(reach['dc']) & CNT_MASK} traps={ntr} mcause={dmc} trace_ecause_0x1e={len(ev)}"
            )
            if (
                ntr != 1
                or len(dtrap) != 1
                or int(dtrap[0]["mcause"]) != MCAUSE_MCEIP
                or len(ev) != 1
                or int(reach["dc"]) & CNT_MASK < thr
            ):
                raise AssertionError(f"CHK-TCM-CE FAIL: {rbody}")
            self.logger.info("CHK-TCM-CE PASS: %s", rbody)
            n += 1
        if len(mceip_traps) != 2:
            raise AssertionError(
                f"CHK-TCM-CE FAIL: {len(mceip_traps)} MCEIP traps in the leaf, expected 2 (one per memory)"
            )

        # DCCM silent: the accesses with mie[30] clear.
        silent = [kv for kv in ds if kv["tag"] in ("silent", "post")]
        sbad = []
        # The trap count before each access is the count of the last SAMPLE or
        # ARM line of the leg ahead of it (an arming traps between samples).
        seq = sorted(
            [(r.clk, "s", r.kv) for r in self._recs("SAMPLE") if r.kv.get("leg") == "dccm"]
            + [(r.clk, "a", r.kv) for r in self._recs("ARM") if r.kv.get("leg") == "dccm"],
            key=lambda x: x[0],
        )
        prev_traps = None
        for _i, kind, kv in seq:
            if kind == "a":
                prev_traps = int(kv["traps_after"])
                continue
            if kv["tag"] in ("silent", "post"):
                if int(kv["mie"]) & MIE_MCEIE:
                    sbad.append(f"k={kv['k']} mie30=1")
                if prev_traps is not None and int(kv["traps"]) != prev_traps:
                    sbad.append(f"k={kv['k']} traps {prev_traps}->{kv['traps']}")
                win = self._window("dccm_ce", int(kv["k"]))
                if self._intr_events(win):
                    sbad.append(f"k={kv['k']} trace interrupt event")
            prev_traps = int(kv["traps"])
        top = max(int(kv["dc"]) & CNT_MASK for kv in silent) if silent else -1
        top_kv = next((kv for kv in silent if int(kv["dc"]) & CNT_MASK == top), None)
        body = (
            f"mie30=0 mem=DCCM accesses={len(silent)} counter={top} traps=0 "
            f"mceip={(int(top_kv['mip']) & MIP_MCEIP) >> 30 if top_kv else -1} "
            f"control_trap_at_arming={len(dtrap)}"
        )
        if sbad or top < thr or len(dtrap) != 1:
            raise AssertionError(f"CHK-TCM-SILENT FAIL: {body} {sbad}")
        self.logger.info("CHK-TCM-SILENT PASS: %s", body)
        return n + 1

    def _chk_ue(self) -> int:
        cfg = self.tcfg
        n = 0
        nbrs = {r.kv["access"]: r.kv for r in self._recs("UNC-NBR")}
        uncs = {r.kv["access"]: r.kv for r in self._recs("UNC")}
        for access, tag, wtag, cause, exp_nbr in (
            ("load", "ld", "ue_load", MCAUSE_LOAD_FAULT, cfg.data[cfg.ld_nbr]),
            ("store", "st", "ue_store", MCAUSE_STORE_FAULT, cfg.st_nbr_exp()),
        ):
            nbr, unc = nbrs[access], uncs[access]
            traps = self._traps(tag)
            win = self._window(wtag)
            pul = self._pulses_in(win)
            pattern = "".join("1" if pul[b] else "0" for b in DBG_BITS)
            exc = [r for r in self._trace_in(win) if r[3] and not r[4]]
            nbr_ok = int(nbr["got"]) == exp_nbr and int(nbr["traps"]) == 0
            body = (
                f"access=DCCM_{access.upper()} mcause=0x{int(traps[0]['mcause']):x} "
                f"mscause=0x{int(traps[0]['mscause']):x} pulse=0b{pattern} "
                if traps
                else f"access=DCCM_{access.upper()} mcause=none "
            )
            body += (
                f"trace_exceptions={len(exc)} trace_ecause="
                + ",".join(str(r[5]) for r in exc)
                + f" clean_neighbour={'ok' if nbr_ok else 'bad'} neighbour_got=0x{int(nbr['got']):08x} "
                f"neighbour_exp=0x{exp_nbr:08x}"
            )
            ok = (
                len(traps) == 1
                and int(unc["traps"]) == 1
                and int(traps[0]["mcause"]) == cause
                and int(traps[0]["mscause"]) == MSCAUSE_ECC
                and pul[BIT_D_DB]
                and len(exc) == 1
                and exc[0][5] == cause
                and nbr_ok
            )
            if not ok:
                raise AssertionError(f"CHK-TCM-UE FAIL: {body}")
            self.logger.info("CHK-TCM-UE PASS: %s", body)
            n += 1
        return n

    def _chk_nmi(self, sy: dict[str, int]) -> int:
        vec = sy["_nmi_handler"]
        rec = self._recs("NMI")
        setup = self._recs("NMI-SETUP")
        if self.con.text_lines("SRC2-ISR") or self.con.text_lines("NMI-MISSING") or len(rec) != 1:
            raise AssertionError(
                f"CHK-TCM-NMI FAIL: NMI lines={len(rec)} src2_isr={bool(self.con.text_lines('SRC2-ISR'))} "
                f"missing={bool(self.con.text_lines('NMI-MISSING'))}"
            )
        kv = rec[0].kv
        b = self._line_idx("B nmi")
        tr = [r for r in self.trace if r[1] >= b + 1]
        ev_i = next((i for i, r in enumerate(tr) if r[3] or r[4]), None)
        ret = (
            next((r for r in tr[ev_i + 1 :] if not (r[3] or r[4])), None)
            if ev_i is not None
            else None
        )
        ext_traps = [t for t in self._traps() if int(t["mcause"]) == MCAUSE_EXT]
        pend = int(setup[0].kv["meip0"]) >> PIC_SRC & 1 if setup else 0
        body = (
            f"mcause=0x{int(kv['mcause']):08x} vec=0x{vec:08x} "
            f"retired_pc=0x{ret[2] if ret else 0:08x} vec_rb=0x{int(kv['vec_rb']):08x} "
            f"event_ecause={tr[ev_i][5] if ev_i is not None else 'none'} "
            f"event_interrupt={tr[ev_i][4] if ev_i is not None else 'none'} "
            f"src2_pending_before={pend} ext_irq_traps_before={len(ext_traps)}"
        )
        ok = (
            int(kv["mcause"]) == MCAUSE_NMI_ECC
            and int(kv["vec_rb"]) == vec
            and ret is not None
            and ret[2] == vec
            and pend == 1
            and not ext_traps
            and setup
            and int(setup[0].kv["src2_isr"]) == sy["src2_isr"]
        )
        if not ok:
            raise AssertionError(f"CHK-TCM-NMI FAIL: {body}")
        self.logger.info("CHK-TCM-NMI PASS: %s", body)
        return 1

    def _chk_dbg(self) -> int:
        cfg = self.tcfg
        bad = []
        per_word = []
        cnt = dict.fromkeys(DBG_BITS, 0)

        def window(name: str, win: tuple[int, int], want: int) -> int:
            pul = self._pulses_in(win)
            for b in (BIT_I_SB, BIT_D_SB, BIT_D_DB):
                if b == want and not pul[b]:
                    bad.append(f"{name}: no pulse on bit {b}")
                if b != want and pul[b]:
                    bad.append(f"{name}: {len(pul[b])} pulses on bit {b}")
            cnt[want] += len(pul[want])
            return len(pul[want])

        window("iccm_block", self._window("iccm_block"), BIT_I_SB)
        for kv in self._samples("dccm"):
            if kv["tag"] in ("silent", "cross", "post"):
                k = int(kv["k"])
                per_word.append(window(f"dccm_ce k={k}", self._window("dccm_ce", k), BIT_D_SB))
        window("ue_load", self._window("ue_load"), BIT_D_DB)
        window("ue_store", self._window("ue_store"), BIT_D_DB)
        window("nmi", self._window("nmi"), BIT_D_DB)
        wide = [p for p in self.pulses if p.bit != BIT_I_DB and p.width != 1]
        if wide:
            bad.append(
                f"{len(wide)} pulses wider than one clock: {[(p.bit, p.width) for p in wide[:6]]}"
            )
        db366 = [p for p in self.pulses if p.bit == BIT_I_DB]
        self.logger.info(
            "OBS-TCM-DBG366 LOG pulses=%d widths=%s", len(db366), [p.width for p in db366[:8]]
        )
        with_pulse = sum(1 for x in per_word if x)
        body = (
            f"bit365={cnt[BIT_D_SB]} bit367={cnt[BIT_I_SB]} bit364={cnt[BIT_D_DB]} width_clk=1 "
            f"words_with_pulse={with_pulse}/{len(per_word)} "
            f"pulses_per_word={min(per_word) if per_word else 0}-{max(per_word) if per_word else 0}"
        )
        if bad or len(per_word) != cfg.n:
            raise AssertionError(f"CHK-TCM-DBG FAIL: {body}: {bad[:8]}")
        self.logger.info("CHK-TCM-DBG PASS: %s", body)
        return 1

    def _chk_no_pic(self) -> int:
        meip = {r.kv["when"]: r.kv for r in self._recs("MEIP")}
        keys = [f"w{i}" for i in range(8)]
        base = meip["baseline"]
        n = 0
        if not int(base["w0"]) >> PIC_SRC & 1:
            raise AssertionError(
                f"CHK-TCM-NO-PIC FAIL: baseline meip0=0x{int(base['w0']):08x} lacks source {PIC_SRC}"
            )
        for when in ("correctable", "dccm_load", "dccm_store"):
            kv = meip[when]
            same = all(int(kv[k]) == int(base[k]) for k in keys)
            micect = int(kv["micect"])
            body = (
                f"after={when} meip0=0x{int(kv['w0']):08x} meip1=0x{int(kv['w1']):08x} "
                f"same={int(same)} micect={micect} baseline_meip0=0x{int(base['w0']):08x}"
            )
            if not same or micect:
                raise AssertionError(
                    f"CHK-TCM-NO-PIC FAIL: {body} words="
                    + ",".join(f"0x{int(kv[k]):08x}" for k in keys)
                    + " baseline="
                    + ",".join(f"0x{int(base[k]):08x}" for k in keys)
                )
            self.logger.info("CHK-TCM-NO-PIC PASS: %s", body)
            n += 1
        # Vector unchanged around each correctable pulse.
        ce_wins = [self._window("iccm_block")] + [
            self._window("dccm_ce", int(kv["k"]))
            for kv in self._samples("dccm")
            if kv["tag"] in ("silent", "cross", "post")
        ]
        ce_pulses = [
            p
            for p in self.pulses
            if p.bit in (BIT_I_SB, BIT_D_SB) and any(w[0] <= p.nl <= w[1] for w in ce_wins)
        ]
        moved = [
            p.clk
            for p in ce_pulses
            if any(p.clk - VEC_WINDOW < c <= p.clk + VEC_WINDOW for c, *_ in self.vec_changes)
        ]
        setup = self._leg("pic_setup")
        rise = 0
        for _c, nl, old, new in self.vec_changes:
            if old is None or not setup[0] <= nl <= setup[1]:
                continue
            if old[len(old) - PIC_SRC] == "0" and new[len(new) - PIC_SRC] == "1":
                rise = 1
        dc_live = any(int(kv["dc"]) & CNT_MASK for kv in self._samples("dccm"))
        body = (
            f"vector_unchanged_pulses={len(ce_pulses) - len(moved)}/{len(ce_pulses)} "
            f"window_clk={VEC_WINDOW} control_src2_bit_rise={rise} control_mdccmect_nonzero={int(dc_live)}"
        )
        if moved or not ce_pulses or not rise or not dc_live:
            raise AssertionError(f"CHK-TCM-NO-PIC FAIL: {body} moved_at={moved[:6]}")
        self.logger.info("CHK-TCM-NO-PIC PASS: %s", body)
        return n + 1

    # ---- stimulus ----
    def _stage(self, cfg: TcmCfg, sy: dict[str, int]) -> str:
        need = ("BSS_END", "STACK", "_nmi_handler", "_dummy_int_handler", "src2_isr", "iccm_block")
        missing = [k for k in need if k not in sy]
        if missing:
            raise AssertionError(f"firmware symbol listing lacks {missing} in {_FW_DIR}")
        if sy["BSS_END"] > WIN_BASE or TBL_BASE + 4 * TBL_WORDS > sy["STACK"] - STACK_RESERVE:
            raise AssertionError(
                f"reserved window 0x{WIN_BASE:08x}-0x{TBL_BASE + 4 * TBL_WORDS - 1:08x} overlaps "
                f".bss (end 0x{sy['BSS_END']:08x}) or the stack (top 0x{sy['STACK']:08x})"
            )
        slots = slot_offsets(_ITCM_HEX)
        if any(ICCM_BASE + s < sy["iccm_block"] for s in slots):
            raise AssertionError("an ICCM slot word lies before the iccm_block symbol")
        tbl = [sy["_dummy_int_handler"]] * TBL_WORDS
        tbl[PIC_SRC] = sy["src2_isr"]
        mid = os.path.join(os.getcwd(), "sep_dtcm_tcm_ecc_prm.hex")
        dtcm = os.path.join(os.getcwd(), "sep_dtcm_tcm_ecc.hex")
        patch_param_block(_DTCM_HEX, mid, P_MAGIC, cfg.words())
        place_words(mid, dtcm, WIN_BASE - DCCM_BASE, cfg.data + tbl, limit=DCCM_BYTES)
        flips = cfg.flips(slots)
        write_flip_list(os.path.join(os.getcwd(), _FLIP_LIST), [(a, m) for a, m, _ in flips])
        for a, m, what in flips:
            self.logger.info("CTL-TCM-FLIP LOG addr=0x%08x mask=0x%010x what=%s", a, m, what)
        return dtcm

    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.tcfg = cfg = TcmCfg.from_seed(seed)
        self.logger.info("SEED seed=%d", seed)
        for line in cfg.draw_lines():
            self.logger.info("%s", line)
        sy = load_symbols(_FW_DIR)
        dtcm = self._stage(cfg, sy)
        self.pulses: list[Pulse] = []
        self.vec_changes: list[tuple] = []
        self.trace: list[tuple] = []
        self.sb.expected_line = _BANNER
        self.con = SepFwConsole(self, graded_test=TEST).start()
        smp = cocotb.start_soon(self._sample())
        close_graded_window(self.logger)
        try:
            await self.boot_firmware(
                self.sb,
                _ITCM_HEX,
                dtcm,
                rst_vec=ICCM_BASE >> 1,
                max_run_cycles=_MAX_RUN_CYCLES,
                no_boot_cycles=_NO_BOOT_CYCLES,
            )
        finally:
            smp.cancel()
            await self.con.stop()
        assert self.sb.fw_done and self.sb.fw_pass, "firmware did not complete with PASS"
        seeds = self.con.text_lines("SEED")
        if not seeds or f"seed=0x{seed & _M32:08x}" not in seeds[0]:
            raise AssertionError(f"firmware did not run the patched block: {seeds}")
        n = self._chk_clamp()
        n += self._chk_ce_silent()
        n += self._chk_ue()
        n += self._chk_nmi(sy)
        n += self._chk_dbg()
        n += self._chk_no_pic()
        self.result_pass(TEST, seed, n)
