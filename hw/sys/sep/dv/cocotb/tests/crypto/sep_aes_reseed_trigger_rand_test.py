# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The AES masking PRNG reseed rate, the reseed trigger and the clear triggers.

Contract (``vendor/lowRISC/opentitan/overlay/regs/aes/regs/gen/adoc/aes.adoc``,
CTRL_SHADOWED, TRIGGER; ``vendor/lowRISC/opentitan/upstream/hw/ip/aes/data/aes.hjson``,
PRNG_RESEED_RATE and TRIGGER.PRNG_RESEED):
  * PRNG_RESEED_RATE PER_1 reseeds once per block, PER_64 about once per 64
    blocks, PER_8K about once per 8192 blocks; 3'b000 and multi-hot values map
    to PER_1.
  * A TRIGGER write with PRNG_RESEED = 0 keeps the current PRNG states.
  * After TRIGGER.KEY_IV_DATA_IN_CLEAR the engine takes a new key, IV and
    plaintext and encrypts them.
  * Each block is the AES result of its key and plaintext at every rate
    (``hw/sys/sep/doc/aes.adoc``).

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense``,
``+esrc_noise_force``. The internal entropy source feeds ESRC, CSRNG and EDN.
HMAC, KMAC, OTBN and ABR stay in reset, so ``crypto_edn_ack_o[0]`` (the AES
client of EDN, approved probe) counts AES reseeds only. CTRL_AUX_SHADOWED keeps
its reset value for the whole leaf.

Randomization (``SepSeededRng`` from the run seed, drawn before the first
stimulus): the multi-hot invalid rate, the order of the five rate runs, the
block count N (129 to 300), the order of the two clear trials, the rate of the
trigger leg, the key row, the plaintexts and the reload key row of the key clear
(a different row). All five rate runs use the same
key and the same plaintexts, so only the rate differs between them.

Checkers:
  CHK-AES-RESEED-RATE     count(PER_1) > count(PER_64) > count(PER_8K) over N blocks
                          (rises of ``crypto_edn_ack_o[0]``).
  CHK-AES-RESEED-INVALID  3'b000 and the multi-hot value each map to PER_1
                          (aes.adoc:109): each count equals count(PER_1) of the
                          same key and plaintexts. Control: each count is above
                          count(PER_64).
  CHK-AES-RESEED-TRIG     no acknowledge in 4 x t_r clocks after a TRIGGER write
                          of 0 on an idle unit. Control: a PRNG_RESEED write is
                          acknowledged in a window of the same length.
  CHK-AES-IDLE-RESEED     STATUS.IDLE reads 0 on a sample between the
                          PRNG_RESEED write and the return to idle. Control:
                          STATUS.IDLE reads 1 before that write. A register
                          clear returns to idle before the STATUS read that
                          follows the trigger write, so that clause of the
                          same sentence is not a sample.
  CHK-AES-CLEAR-KEY       after KEY_IV_DATA_IN_CLEAR and a reload of a key row
                          that differs from the key loaded before the clear,
                          the ciphertext equals the golden of the reloaded key.
                          Control: the IV read before the clear equals the
                          written IV.
  CHK-AES-RATE-CT         every block of the five rate runs equals the golden.
DATA_OUT after DATA_OUT_CLEAR has no exact form: ``aes.hjson``:909-913 states only
"clear those registers with pseudo-random data", and no value, status bit or
read effect. A check that the value differs from the output before the clear
fails a healthy DUT with probability 2^-128 and passes a partial clear, so it is
not a check. The leaf logs ``OBS-BLOCKED CHK-AES-CLEAR-OUT`` and
``OBS-AES-CLEAR-OUT`` and grades nothing there. The IV after the clear is logged
as ``OBS-AES-CLEAR-IV``.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from env.sep_aes_golden import aes_encrypt_words
from env.sep_bit_watch import BitWatchTimeout, SepBitWatch
from env.sep_chk_log import SepChkLog
from env.sep_crypto_kat_rows import AES_KEY_ROWS, KMAC_SAMPLE_KEY_ROW, SP800_38A_CBC_IV
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_seeded_rng import SepSeededRng
from env.sep_trial_wait import TrialTimeout, poll_until, wait_until
from sep_base_test import sep_base_test
from sep_reg_meta import AES
from seq_lib.sep_aes_seq import (
    AES_CTRL_SHADOWED,
    AES_DATA_IN_0,
    AES_DATA_OUT_0,
    AES_IV_0,
    AES_KEY_LEN_256,
    AES_MODE_ECB,
    AES_OP_ENC,
    AES_PRS_RATE_PER_1,
    AES_PRS_RATE_PER_8K,
    AES_PRS_RATE_PER_64,
    AES_STATUS,
    AES_TRIGGER,
    AES_TRIGGER_DATA_OUT_CLEAR,
    AES_TRIGGER_PRNG_RESEED,
    SepAes,
    build_aes_ctrl,
)

TEST = "sep_aes_reseed_trigger_rand_test"

# PRNG_RESEED_RATE codes: the aes.hjson CTRL_SHADOWED.PRNG_RESEED_RATE enum, exported by
# seq_lib/sep_aes_seq.py.
PER_1, PER_64, PER_8K = AES_PRS_RATE_PER_1, AES_PRS_RATE_PER_64, AES_PRS_RATE_PER_8K
RATE_MULTI = (0b011, 0b101, 0b110, 0b111)
RUNS = ("per1", "per64", "per8k", "zero", "multi")
LEGAL_RATE = {"per1": PER_1, "per64": PER_64, "per8k": PER_8K}

# Published 256-bit test constants (env/sep_crypto_kat_rows.py). The seed picks a row,
# never the bytes.
KEY_ROWS = AES_KEY_ROWS[256] + (KMAC_SAMPLE_KEY_ROW,)
IV_ROW = SP800_38A_CBC_IV

ST_IDLE = AES.field_mask("STATUS", "idle")
ST_OV = AES.field_mask("STATUS", "output_valid")
TRIG_KEY_IV_CLEAR = AES.field_mask("TRIGGER", "key_iv_data_in_clear")
PRNG_RATE_LSB = AES.field_lsb("CTRL_SHADOWED", "prng_reseed_rate")
PRNG_RATE_MASK = AES.field_mask("CTRL_SHADOWED", "prng_reseed_rate")

WAIT_LIMIT = 20_000  # outer limit of a wait that has no clean time yet (logged as bound=)
OV_BOUND_FACTOR = 256  # bounded OUTPUT_VALID wait = 256 x t_blk
TRIG_WINDOW_FACTOR = 4  # 4 x t_r (test parameter)
CLEAR_WAIT_FACTOR = 4  # 4 x t_blk (test parameter)


def _le_words(data: bytes) -> list[int]:
    return [int.from_bytes(data[i : i + 4], "little") for i in range(0, len(data), 4)]


@dataclass(frozen=True)
class Plan:
    seed: int
    multi: int
    order: tuple[str, ...]
    n_blocks: int
    clear_order: tuple[str, ...]
    trig_rate: str
    key_row: int
    pts: tuple[tuple[int, ...], ...]
    p_clear: tuple[int, ...]
    reload_row: int

    @property
    def key(self) -> list[int]:
        return _le_words(KEY_ROWS[self.key_row][1])

    @property
    def reload_key(self) -> list[int]:
        return _le_words(KEY_ROWS[self.reload_row][1])

    def rate_value(self, run: str) -> int:
        if run == "zero":
            return 0
        if run == "multi":
            return self.multi
        return LEGAL_RATE[run]

    def describe(self) -> str:
        return (
            f"multi=0b{self.multi:03b} order={','.join(self.order)} n={self.n_blocks} "
            f"clear_order={','.join(self.clear_order)} trig_rate={self.trig_rate} "
            f"key_row={KEY_ROWS[self.key_row][0]} pt0={[hex(w) for w in self.pts[0]]} "
            f"p_clear={[hex(w) for w in self.p_clear]} "
            f"reload_row={KEY_ROWS[self.reload_row][0]}"
        )


def _unique_words(rng: SepSeededRng, n: int, used: set[int]) -> list[int]:
    out: list[int] = []
    while len(out) < n:
        w = rng.getrandbits(32)
        if w and w not in used:
            used.add(w)
            out.append(w)
    return out


def draw_plan(seed: int) -> Plan:
    """Every draw of the leaf, in a fixed order, with no simulator access."""
    rng = SepSeededRng(seed)
    multi = rng.choice(RATE_MULTI)
    order = list(RUNS)
    rng.shuffle(order)
    n_blocks = rng.randrange(129, 301)
    clear_order = ["out", "key"]
    rng.shuffle(clear_order)
    trig_rate = rng.choice(tuple(LEGAL_RATE))
    key_row = rng.randrange(len(KEY_ROWS))
    used: set[int] = set()
    words = _unique_words(rng, 4 * n_blocks, used)
    pts = tuple(tuple(words[4 * i : 4 * i + 4]) for i in range(n_blocks))
    p_clear = tuple(_unique_words(rng, 4, used))
    reload_row = rng.choice(
        [i for i in range(len(KEY_ROWS)) if KEY_ROWS[i][1] != KEY_ROWS[key_row][1]]
    )
    return Plan(
        seed,
        multi,
        tuple(order),
        n_blocks,
        tuple(clear_order),
        trig_rate,
        key_row,
        pts,
        p_clear,
        reload_row,
    )


@pyuvm.test()
class sep_aes_reseed_trigger_rand_test(sep_base_test):
    """Reseed-rate order, invalid-rate mapping, the zero trigger and the key clear."""

    required_evidence = (
        "CHK-AES-RESEED-RATE",
        "CHK-AES-RESEED-INVALID",
        "CHK-AES-RESEED-TRIG",
        "CHK-AES-IDLE-RESEED",
        "CHK-AES-CLEAR-KEY",
        "CHK-AES-RATE-CT",
    )

    async def run_scenario(self) -> None:
        dut = cocotb.top
        await self.bring_up_no_cpu(park=("otbn", "hmac", "kmac", "abr"))
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
        # Clock count of the leaf: the clk of a watcher that samples every rising edge.
        self.clk = SepBitWatch(cocotb.top.rst_ni, {"rst_ni": 0}, name="clk_count").start()
        self.ack = SepBitWatch(dut.crypto_edn_ack_o, {"aes": 0}, name="crypto_edn_ack_o").start()
        self.t_blk: int | None = None

        counts: dict[str, int | None] = {}
        mismatches = 0
        bad_runs: list[str] = []
        for run in plan.order:
            count, bad = await self._rate_run(run)
            counts[run] = count
            mismatches += bad
            if bad or count is None:
                bad_runs.append(run)
        close_graded_window(self.logger)
        self._grade_rates(counts)
        self.chk.ok(
            "AES-RATE-CT",
            mismatches == 0 and not bad_runs,
            blocks=len(RUNS) * plan.n_blocks,
            mismatches=mismatches,
            bad_runs=",".join(bad_runs) or "none",
        )

        await self._trigger_leg()
        for trial in plan.clear_order:
            if trial == "out":
                await self._clear_out_trial()
            else:
                await self._clear_key_trial()
        close_graded_window(self.logger)

        self.chk.blocked(
            "CHK-AES-CLEAR-OUT", "no exact form: aes.hjson:909-913 states pseudo-random data only"
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

    def _ov_bound(self) -> int:
        return WAIT_LIMIT if self.t_blk is None else OV_BOUND_FACTOR * self.t_blk

    def _ctrl_word(self, rate: int) -> int:
        word = build_aes_ctrl(
            sideload=False, operation=AES_OP_ENC, mode=AES_MODE_ECB, key_len=AES_KEY_LEN_256
        )
        return (word & ~PRNG_RATE_MASK) | ((rate << PRNG_RATE_LSB) & PRNG_RATE_MASK)

    async def _ctrl(self, value: int) -> None:
        await self.aes._wr(AES_CTRL_SHADOWED, value)
        await self.aes._wr(AES_CTRL_SHADOWED, value)

    async def _key_and_clear(self) -> None:
        await self.aes.write_key(self.plan.key)
        await self._wait(ST_IDLE, ST_IDLE, WAIT_LIMIT, "idle_after_key")
        await self.aes._wr(AES_TRIGGER, AES_TRIGGER_DATA_OUT_CLEAR)
        await self._wait(ST_IDLE, ST_IDLE, WAIT_LIMIT, "idle_after_clear")

    async def _write_block(self, words) -> None:
        for i, w in enumerate(words):
            await self.aes._wr(AES_DATA_IN_0 + 4 * i, w)

    async def _read_out(self) -> list[int]:
        return [await self.aes._rd(AES_DATA_OUT_0 + 4 * i) for i in range(4)]

    async def _read_iv(self) -> list[int]:
        return [await self.aes._rd(AES_IV_0 + 4 * i) for i in range(4)]

    async def _write_iv(self, iv: list[int]) -> None:
        for i, w in enumerate(iv):
            await self.aes._wr(AES_IV_0 + 4 * i, w)

    # --- rate runs --------------------------------------------------------------
    async def _rate_run(self, run: str) -> tuple[int | None, int]:
        """One rate run of N blocks. Returns (ack rise count or None, bad block count)."""
        plan = self.plan
        key = plan.key
        await self._pulse_aes()
        value = plan.rate_value(run)
        open_graded_window(TEST, self.logger)
        bad = 0
        try:
            await self._ctrl(self._ctrl_word(value))
            mark = self.ack.mark()
            await self._key_and_clear()
            for b, pt in enumerate(plan.pts):
                await self._write_block(pt)
                t_resp = self.clk.clk
                samples = await self._wait(ST_OV, ST_OV, self._ov_bound(), f"output_valid.b{b}")
                if self.t_blk is None:
                    self.t_blk = max(1, samples[-1][0] - t_resp)
                    self.logger.info("t_blk=%d clk_i (run=%s block 0)", self.t_blk, run)
                ct = await self._read_out()
                if ct != aes_encrypt_words("ecb", key, list(pt)):
                    bad += 1
            await self._wait(ST_IDLE, ST_IDLE, WAIT_LIMIT, "idle_after_run")
        except TrialTimeout as exc:
            close_graded_window(self.logger)
            self.logger.info("rate run %s stopped: timeout %s bound=%d", run, exc.what, exc.bound)
            return None, bad + 1
        count = self.ack.rises_since(mark, "aes")
        close_graded_window(self.logger)
        self.chk.obs("AES-RATE-RUN", run=run, value=f"0b{value:03b}", acks=count, mismatches=bad)
        return count, bad

    def _grade_rates(self, c: dict[str, int | None]) -> None:
        a, b, d = c.get("per1"), c.get("per64"), c.get("per8k")
        known = None not in (a, b, d)
        ordered = bool(known and a > b > d)
        self.chk.ok(
            "AES-RESEED-RATE",
            ordered,
            n=self.plan.n_blocks,
            c_per1=a,
            c_per64=b,
            c_per8k=d,
            order="a>b>c" if ordered else "broken",
        )
        for run in ("zero", "multi"):
            v = c.get(run)
            # aes.adoc:109: 3'b000 and multi-hot values map to PER_1. The five runs share
            # key and plaintexts, so a mapped run gives the count of the PER_1 run.
            self.chk.ctrl(
                "AES-RESEED-INVALID",
                v is not None and b is not None and v > b,
                run=run,
                c=v,
                c_per64=b,
            )
            self.chk.ok(
                "AES-RESEED-INVALID",
                v is not None and a is not None and v == a,
                value=f"0b{self.plan.rate_value(run):03b}",
                c=v,
                c_per1=a,
                c_per64=b,
            )

    # --- trigger leg ------------------------------------------------------------
    async def _trigger_leg(self) -> None:
        plan = self.plan
        await self._pulse_aes()
        t_r = None
        acks0 = None
        ctrl_acks = None
        reason = ""
        idle_reason = ""
        idle_before = False
        busy = 0
        n_status = 0
        try:
            await self._ctrl(self._ctrl_word(LEGAL_RATE[plan.trig_rate]))
            await self.aes.write_key(plan.key)
            await self._wait(ST_IDLE, ST_IDLE, WAIT_LIMIT, "idle_after_key")
            pre = await self.aes._rd(AES_STATUS)
            idle_before = bool(pre & ST_IDLE)
            m = self.ack.mark()
            open_graded_window(TEST, self.logger)
            await self.aes._wr(AES_TRIGGER, AES_TRIGGER_PRNG_RESEED)
            t_resp = self.ack.clk
            samples = await self._wait(ST_IDLE, ST_IDLE, WAIT_LIMIT, "idle_after_reseed")
            close_graded_window(self.logger)
            n_status = len(samples)
            busy = sum(1 for _, st in samples[:-1] if not (st & ST_IDLE))
            rises = self.ack.rise_clks_since(m, "aes")
            if rises:
                t_r = max(1, rises[0] - t_resp)
            else:
                reason = "timeout:aes ack did not rise before STATUS.IDLE returned"
        except (TrialTimeout, BitWatchTimeout) as exc:
            close_graded_window(self.logger)
            idle_reason = f"timeout:{exc} bound={WAIT_LIMIT}"
            reason = idle_reason
        self.chk.ctrl("AES-IDLE-RESEED", idle_before, status_idle_before=int(idle_before))
        idle_fields = {
            "busy_samples": busy,
            "status_reads": n_status,
            "status_idle_before": int(idle_before),
        }
        if idle_reason:
            idle_fields["reason"] = idle_reason
        self.chk.ok("AES-IDLE-RESEED", not idle_reason and idle_before and busy >= 1, **idle_fields)
        if t_r is not None:
            try:
                window = TRIG_WINDOW_FACTOR * t_r
                open_graded_window(TEST, self.logger)
                m0 = self.ack.mark()
                await self.aes._wr(AES_TRIGGER, 0)
                await ClockCycles(cocotb.top.clk_i, window)
                acks0 = self.ack.rises_since(m0, "aes")
                close_graded_window(self.logger)
                m1 = self.ack.mark()
                await self.aes._wr(AES_TRIGGER, AES_TRIGGER_PRNG_RESEED)
                await ClockCycles(cocotb.top.clk_i, window)
                ctrl_acks = self.ack.rises_since(m1, "aes")
                await self._wait(ST_IDLE, ST_IDLE, WAIT_LIMIT, "idle_after_ctrl_reseed")
            except (TrialTimeout, BitWatchTimeout) as exc:
                close_graded_window(self.logger)
                reason = f"timeout:{exc} bound={WAIT_LIMIT}"
        window = TRIG_WINDOW_FACTOR * t_r if t_r else 0
        self.chk.ctrl("AES-RESEED-TRIG", bool(ctrl_acks), ctrl_acks_after_write=ctrl_acks)
        fields = {
            "window_clk": window,
            "acks_after_zero_write": acks0,
            "ctrl_acks_after_write": ctrl_acks,
            "t_r_clk": t_r,
            "rate": plan.trig_rate,
        }
        if reason:
            fields["reason"] = reason
        self.chk.ok("AES-RESEED-TRIG", not reason and acks0 == 0, **fields)

    # --- clear trials -------------------------------------------------------------
    async def _clear_out_trial(self) -> None:
        """DATA_OUT_CLEAR: values logged only (aes.hjson:909-913 gives no exact form)."""
        plan = self.plan
        await self._pulse_aes()
        try:
            await self._ctrl(self._ctrl_word(PER_1))
            await self._key_and_clear()
            await self._write_block(plan.p_clear)
            await self._wait(ST_OV, ST_OV, self._ov_bound(), "clear_out_output_valid")
            o0 = await self._read_out()
            o0b = await self._read_out()
            await self._wait(ST_IDLE, ST_IDLE, WAIT_LIMIT, "clear_out_idle")
            await self.aes._wr(AES_TRIGGER, AES_TRIGGER_DATA_OUT_CLEAR)
            await ClockCycles(cocotb.top.clk_i, CLEAR_WAIT_FACTOR * (self.t_blk or 1))
            await self._wait(ST_IDLE, ST_IDLE, WAIT_LIMIT, "clear_out_idle_after")
            after = await self._read_out()
        except TrialTimeout as exc:
            self.chk.obs("AES-CLEAR-OUT", reason=f"timeout:{exc.what}", bound=exc.bound)
            return
        self.chk.obs(
            "AES-CLEAR-OUT",
            before="0x" + "".join(f"{w:08x}" for w in reversed(o0)),
            after="0x" + "".join(f"{w:08x}" for w in reversed(after)),
            ctrl_reads_equal=int(o0 == o0b),
        )

    async def _clear_key_trial(self) -> None:
        plan = self.plan
        key = plan.key
        reload_key = plan.reload_key
        iv = _le_words(IV_ROW)
        # The golden of the reloaded key differs from that of the key before the clear, so
        # a DUT that keeps the old key fails the compare.
        golden = aes_encrypt_words("ecb", reload_key, list(plan.p_clear))
        assert golden != aes_encrypt_words("ecb", key, list(plan.p_clear)), "reload key golden"
        await self._pulse_aes()
        open_graded_window(TEST, self.logger)
        iv_before: list[int] | None = None
        iv_after: list[int] | None = None
        ct: list[int] | None = None
        reason = ""
        try:
            await self._ctrl(self._ctrl_word(PER_1))
            await self.aes.write_key(key)
            await self._wait(ST_IDLE, ST_IDLE, WAIT_LIMIT, "idle_after_key")
            await self._write_iv(iv)
            iv_before = await self._read_iv()
            await self.aes._wr(AES_TRIGGER, TRIG_KEY_IV_CLEAR)
            await ClockCycles(cocotb.top.clk_i, CLEAR_WAIT_FACTOR * (self.t_blk or 1))
            await self._wait(ST_IDLE, ST_IDLE, WAIT_LIMIT, "idle_after_key_iv_clear")
            iv_after = await self._read_iv()
            await self.aes.write_key(reload_key)
            await self._wait(ST_IDLE, ST_IDLE, WAIT_LIMIT, "idle_after_reload")
            await self._write_iv(iv)
            await self.aes._wr(AES_TRIGGER, AES_TRIGGER_DATA_OUT_CLEAR)
            await self._wait(ST_IDLE, ST_IDLE, WAIT_LIMIT, "idle_after_clear")
            await self._write_block(plan.p_clear)
            await self._wait(ST_OV, ST_OV, self._ov_bound(), "reload_output_valid")
            ct = await self._read_out()
        except TrialTimeout as exc:
            reason = f"timeout:{exc.what} bound={exc.bound}"
        close_graded_window(self.logger)
        iv_ok = iv_before == iv
        self.chk.ctrl("AES-CLEAR-KEY", iv_ok, ctrl_iv_read_equal=int(iv_ok))
        self.chk.obs(
            "AES-CLEAR-IV",
            iv_before="0x" + "".join(f"{w:08x}" for w in reversed(iv_before or [])),
            iv_after="0x" + "".join(f"{w:08x}" for w in reversed(iv_after or [])),
        )
        fields = {
            "reload_ct==golden": int(ct == golden),
            "ctrl_iv_read_equal": int(iv_ok),
            "key_row": KEY_ROWS[plan.key_row][0],
            "reload_row": KEY_ROWS[plan.reload_row][0],
        }
        if reason:
            fields["reason"] = reason
        self.chk.ok("AES-CLEAR-KEY", ct == golden, **fields)
