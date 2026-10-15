# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""KMAC entropy modes: software seeding, the mode lock, the EDN wait timer, the hash counter and the counter reseed.

Contract (``vendor/lowRISC/opentitan/overlay/regs/kmac/regs/gen/adoc/kmac.adoc``,
``CFG_SHADOWED``, ``CMD``, ``ENTROPY_PERIOD``, ``ENTROPY_REFRESH_HASH_CNT``,
``ENTROPY_REFRESH_THRESHOLD_SHADOWED``, ``ENTROPY_SEED``;
``vendor/lowRISC/opentitan/upstream/hw/ip/kmac/data/kmac.hjson`` for the mode
codes, the six-word seed gate and the counter reseed):

* ``entropy_mode`` is idle (0) after a KMAC reset. After ``entropy_ready`` the
  PRNG configuration is fixed, and a later write changes only the readback.
* In sw mode KMAC processes commands only after six ``ENTROPY_SEED`` writes.
* In EDN mode ``ENTROPY_PERIOD.wait_timer`` bounds the wait for EDN; expiry
  gives ``kmac_err``; 0 waits for ever. The prescaler sets the timer pulse period.
* ``ENTROPY_REFRESH_HASH_CNT`` counts keyed hashes; ``CMD.hash_cnt_clr`` and
  ``CMD.entropy_req`` clear it, and ``entropy_req`` reseeds from EDN.
* With a threshold R the module reseeds from EDN when the counter reaches R;
  with 0 the counter reseed is off.

Legs: a six-seed leg first (gives t_ctrl, the clean start time), then in drawn
order: seed count (5 and 0 words), mode lock (sw first and edn first), timer
(prescaler 0 and P, wait timers T, 2T, 8, then 0), counter (N hashes,
``hash_cnt_clr``, ``entropy_req``) and reseed (threshold R, then 0 on the same
KMAC). "Chain up" is the state after the ESRC, CSRNG and EDN bring-up. "Chain
uninitialized" is the state after a TRNG reset with no bring-up after it: EDN
does not answer, which is the starvation of the timer leg.

Checkers:
  CHK-KMAC-SWSEED          six seeds -> absorb in bound; SHA3-256 == golden.
  CHK-KMAC-MODE-LOCK       reset mode 0; a late write changes only the readback;
                           with EDN locked, the late write to sw leaves the
                           module in EDN mode: after the hash, ``CMD.entropy_req``
                           gives >= 1 acknowledge on ``crypto_edn_ack_o[1]``
                           (kmac.adoc ``CFG_SHADOWED``:142, ``CMD``:199), and
                           the same window with no command gives none.
  CHK-KMAC-TIMER           kmac_err (INTR_STATE bit and PIC vector bit 22),
                           no acknowledge; error time T < 2T per prescaler and
                           P > 0 per wait timer. ``CTRL-KMAC-TIMER-PRESTATE``
                           reads kmac_err 0 and ERR_CODE at its reset value 0
                           before each run. The register text does not state an
                           ERR_CODE value for the timer expiry, so the code is
                           logged as ``OBS-KMAC-TIMER-ERRCODE`` and not graded.
  CHK-KMAC-TIMER0          wait timer 0 -> no kmac_err, ERR_CODE 0, request pending.
  CHK-KMAC-HASHCNT         counter 1..N, 0 after hash_cnt_clr, 1, 0 after
                           entropy_req, which adds an acknowledge.
  CHK-KMAC-AUTORESEED      threshold R, M hashes -> acknowledge >= 1, counter < M.
  CHK-KMAC-AUTORESEED-OFF  threshold 0, M hashes -> no acknowledge, counter == M.

Log-only (``OBS-BLOCKED``): CHK-KMAC-SWSEED-NEG (five or zero seeds -> no
absorb) and the absorb part of the sw-locked CHK-KMAC-MODE-LOCK leg. The
seed gate text (``kmac.hjson`` ``ENTROPY_SEED``: "Only after that, the module
can start processing commands") does not state whether a start before six
seeds is refused or only gives no digest, and the register text SEP uses
(``kmac.adoc`` ``ENTROPY_SEED``) does not carry it. These legs log the
observed absorb, the seed count and ``kmac_err`` as ``OBS`` lines.

Observables: KMAC register readback over the CPU-LSU master,
``crypto_edn_req_o[1]`` and ``crypto_edn_ack_o[1]`` (client 1 is KMAC,
``hw/sys/sep/doc/trng.adoc`` sink paths), and vector bit 22 of
``sep_internal_interrupts_probe_o`` (PIC source 23, KMAC error,
``hw/sys/sep/doc/interrupts.adoc``). Only the order of the error times is
graded: the exact timer pulse period is not stated.

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense +esrc_noise_force``.
RANDCFG.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_bit_watch import BitWatchTimeout, SepBitWatch
from env.sep_chk_log import SepChkLog
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_kmac_golden import right_encode, sha3
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import KMAC
from seq_lib.sep_kmac_seq import (
    KMAC_CMD,
    KMAC_CMD_DONE,
    KMAC_CMD_PROCESS,
    KMAC_CMD_START,
    KMAC_DIGEST_WORDS,
    KMAC_ERR_CODE,
    KMAC_INTR_KMAC_ERR,
    KMAC_INTR_STATE,
    KMAC_KEY_LEN,
    KMAC_KEY_LEN_256,
    KMAC_KEY_SHARE0_0,
    KMAC_KEY_SHARE1_0,
    KMAC_KEYED_OUT_BITS,
    KMAC_KEYED_PREFIX,
    KMAC_MODE,
    KMAC_STATE_S0,
    KMAC_STATE_S1,
    KMAC_STATUS,
    KMAC_STRENGTH,
    SepKmac,
)

TEST = "sep_kmac_entropy_mode_rand_test"

KMAC_CFG = KMAC.addr("CFG_SHADOWED")
KMAC_INTR_ENABLE = KMAC.addr("INTR_ENABLE")
KMAC_ENTROPY_PERIOD = KMAC.addr("ENTROPY_PERIOD")
KMAC_HASH_CNT = KMAC.addr("ENTROPY_REFRESH_HASH_CNT")
KMAC_THRESHOLD = KMAC.addr("ENTROPY_REFRESH_THRESHOLD_SHADOWED")
KMAC_ENTROPY_SEED = KMAC.addr("ENTROPY_SEED")

ST_IDLE = KMAC.field_mask("STATUS", "sha3_idle")
ST_ABSORB = KMAC.field_mask("STATUS", "sha3_absorb")
ST_SQUEEZE = KMAC.field_mask("STATUS", "sha3_squeeze")
CFG_MODE_MASK = KMAC.field_mask("CFG_SHADOWED", "entropy_mode")
CFG_MODE_LSB = KMAC.field_lsb("CFG_SHADOWED", "entropy_mode")
CFG_READY = KMAC.field_mask("CFG_SHADOWED", "entropy_ready")
CMD_ENTROPY_REQ = KMAC.field_mask("CMD", "entropy_req")
CMD_HASH_CNT_CLR = KMAC.field_mask("CMD", "hash_cnt_clr")
HASH_CNT_MASK = KMAC.field_mask("ENTROPY_REFRESH_HASH_CNT", "hash_cnt")
ERR_CODE_MASK = KMAC.field_mask("ERR_CODE", "err_code")
PERIOD_PRESCALER_LSB = KMAC.field_lsb("ENTROPY_PERIOD", "prescaler")
PERIOD_WAIT_LSB = KMAC.field_lsb("ENTROPY_PERIOD", "wait_timer")

# CFG_SHADOWED.entropy_mode enum (kmac.hjson:511 idle_mode, :522 edn_mode, :544 sw_mode).
ENTROPY_MODE = {"idle": 0, "edn": 1, "sw": 2}

# Vector bit of the KMAC error line: PIC source 23 (interrupts.adoc, KMAC error
# row) at vector index 22 (interrupts.adoc, Sources and Routing: bit i is
# source i + 1).
VEC_KMAC_ERR = 22
# Native crypto EDN client 1 is KMAC (trng.adoc, SEP entropy sink paths).
EDN_CLIENT_KMAC = 1

# Test data rows: published constants only; the seed picks the row.
# SHA3-256 message rows: the SP 800-185 sample data strings and FIPS 202 "abc".
MSG_ROWS: tuple[bytes, ...] = (bytes.fromhex("00010203"), bytes(range(200)), b"abc")
# KMAC key row: the SP 800-185 KMAC sample key 0x40..0x5F.
KEY_ROWS: tuple[bytes, ...] = (bytes(range(0x40, 0x60)),)
# Six ENTROPY_SEED words: the SHA-256 initial hash words H0..H5 of FIPS 180-4.
SEED_ROW: tuple[int, ...] = (
    0x6A09E667,
    0xBB67AE85,
    0x3C6EF372,
    0xA54FF53A,
    0x510E527F,
    0x9B05688C,
)

# Leaf-fixed window multiples and outer wait limits (environment choices, logged).
WIN_MULT = 4  # negative windows: WIN_MULT x the clean reference time
WIN_FLOOR = 64  # clocks; floor of a window built from a short reference
POLL_EVERY = 4  # clocks between STATUS polls
BOUND_CLK = 60_000  # outer limit of a start, squeeze, idle, seeding or request wait
LEGS = ("seed_count", "mode_lock", "timer", "counter", "reseed")
# The seed gate does not state whether a start before six seeds is refused.
SEED_GATE_BLOCKED = "sw_start_before_six_seeds_not_stated"


@dataclass(frozen=True)
class Plan:
    legs: tuple[str, ...]
    seed_counts: tuple[int, ...]
    lock_order: tuple[str, ...]
    late_sw: str
    prescaler_order: tuple[str, ...]
    t: int
    p: int
    n: int
    r: int
    m: int
    msg_row: int
    key_row: int

    def line(self, seed: int) -> str:
        return (
            f"PLAN seed={seed} legs={','.join(self.legs)} seed_counts="
            f"{','.join(map(str, self.seed_counts))} lock_order={','.join(self.lock_order)} "
            f"late_when_sw={self.late_sw} late_when_edn=sw prescaler_order="
            f"{','.join(self.prescaler_order)} T={self.t} P={self.p} N={self.n} R={self.r} "
            f"M={self.m} msg_row={self.msg_row} key_row={self.key_row}"
        )


def draw_plan(seed: int) -> Plan:
    """Every draw of the leaf, in a fixed order, with no simulator access."""
    rng = SepSeededRng(seed)
    legs = list(LEGS)
    rng.shuffle(legs)
    counts = [5, 0]
    rng.shuffle(counts)
    locks = ["sw", "edn"]
    rng.shuffle(locks)
    late_sw = rng.choice(("edn", "idle"))
    pres = ["p0", "p"]
    rng.shuffle(pres)
    t = rng.randrange(2, 5)
    p = rng.randrange(2, 16)
    n = rng.randrange(2, 11)
    r = rng.randrange(2, 5)
    m = rng.randrange(r + 2, 13)
    msg_row = rng.randrange(len(MSG_ROWS))
    key_row = rng.randrange(len(KEY_ROWS))
    return Plan(
        tuple(legs),
        tuple(counts),
        tuple(locks),
        late_sw,
        tuple(pres),
        t,
        p,
        n,
        r,
        m,
        msg_row,
        key_row,
    )


def _le_words(data: bytes) -> list[int]:
    return [int.from_bytes(data[i : i + 4], "little") for i in range(0, len(data), 4)]


class _KmacEntropy(SepKmac):
    """KMAC entropy-mode programming on top of the open KMAC driver."""

    _DRIVER_TAG = "KMAC"

    @staticmethod
    def cfg_word(*, entropy_mode: str, ready: bool, keyed: bool) -> int:
        """SHA3-256 (``keyed`` False) or keyed cSHAKE-256 with ``kmac_en`` (True)."""
        mode = KMAC_MODE["cshake" if keyed else "sha3"]
        return (
            int(keyed)
            | (KMAC_STRENGTH[256] << KMAC.field_lsb("CFG_SHADOWED", "kstrength"))
            | (mode << KMAC.field_lsb("CFG_SHADOWED", "mode"))
            | (ENTROPY_MODE[entropy_mode] << CFG_MODE_LSB)
            | (CFG_READY if ready else 0)
        )

    async def write_cfg(self, word: int) -> None:
        await self._wr(KMAC_CFG, word)
        await self._wr(KMAC_CFG, word)

    async def program(self, *, entropy_mode: str, keyed: bool) -> None:
        """Write CFG_SHADOWED twice with entropy_ready 0, then twice with 1."""
        await self.write_cfg(self.cfg_word(entropy_mode=entropy_mode, ready=False, keyed=keyed))
        await self.write_cfg(self.cfg_word(entropy_mode=entropy_mode, ready=True, keyed=keyed))

    async def write_keyed_regs(self, key: bytes) -> None:
        """KEY_LEN, PREFIX and the key shares of a keyed KMAC-256 (share 1 zero)."""
        await self._wr(KMAC_KEY_LEN, KMAC_KEY_LEN_256)
        await self._write_prefix(KMAC_KEYED_PREFIX)
        for i, word in enumerate(_le_words(key)):
            await self._wr(KMAC_KEY_SHARE0_0 + 4 * i, word)
            await self._wr(KMAC_KEY_SHARE1_0 + 4 * i, 0)

    async def seed(self, word: int) -> None:
        await self._wr(KMAC_ENTROPY_SEED, word)

    async def set_threshold(self, value: int) -> None:
        await self._wr(KMAC_THRESHOLD, value)
        await self._wr(KMAC_THRESHOLD, value)

    async def set_period(self, *, wait_timer: int, prescaler: int) -> None:
        await self._wr(
            KMAC_ENTROPY_PERIOD,
            (wait_timer << PERIOD_WAIT_LSB) | (prescaler << PERIOD_PRESCALER_LSB),
        )

    async def cmd(self, value: int) -> None:
        await self._wr(KMAC_CMD, value)

    async def read(self, addr: int) -> int:
        return await self._rd(addr)

    async def push(self, data: bytes) -> None:
        await self._push_msg_bytes(data)

    async def read_state_xor(self, nwords: int = KMAC_DIGEST_WORDS) -> list[int]:
        out = []
        for i in range(nwords):
            s0 = await self._rd(KMAC_STATE_S0 + 4 * i)
            s1 = await self._rd(KMAC_STATE_S1 + 4 * i)
            out.append((s0 ^ s1) & 0xFFFF_FFFF)
        return out


@pyuvm.test()
class sep_kmac_entropy_mode_rand_test(sep_base_test):
    """KMAC sw seeding, mode lock, EDN wait timer, hash counter and counter reseed."""

    required_evidence = (
        "CHK-KMAC-SWSEED",
        "CHK-KMAC-MODE-LOCK",
        "CHK-KMAC-TIMER",
        "CHK-KMAC-TIMER0",
        "CHK-KMAC-HASHCNT",
        "CHK-KMAC-AUTORESEED",
        "CHK-KMAC-AUTORESEED-OFF",
    )

    # ------------------------------------------------------------------ infra
    def _clk(self) -> int:
        return self.w_ack.clk

    async def _wait_clocks(self, n: int) -> None:
        await ClockCycles(cocotb.top.clk_i, max(n, 1))

    def _open(self) -> None:
        open_graded_window(TEST, self.logger)

    def _close(self) -> None:
        close_graded_window(self.logger)

    async def _poll(self, mask: int, bound: int) -> int | None:
        """Clocks until STATUS shows a bit of ``mask``; None after ``bound`` clocks."""
        t0 = self._clk()
        while self._clk() - t0 <= bound:
            if await self.kmac.read(KMAC_STATUS) & mask:
                return self._clk() - t0
            await self._wait_clocks(POLL_EVERY)
        return None

    async def _hold_no_absorb(self, window: int) -> tuple[int, int]:
        """Read STATUS for ``window`` clocks; return (reads, reads with absorb 1)."""
        t0 = self._clk()
        reads = absorbs = 0
        while self._clk() - t0 < window:
            st = await self.kmac.read(KMAC_STATUS)
            reads += 1
            absorbs += int(bool(st & ST_ABSORB))
            await self._wait_clocks(POLL_EVERY)
        return reads, absorbs

    async def _wait_rst(self, level: int) -> None:
        """Bring-up wait on the KMAC gated-reset probe; a timeout raises."""
        probe = cocotb.top.kmac_gated_rst_n_probe_o
        for _ in range(BOUND_CLK):
            if self.rd_known(probe) == level:
                return
            await self._wait_clocks(1)
        raise AssertionError(f"kmac_gated_rst_n_probe_o did not reach {level}")

    async def _reset_kmac(self) -> None:
        """Bit 4 of SW_RESET_N low, then high."""
        await self.swrst.park("kmac")
        await self._wait_rst(0)
        await self.swrst.release("kmac")
        await self._wait_rst(1)

    # ------------------------------------------------------------ entropy chain
    async def _chain_up(self) -> None:
        """ESRC, CSRNG and EDN bring-up with KMAC held in reset; graded window closed."""
        self._close()
        await self.swrst.park("kmac")
        await self.bring_up_entropy(strict=True, score_km=False)
        self.start_fifo_drain(log_batches=False)
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        await self.swrst.release("kmac")
        self.chain = "up"
        self.logger.info("CHAIN up (bring-up %d)", self.bringups)
        self.bringups += 1

    async def _retire_scoreboard(self) -> None:
        """Grade CHK1..CHK4 of the running bring-up, then stop its tasks."""
        await self.stop_fifo_drain()
        assert self.drbg_sb.report(), "entropy scoreboard report failed"
        self.drbg_sb.stop()

    async def _chain_uninit(self) -> None:
        """TRNG reset (bit 5 low, then high) with no bring-up after it."""
        self._close()
        if self.chain == "up":
            await self._retire_scoreboard()
        await self.swrst.park("kmac")
        await self.swrst.park("trng")
        await self.swrst.release("trng")
        await self.swrst.release("kmac")
        self.chain = "uninit"
        self.logger.info("CHAIN uninitialized (TRNG reset, no bring-up)")

    async def _need_chain_up(self) -> None:
        if self.chain != "up":
            await self._chain_up()

    # --------------------------------------------------------------- hashing
    async def _sha3_hash(self, msg: bytes) -> tuple[str, list[int]]:
        """Start (already issued by the caller) -> absorb -> message -> squeeze -> XOR -> done.

        Returns (status, digest); status is "ok" or the stage that timed out.
        """
        await self.kmac.push(msg)
        await self.kmac.cmd(KMAC_CMD_PROCESS)
        if await self._poll(ST_SQUEEZE, BOUND_CLK) is None:
            return "squeeze_timeout", []
        digest = await self.kmac.read_state_xor()
        await self.kmac.cmd(KMAC_CMD_DONE)
        if await self._poll(ST_IDLE, BOUND_CLK) is None:
            return "idle_timeout", digest
        return "ok", digest

    async def _keyed_hash(self) -> str:
        """One keyed KMAC-256 hash; the digest is not graded here."""
        if await self._poll(ST_IDLE, BOUND_CLK) is None:
            return "idle_timeout"
        await self.kmac.cmd(KMAC_CMD_START)
        if await self._poll(ST_ABSORB, BOUND_CLK) is None:
            return "absorb_timeout"
        status, _ = await self._sha3_hash(self.msg + right_encode(KMAC_KEYED_OUT_BITS))
        return status

    async def _keyed_run(self, count: int) -> tuple[str, list[int]]:
        """``count`` keyed hashes; the counter is read after each."""
        cnts = []
        for _ in range(count):
            status = await self._keyed_hash()
            if status != "ok":
                return status, cnts
            cnts.append(await self.kmac.read(KMAC_HASH_CNT) & HASH_CNT_MASK)
        return "ok", cnts

    async def _measure_t_reseed(self, req_mark, ack_mark) -> int | None:
        """Clocks from the crypto_edn_req_o[1] rise to the next ack rise (window closed)."""
        try:
            req_clk = await self.w_req.wait_rise(req_mark, BOUND_CLK)
            ack_clk = await self.w_ack.wait_rise(ack_mark, BOUND_CLK)
        except BitWatchTimeout as exc:
            self.logger.info("t_reseed not measured: %s", exc)
            return None
        return max(ack_clk - req_clk, 1)

    # ------------------------------------------------------------------ legs
    async def _leg_six_seed(self) -> None:
        await self._reset_kmac()
        self._open()
        await self.kmac.program(entropy_mode="sw", keyed=False)
        seed_words = SEED_ROW
        for word in seed_words[:6]:
            await self.kmac.seed(word)
        t0 = self._clk()
        await self.kmac.cmd(KMAC_CMD_START)
        absorb = await self._poll(ST_ABSORB, BOUND_CLK)
        if absorb is None:
            self.chk.ok("KMAC-SWSEED", False, seeds=6, absorb=0, reason="timeout", bound=BOUND_CLK)
            self._close()
            await self._reset_kmac()
            return
        self.t_ctrl = max(self._clk() - t0, 1)
        status, digest = await self._sha3_hash(self.msg)
        golden = _le_words(sha3(self.msg, 256))
        self.chk.ok(
            "KMAC-SWSEED",
            status == "ok" and digest == golden,
            seeds=6,
            absorb=1,
            t_ctrl_clk=self.t_ctrl,
            stage=status,
            digest_eq_golden=int(digest == golden),
            digest0=f"0x{digest[0]:08x}" if digest else "none",
            golden0=f"0x{golden[0]:08x}",
        )
        self._close()
        if status != "ok":
            await self._reset_kmac()

    def _neg_window(self) -> int:
        if self.t_ctrl is None:
            return BOUND_CLK
        return max(WIN_MULT * self.t_ctrl, WIN_FLOOR)

    async def _leg_seed_count(self) -> None:
        self.chk.blocked("KMAC-SWSEED-NEG", SEED_GATE_BLOCKED)
        window = self._neg_window()
        # Log-only leg: the graded FCOV window stays closed.
        for count in self.plan.seed_counts:
            await self._reset_kmac()
            await self.kmac.program(entropy_mode="sw", keyed=False)
            for word in SEED_ROW[:count]:
                await self.kmac.seed(word)
            await self.kmac.cmd(KMAC_CMD_START)
            reads, absorbs = await self._hold_no_absorb(window)
            intr = await self.kmac.read(KMAC_INTR_STATE)
            self.chk.obs(
                "KMAC-SWSEED-NEG",
                seeds_written=count,
                window_clk=window,
                reads=reads,
                absorb_reads=absorbs,
                absorb=int(absorbs > 0),
                ctrl_absorb_clk=self.t_ctrl,
                kmac_err=int(bool(intr & KMAC_INTR_KMAC_ERR)),
            )
            self._close()
        await self._reset_kmac()

    async def _leg_mode_lock(self) -> None:
        for locked in self.plan.lock_order:
            await self._need_chain_up()
            await self._reset_kmac()
            self._open()
            reset_mode = (await self.kmac.read(KMAC_CFG) & CFG_MODE_MASK) >> CFG_MODE_LSB
            req_m, ack_m = self.w_req.mark(), self.w_ack.mark()
            await self.kmac.program(entropy_mode=locked, keyed=False)
            late = self.plan.late_sw if locked == "sw" else "sw"
            await self.kmac.write_cfg(
                self.kmac.cfg_word(entropy_mode=late, ready=True, keyed=False)
            )
            readback = (await self.kmac.read(KMAC_CFG) & CFG_MODE_MASK) >> CFG_MODE_LSB
            await self.kmac.cmd(KMAC_CMD_START)
            fields = dict(
                locked=locked,
                reset_mode=reset_mode,
                late_write=late,
                readback=readback,
            )
            if locked == "edn":
                # The initial EDN reseed after entropy_ready sets the request window.
                t_reseed = await self._measure_t_reseed(req_m, ack_m)
            regs_ok = reset_mode == ENTROPY_MODE["idle"] and readback == ENTROPY_MODE[late]
            if locked == "sw":
                self.chk.ok("KMAC-MODE-LOCK", regs_ok, **fields, part="readback")
                self.chk.blocked("KMAC-MODE-LOCK", SEED_GATE_BLOCKED)
                window = self._neg_window()
                reads, absorbs = await self._hold_no_absorb(window)
                intr = await self.kmac.read(KMAC_INTR_STATE)
                self.chk.obs(
                    "KMAC-MODE-LOCK-SW",
                    seeds_written=0,
                    window_clk=window,
                    reads=reads,
                    absorb_reads=absorbs,
                    absorb=int(absorbs > 0),
                    kmac_err=int(bool(intr & KMAC_INTR_KMAC_ERR)),
                )
            else:
                absorb = await self._poll(ST_ABSORB, BOUND_CLK)
                if absorb is None:
                    self.chk.ok(
                        "KMAC-MODE-LOCK",
                        False,
                        **fields,
                        absorb=0,
                        reason="timeout",
                        bound=BOUND_CLK,
                    )
                    self._close()
                    await self._reset_kmac()
                    continue
                status, digest = await self._sha3_hash(self.msg)
                golden = _le_words(sha3(self.msg, 256))
                hash_ok = status == "ok" and digest == golden
                # Mode observable: CMD.entropy_req reseeds from EDN only in EDN mode
                # (kmac.adoc:199). Control: the same window with no command, after the
                # hash and with the module idle, gives no acknowledge.
                window = max(WIN_MULT * (t_reseed or BOUND_CLK // WIN_MULT), WIN_FLOOR)
                ctrl_m = self.w_ack.mark()
                await self._wait_clocks(window)
                ctrl_acks = self.w_ack.high_clocks_since(ctrl_m)
                self.chk.ctrl(
                    "KMAC-MODE-LOCK", ctrl_acks == 0, ctrl_acks=ctrl_acks, window_clk=window
                )
                req_ack_m = self.w_ack.mark()
                await self.kmac.cmd(CMD_ENTROPY_REQ)
                await self._wait_clocks(window)
                acks = self.w_ack.high_clocks_since(req_ack_m)
                behaviour_ok = hash_ok and acks >= 1 and ctrl_acks == 0
                self.chk.ok(
                    "KMAC-MODE-LOCK",
                    regs_ok and behaviour_ok,
                    **fields,
                    absorb=1,
                    stage=status,
                    digest_eq_golden=int(digest == golden),
                    entropy_req_acks=acks,
                    ctrl_acks=ctrl_acks,
                    window_clk=window,
                    t_reseed_clk=t_reseed,
                    behaviour="locked" if behaviour_ok else "late_write_taken",
                )
            self._close()
            await self._reset_kmac()

    async def _timer_run(self, *, wait_timer: int, prescaler: int) -> dict:
        """One EDN starvation run; returns the measured fields."""
        await self._reset_kmac()
        self._open()
        await self.kmac._wr(KMAC_INTR_ENABLE, KMAC_INTR_KMAC_ERR)
        pre_intr = await self.kmac.read(KMAC_INTR_STATE) & KMAC_INTR_KMAC_ERR
        pre_code = await self.kmac.read(KMAC_ERR_CODE) & ERR_CODE_MASK
        self.chk.ctrl(
            "KMAC-TIMER-PRESTATE",
            pre_intr == 0 and pre_code == 0,
            wt=wait_timer,
            p=prescaler,
            kmac_err=int(bool(pre_intr)),
            err_code=f"0x{pre_code:x}",
        )
        await self.kmac.set_period(wait_timer=wait_timer, prescaler=prescaler)
        req_m, ack_m, err_m = self.w_req.mark(), self.w_ack.mark(), self.w_vec.mark()
        await self.kmac.program(entropy_mode="edn", keyed=False)
        bound = 64 * (prescaler + 1) * (wait_timer + 2) + 2_000
        out = dict(wt=wait_timer, p=prescaler, pre_err=pre_intr, pre_code=pre_code, bound=bound)
        try:
            req_clk = await self.w_req.wait_rise(req_m, bound)
            err_clk = await self.w_vec.wait_rise(err_m, bound)
        except BitWatchTimeout:
            out.update(err_clk=None, acks=self.w_ack.high_clocks_since(ack_m))
            self._close()
            return out
        acks = self.w_ack.high_clocks_since(ack_m)
        intr = await self.kmac.read(KMAC_INTR_STATE)
        code = await self.kmac.read(KMAC_ERR_CODE) & ERR_CODE_MASK
        out.update(
            err_clk=err_clk - req_clk,
            acks=acks,
            err=int(bool(intr & KMAC_INTR_KMAC_ERR)),
            code=code,
        )
        self._close()
        return out

    async def _leg_timer(self) -> None:
        await self._chain_uninit()
        t = self.plan.t
        wts = (t, 2 * t, 8)
        passes: dict[str, list[dict]] = {}
        for name in self.plan.prescaler_order:
            prescaler = 0 if name == "p0" else self.plan.p
            runs = []
            for wt in wts:
                run = await self._timer_run(wait_timer=wt, prescaler=prescaler)
                self.logger.info("TIMER-RUN %s", run)
                runs.append(run)
            passes[name] = runs
            await self._timer0(prescaler, runs[2])
        await self._reset_kmac()

        def clean(run: dict) -> bool:
            return (
                run["err_clk"] is not None
                and run["pre_err"] == 0
                and run["pre_code"] == 0
                and run["err"] == 1
                and run["acks"] == 0
            )

        p0, pp = passes["p0"], passes["p"]
        all_clean = all(clean(r) for r in p0 + pp)
        order_ok = (
            all_clean
            and all(runs[0]["err_clk"] < runs[1]["err_clk"] for runs in (p0, pp))
            and all(pp[i]["err_clk"] > p0[i]["err_clk"] for i in range(3))
        )

        def clks(runs: list[dict]) -> str:
            return ",".join(str(r["err_clk"]) for r in runs)

        self.chk.ok(
            "KMAC-TIMER",
            order_ok,
            t=t,
            p=self.plan.p,
            p0_err_clk=clks(p0),
            p_err_clk=clks(pp),
            acks=sum(r["acks"] for r in p0 + pp),
            reason="ok" if all_clean else "timeout_or_no_error",
        )
        self.chk.obs(
            "KMAC-TIMER-ERRCODE",
            p0_code=",".join(f"0x{r['code']:x}" if "code" in r else "na" for r in p0),
            p_code=",".join(f"0x{r['code']:x}" if "code" in r else "na" for r in pp),
        )

    async def _timer0(self, prescaler: int, ctrl: dict) -> None:
        ctrl_clk = ctrl["err_clk"]
        self.chk.ctrl("KMAC-TIMER0", ctrl_clk is not None, wt=8, p=prescaler, ctrl_err_clk=ctrl_clk)
        window = max(WIN_MULT * ctrl_clk, WIN_FLOOR) if ctrl_clk is not None else BOUND_CLK
        await self._reset_kmac()
        self._open()
        await self.kmac._wr(KMAC_INTR_ENABLE, KMAC_INTR_KMAC_ERR)
        await self.kmac.set_period(wait_timer=0, prescaler=prescaler)
        req_m, ack_m, err_m = self.w_req.mark(), self.w_ack.mark(), self.w_vec.mark()
        await self.kmac.program(entropy_mode="edn", keyed=False)
        await self._wait_clocks(window)
        line = self.w_vec.any_high_since(err_m)
        acks = self.w_ack.high_clocks_since(ack_m)
        req = int(self.w_req.rose_since(req_m) or self.w_req.level() == 1)
        intr = await self.kmac.read(KMAC_INTR_STATE)
        code = await self.kmac.read(KMAC_ERR_CODE) & ERR_CODE_MASK
        err = int(bool(intr & KMAC_INTR_KMAC_ERR))
        self.chk.ok(
            "KMAC-TIMER0",
            err == 0 and not line and code == 0 and req == 1 and acks == 0,
            p=prescaler,
            window_clk=window,
            err=err,
            line=int(line),
            code=f"0x{code:x}",
            req=req,
            acks=acks,
            ctrl_err_clk=ctrl_clk,
        )
        self._close()
        await self._reset_kmac()

    async def _keyed_setup(self, threshold: int) -> int | None:
        """KMAC reset, threshold, keyed program in EDN mode; returns t_reseed."""
        await self._reset_kmac()
        self._open()
        await self.kmac.set_threshold(threshold)
        await self.kmac.write_keyed_regs(self.key)
        await self.kmac.write_cfg(self.kmac.cfg_word(entropy_mode="edn", ready=False, keyed=True))
        self._close()
        req_m, ack_m = self.w_req.mark(), self.w_ack.mark()
        await self.kmac.write_cfg(self.kmac.cfg_word(entropy_mode="edn", ready=True, keyed=True))
        t_reseed = await self._measure_t_reseed(req_m, ack_m)
        self.logger.info("T-RESEED threshold=%d t_reseed_clk=%s", threshold, t_reseed)
        return t_reseed

    async def _leg_counter(self) -> None:
        await self._need_chain_up()
        n = self.plan.n
        t_reseed = await self._keyed_setup(n + 5)
        window = max(WIN_MULT * (t_reseed or BOUND_CLK // WIN_MULT), WIN_FLOOR)
        self._open()
        status, cnts = await self._keyed_run(n)
        fields = dict(n=n, cnts=",".join(map(str, cnts)), window_clk=window)
        if status != "ok":
            self.chk.ok("KMAC-HASHCNT", False, **fields, reason="timeout", stage=status)
            self._close()
            await self._reset_kmac()
            return
        await self.kmac.cmd(CMD_HASH_CNT_CLR)
        after_clr = await self.kmac.read(KMAC_HASH_CNT) & HASH_CNT_MASK
        status, one = await self._keyed_run(1)
        if status != "ok":
            self.chk.ok("KMAC-HASHCNT", False, **fields, reason="timeout", stage=status)
            self._close()
            await self._reset_kmac()
            return
        self._close()
        ctrl_m = self.w_ack.mark()
        await self._wait_clocks(window)
        ctrl_acks = self.w_ack.high_clocks_since(ctrl_m)
        self.chk.ctrl("KMAC-HASHCNT", ctrl_acks == 0, ctrl_acks=ctrl_acks, window_clk=window)
        self._open()
        req_m = self.w_ack.mark()
        await self.kmac.cmd(CMD_ENTROPY_REQ)
        await self._wait_clocks(window)
        acks = self.w_ack.high_clocks_since(req_m)
        after_req = await self.kmac.read(KMAC_HASH_CNT) & HASH_CNT_MASK
        self.chk.ok(
            "KMAC-HASHCNT",
            cnts == list(range(1, n + 1))
            and after_clr == 0
            and one == [1]
            and after_req == 0
            and acks >= 1
            and ctrl_acks == 0,
            **fields,
            cnt=cnts[-1],
            after_clr=after_clr,
            after_one=one[0],
            after_req=after_req,
            acks=acks,
            ctrl_acks=ctrl_acks,
        )
        self._close()
        await self._reset_kmac()

    async def _leg_reseed(self) -> None:
        await self._need_chain_up()
        r, m = self.plan.r, self.plan.m
        t_reseed = await self._keyed_setup(r)
        settle = max(WIN_MULT * (t_reseed or BOUND_CLK // WIN_MULT), WIN_FLOOR)
        # The first hash ends after the initial seeding and is not counted.
        status = await self._keyed_hash()
        if status != "ok":
            self.chk.ok("KMAC-AUTORESEED", False, thr=r, n=m, reason="timeout", stage=status)
            self.chk.ok("KMAC-AUTORESEED-OFF", False, thr=0, n=m, reason="r_run_missing")
            await self._reset_kmac()
            return
        self._open()
        await self.kmac.cmd(CMD_HASH_CNT_CLR)
        clr_r = await self.kmac.read(KMAC_HASH_CNT) & HASH_CNT_MASK
        ack_m = self.w_ack.mark()
        status, cnts = await self._keyed_run(m)
        cnt_r = cnts[-1] if cnts else None
        if status == "ok":
            await self._wait_clocks(settle)
            try:
                await self.w_req.wait_level(0, BOUND_CLK, "req")
            except BitWatchTimeout:
                status = "req_low_timeout"
        acks_r = self.w_ack.high_clocks_since(ack_m)
        r_ok = status == "ok" and clr_r == 0 and acks_r >= 1 and cnt_r is not None and cnt_r < m
        self.chk.ok(
            "KMAC-AUTORESEED",
            r_ok,
            thr=r,
            n=m,
            clr=clr_r,
            acks=acks_r,
            cnt_after=cnt_r,
            cnt_below_n=int(cnt_r is not None and cnt_r < m),
            settle_clk=settle,
            stage=status,
        )
        if status != "ok":
            self.chk.ok("KMAC-AUTORESEED-OFF", False, thr=0, n=m, reason="r_run_missing")
            self._close()
            await self._reset_kmac()
            return
        self.chk.ctrl("KMAC-AUTORESEED-OFF", acks_r >= 1, thr=r, ctrl_acks=acks_r)
        await self.kmac.set_threshold(0)
        await self.kmac.cmd(CMD_HASH_CNT_CLR)
        clr_0 = await self.kmac.read(KMAC_HASH_CNT) & HASH_CNT_MASK
        ack_m = self.w_ack.mark()
        status, cnts = await self._keyed_run(m)
        acks_0 = self.w_ack.high_clocks_since(ack_m)
        cnt_0 = cnts[-1] if cnts else None
        self.chk.ok(
            "KMAC-AUTORESEED-OFF",
            status == "ok" and clr_0 == 0 and acks_0 == 0 and cnt_0 == m,
            thr=0,
            n=m,
            clr=clr_0,
            acks=acks_0,
            cnt_after=cnt_0,
            ctrl_acks=acks_r,
            stage=status,
        )
        self._close()
        await self._reset_kmac()

    # -------------------------------------------------------------- scenario
    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.plan = draw_plan(seed)
        self.logger.info(self.plan.line(seed))
        self.msg = MSG_ROWS[self.plan.msg_row]
        self.key = KEY_ROWS[self.plan.key_row]
        self.chk = SepChkLog(self, TEST, seed)
        self.t_ctrl: int | None = None
        self.chain = "none"
        self.bringups = 0

        await self.bring_up_no_cpu(park=("otbn", "aes", "hmac", "abr"))
        self.logger.info("BASELINE SW_RESET_N=0x%08x", await self.swrst.read_back())
        dut = cocotb.top
        self.w_req = SepBitWatch(dut.crypto_edn_req_o, {"req": EDN_CLIENT_KMAC}).start()
        self.w_ack = SepBitWatch(dut.crypto_edn_ack_o, {"ack": EDN_CLIENT_KMAC}).start()
        self.w_vec = SepBitWatch(dut.sep_internal_interrupts_probe_o, {"err": VEC_KMAC_ERR}).start()
        self.kmac = _KmacEntropy(self)

        await self._chain_up()
        await self._leg_six_seed()
        runners = {
            "seed_count": self._leg_seed_count,
            "mode_lock": self._leg_mode_lock,
            "timer": self._leg_timer,
            "counter": self._leg_counter,
            "reseed": self._leg_reseed,
        }
        for leg in self.plan.legs:
            self.logger.info("LEG %s", leg)
            await runners[leg]()

        self._close()
        if self.chain == "up":
            await self._retire_scoreboard()
        for watch in (self.w_req, self.w_ack, self.w_vec):
            await watch.stop()
        self.chk.finish()
