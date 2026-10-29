# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""KMAC stages, both endianness bits, length corners, run, the idle state, the config lock and the done line.

Contract (``vendor/lowRISC/opentitan/overlay/regs/kmac/regs/gen/adoc/kmac.adoc``
and ``vendor/lowRISC/opentitan/upstream/hw/ip/kmac/data/kmac.hjson``):
``CMD.start`` moves ``STATUS`` to ``sha3_absorb`` (kmac.hjson lines 638-640;
kmac.adoc lines 241-244), and ``CMD.run`` in the squeeze stage runs the 24
rounds again (kmac.hjson lines 656-660). With no command ``STATUS`` stays idle
(kmac.adoc line 244, ``sha3_idle`` reset 1) and ``kmac_done`` reads 0
(kmac.adoc line 57). ``msg_endianness`` = 1 adds each multi-byte ``MSG_FIFO``
write in big-endian byte order and leaves a one-byte write unchanged
(kmac.adoc lines 160-168); ``state_endianness`` = 1 byte-swaps each ``STATE``
word and keeps the word order (kmac.adoc lines 152-156). With
``INTR_ENABLE.kmac_done`` set, the completion sets ``INTR_STATE.kmac_done``
and vector bit 20 (source 21) rises (kmac.adoc lines 57 and 69;
``hw/sys/sep/doc/interrupts.adoc`` lines 129-131; ``hw/sys/sep/doc/kmac.adoc``
line 40). ``CFG_REGWEN`` resets to 1 (kmac.adoc line 102) and the contents of
``CFG_SHADOWED`` cannot change while the KMAC is in operation (kmac.hjson
lines 354-358). The digest golden is FIPS 202 (``env/sep_kmac_golden.py``).

The 18 cells are the six legal (mode, strength) pairs (SHA3 224, 256, 384,
512; SHAKE 128, 256) x message length {rate - 1, rate, rate + 1} bytes, with
``kmac_en`` = 0 in EDN entropy mode. Cell i of the drawn order runs the
(``msg_endianness``, ``state_endianness``) cell i mod 4.

Checkers:
  CHK-KMAC-SEQ        after start: absorb=1, idle=0; after run in squeeze:
                      squeeze=1. Controls: squeeze after process, idle after done.
  CHK-KMAC-DIGEST     STATE share0 ^ share1 equals the Keccak golden with both
                      endianness bits applied (SHA3: digest size; SHAKE: rate).
  CHK-KMAC-RUN        SHAKE: after run the STATE rate block equals block 2 of
                      the golden output.
  CHK-KMAC-IDLE       with no command every read of the idle window shows
                      idle=1, absorb=0, squeeze=0, kmac_done=0. Control: the
                      following start reaches absorb in a wait of the same length.
  CHK-KMAC-DONE-LINE  vector bit 20 reads 0 at the process write, kmac_done
                      reads 1 and bit 20 rises; the rise is at or after the start
                      of the last ``INTR_STATE`` read that showed
                      ``kmac_done`` = 0 (the ``CMD.process`` write mark when
                      the first read already shows 1), and at most the rise
                      bound (``_IDLE_MULT`` x t_start) after the mark of the
                      ``CMD.process`` write. ``INTR_STATE`` is polled from the
                      process write with no ``STATUS`` read in between.
  CHK-KMAC-FIFO-DONE  the first ``STATUS`` read after ``kmac_done`` reads 1:
                      ``fifo_depth`` 0, ``fifo_empty`` 1, ``fifo_full`` 0
                      (kmac.adoc lines 226-239). Graded on every cell. Control,
                      on each rate + 1 cell: the first ``_FILL_BYTES`` or more
                      message bytes are written while the inject
                      ``kmac_fifo_drain_stall_i`` holds the read side of the
                      message FIFO, and the ``STATUS`` read right after them shows
                      ``fifo_depth`` >= 1 and ``fifo_empty`` 0 (the FIFO holds the
                      words the engine cannot take; a ``STATUS`` stuck at its reset
                      value fails); the inject is then released, and the cell wrote
                      more than rate message bytes.
  CHK-KMAC-REGWEN     CFG_REGWEN 1 in the idle window, 0 in absorb; a double
                      write of CFG_SHADOWED in absorb leaves it at C. The line
                      logs the AXI response of each locked write
                      (``locked_wr_resp``, not graded). Control: the idle
                      write reads back C.
  CHK-KMAC-REGWEN-GATED  on one drawn cell: in absorb, with CFG_REGWEN read 0,
                      a write of PREFIX_n = pre XOR mask reads back pre
                      (role=prefix), and a write of ENTROPY_PERIOD = pre XOR
                      mask (prescaler field) reads back pre at idle after
                      ``CMD.done`` (role=entropy_period). CFG_REGWEN gates both
                      registers (``vendor/lowRISC/opentitan/upstream/hw/ip/kmac/doc/registers.md``
                      lines 462 and 728; kmac.hjson lines 772 and 1001).
                      Control CTRL-KMAC-REGWEN-GATED, before that cell with the
                      graded FCOV window closed: the same writes at idle read
                      back pre XOR mask, and the restore reads back pre.
  CHK-KMAC-NARROW-WRITE  one fixed SHA3-256 message written with 8-bit and
                      16-bit writes at byte lanes 1 to 3 of MSG_FIFO: every
                      write completes OKAY and the digest equals the golden of
                      the bytes in write order (kmac.hjson lines 1052-1058:
                      software writes bytes or words to any address of the
                      window; the low 12 address bits are ignored). It runs
                      once per seed after the cells, with the graded FCOV
                      window closed.
  CHK-KMAC-FE-INTRTEST  after a KMAC reset, at idle with the graded FCOV window
                      closed: ``INTR_STATE.fifo_empty`` reads 0 (reset 0x0),
                      and the first read after a write of 1 to
                      ``INTR_TEST.fifo_empty`` reads 1 (kmac.adoc lines 50
                      and 80: "Write 1 to force !!INTR_STATE.fifo_empty to 1.").

The cells write each message beat at byte lane 0 of ``MSG_FIFO`` in the drawn
width, so the cell checks grade the stages, endianness, corners and lock on
their own; the byte-lane placement is graded only by CHK-KMAC-NARROW-WRITE.

Observations: ``OBS-KMAC-DONE-FALL`` logs bit 20 after the write-one clear.
``INFO-KMAC-FIFO-DONE`` logs the whole ``STATUS`` word of the graded read.
``OBS-KMAC-REGWEN-GATED-ERR`` logs ``INTR_STATE.kmac_err`` and ``ERR_CODE``
after the gated writes (registers.md lines 724-725 say an update while hashing
reports an error and state no code). ``OBS-KMAC-REGWEN-GATED-RSVD`` logs the
ENTROPY_PERIOD reserved bits, which have no stated value.
``OBS-KMAC-REGWEN-SQUEEZE`` logs ``CFG_REGWEN`` in squeeze and at idle after
``CMD.done`` of each cell. ``OBS-KMAC-FE-INTRTEST`` logs ``INTR_STATE.fifo_empty``
of the CHK-KMAC-FE-INTRTEST leg after a settle window and after a write-one
clear: no text states whether the forced bit stays set or whether the clear
acts on it.

FCOV gate: the leaf opens the graded window of its owner code before the cells.
The first FAIL or missing control closes the window before it is recorded, and
the window stays closed for the rest of the run. The stage, endianness, length
corner, run and ``kmac_done`` cells of a cell are held by the sampler; after
every check and control of that cell passed, the leaf writes the pass label
``kmac_stream_pass`` (``set_kmac_stream_pass``), and only then do they sample.

Time bounds: t_start is the clean start time of the warm-up hash, from the
``CMD.start`` write to the read that shows absorb. The idle window and the
start wait are ``_IDLE_MULT`` x t_start. The hash waits use the outer limit
``_OUTER_CLK`` and log the measured clocks.

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense
+esrc_noise_force``. RAND-REP: the seed draws the cell order, the message
bytes and the write widths; the 18 cells are the same on every seed. After
those draws it draws the CHK-KMAC-REGWEN-GATED cell, the PREFIX index n and
the two non-zero masks.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.sep_axi_agent import SepAxiOp
from env.sep_bit_watch import BitMark, BitWatchTimeout, SepBitWatch
from env.sep_chk_log import SepChkLog
from env.sep_fcov_gate import close_graded_window, open_graded_window, set_kmac_stream_pass
from env.sep_kmac_golden import sha3, shake
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import KMAC, sym
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_kmac_seq import (
    KMAC_CFG_SHADOWED,
    KMAC_CMD,
    KMAC_CMD_CODES,
    KMAC_CMD_DONE,
    KMAC_CMD_PROCESS,
    KMAC_CMD_START,
    KMAC_ERR_CODE,
    KMAC_INTR_STATE,
    KMAC_MODE,
    KMAC_MSG_FIFO,
    KMAC_PREFIX_0,
    KMAC_STATUS,
    KMAC_STRENGTH,
    SepKmac,
    build_kmac_cfg,
)

TEST = "sep_kmac_stream_cfg_rand_test"

# kmac.hjson CMD.cmd enum (lines 656-660): run.
_KMAC_CMD_RUN = KMAC_CMD_CODES["run"] << KMAC.field_lsb("CMD", "cmd")

_KMAC_INTR_ENABLE = KMAC.addr("INTR_ENABLE")
_KMAC_CFG_REGWEN = KMAC.addr("CFG_REGWEN")
_IDLE = KMAC.field_mask("STATUS", "sha3_idle")
_ABSORB = KMAC.field_mask("STATUS", "sha3_absorb")
_SQUEEZE = KMAC.field_mask("STATUS", "sha3_squeeze")
_DONE = KMAC.field_mask("INTR_STATE", "kmac_done")
_DONE_EN = KMAC.field_mask("INTR_ENABLE", "kmac_done")
_REGWEN_EN = KMAC.field_mask("CFG_REGWEN", "en")
_CFG_MASK = KMAC.mask32("CFG_SHADOWED")
_MSG_END_LSB = KMAC.field_lsb("CFG_SHADOWED", "msg_endianness")
_STATE_END = KMAC.field_mask("CFG_SHADOWED", "state_endianness")
_STATE_END_LSB = KMAC.field_lsb("CFG_SHADOWED", "state_endianness")
_KMAC_ERR = KMAC.field_mask("INTR_STATE", "kmac_err")
_FIFO_DEPTH = KMAC.field_mask("STATUS", "fifo_depth")
_FIFO_DEPTH_LSB = KMAC.field_lsb("STATUS", "fifo_depth")
_FIFO_EMPTY = KMAC.field_mask("STATUS", "fifo_empty")
_KMAC_INTR_TEST = KMAC.addr("INTR_TEST")
_INTR_TEST_FIFO_EMPTY = KMAC.field_mask("INTR_TEST", "fifo_empty")
_INTR_FIFO_EMPTY = KMAC.field_mask("INTR_STATE", "fifo_empty")
_FIFO_FULL = KMAC.field_mask("STATUS", "fifo_full")
_KMAC_ENTROPY_PERIOD = KMAC.addr("ENTROPY_PERIOD")
_EP_PRESCALER_LSB = KMAC.field_lsb("ENTROPY_PERIOD", "prescaler")
_EP_PRESCALER_WIDTH = KMAC.field_width("ENTROPY_PERIOD", "prescaler")
# The named ENTROPY_PERIOD fields; the bits between them are reserved with no
# stated value (kmac.adoc ENTROPY_PERIOD table).
_EP_FIELDS = KMAC.field_mask("ENTROPY_PERIOD", "prescaler") | KMAC.field_mask(
    "ENTROPY_PERIOD", "wait_timer"
)
# PREFIX_0 to PREFIX_10: one 32-bit field each (kmac.rdl PREFIX[11]).
_PREFIX_STRIDE = sym("KMAC_PREFIX_1__REG_ADDR") - KMAC_PREFIX_0
_PREFIX_COUNT = (sym("KMAC_PREFIX_10__REG_ADDR") - KMAC_PREFIX_0) // _PREFIX_STRIDE + 1
_PREFIX_FIELD = KMAC.field_mask("PREFIX", "prefix_0")

# hw/sys/sep/doc/interrupts.adoc lines 129-131: KMAC done is source 21, bit 20.
_VEC_KMAC_DONE = 20

# The six legal (mode, strength) pairs of the walk.
_PAIRS = (
    ("sha3", 224),
    ("sha3", 256),
    ("sha3", 384),
    ("sha3", 512),
    ("shake", 128),
    ("shake", 256),
)
_LEN_CORNERS = (-1, 0, 1)
_CELLS = tuple((m, s, d) for m, s in _PAIRS for d in _LEN_CORNERS)

# Write widths in bytes (32, 16 and 8 bit). A cell write is at byte lane 0,
# which is naturally aligned for every width.
_WIDTHS = (4, 2, 1)
# The fixed narrow-lane message: (byte lane, width) of each write, in order,
# with 8-bit writes at lanes 1, 2, 3 and 16-bit writes at lane 2.
_NARROW_WRITES = ((1, 1), (2, 1), (3, 1), (2, 2), (1, 1), (3, 1), (2, 2), (3, 1))
_NARROW_VALUES = (0xA1, 0xB2, 0xC3, 0xE5D4, 0xF6, 0x17, 0x3928, 0x4A)
_AXSIZE = {1: 0, 2: 1, 4: 2}

_IDLE_MULT = 4
# Message bytes written under the drain stall before the fill read: two 64-bit FIFO
# words, below any FIFO depth that holds the data of one Keccak run
# (vendor/lowRISC/opentitan/upstream/hw/ip/kmac/doc/theory_of_operation.md lines
# 151-152), so no write waits on a full FIFO.
_FILL_BYTES = 16
# clk_i edges the pass label stays 1: the edge that registers the write and one
# on which the sampler sees the rise.
_LABEL_EDGES = 2
_OUTER_CLK = 20_000
# Clocks from the INTR_TEST write to the second INTR_STATE read of
# OBS-KMAC-FE-INTRTEST. A testbench timing, not a spec value.
_FE_SETTLE_CLK = 64
_RESET_EDGE_CLK = 200


def keccak_rate_bytes(strength: int) -> int:
    """FIPS 202: rate = 1600 - 2 x capacity bits of the strength, in bytes."""
    return (1600 - 2 * strength) // 8


@dataclass(frozen=True)
class Cell:
    index: int
    mode: str
    strength: int
    corner: int
    msg_end: int
    state_end: int
    writes: tuple[tuple[int, int], ...]  # (byte offset in the word, width), in order
    values: tuple[int, ...]  # the value of each write

    @property
    def length(self) -> int:
        return sum(w for _, w in self.writes)

    def message(self) -> bytes:
        """The byte sequence the writes add (kmac.adoc lines 160-168)."""
        out = b""
        for (_, width), value in zip(self.writes, self.values):
            order = "big" if self.msg_end and width > 1 else "little"
            out += value.to_bytes(width, order)
        return out


@dataclass(frozen=True)
class Plan:
    cells: tuple[Cell, ...]
    redraws: int
    rg_cell: int  # index of the cell that runs CHK-KMAC-REGWEN-GATED
    rg_prefix: int  # PREFIX index n
    rg_prefix_mask: int  # non-zero 32-bit XOR mask of PREFIX_n
    rg_ep_mask: int  # non-zero XOR mask inside the ENTROPY_PERIOD prescaler field


def _draw_writes(
    rng: SepSeededRng, nbytes: int
) -> tuple[tuple[tuple[int, int], ...], tuple[int, ...]]:
    writes: list[tuple[int, int]] = []
    values: list[int] = []
    pos = 0
    while pos < nbytes:
        lane = 0
        allowed = [w for w in _WIDTHS if w <= nbytes - pos]
        width = rng.choice(allowed)
        # The bytes of one multi-byte write differ from each other, so a byte
        # reorder changes the message.
        data: list[int] = []
        while len(data) < width:
            b = rng.getrandbits(8)
            if b not in data:
                data.append(b)
        writes.append((lane, width))
        values.append(int.from_bytes(bytes(data), "little"))
        pos += width
    return tuple(writes), tuple(values)


def draw_plan(seed: int) -> Plan:
    """The whole plan of one seed. Pure: no simulator access."""
    rng = SepSeededRng(seed)
    order = list(_CELLS)
    rng.shuffle(order)
    redraws = 0
    while True:
        cells = []
        for i, (mode, strength, corner) in enumerate(order):
            ecell = i % 4
            nbytes = keccak_rate_bytes(strength) + corner
            writes, values = _draw_writes(rng, nbytes)
            cells.append(Cell(i, mode, strength, corner, ecell >> 1, ecell & 1, writes, values))
        if any(c.msg_end and any(w == 1 for _, w in c.writes) for c in cells):
            break
        redraws += 1
    # Drawn after the cells, so the cell order and messages of a seed stay as they are.
    rg_cell = rng.randrange(len(cells))
    rg_prefix = rng.randrange(_PREFIX_COUNT)
    rg_prefix_mask = rng.randrange(1, _PREFIX_FIELD + 1)
    rg_ep_mask = rng.randrange(1, 1 << _EP_PRESCALER_WIDTH) << _EP_PRESCALER_LSB
    return Plan(tuple(cells), redraws, rg_cell, rg_prefix, rg_prefix_mask, rg_ep_mask)


def _cfg_word(mode: str, strength: int, msg_end: int = 0, state_end: int = 0) -> int:
    """CFG_SHADOWED: kmac_en 0, sideload 0, EDN entropy mode, entropy_ready 1."""
    return (
        build_kmac_cfg(
            mode=KMAC_MODE[mode], kstrength=KMAC_STRENGTH[strength], kmac_en=False, sideload=False
        )
        | (msg_end << _MSG_END_LSB)
        | (state_end << _STATE_END_LSB)
    )


def _words(data: bytes, state_end: int) -> list[int]:
    """STATE words of ``data``; byte-swapped per word when state_endianness = 1."""
    order = "big" if state_end else "little"
    return [int.from_bytes(data[i : i + 4], order) for i in range(0, len(data), 4)]


def _bits(v: int, m: int) -> int:
    return int(bool(v & m))


def _prefix_addr(n: int) -> int:
    return KMAC_PREFIX_0 + _PREFIX_STRIDE * n


class CellTimeout(Exception):
    """A cell cannot go on; the owning check or control already logged FAIL or CTRL-MISSING."""


@pyuvm.test()
class sep_kmac_stream_cfg_rand_test(sep_base_test):
    """KMAC start/run stages, endianness, length corners, idle, config lock and done line."""

    required_evidence = (
        "CHK-KMAC-SEQ",
        "CHK-KMAC-DIGEST",
        "CHK-KMAC-RUN",
        "CHK-KMAC-IDLE",
        "CHK-KMAC-DONE-LINE",
        "CHK-KMAC-REGWEN",
        "CHK-KMAC-NARROW-WRITE",
        "CHK-KMAC-FIFO-DONE",
        "CHK-KMAC-REGWEN-GATED",
        "CHK-KMAC-FE-INTRTEST",
    )

    # --- FCOV window and grading ----------------------------------------------
    def _open(self) -> None:
        """Open the graded window, unless a FAIL already closed it for the run."""
        if not self._win_dead:
            open_graded_window(TEST, self.logger)

    def _close(self) -> None:
        close_graded_window(self.logger)

    def _fail_closes_window(self, cond: bool) -> None:
        if not cond and not self._win_dead:
            close_graded_window(self.logger)
            self._win_dead = True

    def _ok(self, name: str, cond: bool, **fields) -> bool:
        """``SepChkLog.ok``; a FAIL closes the window before it is recorded."""
        self._fail_closes_window(bool(cond))
        return self.chk.ok(name, cond, **fields)

    def _ctrl(self, name: str, cond: bool, **fields) -> bool:
        """``SepChkLog.ctrl``; a missing control closes the window before it is recorded."""
        self._fail_closes_window(bool(cond))
        return self.chk.ctrl(name, cond, **fields)

    async def _release_cell(self) -> None:
        """Write the pass label after every check and control of a cell passed.

        The sampler holds the stage, endianness, length corner, run and
        ``kmac_done`` cells of the cell and samples them on the label rise.
        The label is 1 for _LABEL_EDGES clk_i edges, then 0 one edge before the
        next access, so the next ``CMD.start`` sees it low.
        """
        if self._win_dead:
            return
        set_kmac_stream_pass(True, self.logger)
        await ClockCycles(cocotb.top.clk_i, _LABEL_EDGES)
        set_kmac_stream_pass(False, self.logger)
        await ClockCycles(cocotb.top.clk_i, 1)

    # --- clocks and register access -----------------------------------------
    def _now_clk(self) -> int:
        return int(get_sim_time("ps")) // self._clk_ps

    async def _rd(self, addr: int) -> int:
        return await self.kmac._rd(addr)

    async def _wr(self, addr: int, data: int) -> None:
        await self.kmac._wr(addr, data)

    async def _write_cfg(self, word: int) -> None:
        await self._wr(KMAC_CFG_SHADOWED, word)
        await self._wr(KMAC_CFG_SHADOWED, word)

    async def _poll(
        self, addr: int, mask: int, want: int, t0: int, bound: int
    ) -> tuple[bool, int, int]:
        """Read ``addr`` until ``value & mask == want`` or ``bound`` clocks pass from ``t0``."""
        while True:
            value = await self._rd(addr)
            elapsed = self._now_clk() - t0
            if (value & mask) == want:
                return True, value, elapsed
            if elapsed > bound:
                return False, value, elapsed
            await ClockCycles(cocotb.top.clk_i, 4)

    async def _poll_marked(
        self, addr: int, mask: int, want: int, t0: int, bound: int
    ) -> tuple[bool, int, BitMark | None]:
        """``_poll`` that also returns the vector-watch mark taken before the last miss read.

        A read that does not match was sampled after its mark, so an event that the read
        shows as not yet done cannot have happened before that mark.
        """
        last_miss = None
        while True:
            m = self.vec.mark()
            value = await self._rd(addr)
            elapsed = self._now_clk() - t0
            if (value & mask) == want:
                return True, value, last_miss
            last_miss = m
            if elapsed > bound:
                return False, value, last_miss
            await ClockCycles(cocotb.top.clk_i, 4)

    async def _wait_probe(self, sig, level: int, bound: int) -> None:
        for _ in range(bound):
            await RisingEdge(cocotb.top.clk_i)
            await ReadOnly()
            if self.rd_known(sig) == level:
                return
        raise AssertionError(f"{sig._name} did not read {level} within {bound} clocks")

    async def _reset_kmac(self) -> None:
        """One KMAC reset: bit 4 of SW_RESET_N low, then high, then idle."""
        probe = cocotb.top.kmac_gated_rst_n_probe_o
        await self.swrst.park("kmac")
        await self._wait_probe(probe, 0, _RESET_EDGE_CLK)
        await self.swrst.release("kmac")
        await self._wait_probe(probe, 1, _RESET_EDGE_CLK)
        await RisingEdge(cocotb.top.clk_i)
        ok, status, _ = await self._poll(KMAC_STATUS, _IDLE, _IDLE, self._now_clk(), _OUTER_CLK)
        if not ok:
            raise AssertionError(f"KMAC not idle after reset (STATUS=0x{status:08x})")

    async def _write_msg(self, cell: Cell) -> list[str]:
        """The message writes of ``cell``."""
        return await self._write_beats(cell.writes, cell.values)

    async def _write_msg_filled(self, cell: Cell) -> tuple[list[str], int]:
        """The message writes of ``cell``, the first ``_FILL_BYTES`` under the drain stall.

        ``kmac_fifo_drain_stall_i`` holds the read side of the message FIFO, so the words
        of those bytes stay in the FIFO; ``STATUS`` is read before the release. Returns
        the refused writes and that ``STATUS`` word.
        """
        dut = cocotb.top
        n = 0
        nbytes = 0
        while nbytes < _FILL_BYTES:
            nbytes += cell.writes[n][1]
            n += 1
        dut.kmac_fifo_drain_stall_i.value = 1
        try:
            await RisingEdge(dut.clk_i)
            refused = await self._write_beats(cell.writes[:n], cell.values[:n])
            fill = await self._rd(KMAC_STATUS)
        finally:
            dut.kmac_fifo_drain_stall_i.value = 0
        await RisingEdge(dut.clk_i)
        refused += await self._write_beats(cell.writes[n:], cell.values[n:])
        return refused, fill

    async def _write_beats(
        self, writes: tuple[tuple[int, int], ...], values: tuple[int, ...]
    ) -> list[str]:
        """Each write at its byte lane of ``MSG_FIFO``, AxSIZE of its width.

        kmac.hjson lines 1052-1058: software writes bytes or words to any
        address of the ``MSG_FIFO`` window. Returns ``lane/width/resp`` of
        each write that does not complete OKAY; the caller grades them.
        """
        refused: list[str] = []
        for (lane, width), value in zip(writes, values):
            seq = SepAxiAccessSeq(
                "kmac_msg_wr",
                op=SepAxiOp.WRITE,
                addr=KMAC_MSG_FIFO + lane,
                wdata=value,
                length=width,
                size=_AXSIZE[width],
            )
            await self.start_seq(seq)
            if not seq.resp_ok:
                refused.append(f"{lane}/{width}/{seq.resp_code}")
        return refused

    async def _read_state(self, nwords: int) -> list[int]:
        return await self.kmac.read_digest(nwords)

    # --- scenario -------------------------------------------------------------
    async def run_scenario(self) -> None:
        self._clk_ps = int(round(self.cfg.sys_clk_period_ns * 1000))
        # Step 1: OTBN, AES, HMAC and ABR held in reset; KMAC and TRNG released.
        await self.bring_up_no_cpu(park=("otbn", "aes", "hmac", "abr"))
        await self.bring_up_entropy(strict=True, score_km=False)
        self.start_fifo_drain()
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        baseline = await self.swrst.read_back()
        self.logger.info("INFO-BASELINE SW_RESET_N=0x%08x", baseline)

        seed = self.random_seed()
        self.kmac = SepKmac(self)
        self.chk = SepChkLog(self, TEST, seed)
        self._win_dead = False
        self._rg_twin_landed = 0
        self.vec = SepBitWatch(
            cocotb.top.sep_internal_interrupts_probe_o, {"kmac_done": _VEC_KMAC_DONE}
        ).start()
        plan = draw_plan(seed)
        self.chk.info(
            "PLAN",
            redraws=plan.redraws,
            rg_cell=plan.rg_cell,
            rg_prefix=plan.rg_prefix,
            rg_prefix_mask=f"0x{plan.rg_prefix_mask:08x}",
            rg_ep_mask=f"0x{plan.rg_ep_mask:08x}",
            cells=",".join(
                f"{c.mode}{c.strength}/L{c.length}/me{c.msg_end}se{c.state_end}"
                f"/w{''.join(str(w) for _, w in c.writes)}"
                for c in plan.cells
            ),
        )

        t_start = await self._warm_up()
        window = _IDLE_MULT * t_start
        self.chk.info("T-START", t_start=t_start, window_clk=window)

        self._open()
        for cell in plan.cells:
            rg = plan if cell.index == plan.rg_cell else None
            if rg is not None:
                # The idle control of CHK-KMAC-REGWEN-GATED runs with the window
                # closed, before the graded writes of the same registers.
                self._close()
                await self._regwen_gated_twin(seed, plan)
                self._open()
            try:
                await self._run_cell(seed, cell, window, rg)
            except CellTimeout:
                self._close()
                await self._reset_kmac()
                self._open()
        self._close()

        await self._fe_intrtest_leg()
        await self._narrow_lane_leg(seed)

        await self.vec.stop()
        await self.stop_fifo_drain()
        assert self.drbg_sb.report()
        self.chk.finish()

    async def _warm_up(self) -> int:
        """Step 3: one SHA3-256 hash of one byte that no check grades; returns t_start."""
        await self._reset_kmac()
        await self._write_cfg(_cfg_word("sha3", 256))
        t0 = self._now_clk()
        await self._wr(KMAC_CMD, KMAC_CMD_START)
        ok, status, t_start = await self._poll(KMAC_STATUS, _ABSORB, _ABSORB, t0, _OUTER_CLK)
        if not ok:
            raise AssertionError(f"warm-up: no absorb within {_OUTER_CLK} clocks (0x{status:x})")
        await self.kmac._push_msg_bytes(b"\x5a")
        await self._wr(KMAC_CMD, KMAC_CMD_PROCESS)
        ok, status, _ = await self._poll(KMAC_STATUS, _SQUEEZE, _SQUEEZE, t0, _OUTER_CLK)
        if not ok:
            raise AssertionError(f"warm-up: no squeeze within {_OUTER_CLK} clocks (0x{status:x})")
        await self._wr(KMAC_CMD, KMAC_CMD_DONE)
        t1 = self._now_clk()
        ok, status, _ = await self._poll(KMAC_STATUS, _IDLE, _IDLE, t1, _OUTER_CLK)
        if not ok:
            raise AssertionError(f"warm-up: no idle within {_OUTER_CLK} clocks (0x{status:x})")
        # The write-one clear of kmac_done (INTR_STATE RW1C), the same contract as the
        # cell control CTRL-KMAC-SEQ. A failed clear is recorded and the leaf continues.
        await self._wr(KMAC_INTR_STATE, _DONE)
        intr = await self._rd(KMAC_INTR_STATE)
        self._ctrl(
            "KMAC-SEQ",
            not intr & _DONE,
            phase="warm_up",
            cmd="done",
            expected_done_after_w1c=0,
            done_after_w1c=_bits(intr, _DONE),
            intr_state=f"0x{intr:08x}",
        )
        return t_start

    async def _run_cell(self, seed: int, cell: Cell, window: int, rg: Plan | None = None) -> None:
        """Steps 4-15 of one cell; ``rg`` is the plan on the CHK-KMAC-REGWEN-GATED cell."""
        tag = dict(
            seed=seed,
            cell=cell.index,
            mode=cell.mode,
            strength=cell.strength,
            len=cell.length,
            msg_end=cell.msg_end,
            state_end=cell.state_end,
        )
        # Step 3b: on the drawn cell, the earlier values of PREFIX_n and
        # ENTROPY_PERIOD, read at idle inside the graded window.
        rg_pre = None
        if rg is not None:
            rg_pre = (
                await self._rd(_prefix_addr(rg.rg_prefix)),
                await self._rd(_KMAC_ENTROPY_PERIOD),
            )

        # Step 4: the cell configuration C, read back (control of the lock check).
        c_word = _cfg_word(cell.mode, cell.strength, cell.msg_end, cell.state_end)
        await self._write_cfg(c_word)
        c_read = await self._rd(KMAC_CFG_SHADOWED) & _CFG_MASK
        c_live = c_read == (c_word & _CFG_MASK)

        # Step 5: idle window with no command.
        w0 = self._now_clk()
        reads = 0
        bad: list[str] = []
        idle_regwen = None
        while True:
            status = await self._rd(KMAC_STATUS)
            intr = await self._rd(KMAC_INTR_STATE)
            reads += 1
            if (status & (_IDLE | _ABSORB | _SQUEEZE)) != _IDLE or intr & _DONE:
                bad.append(f"0x{status & (_IDLE | _ABSORB | _SQUEEZE):x}/{_bits(intr, _DONE)}")
            if idle_regwen is None:
                idle_regwen = _bits(await self._rd(_KMAC_CFG_REGWEN), _REGWEN_EN)
            if self._now_clk() - w0 >= window:
                break
        window_clk = self._now_clk() - w0

        # Step 6: enable the kmac_done line.
        await self._wr(_KMAC_INTR_ENABLE, _DONE_EN)

        # Step 7: start; absorb=1 and idle=0 within a wait as long as the window.
        t0 = self._now_clk()
        await self._wr(KMAC_CMD, KMAC_CMD_START)
        seen, status, absorb_clk = await self._poll(
            KMAC_STATUS, _ABSORB | _IDLE, _ABSORB, t0, window
        )
        self._ok(
            "KMAC-IDLE",
            not bad,
            **tag,
            window_clk=window_clk,
            reads=reads,
            idle=int(not bad),
            absorb=0 if not bad else "x",
            squeeze=0 if not bad else "x",
            done=0 if not bad else "x",
            bad=",".join(bad[:4]) or "-",
            ctrl_absorb_clk=absorb_clk if seen else "none",
        )
        self._ctrl("KMAC-IDLE", seen, **tag, ctrl_absorb_clk=absorb_clk, bound=window)
        if not seen:
            self._ok(
                "KMAC-SEQ",
                False,
                **tag,
                cmd="start",
                reason="timeout",
                bound=window,
                idle=_bits(status, _IDLE),
                absorb=_bits(status, _ABSORB),
                squeeze=_bits(status, _SQUEEZE),
            )
            raise CellTimeout
        start_status = status

        # Step 8: the lock in the absorb stage.
        absorb_regwen = _bits(await self._rd(_KMAC_CFG_REGWEN), _REGWEN_EN)
        locked_wr_resp = [
            await self._wr_resp(KMAC_CFG_SHADOWED, c_word ^ _STATE_END) for _ in range(2)
        ]
        cfg_after = await self._rd(KMAC_CFG_SHADOWED) & _CFG_MASK
        self._ok(
            "KMAC-REGWEN",
            idle_regwen == 1 and absorb_regwen == 0 and cfg_after == (c_word & _CFG_MASK),
            **tag,
            idle_regwen=idle_regwen,
            absorb_regwen=absorb_regwen,
            cfg=f"0x{c_word & _CFG_MASK:08x}",
            cfg_after_locked_write=f"0x{cfg_after:08x}",
            locked_wr_resp=locked_wr_resp,
        )
        self._ctrl("KMAC-REGWEN", c_live, **tag, idle_cfg_readback=f"0x{c_read:08x}")

        # Step 8b: on the drawn cell, writes of PREFIX_n and ENTROPY_PERIOD in
        # absorb; PREFIX_n is graded here, ENTROPY_PERIOD at idle in step 15.
        rg_ep = None
        if rg is not None:
            rg_ep = await self._regwen_gated_writes(tag, rg, rg_pre)

        # Step 9: the message in the drawn widths. Every write must complete
        # OKAY; a refused write is a CHK-KMAC-DIGEST FAIL, and the digest below
        # is still graded.
        fill = None
        if cell.corner > 0:
            refused, fill = await self._write_msg_filled(cell)
        else:
            refused = await self._write_msg(cell)
        written = cell.length - sum(int(r.split("/")[1]) for r in refused)
        if refused:
            self._ok(
                "KMAC-DIGEST",
                False,
                **tag,
                reason="msg_write_resp",
                writes=len(cell.writes),
                refused=len(refused),
                lane_width_resp=",".join(refused[:4]),
            )

        # Steps 10-11: process, then kmac_done and the line rise, then the FIFO
        # state. INTR_STATE is polled from the process write with no STATUS read
        # in between, so the one STATUS read after the done-line grade is the
        # first STATUS read after the completion.
        mark = self.vec.mark()
        vec_before = self.vec.level("kmac_done")
        t1 = self._now_clk()
        await self._wr(KMAC_CMD, KMAC_CMD_PROCESS)
        seen, _, done_miss = await self._poll_marked(KMAC_INTR_STATE, _DONE, _DONE, t1, _OUTER_CLK)
        lower, lower_src = mark, "process"
        if done_miss is not None:
            lower, lower_src = done_miss, "done0"
        rise_clk = None
        if seen:
            try:
                rise_clk = await self.vec.wait_rise(mark, window, "kmac_done")
            except BitWatchTimeout:
                rise_clk = None
        in_order = rise_clk is not None and lower.clk <= rise_clk <= mark.clk + window
        self._ok(
            "KMAC-DONE-LINE",
            vec_before == 0 and seen and in_order,
            **tag,
            enable=1,
            state=int(seen),
            vec20_before=vec_before,
            vec20=int(rise_clk is not None),
            rise_clk=rise_clk if rise_clk is not None else "none",
            lower_clk=lower.clk,
            lower_src=lower_src,
            process_clk=mark.clk,
            rise_bound=window,
            **({} if seen else {"reason": "timeout", "bound": _OUTER_CLK}),
        )
        if not seen:
            raise CellTimeout
        done_status = await self._rd(KMAC_STATUS)
        ctrl_process_squeeze = _bits(done_status, _SQUEEZE)
        self._grade_fifo_done(tag, cell, done_status, written, fill)
        squeeze_regwen = _bits(await self._rd(_KMAC_CFG_REGWEN), _REGWEN_EN)

        # Step 12: write-one clear of kmac_done; the line fall is logged only.
        await self._wr(KMAC_INTR_STATE, _DONE)
        done_after = _bits(await self._rd(KMAC_INTR_STATE), _DONE)
        await RisingEdge(cocotb.top.clk_i)
        self.chk.obs(
            "KMAC-DONE-FALL",
            seed=seed,
            cell=cell.index,
            state_after_w1c=done_after,
            vec20_after_w1c=self.vec.level("kmac_done"),
        )

        # Step 13: the digest (SHA3) or the first rate block (SHAKE).
        msg = cell.message()
        rate = keccak_rate_bytes(cell.strength)
        if cell.mode == "sha3":
            gold_bytes = sha3(msg, cell.strength)
            block2 = None
        else:
            out = shake(msg, cell.strength, 2 * rate)
            gold_bytes, block2 = out[:rate], out[rate:]
        golden = _words(gold_bytes, cell.state_end)
        got = await self._read_state(len(golden))
        match = got == golden
        self._ok(
            "KMAC-DIGEST",
            match,
            **tag,
            kmac_en=0,
            widths="".join(str(8 * w) + "." for _, w in cell.writes).rstrip("."),
            words=len(golden),
            digest_eq_golden=int(match),
            first_diff=next((i for i, (a, b) in enumerate(zip(got, golden)) if a != b), "-"),
        )

        # Step 14: run on a SHAKE cell gives golden block 2.
        run_ok = True
        if block2 is not None:
            run_ok = await self._run_block2(tag, cell, block2)

        # Step 15: done, idle; clear kmac_done before the next idle window.
        t2 = self._now_clk()
        await self._wr(KMAC_CMD, KMAC_CMD_DONE)
        done_idle, status, _ = await self._poll(
            KMAC_STATUS, _IDLE | _SQUEEZE, _IDLE, t2, _OUTER_CLK
        )
        await self._wr(KMAC_INTR_STATE, _DONE)
        cleared = _bits(await self._rd(KMAC_INTR_STATE), _DONE) == 0
        self.chk.obs(
            "KMAC-REGWEN-SQUEEZE",
            seed=seed,
            cell=cell.index,
            squeeze=ctrl_process_squeeze,
            squeeze_regwen=squeeze_regwen,
            idle_after_done=int(done_idle),
            done_regwen=_bits(await self._rd(_KMAC_CFG_REGWEN), _REGWEN_EN),
        )

        # Step 15b: the ENTROPY_PERIOD write in absorb, read back at idle.
        if rg_ep is not None:
            await self._grade_entropy_period_held(tag, rg_ep, done_idle, status)

        self._ok(
            "KMAC-SEQ",
            _bits(start_status, _ABSORB) == 1 and _bits(start_status, _IDLE) == 0,
            **tag,
            cmd="start",
            idle=_bits(start_status, _IDLE),
            absorb=_bits(start_status, _ABSORB),
            squeeze=_bits(start_status, _SQUEEZE),
            ctrl_process_squeeze=ctrl_process_squeeze,
            ctrl_done_idle=int(done_idle),
        )
        # Steps 12 and 15: the write-one clear of kmac_done (INTR_STATE RW1C) reads 0.
        self._ctrl(
            "KMAC-SEQ",
            ctrl_process_squeeze == 1 and done_idle and done_after == 0 and cleared,
            **tag,
            ctrl_process_squeeze=ctrl_process_squeeze,
            ctrl_done_idle=int(done_idle),
            done_after_w1c=done_after,
            done_cleared=int(cleared),
        )
        if not done_idle or not cleared or not run_ok:
            raise CellTimeout
        await self._release_cell()

    def _grade_fifo_done(
        self, tag: dict, cell: Cell, status: int, written: int, fill: int | None
    ) -> None:
        """CHK-KMAC-FIFO-DONE on the first STATUS read after kmac_done reads 1.

        kmac.adoc lines 226-239: ``fifo_depth`` counts the occupied entries,
        ``fifo_empty`` is 1 when the FIFO holds none, ``fifo_full`` is 0 below
        full. After the completion the whole message has left the FIFO.
        """
        depth = (status & _FIFO_DEPTH) >> _FIFO_DEPTH_LSB
        empty = _bits(status, _FIFO_EMPTY)
        full = _bits(status, _FIFO_FULL)
        exp_depth = 0
        rate = keccak_rate_bytes(cell.strength)
        self._ok(
            "KMAC-FIFO-DONE",
            depth == exp_depth and empty == 1 and full == 0,
            **tag,
            rate=rate,
            written=written,
            fifo_depth=depth,
            expected_fifo_depth=exp_depth,
            fifo_empty=empty,
            fifo_full=full,
            squeeze=_bits(status, _SQUEEZE),
        )
        self.chk.info("KMAC-FIFO-DONE", **tag, status=f"0x{status:08x}")
        if cell.corner > 0:
            # Positive probe from the DUT: under the drain stall the FIFO held message
            # words (fifo_depth >= 1, fifo_empty 0), and the cell wrote more than one
            # rate block.
            fill_depth = -1 if fill is None else (fill & _FIFO_DEPTH) >> _FIFO_DEPTH_LSB
            fill_empty = -1 if fill is None else _bits(fill, _FIFO_EMPTY)
            self._ctrl(
                "KMAC-FIFO-DONE",
                written > rate and fill_depth >= 1 and fill_empty == 0,
                **tag,
                rate=rate,
                written=written,
                fill_bytes=_FILL_BYTES,
                fill_fifo_depth=fill_depth,
                fill_fifo_empty=fill_empty,
                fill_status="none" if fill is None else f"0x{fill:08x}",
            )

    async def _wr_resp(self, addr: int, data: int) -> int:
        """One 32-bit register write; returns its AXI response code."""
        seq = SepAxiAccessSeq(
            "kmac_rg_wr", op=SepAxiOp.WRITE, addr=addr, wdata=data, length=4, size=_AXSIZE[4]
        )
        await self.start_seq(seq)
        return seq.resp_code

    async def _regwen_gated_twin(self, seed: int, plan: Plan) -> None:
        """CTRL-KMAC-REGWEN-GATED: at idle with CFG_REGWEN 1 the same writes land.

        Runs with the graded window closed. Each register is written with
        pre XOR mask, read back, then restored to pre and read back.
        """
        p_addr = _prefix_addr(plan.rg_prefix)
        regwen = _bits(await self._rd(_KMAC_CFG_REGWEN), _REGWEN_EN)
        p_pre = await self._rd(p_addr)
        await self._wr(p_addr, p_pre ^ plan.rg_prefix_mask)
        p_got = await self._rd(p_addr)
        await self._wr(p_addr, p_pre)
        p_back = await self._rd(p_addr)
        e_pre = await self._rd(_KMAC_ENTROPY_PERIOD)
        await self._wr(_KMAC_ENTROPY_PERIOD, e_pre ^ plan.rg_ep_mask)
        e_got = await self._rd(_KMAC_ENTROPY_PERIOD)
        await self._wr(_KMAC_ENTROPY_PERIOD, e_pre)
        e_back = await self._rd(_KMAC_ENTROPY_PERIOD)
        self._ctrl(
            "KMAC-REGWEN-GATED",
            regwen == 1
            and p_got == (p_pre ^ plan.rg_prefix_mask)
            and p_back == p_pre
            and (e_got & _EP_FIELDS) == ((e_pre ^ plan.rg_ep_mask) & _EP_FIELDS)
            and (e_back & _EP_FIELDS) == (e_pre & _EP_FIELDS),
            seed=seed,
            cell=plan.rg_cell,
            phase="idle",
            regwen=regwen,
            prefix_n=plan.rg_prefix,
            prefix_pre=f"0x{p_pre:08x}",
            prefix_wrote=f"0x{p_pre ^ plan.rg_prefix_mask:08x}",
            prefix_read=f"0x{p_got:08x}",
            prefix_restored=f"0x{p_back:08x}",
            ep_pre=f"0x{e_pre & _EP_FIELDS:08x}",
            ep_wrote=f"0x{(e_pre ^ plan.rg_ep_mask) & _EP_FIELDS:08x}",
            ep_read=f"0x{e_got & _EP_FIELDS:08x}",
            ep_restored=f"0x{e_back & _EP_FIELDS:08x}",
        )
        self._rg_twin_landed = int(
            p_got == (p_pre ^ plan.rg_prefix_mask)
            and (e_got & _EP_FIELDS) == ((e_pre ^ plan.rg_ep_mask) & _EP_FIELDS)
        )

    async def _regwen_gated_writes(
        self, tag: dict, plan: Plan, pre: tuple[int, int]
    ) -> tuple[int, int, int, int, int]:
        """CHK-KMAC-REGWEN-GATED role=prefix in absorb; returns the ENTROPY_PERIOD leg.

        With CFG_REGWEN read 0, PREFIX_n = pre XOR mask is written and read back;
        the read must return pre. ENTROPY_PERIOD = pre XOR mask is written in the
        same stage and graded at idle after ``CMD.done``.
        """
        p_pre, e_pre = pre
        p_addr = _prefix_addr(plan.rg_prefix)
        regwen = _bits(await self._rd(_KMAC_CFG_REGWEN), _REGWEN_EN)
        p_wrote = p_pre ^ plan.rg_prefix_mask
        p_resp = await self._wr_resp(p_addr, p_wrote)
        p_got = await self._rd(p_addr)
        e_wrote = e_pre ^ plan.rg_ep_mask
        e_resp = await self._wr_resp(_KMAC_ENTROPY_PERIOD, e_wrote)
        intr = await self._rd(KMAC_INTR_STATE)
        err_code = await self._rd(KMAC_ERR_CODE)
        self._ok(
            "KMAC-REGWEN-GATED",
            regwen == 0 and self._rg_twin_landed == 1 and p_got == p_pre,
            **tag,
            role="prefix",
            regwen=regwen,
            ctrl_twin_landed=self._rg_twin_landed,
            prefix_n=plan.rg_prefix,
            pre=f"0x{p_pre:08x}",
            wrote=f"0x{p_wrote:08x}",
            read=f"0x{p_got:08x}",
            expected=f"0x{p_pre:08x}",
            wr_resp=p_resp,
        )
        self.chk.obs(
            "KMAC-REGWEN-GATED-ERR",
            **tag,
            kmac_err=_bits(intr, _KMAC_ERR),
            err_code=f"0x{err_code:08x}",
        )
        return e_pre, e_wrote, regwen, e_resp, self._rg_twin_landed

    async def _grade_entropy_period_held(
        self, tag: dict, leg: tuple[int, int, int, int, int], idle: bool, status: int
    ) -> None:
        """CHK-KMAC-REGWEN-GATED role=entropy_period: the named fields read pre at idle.

        The register is read only when the ``CMD.done`` poll showed idle; a
        poll that timed out is a FAIL of this check with no read.
        """
        e_pre, e_wrote, regwen, e_resp, twin = leg
        e_got = await self._rd(_KMAC_ENTROPY_PERIOD) if idle else None
        held = e_got is not None and (e_got & _EP_FIELDS) == (e_pre & _EP_FIELDS)
        self._ok(
            "KMAC-REGWEN-GATED",
            regwen == 0 and twin == 1 and held,
            **tag,
            role="entropy_period",
            regwen=regwen,
            ctrl_twin_landed=twin,
            idle_at_read=_bits(status, _IDLE),
            pre=f"0x{e_pre & _EP_FIELDS:08x}",
            wrote=f"0x{e_wrote & _EP_FIELDS:08x}",
            read=f"0x{e_got & _EP_FIELDS:08x}" if e_got is not None else "none",
            expected=f"0x{e_pre & _EP_FIELDS:08x}",
            wr_resp=e_resp,
            **({} if idle else {"reason": "done_timeout", "bound": _OUTER_CLK}),
        )
        if e_got is not None:
            self.chk.obs(
                "KMAC-REGWEN-GATED-RSVD",
                **tag,
                rsvd_pre=f"0x{e_pre & ~_EP_FIELDS:08x}",
                rsvd_read=f"0x{e_got & ~_EP_FIELDS:08x}",
            )

    async def _run_block2(self, tag: dict, cell: Cell, block2: bytes) -> bool:
        """Step 14: CMD.run, then poll STATUS and STATE for golden block 2."""
        golden = _words(block2, cell.state_end)
        t0 = self._now_clk()
        await self._wr(KMAC_CMD, _KMAC_CMD_RUN)
        status = 0
        polls = 0
        while True:
            status = await self._rd(KMAC_STATUS)
            polls += 1
            if status & _SQUEEZE and await self._read_state(len(golden)) == golden:
                clk = self._now_clk() - t0
                # The run has completed once STATE shows block 2; grade the
                # STATUS read taken after that, not the poll read before it.
                post = await self._rd(KMAC_STATUS)
                self._ok(
                    "KMAC-RUN",
                    True,
                    **tag,
                    shake=cell.strength,
                    block2_eq_golden=1,
                    run_clk=clk,
                    polls=polls,
                )
                self._ok(
                    "KMAC-SEQ",
                    _bits(post, _SQUEEZE) == 1,
                    **tag,
                    cmd="run",
                    idle=_bits(post, _IDLE),
                    absorb=_bits(post, _ABSORB),
                    squeeze=_bits(post, _SQUEEZE),
                    poll_squeeze=_bits(status, _SQUEEZE),
                )
                return _bits(post, _SQUEEZE) == 1
            if self._now_clk() - t0 > _OUTER_CLK:
                break
            await ClockCycles(cocotb.top.clk_i, 4)
        squeeze = _bits(status, _SQUEEZE)
        self._ok(
            "KMAC-RUN",
            False,
            **tag,
            shake=cell.strength,
            block2_eq_golden=0,
            reason="timeout",
            bound=_OUTER_CLK,
            squeeze=squeeze,
        )
        self._ok(
            "KMAC-SEQ",
            squeeze == 1,
            **tag,
            cmd="run",
            idle=_bits(status, _IDLE),
            absorb=_bits(status, _ABSORB),
            squeeze=squeeze,
        )
        return False

    async def _fe_intrtest_leg(self) -> None:
        """CHK-KMAC-FE-INTRTEST: ``INTR_TEST.fifo_empty`` at idle sets ``INTR_STATE.fifo_empty``.

        The graded FCOV window stays closed. The reads after the settle window
        and after the write-one clear are logged only.
        """
        await self._reset_kmac()
        before = _bits(await self._rd(KMAC_INTR_STATE), _INTR_FIFO_EMPTY)
        await self._wr(_KMAC_INTR_TEST, _INTR_TEST_FIFO_EMPTY)
        await ClockCycles(cocotb.top.clk_i, 1)
        st_1 = _bits(await self._rd(KMAC_INTR_STATE), _INTR_FIFO_EMPTY)
        await ClockCycles(cocotb.top.clk_i, _FE_SETTLE_CLK)
        st_settle = _bits(await self._rd(KMAC_INTR_STATE), _INTR_FIFO_EMPTY)
        await self._wr(KMAC_INTR_STATE, _INTR_FIFO_EMPTY)
        st_w1c = _bits(await self._rd(KMAC_INTR_STATE), _INTR_FIFO_EMPTY)
        self._ok(
            "KMAC-FE-INTRTEST",
            before == 0 and st_1 == 1,
            state_before=before,
            state_1clk=st_1,
        )
        self.chk.obs(
            "KMAC-FE-INTRTEST",
            state_settle=st_settle,
            settle_clk=_FE_SETTLE_CLK,
            state_after_w1c=st_w1c,
        )
        await self._reset_kmac()

    async def _narrow_lane_leg(self, seed: int) -> None:
        """CHK-KMAC-NARROW-WRITE: the fixed message at byte lanes 1 to 3, SHA3-256.

        The graded FCOV window stays closed. Each bounded wait that expires is
        a FAIL of this check, then a KMAC reset.
        """
        msg = b"".join(v.to_bytes(w, "little") for (_, w), v in zip(_NARROW_WRITES, _NARROW_VALUES))
        golden = _words(sha3(msg, 256), 0)
        tag = dict(
            seed=seed,
            mode="sha3",
            strength=256,
            len=len(msg),
            lanes_widths=",".join(f"{lane}/{w}" for lane, w in _NARROW_WRITES),
        )
        await self._reset_kmac()
        await self._write_cfg(_cfg_word("sha3", 256))
        t0 = self._now_clk()
        await self._wr(KMAC_CMD, KMAC_CMD_START)
        ok, status, _ = await self._poll(KMAC_STATUS, _ABSORB, _ABSORB, t0, _OUTER_CLK)
        if not ok:
            self._ok("KMAC-NARROW-WRITE", False, **tag, reason="start_timeout", bound=_OUTER_CLK)
            await self._reset_kmac()
            return
        refused = await self._write_beats(_NARROW_WRITES, _NARROW_VALUES)
        t1 = self._now_clk()
        await self._wr(KMAC_CMD, KMAC_CMD_PROCESS)
        ok, status, _ = await self._poll(KMAC_STATUS, _SQUEEZE, _SQUEEZE, t1, _OUTER_CLK)
        got = await self._read_state(len(golden)) if ok else []
        match = got == golden
        self._ok(
            "KMAC-NARROW-WRITE",
            ok and not refused and match,
            **tag,
            writes=len(_NARROW_WRITES),
            all_okay=int(not refused),
            refused_lane_width_resp=",".join(refused) or "-",
            digest_eq_golden=int(match),
            digest0=f"0x{got[0]:08x}" if got else "none",
            golden0=f"0x{golden[0]:08x}",
            **({} if ok else {"reason": "squeeze_timeout", "bound": _OUTER_CLK}),
        )
        await self._reset_kmac()
