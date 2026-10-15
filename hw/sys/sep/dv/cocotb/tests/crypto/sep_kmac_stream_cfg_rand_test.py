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
                      of the last read that showed the hash not complete
                      (``STATUS.sha3_squeeze`` = 0 or ``kmac_done`` = 0), and
                      within the rise bound after the read that shows
                      ``kmac_done`` = 1.
  CHK-KMAC-REGWEN     CFG_REGWEN 1 in the idle window, 0 in absorb; a double
                      write of CFG_SHADOWED in absorb leaves it at C. Control:
                      the idle write reads back C.
  CHK-KMAC-NARROW-WRITE  one fixed SHA3-256 message written with 8-bit and
                      16-bit writes at byte lanes 1 to 3 of MSG_FIFO: every
                      write completes OKAY and the digest equals the golden of
                      the bytes in write order (kmac.hjson lines 1052-1058:
                      software writes bytes or words to any address of the
                      window; the low 12 address bits are ignored). It runs
                      once per seed after the cells, with the graded FCOV
                      window closed.

The cells write each message beat at byte lane 0 of ``MSG_FIFO`` in the drawn
width, so the cell checks grade the stages, endianness, corners and lock on
their own; the byte-lane placement is graded only by CHK-KMAC-NARROW-WRITE.

Observations: ``OBS-KMAC-DONE-FALL`` logs bit 20 after the write-one clear.

Time bounds: t_start is the clean start time of the warm-up hash, from the
``CMD.start`` write to the read that shows absorb. The idle window and the
start wait are ``_IDLE_MULT`` x t_start. The hash waits use the outer limit
``_OUTER_CLK`` and log the measured clocks.

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense
+esrc_noise_force``. RAND-REP: the seed draws the cell order, the message
bytes and the write widths; the 18 cells are the same on every seed.
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
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_kmac_golden import sha3, shake
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import KMAC
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_kmac_seq import (
    KMAC_CFG_SHADOWED,
    KMAC_CMD,
    KMAC_CMD_DONE,
    KMAC_CMD_PROCESS,
    KMAC_CMD_START,
    KMAC_INTR_STATE,
    KMAC_MODE,
    KMAC_MSG_FIFO,
    KMAC_STATUS,
    KMAC_STRENGTH,
    SepKmac,
    build_kmac_cfg,
)

TEST = "sep_kmac_stream_cfg_rand_test"

# kmac.hjson CMD.cmd enum (lines 656-660): run = 49.
_KMAC_CMD_RUN = 49

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
_OUTER_CLK = 20_000
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
            return Plan(tuple(cells), redraws)
        redraws += 1


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


class CellTimeout(Exception):
    """A bounded wait of a cell expired; the owning check already logged FAIL."""


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
    )

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
        self.logger.info("SW_RESET_N baseline=0x%08x", baseline)

        seed = self.random_seed()
        self.kmac = SepKmac(self)
        self.chk = SepChkLog(self, TEST, seed)
        self.vec = SepBitWatch(
            cocotb.top.sep_internal_interrupts_probe_o, {"kmac_done": _VEC_KMAC_DONE}
        ).start()
        plan = draw_plan(seed)
        self.logger.info(
            "PLAN seed=%d redraws=%d cells=%s",
            seed,
            plan.redraws,
            ",".join(
                f"{c.mode}{c.strength}/L{c.length}/me{c.msg_end}se{c.state_end}"
                f"/w{''.join(str(w) for _, w in c.writes)}"
                for c in plan.cells
            ),
        )

        t_start = await self._warm_up()
        window = _IDLE_MULT * t_start
        self.logger.info("t_start seed=%d t_start=%d window_clk=%d", seed, t_start, window)

        open_graded_window(TEST)
        for cell in plan.cells:
            try:
                await self._run_cell(seed, cell, window)
            except CellTimeout:
                close_graded_window()
                await self._reset_kmac()
                open_graded_window(TEST)
        close_graded_window()

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
        await self._wr(KMAC_INTR_STATE, _DONE)
        intr = await self._rd(KMAC_INTR_STATE)
        if intr & _DONE:
            raise AssertionError(f"warm-up: kmac_done reads 1 after W1C (0x{intr:x})")
        return t_start

    async def _run_cell(self, seed: int, cell: Cell, window: int) -> None:
        """Steps 4-15 of one cell."""
        tag = dict(
            seed=seed,
            cell=cell.index,
            mode=cell.mode,
            strength=cell.strength,
            len=cell.length,
            msg_end=cell.msg_end,
            state_end=cell.state_end,
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
        self.chk.ok(
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
        self.chk.ctrl("KMAC-IDLE", seen, **tag, ctrl_absorb_clk=absorb_clk, bound=window)
        if not seen:
            self.chk.ok(
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
        await self._write_cfg(c_word ^ _STATE_END)
        cfg_after = await self._rd(KMAC_CFG_SHADOWED) & _CFG_MASK
        self.chk.ok(
            "KMAC-REGWEN",
            idle_regwen == 1 and absorb_regwen == 0 and cfg_after == (c_word & _CFG_MASK),
            **tag,
            idle_regwen=idle_regwen,
            absorb_regwen=absorb_regwen,
            cfg=f"0x{c_word & _CFG_MASK:08x}",
            cfg_after_locked_write=f"0x{cfg_after:08x}",
        )
        self.chk.ctrl("KMAC-REGWEN", c_live, **tag, idle_cfg_readback=f"0x{c_read:08x}")

        # Step 9: the message in the drawn widths. Every write must complete
        # OKAY; a refused write is a CHK-KMAC-DIGEST FAIL, and the digest below
        # is still graded.
        refused = await self._write_msg(cell)
        if refused:
            self.chk.ok(
                "KMAC-DIGEST",
                False,
                **tag,
                reason="msg_write_resp",
                writes=len(cell.writes),
                refused=len(refused),
                lane_width_resp=",".join(refused[:4]),
            )

        # Steps 10-11: process, squeeze, then kmac_done and the line rise.
        mark = self.vec.mark()
        vec_before = self.vec.level("kmac_done")
        t1 = self._now_clk()
        await self._wr(KMAC_CMD, KMAC_CMD_PROCESS)
        seen, status, sq_miss = await self._poll_marked(
            KMAC_STATUS, _SQUEEZE, _SQUEEZE, t1, _OUTER_CLK
        )
        ctrl_process_squeeze = int(seen)
        state_seen = False
        rise_clk = None
        lower, lower_src = mark, "process"
        if sq_miss is not None:
            lower, lower_src = sq_miss, "squeeze0"
        if seen:
            state_seen, intr, done_miss = await self._poll_marked(
                KMAC_INTR_STATE, _DONE, _DONE, t1, _OUTER_CLK
            )
            if done_miss is not None:
                lower, lower_src = done_miss, "done0"
            if state_seen:
                try:
                    rise_clk = await self.vec.wait_rise(mark, window, "kmac_done")
                except BitWatchTimeout:
                    rise_clk = None
        in_order = rise_clk is not None and rise_clk >= lower.clk
        self.chk.ok(
            "KMAC-DONE-LINE",
            vec_before == 0 and state_seen and in_order,
            **tag,
            enable=1,
            state=int(state_seen),
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
        self.chk.ok(
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

        self.chk.ok(
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
        self.chk.ctrl(
            "KMAC-SEQ",
            ctrl_process_squeeze == 1 and done_idle,
            **tag,
            ctrl_process_squeeze=ctrl_process_squeeze,
            ctrl_done_idle=int(done_idle),
            done_cleared=int(cleared),
        )
        if not done_idle or not cleared or not run_ok:
            raise CellTimeout

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
                self.chk.ok(
                    "KMAC-RUN",
                    True,
                    **tag,
                    shake=cell.strength,
                    block2_eq_golden=1,
                    run_clk=clk,
                    polls=polls,
                )
                self.chk.ok(
                    "KMAC-SEQ",
                    True,
                    **tag,
                    cmd="run",
                    idle=_bits(status, _IDLE),
                    absorb=_bits(status, _ABSORB),
                    squeeze=1,
                )
                return True
            if self._now_clk() - t0 > _OUTER_CLK:
                break
            await ClockCycles(cocotb.top.clk_i, 4)
        squeeze = _bits(status, _SQUEEZE)
        self.chk.ok(
            "KMAC-RUN",
            False,
            **tag,
            shake=cell.strength,
            block2_eq_golden=0,
            reason="timeout",
            bound=_OUTER_CLK,
            squeeze=squeeze,
        )
        self.chk.ok(
            "KMAC-SEQ",
            squeeze == 1,
            **tag,
            cmd="run",
            idle=_bits(status, _IDLE),
            absorb=_bits(status, _ABSORB),
            squeeze=squeeze,
        )
        return False

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
            self.chk.ok("KMAC-NARROW-WRITE", False, **tag, reason="start_timeout", bound=_OUTER_CLK)
            await self._reset_kmac()
            return
        refused = await self._write_beats(_NARROW_WRITES, _NARROW_VALUES)
        t1 = self._now_clk()
        await self._wr(KMAC_CMD, KMAC_CMD_PROCESS)
        ok, status, _ = await self._poll(KMAC_STATUS, _SQUEEZE, _SQUEEZE, t1, _OUTER_CLK)
        got = await self._read_state(len(golden)) if ok else []
        match = got == golden
        self.chk.ok(
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
