# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""An HMAC start with an illegal configuration is blocked and signalled; the engine recovers.

RAND-REP, ``no_cpu``. The leaf drives the HMAC engine over the CPU-LSU master and walks ten
start classes in a drawn order on every seed:

    blocked  B1 Key_None/SHA2_256, B2 Key_None/SHA2_384, B3 Key_None/SHA2_512 (hmac_en = 1)
             B4 Key_1024/SHA2_256 (hmac_en = 1)
             B5 an invalid multi-bit key_length on SHA2_256 (hmac_en = 1)
             B6 digest_size all-zero (hmac_en = 0)
             B7 an invalid multi-bit digest_size (hmac_en = 0)
    legal    L1 hmac_en = 0 with Key_None on a drawn digest size
             L2 Key_1024/SHA2_384, L3 Key_1024/SHA2_512 (hmac_en = 1)

Spec: ``vendor/lowRISC/opentitan/overlay/regs/hmac/regs/gen/adoc/hmac.adoc`` (``CFG``:106
"starting is blocked and an error is signalled to SW", :110 invalid digest_size maps to
SHA2_None; ``INTR_STATE``:44 ``hmac_err`` RW1C; ``ERR_CODE``:171) and
``vendor/lowRISC/opentitan/upstream/hw/ip/hmac/data/hmac.hjson`` (:272 SHA2_None blocks a start;
:329-331 Key_None blocks a keyed start and does not block ``hmac_en`` = 0).

Checkers:
  CHK-HMAC-BLOCK    a blocked start sets ``hmac_err`` (read before any message write; it reads
                    0 before the start in ``CTRL-HMAC-PRESTATE``); the message and ``hash_process`` that
                    complete a legal hash then give no ``hmac_done`` for the hold, and
                    DIGEST stays at D_prev (read under the restored ``CFG`` of the last
                    completed hash). The hold is 3 x t_worst: t_worst is the measured
                    hash_start-to-done time of the longest hash any class can start
                    (HMAC-SHA2_512, Key_1024, a 64-byte message), so a wrongly started
                    engine finishes inside the hold
  CHK-HMAC-RECOVER  after the write-one clear ``hmac_err`` reads 0, and a legal HMAC hash
                    returns its golden, which differs from D_prev

Controls: ``CTRL-HMAC-NOBLOCK`` (each legal class raises no error, sets ``hmac_done`` and
returns its golden), ``CTRL-HMAC-DPREV`` (D_prev equals the golden of the last completed hash
and is non-zero), ``CTRL-HMAC-REF`` (the reference hash and the worst-case hash return their
goldens). Log-only:
``OBS-HMAC-ERRCODE`` (the value; the register text, hmac.adoc:171-172, states no value),
``OBS-HMAC-BLOCKED-MSG-RESP`` (non-OKAY responses to the message written after a blocked
start; the register text does not state them) and
``OBS-HMAC-IDLE`` (``STATUS.hmac_idle``; the register text does not state its value after a
blocked start), ``OBS-HMAC-DIGEST-ORDER`` (the byte order inside a DIGEST word).

DIGEST byte order: hmac.adoc:114 (``CFG.digest_swap``) states a byte swap, and no register text
states the byte order inside a DIGEST word at ``digest_swap`` = 0. A readback equals its golden
when every word is the big-endian ("be") or every word is the little-endian ("le") read of
digest bytes 4n..4n+3, and every readback of the seed uses the order of the first one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time
from env.sep_axi_agent import SepAxiOp
from env.sep_chk_log import SepChkLog
from env.sep_crypto_kat_rows import RFC4231_KEYS
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_hmac_golden import hmac_sha2_bytes, sha2_bytes
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import HMAC
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_hmac_seq import (
    HMAC_CFG,
    HMAC_CMD,
    HMAC_CMD_HASH_PROCESS,
    HMAC_CMD_HASH_START,
    HMAC_DIGEST_0,
    HMAC_DIGEST_SIZE,
    HMAC_DIGEST_WORDS,
    HMAC_ERR_CODE,
    HMAC_ILLEGAL_KEYED,
    HMAC_INTR_DONE,
    HMAC_INTR_ERR,
    HMAC_INTR_STATE,
    HMAC_KEY_0,
    HMAC_KEY_LENGTH,
    HMAC_MSG_FIFO,
    HMAC_NUM_PUBLIC_KEY,
    HMAC_STATUS,
    HMAC_STATUS_IDLE,
    SepHmac,
)
from seq_lib.sep_sw_reset_seq import SW_RESET_N_BIT, SepSwReset

TEST = "sep_hmac_illegal_cfg_start_test"

# hmac.hjson CFG.key_length: 6'b10_0000 is Key_None (:329); an all-zero or any other
# unsupported value maps to it (:329). CFG.digest_size: an all-zero or invalid value maps to
# SHA2_None (:272; hmac.adoc:110).
KEY_NONE = 0x20
DIGEST_ZERO = 0x0
INVALID_DIGEST = (0b011, 0b101, 0b110, 0b111)
INVALID_KEYLEN = tuple(v for v in range(32) if 2 <= bin(v).count("1") <= 5)
SW_RESET_BASELINE = 0x7E
INTR_FIELDS = HMAC_INTR_DONE | HMAC_INTR_ERR | HMAC.field_mask("INTR_STATE", "fifo_empty")
CFG_LSB = {f: HMAC.field_lsb("CFG", f) for f in ("hmac_en", "sha_en", "digest_size", "key_length")}

# Published test keys, RFC 4231 sections 4.2 to 4.7 (test cases 1 to 6,
# env/sep_crypto_kat_rows.py). The seed picks a row, never the bytes. A row is zero-padded
# to the 1024-bit KEY multireg; hmac.hjson KEY ("key[1023:0] = {KEY0, KEY1, ... , KEY31}")
# makes KEY_0 the most-significant word, so a key of k bits is the first k/8 bytes of the row.
KEY_ROWS = RFC4231_KEYS


def _row128(row: int) -> bytes:
    return KEY_ROWS[row][:128].ljust(128, b"\x00")


def _row_words(row: int) -> list[int]:
    raw = _row128(row)
    return [int.from_bytes(raw[i : i + 4], "big") for i in range(0, 128, 4)]


def _words(raw: bytes) -> tuple[int, ...]:
    """Big-endian reads of digest bytes 4n..4n+3 (the "be" candidate order)."""
    return tuple(int.from_bytes(raw[i : i + 4], "big") for i in range(0, len(raw), 4))


def _bswap32(w: int) -> int:
    return int.from_bytes((w & 0xFFFF_FFFF).to_bytes(4, "little"), "big")


def _order_of(got: tuple[int, ...], golden: tuple[int, ...]) -> str | None:
    """Return "be" or "le" when ``got`` equals ``golden`` in that in-word byte order."""
    if tuple(got) == tuple(golden):
        return "be"
    if tuple(got) == tuple(_bswap32(w) for w in golden):
        return "le"
    return None


@dataclass(frozen=True)
class Hash:
    """One completed hash: its CFG fields, data and golden digest words."""

    sha: int
    hmac_en: int
    key_bits: int | None
    row: int | None
    msg: bytes
    golden: tuple[int, ...]

    def cfg(self) -> int:
        klen = HMAC_KEY_LENGTH[self.key_bits] if self.key_bits is not None else KEY_NONE
        return cfg_word(HMAC_DIGEST_SIZE[self.sha], klen, self.hmac_en)


@dataclass(frozen=True)
class ClassStep:
    """One start class. ``blocked`` classes carry their recovery hash."""

    name: str
    blocked: bool
    digest_code: int
    key_code: int
    hmac_en: int
    row: int | None
    legal: Hash | None = None
    recovery: Hash | None = None


@dataclass
class Plan:
    seed: int
    reference: Hash
    steps: list[ClassStep] = field(default_factory=list)
    # The longest hash any class can start: it sizes the blocked-start hold.
    worst: Hash | None = None

    def summary(self) -> str:
        order = ",".join(s.name for s in self.steps)
        cells = " ".join(
            f"{s.name}:d=0b{s.digest_code:04b}/k=0b{s.key_code:06b}/e={s.hmac_en}"
            for s in self.steps
        )
        return f"order={order} ref_len={len(self.reference.msg)} {cells}"


def cfg_word(digest_code: int, key_code: int, hmac_en: int) -> int:
    """CFG with sha_en = 1, endian_swap = digest_swap = key_swap = 0."""
    return (
        (hmac_en & 1) << CFG_LSB["hmac_en"]
        | 1 << CFG_LSB["sha_en"]
        | digest_code << CFG_LSB["digest_size"]
        | key_code << CFG_LSB["key_length"]
    ) & 0xFFFF_FFFF


def _golden(sha: int, hmac_en: int, key_bits: int | None, row: int | None, msg: bytes):
    if hmac_en:
        assert key_bits is not None and row is not None
        return _words(hmac_sha2_bytes(_row128(row)[: key_bits // 8], msg, sha))
    return _words(sha2_bytes(msg, sha))


MSG_MAX = 64


def _draw_msg(rng: SepSeededRng, n: int | None = None) -> bytes:
    """0..MSG_MAX bytes (or ``n``); each whole word is unique and non-zero (MSG_FIFO data)."""
    if n is None:
        n = rng.randrange(0, MSG_MAX + 1)
    words: list[int] = []
    while len(words) < (n + 3) // 4:
        w = rng.getrandbits(32)
        if w and w not in words:
            words.append(w)
    return b"".join(w.to_bytes(4, "little") for w in words)[:n]


def _draw_hash(rng, sha, hmac_en, key_bits, *, avoid=None, nonzero=True, n=None) -> Hash:
    row = rng.randrange(len(KEY_ROWS)) if hmac_en else None
    while True:
        msg = _draw_msg(rng, n)
        g = _golden(sha, hmac_en, key_bits, row, msg)
        if nonzero and not any(g):
            continue
        if avoid is not None and g == avoid:
            continue
        return Hash(sha, hmac_en, key_bits, row, msg, g)


def _legal_keys(sha: int) -> list[int]:
    return [k for k in HMAC_KEY_LENGTH if (sha, k) not in HMAC_ILLEGAL_KEYED]


def draw_plan(seed: int) -> Plan:
    """The whole plan of a seed, in a fixed draw order. No simulator access."""
    rng = SepSeededRng(seed)
    names = ["B1", "B2", "B3", "B4", "B5", "B6", "B7", "L1", "L2", "L3"]
    rng.shuffle(names)
    l1_sha = rng.choice([256, 384, 512])
    bad_digest = rng.choice(list(INVALID_DIGEST))
    bad_keylen = rng.choice(list(INVALID_KEYLEN))
    reference = _draw_hash(rng, 256, 0, None)
    plan = Plan(seed, reference)
    last = reference
    for name in names:
        if name.startswith("L"):
            if name == "L1":
                h = _draw_hash(rng, l1_sha, 0, None)
                step = ClassStep(name, False, HMAC_DIGEST_SIZE[l1_sha], KEY_NONE, 0, None, legal=h)
            else:
                sha = 384 if name == "L2" else 512
                h = _draw_hash(rng, sha, 1, 1024)
                step = ClassStep(
                    name, False, HMAC_DIGEST_SIZE[sha], HMAC_KEY_LENGTH[1024], 1, h.row, legal=h
                )
            last = h
        else:
            digest_code, key_code, hmac_en = {
                "B1": (HMAC_DIGEST_SIZE[256], KEY_NONE, 1),
                "B2": (HMAC_DIGEST_SIZE[384], KEY_NONE, 1),
                "B3": (HMAC_DIGEST_SIZE[512], KEY_NONE, 1),
                "B4": (HMAC_DIGEST_SIZE[256], HMAC_KEY_LENGTH[1024], 1),
                "B5": (HMAC_DIGEST_SIZE[256], bad_keylen, 1),
                "B6": (DIGEST_ZERO, KEY_NONE, 0),
                "B7": (bad_digest, KEY_NONE, 0),
            }[name]
            row = rng.randrange(len(KEY_ROWS)) if hmac_en else None
            rsha = rng.choice([256, 384, 512])
            rkey = rng.choice(_legal_keys(rsha))
            # D_prev is the golden of the last completed hash; the recovery digest differs.
            rec = _draw_hash(rng, rsha, 1, rkey, avoid=last.golden)
            step = ClassStep(name, True, digest_code, key_code, hmac_en, row, recovery=rec)
            last = rec
        plan.steps.append(step)
    plan.worst = _draw_hash(rng, 512, 1, 1024, n=MSG_MAX)
    return plan


@pyuvm.test()
class sep_hmac_illegal_cfg_start_test(sep_base_test):
    """Blocked HMAC starts raise hmac_err with DIGEST unchanged; the engine then recovers."""

    required_evidence = ("CHK-HMAC-BLOCK", "CHK-HMAC-RECOVER")

    async def run_scenario(self) -> None:
        dut = cocotb.top
        seed = self.random_seed()
        self.seed = seed
        plan = draw_plan(seed)
        self.chk = SepChkLog(self, TEST, seed)
        self.logger.info("PLAN seed=%d %s", seed, plan.summary())

        await self.bring_up_no_cpu()
        self.hmac = SepHmac(self)
        self.swrst = SepSwReset(self)
        self.swrst.value = SW_RESET_BASELINE
        await self.swrst.release()
        self.logger.info("CTRL-HMAC-BASELINE seed=%d sw_reset_n=0x%02x", seed, SW_RESET_BASELINE)
        self._period_ps = round(self.cfg.sys_clk_period_ns * 1000)
        self._dorder: str | None = None
        await self._reset_hmac(dut)

        # Worst-case hash: HMAC-SHA2_512 with Key_1024 and a MSG_MAX-byte message is the
        # longest hash a class can start (largest block, keyed, longest message). Its
        # hash_start-to-done time exceeds the hash_process-to-done time of any started
        # class, so 3 x t_worst is the blocked-start hold.
        worst = plan.worst
        assert worst is not None
        t_worst, wdigest = await self._run_hash(worst, bound=self.REF_BOUND)
        self.chk.ctrl(
            "HMAC-REF",
            t_worst is not None and self._eq(wdigest, worst.golden),
            ref="sha512_key1024",
            len=len(worst.msg),
            t_clean=t_worst,
            bound=self.REF_BOUND,
        )
        if t_worst is None:
            raise AssertionError(f"HMAC worst-case hash timed out (bound={self.REF_BOUND} clocks)")

        # Reference hash: t_clean is the clean time of the bounds of this seed.
        ref = plan.reference
        t_clean, digest = await self._run_hash(ref, bound=self.REF_BOUND)
        self.chk.ctrl(
            "HMAC-REF",
            t_clean is not None and self._eq(digest, ref.golden),
            ref="sha256_nokey",
            len=len(ref.msg),
            t_clean=t_clean,
            bound=self.REF_BOUND,
        )
        if t_clean is None:
            raise AssertionError(f"HMAC reference hash timed out (bound={self.REF_BOUND} clocks)")
        self.t_clean = max(t_clean, t_worst, 1)
        self.hold = 3 * self.t_clean
        self.hash_bound = 64 * self.t_clean
        self.logger.info(
            "HMAC t_clean=%d clocks (ref=%d worst=%d); blocked hold=%d; hash poll bound=%d",
            self.t_clean,
            t_clean,
            t_worst,
            self.hold,
            self.hash_bound,
        )
        last = ref

        for step in plan.steps:
            await self._pre_class(step)
            if step.blocked:
                last = await self._blocked_class(step, last)
            else:
                last = await self._legal_class(step)

        close_graded_window(self.logger)
        self.chk.obs("HMAC-DIGEST-ORDER", dswap0=self._dorder or "-")
        self.chk.finish()

    def _eq(self, got: tuple[int, ...], golden: tuple[int, ...]) -> bool:
        """``got`` equals ``golden`` in the DIGEST byte order of the seed (first match sets it)."""
        order = _order_of(got, golden)
        if order is None:
            return False
        if self._dorder is None:
            self._dorder = order
        return order == self._dorder

    # Outer limit of the clean-time measurement only; never a contract.
    REF_BOUND = 20_000

    def _now_clk(self) -> int:
        return int(get_sim_time("ps")) // self._period_ps

    async def _wr(self, addr: int, data: int, *, length: int = 4) -> None:
        seq = SepAxiAccessSeq(
            "hmac_wr",
            op=SepAxiOp.WRITE,
            addr=addr,
            wdata=data,
            length=length,
            size={4: 2, 2: 1, 1: 0}[length],
        )
        await self.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError(f"HMAC write @0x{addr:08x} not OKAY")

    async def _rd(self, addr: int) -> int:
        return await self.hmac._rd(addr)

    async def _reset_hmac(self, dut) -> None:
        """Clear SW_RESET_N bit 3, wait for the gated reset, restore, wait for an OKAY read."""
        bit = SW_RESET_N_BIT["hmac"]
        await self.swrst.park("hmac")
        for _ in range(2_000):
            if self.rd(dut.hmac_gated_rst_n_probe_o) == 0:
                break
            await ClockCycles(dut.clk_i, 1)
        else:
            raise AssertionError("hmac_gated_rst_n_probe_o did not go active within 2000 clocks")
        await self.swrst.release("hmac")
        assert self.swrst.value == SW_RESET_BASELINE, f"SW_RESET_N 0x{self.swrst.value:x} bit {bit}"
        for _ in range(200):
            seq = SepAxiAccessSeq(
                "hmac_status",
                op=SepAxiOp.READ,
                addr=HMAC_STATUS,
                size=2,
                allow_ungraded_read_resp=True,
            )
            await self.start_seq(seq)
            if seq.resp_ok:
                return
            await ClockCycles(dut.clk_i, 10)
        raise AssertionError("HMAC STATUS read not OKAY within 200 tries after the reset")

    async def _write_msg(self, msg: bytes) -> None:
        """Whole words as 32-bit writes, a tail as one-byte writes (lane order, endian_swap 0)."""
        whole = len(msg) - len(msg) % 4
        for i in range(0, whole, 4):
            await self._wr(HMAC_MSG_FIFO, int.from_bytes(msg[i : i + 4], "little"))
        for b in msg[whole:]:
            await self._wr(HMAC_MSG_FIFO, b, length=1)

    async def _write_msg_logged(self, msg: bytes) -> int:
        """Write ``msg`` as ``_write_msg`` does; return the count of non-OKAY write responses.

        The register text does not state the response of a message write after a blocked
        start, so the count is logged only.
        """
        refused = 0
        whole = len(msg) - len(msg) % 4
        beats = [(int.from_bytes(msg[i : i + 4], "little"), 4) for i in range(0, whole, 4)]
        beats += [(b, 1) for b in msg[whole:]]
        for data, length in beats:
            seq = SepAxiAccessSeq(
                "hmac_wr",
                op=SepAxiOp.WRITE,
                addr=HMAC_MSG_FIFO,
                wdata=data,
                length=length,
                size={4: 2, 1: 0}[length],
            )
            await self.start_seq(seq)
            refused += int(not seq.resp_ok)
        return refused

    async def _write_key_row(self, row: int) -> None:
        for i, word in enumerate(_row_words(row)):
            assert i < HMAC_NUM_PUBLIC_KEY
            await self._wr(HMAC_KEY_0 + 4 * i, word)

    async def _read_digest(self, sha: int) -> tuple[int, ...]:
        return tuple([await self._rd(HMAC_DIGEST_0 + 4 * i) for i in range(HMAC_DIGEST_WORDS[sha])])

    async def _poll_done(self, t0: int, bound: int) -> int | None:
        """Clocks from ``t0`` to the first INTR_STATE read with hmac_done; None on timeout."""
        while True:
            intr = await self._rd(HMAC_INTR_STATE) & INTR_FIELDS
            now = self._now_clk()
            if intr & HMAC_INTR_DONE:
                return now - t0
            if now - t0 > bound:
                return None

    async def _run_hash(self, h: Hash, *, bound: int) -> tuple[int | None, tuple[int, ...]]:
        """CFG, KEY, hash_start, message, hash_process, poll done, read DIGEST, W1C done."""
        await self._wr(HMAC_CFG, h.cfg())
        if h.hmac_en:
            await self._write_key_row(h.row)
        await self._wr(HMAC_CMD, HMAC_CMD_HASH_START)
        t0 = self._now_clk()
        await self._write_msg(h.msg)
        await self._wr(HMAC_CMD, HMAC_CMD_HASH_PROCESS)
        t_done = await self._poll_done(t0, bound)
        digest = await self._read_digest(h.sha)
        await self._wr(HMAC_INTR_STATE, HMAC_INTR_DONE)
        return t_done, digest

    async def _pre_class(self, step: ClassStep) -> None:
        """Clear both events, log hmac_idle, and read INTR_STATE as 0 before the class."""
        await self._wr(HMAC_INTR_STATE, HMAC_INTR_DONE | HMAC_INTR_ERR)
        status = await self._rd(HMAC_STATUS)
        self.chk.obs(
            "HMAC-IDLE",
            **{"class": step.name},
            phase="before",
            idle=int(bool(status & HMAC_STATUS_IDLE)),
        )
        intr = await self._rd(HMAC_INTR_STATE) & INTR_FIELDS
        self.chk.ctrl(
            "HMAC-PRESTATE",
            (intr & (HMAC_INTR_DONE | HMAC_INTR_ERR)) == 0,
            **{"class": step.name},
            intr=f"0x{intr:x}",
        )

    async def _blocked_class(self, step: ClassStep, last: Hash) -> Hash:
        nwords = HMAC_DIGEST_WORDS[last.sha]
        d_prev = await self._read_digest(last.sha)
        self.chk.ctrl(
            "HMAC-DPREV",
            self._eq(d_prev, last.golden) and any(d_prev),
            **{"class": step.name},
            d_prev=f"0x{d_prev[0]:08x}",
            golden=f"0x{last.golden[0]:08x}",
            words=nwords,
        )

        # Error injection: a start with the blocked digest_size, key_length and hmac_en.
        open_graded_window(TEST, self.logger)
        await self._wr(HMAC_CFG, cfg_word(step.digest_code, step.key_code, step.hmac_en))
        if step.hmac_en:
            await self._write_key_row(step.row)
        await self._wr(HMAC_CMD, HMAC_CMD_HASH_START)
        t0 = self._now_clk()
        hold = self.hold
        await ClockCycles(cocotb.top.clk_i, hold)
        # "Signalled": the error state and code, read before any message write so that
        # only the start can have set them.
        intr = await self._rd(HMAC_INTR_STATE) & INTR_FIELDS
        status = await self._rd(HMAC_STATUS)
        err_code = await self._rd(HMAC_ERR_CODE)
        # "Blocked": the stimulus of a legal hash (message, then hash_process), which
        # sets hmac_done within t_clean in CTRL-HMAC-REF and CTRL-HMAC-NOBLOCK. A started
        # engine sets hmac_done in the hold and changes DIGEST; a blocked one does neither.
        rec = step.recovery
        assert rec is not None
        refused = await self._write_msg_logged(rec.msg)
        await self._wr(HMAC_CMD, HMAC_CMD_HASH_PROCESS)
        await ClockCycles(cocotb.top.clk_i, hold)
        intr_proc = await self._rd(HMAC_INTR_STATE) & INTR_FIELDS
        window_clk = self._now_clk() - t0
        await self._wr(HMAC_CFG, last.cfg())
        digest = await self._read_digest(last.sha)
        err = int(bool(intr & HMAC_INTR_ERR))
        done = int(bool((intr | intr_proc) & HMAC_INTR_DONE))
        unchanged = int(digest == d_prev)
        self.chk.ok(
            "HMAC-BLOCK",
            err == 1 and done == 0 and unchanged == 1,
            **{"class": step.name},
            digest=f"0b{step.digest_code:04b}",
            keylen=f"0b{step.key_code:06b}",
            hmac_en=step.hmac_en,
            err=err,
            done=done,
            digest_unchanged=unchanged,
            d_prev=f"0x{d_prev[0]:08x}",
            digest0=f"0x{digest[0]:08x}",
            msg_len=len(rec.msg),
            process_written=1,
            window_clk=window_clk,
            hold=hold,
            t_clean=self.t_clean,
        )
        self.chk.obs("HMAC-ERRCODE", **{"class": step.name}, err_code=f"0x{err_code:x}")
        self.chk.obs("HMAC-BLOCKED-MSG-RESP", **{"class": step.name}, refused=refused)
        self.chk.obs(
            "HMAC-IDLE",
            **{"class": step.name},
            phase="blocked",
            idle=int(bool(status & HMAC_STATUS_IDLE)),
        )

        # Recovery: the write-one clear is graded; the recovery hash runs with the window closed.
        await self._wr(HMAC_INTR_STATE, HMAC_INTR_ERR)
        intr2 = await self._rd(HMAC_INTR_STATE) & INTR_FIELDS
        close_graded_window(self.logger)
        t_rec, rdigest = await self._run_hash(rec, bound=self.hash_bound)
        err_cleared = int(not (intr2 & HMAC_INTR_ERR))
        rec_eq = self._eq(rdigest, rec.golden)
        self.chk.ok(
            "HMAC-RECOVER",
            err_cleared == 1 and t_rec is not None and rec_eq and rdigest != d_prev,
            **{"class": step.name},
            err_cleared=err_cleared,
            sha=rec.sha,
            klen=rec.key_bits,
            digest_eq_golden=int(rec_eq),
            digest_changed=int(rdigest != d_prev),
            t_done=t_rec if t_rec is not None else "timeout",
            bound=self.hash_bound,
        )
        if t_rec is None:
            await self._reset_hmac(cocotb.top)
        return rec

    async def _legal_class(self, step: ClassStep) -> Hash:
        h = step.legal
        assert h is not None
        t_done, digest = await self._run_hash(h, bound=self.hash_bound)
        intr = await self._rd(HMAC_INTR_STATE) & INTR_FIELDS
        eq = self._eq(digest, h.golden)
        self.chk.ctrl(
            "HMAC-NOBLOCK",
            t_done is not None and eq and not (intr & HMAC_INTR_ERR),
            **{"class": step.name},
            digest=h.sha,
            keylen=h.key_bits if h.key_bits is not None else "none",
            hmac_en=h.hmac_en,
            err=int(bool(intr & HMAC_INTR_ERR)),
            done=int(t_done is not None),
            digest_eq_golden=int(eq),
            bound=self.hash_bound,
        )
        if t_done is None:
            await self._reset_hmac(cocotb.top)
        return h
