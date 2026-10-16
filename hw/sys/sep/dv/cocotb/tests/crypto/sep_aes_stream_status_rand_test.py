# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AES automatic-mode streams, stall, automatic START, manual overwrite, IDLE and no interrupt.

Contract (``vendor/lowRISC/opentitan/overlay/regs/aes/regs/gen/adoc/aes.adoc``,
CTRL_SHADOWED, TRIGGER, STATUS; ``hw/sys/sep/doc/aes.adoc``, OCAH
Modifications; ``hw/sys/sep/doc/interrupts.adoc``, PIC source map):
  * MANUAL_OPERATION = 0: the unit starts on new input and stalls in the last
    cycle while the previous output is unread (STALL = 1, IDLE = 0); a
    TRIGGER.START write does not start the unit.
  * MANUAL_OPERATION = 1: the unit starts only on TRIGGER.START, overwrites
    unread output and sets OUTPUT_LOST until the Control Register is rewritten.
  * IDLE is 0 while a block runs.
  * INPUT_READY is 0 while the present DATA_IN values are not loaded into the
    module, and 1 once the unit has loaded them.
  * AES has no interrupt: AES activity changes no bit of the interrupt vector.

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense``,
``+esrc_noise_force``. The internal entropy source feeds ESRC, CSRNG and EDN.
HMAC is out of reset and idle for the control of the no-interrupt check; KMAC,
OTBN and ABR stay in reset.

Randomization (``SepSeededRng`` from the run seed, drawn before the first
stimulus): the order of the ECB, CBC and CTR streams, and per stream the key
size, the operation (encrypt or decrypt for ECB and CBC, encrypt for CTR), the
block count N (34 to 100), the input and output gap of every block (0 to 40
clocks), one or two stall pairs and one or two control pairs (indexes in 1 to
N - 2, no two pairs overlap), the stall delay factor of each pair (2 to 20
times t_blk), the data words, the factor of the manual-leg wait (2 to 8
times t_blk), and the three blocks of the INPUT_READY leg (drawn last). Keys, IVs and the CTR start counter come from published test
constants; the CTR counter keeps its low 32 bits at or below 2^32 - N.

Checkers:
  CHK-AES-STREAM      every block of each stream equals the streaming golden.
  CHK-AES-STALL       per stall pair: STALL = 1 and IDLE = 0 at G clocks with
                      the previous output unread; after the read STALL falls
                      and the next block equals its golden. Control: each
                      control pair reads STALL = 0 at its G.
  CHK-AES-START-AUTO  a START write in automatic mode with no input leaves
                      IDLE = 1 and OUTPUT_VALID = 0 for 20 x t_blk clocks.
                      Control: four DATA_IN words start a block.
  CHK-AES-LOST        manual overwrite sets OUTPUT_LOST, DATA_OUT holds block
                      2, OUTPUT_LOST stays 1 after the full DATA_OUT read, and a
                      Control Register rewrite clears it.
                      Control: a read between the blocks keeps OUTPUT_LOST 0.
  CHK-AES-IDLE        IDLE reads 0 from its first fall until the OUTPUT_VALID
                      sample of each back-to-back polled block. Control: the
                      quiet unit reads IDLE = 1.
  CHK-AES-NOIRQ       the 41 vector bits other than 36 and 37 keep their first
                      value on every clock of the AES legs. Control: one HMAC
                      operation with ``hmac_done`` enabled raises bit 17.
  CHK-AES-INPUT-READY with output 0 unread and block 1 stalled (STALL = 1),
                      block 2 is written: every STATUS read of a window of
                      IR_WINDOW_FACTOR x t_blk clocks shows STALL = 1 and
                      INPUT_READY = 0 (aes.rdl STATUS.INPUT_READY: "If the
                      present values in the DATA_IN registers have not yet
                      been loaded into the module this flag is `0` (not
                      ready)."; theory_of_operation.md:37-39: the stalled unit
                      "only continues once the previous output data has been
                      read"). After output 0 is read, INPUT_READY reads 1
                      inside a window of the same length
                      (programmers_guide.md:56: INPUT_READY becomes 1 when the
                      unit loads the block "and start operation"; :66), and
                      the three outputs equal their goldens. Control: the
                      STALL = 1 read before block 2 is written shows
                      INPUT_READY = 1 (block 1 is loaded).
Vector bits 36 and 37 (entropy pool sources) are logged as ``OBS-POOL-VEC``.
``aes.rdl`` is ``vendor/lowRISC/opentitan/overlay/regs/aes/regs/aes.rdl``; the two ``.md``
files are under ``vendor/lowRISC/opentitan/upstream/hw/ip/aes/doc/``.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from env.sep_aes_golden import aes_cbc_decrypt, aes_decrypt_block, aes_encrypt_words
from env.sep_bit_watch import SepBitWatch
from env.sep_chk_log import SepChkLog
from env.sep_crypto_kat_rows import AES_IV_ROWS, AES_KEY_ROWS
from env.sep_edge_timer import SepEdgeTimer
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_seeded_rng import SepSeededRng
from env.sep_trial_wait import TrialTimeout, poll_until, wait_until
from sep_base_test import sep_base_test
from sep_reg_meta import AES, HMAC, sep_addr_define
from seq_lib.sep_aes_seq import (
    AES_CTRL_SHADOWED,
    AES_DATA_IN_0,
    AES_DATA_OUT_0,
    AES_IV_0,
    AES_KEY_LEN_256,
    AES_KEYLEN_CTRL,
    AES_MODE_CTRL,
    AES_MODE_ECB,
    AES_OP_DEC,
    AES_OP_ENC,
    AES_STATUS,
    AES_TRIGGER,
    AES_TRIGGER_DATA_OUT_CLEAR,
    SepAes,
    build_aes_ctrl,
)
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_hmac_seq import HMAC_STATUS_IDLE, SepHmac

TEST = "sep_aes_stream_status_rand_test"

# Published test constants (env/sep_crypto_kat_rows.py). The seed picks a row, never the
# bytes.
KEY_ROWS = AES_KEY_ROWS
IV_ROWS = AES_IV_ROWS

ST_IDLE = AES.field_mask("STATUS", "idle")
ST_STALL = AES.field_mask("STATUS", "stall")
ST_LOST = AES.field_mask("STATUS", "output_lost")
ST_OV = AES.field_mask("STATUS", "output_valid")
ST_IR = AES.field_mask("STATUS", "input_ready")
CTRL_MANUAL = AES.field_mask("CTRL_SHADOWED", "manual_operation")
TRIG_START = AES.field_mask("TRIGGER", "start")

N_VEC = 43
POOL_BITS = (36, 37)  # sources 37 and 38: entropy pool low, pool fill stall
VEC_MASK = ((1 << N_VEC) - 1) & ~sum(1 << b for b in POOL_BITS)
HMAC_DONE_BIT = 17  # source 18
INTR_ENABLE_OFF = (
    "SEP_TOP_ENTROPY_SOURCE_INTR_ENABLE_BASE_ADDR",
    "SEP_TOP_CSRNG_INTR_ENABLE_BASE_ADDR",
    "SEP_TOP_EDN_INTR_ENABLE_BASE_ADDR",
)

WAIT_LIMIT = 20_000  # outer limit of a wait that has no clean time yet (logged as bound=)
OV_BOUND_FACTOR = 64  # bounded OUTPUT_VALID wait = 64 x t_blk
START_WINDOW_FACTOR = 20  # 20 x t_blk (test parameter)
IR_WINDOW_FACTOR = 8  # held and load windows of the INPUT_READY leg = 8 x t_blk (test parameter)
EXP_HELD_IR = 0  # INPUT_READY with block 2 written and not loaded (aes.rdl STATUS.INPUT_READY)
EXP_LOADED_IR = 1  # INPUT_READY once the block is loaded (programmers_guide.md:56)


def _le_words(data: bytes) -> list[int]:
    return [int.from_bytes(data[i : i + 4], "little") for i in range(0, len(data), 4)]


def _le_bytes(words) -> bytes:
    return b"".join((w & 0xFFFF_FFFF).to_bytes(4, "little") for w in words)


def stream_golden(mode: str, op: str, key: list[int], data: list[int], iv) -> list[int]:
    """Streaming golden of a whole stream (CBC chains, CTR advances by one per block)."""
    if op == "enc":
        return aes_encrypt_words(mode, key, data, iv)
    if mode == "ecb":
        out: list[int] = []
        for i in range(0, len(data), 4):
            out += _le_words(aes_decrypt_block(_le_bytes(key), _le_bytes(data[i : i + 4])))
        return out
    assert mode == "cbc", "decrypt streams are ECB or CBC"
    return _le_words(aes_cbc_decrypt(_le_bytes(key), _le_bytes(iv), _le_bytes(data)))


@dataclass(frozen=True)
class StreamPlan:
    mode: str
    key_bits: int
    key_row: int
    op: str
    n: int
    in_gap: tuple[int, ...]
    out_gap: tuple[int, ...]
    stall: tuple[tuple[int, int], ...]  # (index, G factor)
    ctrl: tuple[tuple[int, int], ...]
    data: tuple[int, ...]

    @property
    def key(self) -> list[int]:
        return _le_words(KEY_ROWS[self.key_bits][self.key_row][1])

    @property
    def iv(self) -> list[int] | None:
        return None if self.mode == "ecb" else _le_words(IV_ROWS[self.mode])

    def block(self, i: int) -> list[int]:
        return list(self.data[4 * i : 4 * i + 4])

    def describe(self) -> str:
        return (
            f"{self.mode}:keylen={self.key_bits},row={KEY_ROWS[self.key_bits][self.key_row][0]},"
            f"op={self.op},n={self.n},stall={list(self.stall)},ctrl={list(self.ctrl)},"
            f"max_in_gap={max(self.in_gap)},max_out_gap={max(self.out_gap)}"
        )


@dataclass(frozen=True)
class Plan:
    seed: int
    streams: tuple[StreamPlan, ...]
    manual_factor: int
    auto_block: tuple[int, ...]
    manual_blocks: tuple[tuple[int, ...], tuple[int, ...]]
    hmac_msg: tuple[int, ...]
    ir_blocks: tuple[tuple[int, ...], ...]

    def describe(self) -> str:
        return (
            f"streams={' '.join(s.describe() for s in self.streams)} "
            f"manual_factor={self.manual_factor} auto_block={[hex(w) for w in self.auto_block]}"
        )


def _unique_words(rng: SepSeededRng, n: int, used: set[int]) -> list[int]:
    out: list[int] = []
    while len(out) < n:
        w = rng.getrandbits(32)
        if w and w not in used:
            used.add(w)
            out.append(w)
    return out


def _draw_pairs(rng: SepSeededRng, n: int, k: int) -> list[int]:
    """k pair indexes in 1..n-2 with no two pairs {i, i+1} overlapping."""
    while True:
        idx = sorted(rng.randrange(1, n - 1) for _ in range(k))
        if all(b - a >= 2 for a, b in zip(idx, idx[1:], strict=False)):
            return idx


def draw_plan(seed: int) -> Plan:
    """Every draw of the leaf, in a fixed order, with no simulator access."""
    rng = SepSeededRng(seed)
    used: set[int] = set()
    modes = ["ecb", "cbc", "ctr"]
    rng.shuffle(modes)
    streams = []
    for mode in modes:
        key_bits = rng.choice((128, 192, 256))
        key_row = rng.randrange(len(KEY_ROWS[key_bits]))
        op = rng.choice(("enc", "dec")) if mode != "ctr" else "enc"
        n = rng.randrange(34, 101)
        in_gap = tuple(rng.randrange(0, 41) for _ in range(n))
        out_gap = tuple(rng.randrange(0, 41) for _ in range(n))
        n_stall = rng.randrange(1, 3)
        n_ctrl = rng.randrange(1, 3)
        idx = _draw_pairs(rng, n, n_stall + n_ctrl)
        rng.shuffle(idx)
        g = [rng.randrange(2, 21) for _ in idx]
        stall = tuple(sorted(zip(idx[:n_stall], g[:n_stall], strict=True)))
        ctrl = tuple(sorted(zip(idx[n_stall:], g[n_stall:], strict=True)))
        data = tuple(_unique_words(rng, 4 * n, used))
        if mode == "ctr":
            low32 = int.from_bytes(IV_ROWS["ctr"][12:16], "big")
            assert low32 <= (1 << 32) - n, "CTR counter row would wrap its low 32 bits"
        streams.append(
            StreamPlan(mode, key_bits, key_row, op, n, in_gap, out_gap, stall, ctrl, data)
        )
    manual_factor = rng.randrange(2, 9)
    auto_block = tuple(_unique_words(rng, 4, used))
    manual_blocks = (tuple(_unique_words(rng, 4, used)), tuple(_unique_words(rng, 4, used)))
    hmac_msg = tuple(_unique_words(rng, 8, used))
    ir_blocks = tuple(tuple(_unique_words(rng, 4, used)) for _ in range(3))
    return Plan(seed, tuple(streams), manual_factor, auto_block, manual_blocks, hmac_msg, ir_blocks)


@pyuvm.test()
class sep_aes_stream_status_rand_test(sep_base_test):
    """AES streams, stall, START in automatic mode, manual overwrite, IDLE, no interrupt."""

    required_evidence = (
        "CHK-AES-STREAM",
        "CHK-AES-STALL",
        "CHK-AES-START-AUTO",
        "CHK-AES-LOST",
        "CHK-AES-IDLE",
        "CHK-AES-NOIRQ",
        "CHK-AES-INPUT-READY",
    )

    async def run_scenario(self) -> None:
        dut = cocotb.top
        await self.bring_up_no_cpu(park=("otbn", "kmac", "abr"))
        await self.bring_up_entropy(strict=True, score_km=False)
        self.start_fifo_drain()
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        self.logger.info("BASELINE sw_reset_n=0x%02x", self.swrst.value)

        seed = self.random_seed()
        plan = draw_plan(seed)
        self.logger.info("PLAN seed=%d %s", seed, plan.describe())
        self.plan = plan
        self.chk = SepChkLog(self, TEST, seed)
        self.aes = SepAes(self)
        self.hmac = SepHmac(self)
        self.bus = SepAxiRegDriver(self)
        # Clock count of the leaf: the clk of a watcher that samples every rising edge.
        self.clk = SepBitWatch(cocotb.top.rst_ni, {"rst_ni": 0}, name="clk_count").start()
        self.t_blk: int | None = None
        self.quiet = False
        self.idle_busy = 0
        self.idle_bad: list[str] = []

        # HMAC out of reset and idle, with hmac_done enabled for the control.
        hmac_st = await self.hmac._rd(HMAC.addr("STATUS"))
        self.chk.ctrl(
            "AES-NOIRQ-HMAC-IDLE", bool(hmac_st & HMAC_STATUS_IDLE), status=f"0x{hmac_st:x}"
        )
        await self.hmac._wr(HMAC.addr("INTR_ENABLE"), HMAC.field_mask("INTR_ENABLE", "hmac_done"))
        for name in INTR_ENABLE_OFF:
            await self.bus._wr(sep_addr_define(name), 0)

        s0 = self.rd_known(dut.sep_internal_interrupts_probe_o)
        vec = SepEdgeTimer(dut.sep_internal_interrupts_probe_o, name="vector").start()
        t0_ps = get_sim_time("ps")
        self.logger.info("S0 vector=0x%011x", s0)

        for s in plan.streams:
            await self._stream(s)
        close_graded_window(self.logger)
        await self._start_auto_leg()
        await self._manual_leg()
        await self._input_ready_leg()
        close_graded_window(self.logger)

        t1_ps = get_sim_time("ps")
        await vec.stop()
        changes, pool, xs = self._vector_changes(vec, s0, t0_ps, t1_ps)
        seen, why = await self._hmac_control()
        self.chk.ctrl("AES-NOIRQ", seen, ctrl_hmac_done_seen=int(seen), helper=why)
        self.chk.obs("POOL-VEC", bit36_changes=pool[0], bit37_changes=pool[1])
        self.chk.ok(
            "AES-NOIRQ",
            changes == 0 and xs == 0,
            vector_bits=N_VEC - len(POOL_BITS),
            vector_changes=changes,
            x_samples=xs,
            ctrl_hmac_done_seen=int(seen),
        )
        quiet = self.quiet
        self.chk.ctrl("AES-IDLE", quiet, ctrl_idle_after_quiet=int(quiet))
        self.chk.ok(
            "AES-IDLE",
            not self.idle_bad,
            idle_busy_samples=self.idle_busy,
            idle_busy=0 if not self.idle_bad else 1,
            bad=";".join(self.idle_bad[:6]) or "none",
            ctrl_idle_after_quiet=int(quiet),
        )

        await self.stop_fifo_drain()
        assert self.drbg_sb.report()
        await self.clk.stop()
        self.chk.finish()

    # --- bus and waits ---------------------------------------------------------
    async def _pulse_aes(self) -> None:
        """AES reset bit 0 then 1, then STATUS.IDLE; a timeout raises."""
        dut = cocotb.top
        await self.swrst.park("aes")
        for _ in range(WAIT_LIMIT):
            if self.rd(dut.aes_gated_rst_n_probe_o) == 0:
                break
            await RisingEdge(dut.clk_i)
        else:
            raise AssertionError("AES gated reset never asserted after SW_RESET_N park")
        await self.swrst.release("aes")
        ok, _ = await self._poll(ST_IDLE, ST_IDLE, WAIT_LIMIT)
        if not ok:
            raise AssertionError(f"AES STATUS.IDLE not 1 after the reset pulse bound={WAIT_LIMIT}")

    async def _poll(self, mask: int, want: int, bound: int) -> tuple[bool, list[tuple[int, int]]]:
        """Back-to-back STATUS reads until (STATUS & mask) == want or bound clocks pass."""
        return await poll_until(self._status, self._now, mask, want, bound)

    async def _wait(self, mask: int, want: int, bound: int, what: str) -> list[tuple[int, int]]:
        return await wait_until(self._status, self._now, mask, want, bound, what)

    async def _status(self) -> int:
        return await self.aes._rd(AES_STATUS)

    def _now(self) -> int:
        return self.clk.clk

    async def _sample(self, window: int) -> list[tuple[int, int]]:
        """Back-to-back STATUS reads for ``window`` clocks (at most ``window + 1`` reads)."""
        samples: list[tuple[int, int]] = []
        t0 = self.clk.clk
        for _ in range(window + 1):
            if self.clk.clk - t0 > window:
                break
            samples.append((self.clk.clk, await self.aes._rd(AES_STATUS)))
        return samples

    def _ov_bound(self) -> int:
        return WAIT_LIMIT if self.t_blk is None else OV_BOUND_FACTOR * self.t_blk

    async def _ctrl(self, value: int) -> None:
        await self.aes._wr(AES_CTRL_SHADOWED, value)
        await self.aes._wr(AES_CTRL_SHADOWED, value)

    async def _load(self, ctrl: int, key: list[int], iv: list[int] | None) -> None:
        await self._ctrl(ctrl)
        await self.aes.write_key(key)
        await self._wait(ST_IDLE, ST_IDLE, WAIT_LIMIT, "idle_after_key")
        if iv is not None:
            for i, w in enumerate(iv):
                await self.aes._wr(AES_IV_0 + 4 * i, w)
            await self._wait(ST_IDLE, ST_IDLE, WAIT_LIMIT, "idle_after_iv")
        await self.aes._wr(AES_TRIGGER, AES_TRIGGER_DATA_OUT_CLEAR)
        await self._wait(ST_IDLE, ST_IDLE, WAIT_LIMIT, "idle_after_clear")

    async def _write_block(self, words) -> None:
        for i, w in enumerate(words):
            await self.aes._wr(AES_DATA_IN_0 + 4 * i, w)

    async def _read_out(self) -> list[int]:
        return [await self.aes._rd(AES_DATA_OUT_0 + 4 * i) for i in range(4)]

    def _grade_idle(self, tag: str, samples: list[tuple[int, int]]) -> None:
        """IDLE = 0 from its first fall until the OUTPUT_VALID sample (that sample excluded)."""
        body = samples[:-1] if samples and samples[-1][1] & ST_OV else samples
        first = next((i for i, (_, st) in enumerate(body) if not st & ST_IDLE), None)
        if first is None:
            self.idle_bad.append(f"{tag}:never_dropped")
            return
        busy = body[first:]
        self.idle_busy += len(busy)
        high = [c for c, st in busy if st & ST_IDLE]
        if high:
            self.idle_bad.append(f"{tag}:idle_at_clk={high[0]}")

    async def _run_block(self, s: StreamPlan, i: int, *, read: bool) -> list[int] | None:
        """Gap, DATA_IN, back-to-back poll to OUTPUT_VALID; read after the output gap."""
        if s.in_gap[i] and i:
            await ClockCycles(cocotb.top.clk_i, s.in_gap[i])
        await self._write_block(s.block(i))
        t_resp = self.clk.clk
        samples = await self._wait(ST_OV, ST_OV, self._ov_bound(), f"output_valid.{s.mode}.b{i}")
        self._grade_idle(f"{s.mode}.b{i}", samples)
        if i == 0:
            t_blk = max(1, samples[-1][0] - t_resp)
            self.chk.obs("AES-TBLK", mode=s.mode, t_blk=t_blk)
            if self.t_blk is None:
                self.t_blk = t_blk
        if not read:
            return None
        if s.out_gap[i]:
            await ClockCycles(cocotb.top.clk_i, s.out_gap[i])
        return await self._read_out()

    # --- streams ------------------------------------------------------------------
    async def _stream(self, s: StreamPlan) -> None:
        await self._pulse_aes()
        golden = stream_golden(s.mode, s.op, s.key, list(s.data), s.iv)
        outs: list[list[int] | None] = [None] * s.n
        stall_at = dict(s.stall)
        ctrl_at = dict(s.ctrl)
        stall_res: list[dict] = []
        ctrl_res: list[dict] = []
        op = AES_OP_ENC if s.op == "enc" else AES_OP_DEC
        ctrl = build_aes_ctrl(
            sideload=False,
            operation=op,
            mode=AES_MODE_CTRL[s.mode],
            key_len=AES_KEYLEN_CTRL[s.key_bits],
        )
        reason = ""
        open_graded_window(TEST, self.logger)
        try:
            await self._load(ctrl, s.key, s.iv)
            i = 0
            while i < s.n:
                if i in stall_at:
                    g = stall_at[i] * (self.t_blk or 1)
                    await self._run_block(s, i, read=False)
                    await self._write_block(s.block(i + 1))
                    await ClockCycles(cocotb.top.clk_i, g)
                    st = await self.aes._rd(AES_STATUS)
                    outs[i] = await self._read_out()
                    await self._wait(
                        ST_STALL | ST_OV, ST_OV, self._ov_bound(), f"stall_release.b{i}"
                    )
                    outs[i + 1] = await self._read_out()
                    stall_res.append(
                        {
                            "block": i,
                            "gap_clk": g,
                            "stall": int(bool(st & ST_STALL)),
                            "idle": int(bool(st & ST_IDLE)),
                            "then_stall": 0,
                            "ct==golden": int(outs[i + 1] == golden[4 * (i + 1) : 4 * (i + 2)]),
                        }
                    )
                    i += 2
                elif i in ctrl_at:
                    g = ctrl_at[i] * (self.t_blk or 1)
                    outs[i] = await self._run_block(s, i, read=False)
                    outs[i] = await self._read_out()
                    await self._write_block(s.block(i + 1))
                    await ClockCycles(cocotb.top.clk_i, g)
                    st = await self.aes._rd(AES_STATUS)
                    await self._wait(ST_OV, ST_OV, self._ov_bound(), f"ctrl_pair.b{i + 1}")
                    outs[i + 1] = await self._read_out()
                    ctrl_res.append({"block": i, "gap_clk": g, "stall": int(bool(st & ST_STALL))})
                    i += 2
                else:
                    outs[i] = await self._run_block(s, i, read=True)
                    i += 1
        except TrialTimeout as exc:
            reason = f"timeout:{exc.what} bound={exc.bound}"
        close_graded_window(self.logger)

        mism = sum(1 for i in range(s.n) if outs[i] != golden[4 * i : 4 * i + 4])
        fields = {
            "mode": s.mode,
            "keylen": s.key_bits,
            "op": s.op,
            "blocks": s.n,
            "mismatches": mism,
            "max_in_gap": max(s.in_gap),
            "max_out_gap": max(s.out_gap),
        }
        if reason:
            fields["reason"] = reason
        self.chk.ok("AES-STREAM", not reason and mism == 0, **fields)

        ctrl_stall = int(any(r["stall"] for r in ctrl_res))
        for r in ctrl_res:
            self.chk.ctrl(
                "AES-STALL", r["stall"] == 0, mode=s.mode, block=r["block"], ctrl_stall=r["stall"]
            )
        if len(ctrl_res) != len(s.ctrl):
            self.chk.ctrl("AES-STALL", False, mode=s.mode, reason="control_pair_not_reached")
        for r in stall_res:
            ok = r["stall"] == 1 and r["idle"] == 0 and r["ct==golden"] == 1
            self.chk.ok("AES-STALL", ok, mode=s.mode, **r, ctrl_stall=ctrl_stall)
        if len(stall_res) != len(s.stall):
            self.chk.ok("AES-STALL", False, mode=s.mode, reason=reason or "stall_pair_not_reached")

    # --- automatic START ----------------------------------------------------------
    async def _start_auto_leg(self) -> None:
        key = _le_words(KEY_ROWS[256][0][1])
        blk = list(self.plan.auto_block)
        await self._pulse_aes()
        ctrl = build_aes_ctrl(sideload=False, mode=AES_MODE_ECB, key_len=AES_KEY_LEN_256)
        window = START_WINDOW_FACTOR * (self.t_blk or 1)
        samples: list[tuple[int, int]] = []
        reason = ""
        try:
            await self._load(ctrl, key, None)
            base = await self.aes._rd(AES_STATUS)
            base_ok = bool(base & ST_IDLE) and not base & ST_OV
            self.chk.ctrl("AES-START-AUTO-BASE", base_ok, status=f"0x{base:x}")
            open_graded_window(TEST, self.logger)
            await self.aes._wr(AES_TRIGGER, TRIG_START)
            samples = await self._sample(window)
            close_graded_window(self.logger)
        except TrialTimeout as exc:
            reason = f"timeout:{exc.what} bound={exc.bound}"
            close_graded_window(self.logger)
        bad = [st for _, st in samples if not st & ST_IDLE or st & ST_OV]
        ctrl_idle = -1
        try:
            await self._write_block(blk)
            await self._wait(ST_IDLE, 0, self._ov_bound(), "ctrl_idle_fall")
            ctrl_idle = 0
            await self._wait(ST_OV, ST_OV, self._ov_bound(), "ctrl_output_valid")
            ct = await self._read_out()
            ctrl_ok = ct == aes_encrypt_words("ecb", key, blk)
            # IDLE control: the quiet unit reads IDLE = 1 in a bounded wait.
            self.quiet, _ = await self._poll(ST_IDLE, ST_IDLE, self._ov_bound())
        except TrialTimeout:
            ctrl_ok = False
        self.chk.ctrl("AES-START-AUTO", ctrl_ok, ctrl_data_in_idle=ctrl_idle)
        fields = {
            "idle_samples": len(samples),
            "idle": 0 if bad else 1,
            "output_valid": 1 if any(st & ST_OV for st in bad) else 0,
            "window_clk": window,
            "ctrl_data_in_idle": ctrl_idle,
        }
        if reason:
            fields["reason"] = reason
        self.chk.ok("AES-START-AUTO", not reason and bool(samples) and not bad, **fields)

    # --- manual leg ---------------------------------------------------------------
    async def _manual_trial(self, *, read_between: bool) -> tuple[int, list[int] | None, int, int]:
        """Returns (OUTPUT_LOST after block 2, DATA_OUT after block 2, OUTPUT_LOST after the
        full DATA_OUT read, OUTPUT_LOST after the rewrite).

        aes.adoc:184: once set, OUTPUT_LOST "remains set until AES operation is restarted by
        re-writing the Control Register", so it reads 1 after the full DATA_OUT read and 0
        only after the rewrite. A DUT that clears it on the DATA_OUT read fails the check.
        """
        key = _le_words(KEY_ROWS[256][0][1])
        b1, b2 = (list(b) for b in self.plan.manual_blocks)
        ctrl = (
            build_aes_ctrl(sideload=False, mode=AES_MODE_ECB, key_len=AES_KEY_LEN_256) | CTRL_MANUAL
        )
        await self._load(ctrl, key, None)
        await self._write_block(b1)
        await self.aes._wr(AES_TRIGGER, TRIG_START)
        samples = await self._wait(ST_OV, ST_OV, self._ov_bound(), "manual_b1_output_valid")
        if not read_between:
            self._grade_idle("manual.b1", samples)
        else:
            await self._read_out()
        await self._write_block(b2)
        await self.aes._wr(AES_TRIGGER, TRIG_START)
        await ClockCycles(cocotb.top.clk_i, self.plan.manual_factor * (self.t_blk or 1))
        await self._wait(ST_IDLE, ST_IDLE, self._ov_bound(), "manual_b2_idle")
        lost = int(bool(await self.aes._rd(AES_STATUS) & ST_LOST))
        data = await self._read_out()
        lost_read = int(bool(await self.aes._rd(AES_STATUS) & ST_LOST))
        lost2 = -1
        if not read_between:
            await self._ctrl(ctrl)
            lost2 = int(bool(await self.aes._rd(AES_STATUS) & ST_LOST))
        return lost, data, lost_read, lost2

    async def _manual_leg(self) -> None:
        key = _le_words(KEY_ROWS[256][0][1])
        g2 = aes_encrypt_words("ecb", key, list(self.plan.manual_blocks[1]))
        await self._pulse_aes()
        reason = ""
        lost = lost_read = lost2 = -1
        data: list[int] | None = None
        open_graded_window(TEST, self.logger)
        try:
            lost, data, lost_read, lost2 = await self._manual_trial(read_between=False)
        except TrialTimeout as exc:
            reason = f"timeout:{exc.what} bound={exc.bound}"
        close_graded_window(self.logger)
        await self._pulse_aes()
        c_lost = -1
        c_data: list[int] | None = None
        try:
            c_lost, c_data, _, _ = await self._manual_trial(read_between=True)
        except TrialTimeout:
            c_lost = -1
        ctrl_ok = c_lost == 0 and c_data == g2
        self.chk.ctrl("AES-LOST", ctrl_ok, ctrl_reads_between=4, ctrl_output_lost=c_lost)
        fields = {
            "output_lost": lost,
            "data_out==block2": int(data == g2),
            "kept_after_read": int(lost_read == 1),
            "rewrite_clears": int(lost2 == 0),
            "ctrl_reads_between": 4,
            "ctrl_output_lost": c_lost,
            "wait_factor": self.plan.manual_factor,
        }
        if reason:
            fields["reason"] = reason
        self.chk.ok(
            "AES-LOST", lost == 1 and data == g2 and lost_read == 1 and lost2 == 0, **fields
        )

    # --- INPUT_READY around a held stall -----------------------------------------------
    async def _input_ready_leg(self) -> None:
        """Block 2 written while block 1 is stalled behind unread output 0.

        The stalled unit holds block 1 until output 0 is read, so block 2 cannot be
        loaded and INPUT_READY reads 0; the STALL bit of every read of the held window
        shows that the hold lasts. After the read the unit continues, loads block 2 and
        INPUT_READY reads 1.
        """
        key = _le_words(KEY_ROWS[256][0][1])
        blocks = [list(b) for b in self.plan.ir_blocks]
        gold = [aes_encrypt_words("ecb", key, b) for b in blocks]
        ctrl = build_aes_ctrl(sideload=False, mode=AES_MODE_ECB, key_len=AES_KEY_LEN_256)
        window = IR_WINDOW_FACTOR * (self.t_blk or 1)
        await self._pulse_aes()
        pre = -1
        held: list[tuple[int, int]] = []
        t_load = -1
        outs: list[list[int] | None] = [None, None, None]
        reason = ""
        open_graded_window(TEST, self.logger)
        try:
            await self._load(ctrl, key, None)
            await self._write_block(blocks[0])
            await self._wait(ST_OV, ST_OV, self._ov_bound(), "ir_b0_output_valid")
            await self._write_block(blocks[1])
            await self._wait(ST_STALL, ST_STALL, self._ov_bound(), "ir_b1_stall")
            pre = await self.aes._rd(AES_STATUS)
            await self._write_block(blocks[2])
            held = await self._sample(window)
            outs[0] = await self._read_out()
            t0 = self.clk.clk
            loaded = await self._wait(ST_IR, ST_IR, window, "ir_b2_load")
            t_load = loaded[-1][0] - t0
            # Output 1 moves to DATA_OUT in the cycle block 2 is loaded (programmers_guide.md:66).
            outs[1] = await self._read_out()
            await self._wait(ST_IDLE | ST_OV, ST_IDLE | ST_OV, self._ov_bound(), "ir_b2_done")
            outs[2] = await self._read_out()
        except TrialTimeout as exc:
            reason = f"timeout:{exc.what} bound={exc.bound}"
        close_graded_window(self.logger)
        pre_ok = pre >= 0 and bool(pre & ST_STALL) and int(bool(pre & ST_IR)) == EXP_LOADED_IR
        self.chk.ctrl(
            "AES-INPUT-READY",
            pre_ok,
            ctrl_stall=int(pre >= 0 and bool(pre & ST_STALL)),
            ctrl_input_ready=int(pre >= 0 and bool(pre & ST_IR)),
        )
        held_ir = sum(1 for _, st in held if int(bool(st & ST_IR)) != EXP_HELD_IR)
        held_unstalled = sum(1 for _, st in held if not st & ST_STALL)
        ct_ok = [int(o == g) for o, g in zip(outs, gold, strict=True)]
        fields = {
            "held_samples": len(held),
            "held_input_ready_bad": held_ir,
            "held_stall0": held_unstalled,
            "t_load_clk": t_load,
            "window_clk": window,
            "ct==golden": ct_ok,
            "ctrl_input_ready": int(pre >= 0 and bool(pre & ST_IR)),
        }
        if reason:
            fields["reason"] = reason
        ok = (
            not reason
            and bool(held)
            and held_ir == 0
            and held_unstalled == 0
            and 0 <= t_load <= window
            and all(ct_ok)
        )
        self.chk.ok("AES-INPUT-READY", ok, **fields)

    # --- vector and HMAC control ------------------------------------------------------
    @staticmethod
    def _vector_changes(vec: SepEdgeTimer, s0: int, t0: int, t1: int) -> tuple[int, list[int], int]:
        changes = 0
        xs = 0
        pool = [0, 0]
        prev = s0
        for c in vec.since(t0, until_ps=t1):
            if c.value is None:
                xs += 1
                continue
            if (c.value ^ prev) & VEC_MASK:
                changes += 1
            for k, b in enumerate(POOL_BITS):
                if ((c.value ^ prev) >> b) & 1:
                    pool[k] += 1
            prev = c.value
        return changes, pool, xs

    async def _hmac_control(self) -> tuple[bool, str]:
        """One plain SHA-256 with hmac_done enabled; vector bit 17 must rise.

        Returns (control seen, reason). A helper that raises (a bounded wait or
        its done write-one-clear check) makes the control absent, so the
        failure is recorded and not hidden.
        """
        watch = SepBitWatch(
            cocotb.top.sep_internal_interrupts_probe_o, {"hmac_done": HMAC_DONE_BIT}, name="vec17"
        ).start()
        await ClockCycles(cocotb.top.clk_i, 1)
        mark = watch.mark()
        reason = "-"
        try:
            await self.hmac.configure_sha256()
            await self.hmac.run_sha256(list(self.plan.hmac_msg))
        except AssertionError as exc:
            reason = str(exc)[:80]
        await ClockCycles(cocotb.top.clk_i, 1)
        seen = watch.rose_since(mark, "hmac_done")
        await watch.stop()
        return seen and reason == "-", reason
