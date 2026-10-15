# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The HMAC message FIFO reports its occupancy, back-pressures a full write and loses no word.

RAND-REP, ``no_cpu``. The leaf drives the HMAC engine over the CPU-LSU master. On every seed it
runs the same plan shape in drawn orders:

    25 length cells   SHA-256 with 0, 1, 3, 4, 55, 56, 63, 64, 65, 200 and 1000 bytes;
                      SHA-384 and SHA-512 with 111, 112, 127, 128, 129, 200 and 1000 bytes;
                      plain SHA-2 or HMAC and the write mode drawn per cell
    3 stalled legs    one per write mode (burst of back-to-back single-beat writes, single
                      writes with a drawn gap, single-byte writes): the FIFO fills under the
                      drain stall, a later beat is held, the stall is released, the
                      1000-byte message completes
    2 fifo_empty legs a FIFO that was full, and a FIFO that never reaches full
    1 wipe leg        ``WIPE_SECRET`` overwrites the digest and the secret key

The drain stall is the bench input ``hmac_fifo_drain_stall_i``: it holds the read side of the
message FIFO idle (``tb/tb_top.sv``, HMAC message-FIFO drain stall).

Spec: ``vendor/lowRISC/opentitan/overlay/regs/hmac/regs/gen/adoc/hmac.adoc`` (``INTR_STATE``
:45-49 ``fifo_empty`` needs a FIFO that has been full and a FIFO that software can still
write; ``CFG``:120 ``endian_swap`` = 0 adds each value in little-endian byte order; ``STATUS``
:157-160 ``fifo_depth``, ``fifo_full`` with back-pressure on the interconnect, ``fifo_empty``)
and ``vendor/lowRISC/opentitan/upstream/hw/ip/hmac/data/hmac.hjson`` (``WIPE_SECRET``:420-425,
the written value overwrites the secret key and the digest and is duplicated into each 64-bit
word; ``KEY``:446, ``KEY_0`` is the most-significant key word).

Checkers:
  CHK-HMAC-STATUS        on every ``STATUS`` sample ``fifo_empty`` = 1 iff ``fifo_depth`` = 0,
                         ``fifo_full`` = 1 implies ``fifo_empty`` = 0, and no not-full sample
                         reports a depth above a full sample of the seed
  CHK-HMAC-BACKPRESSURE-HOLD
                         with the drain stall held and ``fifo_full`` read 1, one of the next
                         ``BP_BEAT_BOUND`` beats gets no write response for 16 times the clean
                         write latency; after the release every beat completes OKAY and the
                         digest equals the golden of the whole message
  CHK-HMAC-MSG           the digest equals the software golden of the whole message
  CHK-HMAC-FIFOEMPTY     ``INTR_STATE.fifo_empty`` reads 1 after a full FIFO drains and 0 for a
                         FIFO that was never full, both before ``hash_process``
  CHK-HMAC-WIPE          after a write of w to ``WIPE_SECRET`` every DIGEST word reads w, and
                         the next HMAC with no ``KEY`` write hashes with an all-w key
  CHK-HMAC-NARROW-WRITE  one fixed SHA-256 message written with 8-bit writes at byte lanes
                         1, 2 and 3 and 16-bit writes at byte lane 2 of the ``MSG_FIFO``
                         window: every write completes OKAY and the digest equals the golden
                         of the bytes in write order (``hmac.hjson``:526-529, ``MSG_FIFO``
                         ``byte-write: "true"``; only address bits [1:0] matter to a write
                         in the window). It runs once per seed, last, after an HMAC reset,
                         with the graded FCOV window closed.

The measurement run of each stalled leg counts the writes until a ``STATUS`` read after each
write shows ``fifo_full`` = 1 (N). The graded run posts N writes, reads ``fifo_full`` = 1 and
issues the next beats one at a time until one is held. The register text states that data
written to the FIFO whilst it is full is back-pressured (``hmac.adoc``:159), but a byte packer
sits in front of the FIFO and the text does not state which write is held. The index of the
held beat is therefore log-only (``OBS-BLOCKED CHK-HMAC-BACKPRESSURE`` and
``OBS-HMAC-BP-HOLD-BEAT``); the graded part is a hold within ``BP_BEAT_BOUND`` beats and no
lost data. The measurement run issues up to ``PROBE_EXTRA_MAX`` more writes with the stall
held and logs how many complete; that count is not graded.

DIGEST byte order: the register text settles the register order (DIGEST_0 holds digest bytes
0..3) and the ``digest_swap`` swap (``hmac.adoc``:116-117), not the byte order of a word at
``digest_swap`` = 0. Every digest-to-golden compare of the leaf accepts the big-endian or the
little-endian read of each word, with one order for every readback of the seed
(``env/sep_hmac_golden.py`` ``SepDigestOrder``); the order is logged as
``OBS-HMAC-DIGEST-ORDER``. The all-w DIGEST read of CHK-HMAC-WIPE compares register words with
the written register value w and does not depend on the digest byte order.

Controls: ``CTRL-HMAC-STALL-FULL`` (a stalled leg reads ``fifo_full`` = 1),
``CTRL-HMAC-BP-CLEAN`` (a beat into a FIFO that is not full completes), ``CTRL-HMAC-LENGTHS``
(every length cell ran), ``CTRL-HMAC-FE-DEPTH`` (the not-full leg writes fewer words than the
depth at full), ``CTRL-HMAC-WIPE-PRE`` (DIGEST before the wipe equals the golden and differs
from w). Log-only: ``OBS-HMAC-IDLE`` (``STATUS.hmac_idle``; the register text gives only its
reset value), ``OBS-HMAC-STALL-N`` (N and the count of writes that the measurement run
completes with the stall held), ``OBS-HMAC-BP-HOLD-BEAT`` (index of the held beat, beats
accepted after ``fifo_full`` reads 1, ``no_resp_clk``, ``hold_clk``).
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from env.sep_axi_agent import SepAxiOp
from env.sep_chk_log import SepChkLog
from env.sep_crypto_kat_rows import RFC4231_KEYS
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_hmac_golden import SepDigestOrder, digest_words, hmac_sha2_bytes, sha2_bytes
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import HMAC
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq, capture_resp_handshake, take_handshake
from seq_lib.sep_hmac_seq import (
    HMAC_CMD,
    HMAC_CMD_HASH_PROCESS,
    HMAC_CMD_HASH_START,
    HMAC_DIGEST_0,
    HMAC_DIGEST_WORDS,
    HMAC_ILLEGAL_KEYED,
    HMAC_INTR_DONE,
    HMAC_INTR_STATE,
    HMAC_KEY_0,
    HMAC_KEY_LENGTH,
    HMAC_MSG_FIFO,
    HMAC_STATUS,
    SepHmac,
    build_cfg,
)
from seq_lib.sep_sw_reset_seq import SepSwReset

TEST = "sep_hmac_fifo_stream_rand_test"

# SW_RESET_N baseline: every engine released except the Key Manager (bit 0)
# (hw/sys/sep/regs/gen/adoc/blocks/sep_reset_ctrl.adoc).
SW_RESET_BASELINE = 0x7E

HMAC_WIPE_SECRET = HMAC.addr("WIPE_SECRET")
ST_IDLE = HMAC.field_mask("STATUS", "hmac_idle")
ST_EMPTY = HMAC.field_mask("STATUS", "fifo_empty")
ST_FULL = HMAC.field_mask("STATUS", "fifo_full")
ST_DEPTH = HMAC.field_mask("STATUS", "fifo_depth")
ST_DEPTH_LSB = HMAC.field_lsb("STATUS", "fifo_depth")
ST_FIELDS = ST_IDLE | ST_EMPTY | ST_FULL | ST_DEPTH
ST_RESET_IDLE = HMAC.field_reset("STATUS", "hmac_idle")
ST_RESET_EMPTY = HMAC.field_reset("STATUS", "fifo_empty")
INTR_FIFO_EMPTY = HMAC.field_mask("INTR_STATE", "fifo_empty")
INTR_FIELDS = HMAC_INTR_DONE | INTR_FIFO_EMPTY | HMAC.field_mask("INTR_STATE", "hmac_err")

# Length cells (bytes) per digest size. The SHA-256 block is 64 bytes and the SHA-384/512
# block is 128 bytes; the lengths sit on, below and above the padding and block edges.
LEN_CELLS: tuple[tuple[int, int], ...] = tuple(
    [(256, n) for n in (0, 1, 3, 4, 55, 56, 63, 64, 65, 200, 1000)]
    + [(sha, n) for sha in (384, 512) for n in (111, 112, 127, 128, 129, 200, 1000)]
)
MODES = ("burst", "gap", "byte")
STALL_MSG_BYTES = 1000

# HMAC keys of the RFC 4231 test cases 1 to 6 (env/sep_crypto_kat_rows.py). A row is
# zero-padded or cut to the 128 bytes of the 32 KEY registers; KEY_0 holds the first four
# bytes, big-endian (hmac.hjson:446).
_RFC4231_KEYS = RFC4231_KEYS
KEY_ROWS: tuple[tuple[int, ...], ...] = tuple(
    tuple(int.from_bytes(k.ljust(128, b"\0")[:128][i : i + 4], "big") for i in range(0, 128, 4))
    for k in _RFC4231_KEYS
)

# Outer limits of clean-time measurements only; never a contract.
DONE_BOUND = 200_000
DRAIN_BOUND = 50_000
RESET_BOUND = 2_000
CLEAN_BOUND = 2_000  # clocks for one beat into a FIFO that is not full
PROBE_EXTRA_MAX = 8  # log-only writes after fifo_full reads 1 in the measurement run
# Fixed narrow-lane message of CHK-HMAC-NARROW-WRITE: (byte lane, width in bytes) per write
# and the value of each write. The bytes join the message in write order, each value in
# little-endian byte order (endian_swap = 0).
NARROW_WRITES = ((1, 1), (2, 1), (3, 1), (2, 2), (1, 1), (3, 1), (2, 2), (3, 1))
NARROW_VALUES = (0xA1, 0xB2, 0xC3, 0xE5D4, 0xF6, 0x17, 0x3928, 0x4A)
AXSIZE = {1: 0, 2: 1, 4: 2}
# Most beats issued after fifo_full reads 1 before one must be held. The register text gives
# no packer capacity, so this is a generous fixed bound, logged as bound=.
BP_BEAT_BOUND = 16


def legal_key_bits(sha: int) -> list[int]:
    return [k for k in HMAC_KEY_LENGTH if (sha, k) not in HMAC_ILLEGAL_KEYED]


def golden_digest(sha: int, hmac_en: bool, key_words, key_bits: int | None, msg: bytes) -> bytes:
    """Digest bytes of the hash; a DIGEST readback is graded with ``SepDigestOrder``."""
    if hmac_en:
        assert key_bits is not None
        key = b"".join(w.to_bytes(4, "big") for w in key_words[: key_bits // 32])
        out = hmac_sha2_bytes(key, msg, sha)
    else:
        out = sha2_bytes(msg, sha)
    assert len(out) == HMAC_DIGEST_WORDS[sha] * 4
    return out


def chunks(msg: bytes, mode: str) -> list[tuple[int, int]]:
    """The writes of a message as (byte count, value). Lane order little-endian (endian_swap 0).

    Burst and gap modes write whole words as 32-bit beats and a tail as one-byte beats.
    """
    if mode == "byte":
        return [(1, b) for b in msg]
    whole = len(msg) - len(msg) % 4
    out = [(4, int.from_bytes(msg[i : i + 4], "little")) for i in range(0, whole, 4)]
    out += [(1, b) for b in msg[whole:]]
    return out


@dataclass
class Hash:
    sha: int
    hmac_en: bool
    key_row: int
    key_bits: int | None

    def tag(self) -> str:
        return f"sha{self.sha}/{'hmac' if self.hmac_en else 'plain'}/k{self.key_bits}"


@dataclass
class Cell:
    h: Hash
    length: int
    mode: str
    gap: int
    rb: int
    msg: bytes


@dataclass
class StallLeg:
    h: Hash
    mode: str
    gap: int
    rb: int
    msg: bytes
    probe: bytes


@dataclass
class FeLeg:
    h: Hash
    probe: bytes


@dataclass
class WipeLeg:
    h: Hash
    msg1: bytes
    msg2: bytes
    w: int


@dataclass
class Plan:
    cells: list[Cell]
    stall: list[StallLeg]
    fe_full: FeLeg
    fe_notfull: FeLeg
    wipe: WipeLeg


def _unique_msg(rng: SepSeededRng, nbytes: int) -> bytes:
    """Message bytes from 32-bit words that are unique and non-zero (the MSG_FIFO reset value)."""
    words: list[int] = []
    seen: set[int] = set()
    while len(words) * 4 < nbytes:
        w = rng.getrandbits(32)
        if w and w not in seen:
            seen.add(w)
            words.append(w)
    return b"".join(w.to_bytes(4, "little") for w in words)[:nbytes]


def _draw_hash(rng: SepSeededRng, sha: int | None = None, hmac_en: bool | None = None) -> Hash:
    if sha is None:
        sha = rng.choice((256, 384, 512))
    if hmac_en is None:
        hmac_en = bool(rng.choice((0, 1)))
    key_row = rng.randrange(len(KEY_ROWS))
    key_bits = rng.choice(legal_key_bits(sha)) if hmac_en else None
    return Hash(sha, hmac_en, key_row, key_bits)


def draw_plan(seed: int) -> Plan:
    """Every draw of the leaf, in a fixed order, as a pure function of the seed."""
    rng = SepSeededRng(seed)
    order = list(range(len(LEN_CELLS)))
    rng.shuffle(order)
    cells = []
    for idx in order:
        sha, length = LEN_CELLS[idx]
        mode = rng.choice(MODES)
        gap = rng.randrange(0, 201)
        rb = rng.randrange(1, 9)
        h = _draw_hash(rng, sha=sha)
        cells.append(Cell(h, length, mode, gap, rb, _unique_msg(rng, length)))
    modes = list(MODES)
    rng.shuffle(modes)
    stall = []
    for mode in modes:
        h = _draw_hash(rng)
        gap = rng.randrange(0, 201)
        rb = rng.randrange(1, 9)
        msg = _unique_msg(rng, STALL_MSG_BYTES)
        probe = _unique_msg(rng, STALL_MSG_BYTES)
        stall.append(StallLeg(h, mode, gap, rb, msg, probe))
    fe_full = FeLeg(_draw_hash(rng), _unique_msg(rng, STALL_MSG_BYTES))
    fe_notfull = FeLeg(_draw_hash(rng), _unique_msg(rng, 8))
    wh = _draw_hash(rng, hmac_en=True)
    msg1 = _unique_msg(rng, rng.randrange(1, 257))
    msg2 = _unique_msg(rng, rng.randrange(1, 257))
    g1 = golden_digest(wh.sha, True, KEY_ROWS[wh.key_row], wh.key_bits, msg1)
    d1 = digest_words(g1, "be") + digest_words(g1, "le")
    while True:
        w = int.from_bytes(bytes(rng.sample(range(256), 4)), "big")
        if w not in d1:
            break
    return Plan(cells, stall, fe_full, fe_notfull, WipeLeg(wh, msg1, msg2, w))


class _TrialTimeout(Exception):
    """A bounded wait inside a trial expired; ``owner`` is the check that owns the wait."""

    def __init__(self, owner: str, bound: int, what: str) -> None:
        super().__init__(f"{owner} {what} bound={bound}")
        self.owner = owner
        self.bound = bound
        self.what = what


@pyuvm.test()
class sep_hmac_fifo_stream_rand_test(sep_base_test):
    """HMAC FIFO status, back-pressure, long messages, fifo_empty interrupt and secret wipe."""

    required_evidence = (
        "CHK-HMAC-STATUS",
        "CHK-HMAC-BACKPRESSURE-HOLD",
        "CHK-HMAC-MSG",
        "CHK-HMAC-FIFOEMPTY",
        "CHK-HMAC-WIPE",
        "CHK-HMAC-NARROW-WRITE",
    )

    async def run_scenario(self) -> None:
        seed = self.random_seed()
        plan = draw_plan(seed)
        self.chk = SepChkLog(self, TEST, seed)
        self.digest_order = SepDigestOrder()
        self.logger.info(
            "PLAN seed=%d cells=[%s] stalled=[%s] fe_full=%s fe_notfull=%s wipe=%s/w=0x%08x/"
            "len1=%d/len2=%d",
            seed,
            ",".join(
                f"{c.h.tag()}:{c.length}:{c.mode}:gap{c.gap}:rb{c.rb}:row{c.h.key_row}"
                for c in plan.cells
            ),
            ",".join(f"{s.mode}:{s.h.tag()}:gap{s.gap}:rb{s.rb}" for s in plan.stall),
            plan.fe_full.h.tag(),
            plan.fe_notfull.h.tag(),
            plan.wipe.h.tag(),
            plan.wipe.w,
            len(plan.wipe.msg1),
            len(plan.wipe.msg2),
        )

        await self.bring_up_no_cpu()
        self.dut = cocotb.top
        self._period_ps = round(self.cfg.sys_clk_period_ns * 1000)
        self.hmac = SepHmac(self)
        self.swrst = SepSwReset(self)
        self.swrst.value = SW_RESET_BASELINE
        await self.swrst.release("hmac")
        self.logger.info("SW_RESET_N baseline=0x%02x", SW_RESET_BASELINE)
        self.dut.hmac_fifo_drain_stall_i.value = 0

        self.samples: list[tuple[str, int, int, int]] = []
        self.depth_at_full: int | None = None
        self.ran_lengths: set[tuple[int, int]] = set()

        # Reset values of STATUS (RDL reset: fifo_empty = 1, hmac_idle = 1).
        await self._reset_hmac()
        await self._status("idle", expect_reset=True)

        for i, cell in enumerate(plan.cells):
            await self._trial(self._cell_leg(cell), cell=i, len=cell.length, mode=cell.mode)
        for leg in plan.stall:
            await self._trial(self._stall_leg(leg), leg="stalled", mode=leg.mode)
        d_full = None
        try:
            d_full = await self._fe_full_leg(plan.fe_full)
        except _TrialTimeout as t:
            await self._timeout_fail(t, leg="full")
        if d_full is not None:
            await self._trial(self._fe_notfull_leg(plan.fe_notfull, d_full), leg="notfull")
        await self._trial(self._wipe_leg(plan.wipe), leg="wipe")

        # Cross-sample relation: a depth read with fifo_full = 0 never exceeds a depth read
        # with fifo_full = 1 (hmac.adoc:157-159).
        full_depths = [d for _, d, f, _ in self.samples if f]
        notfull_depths = [d for _, d, f, _ in self.samples if not f]
        self.chk.ctrl(
            "HMAC-STALL-FULL", bool(full_depths), phase="all", full_samples=len(full_depths)
        )
        if full_depths:
            self.chk.ok(
                "HMAC-STATUS",
                max(notfull_depths, default=0) <= min(full_depths),
                phase="all",
                samples=len(self.samples),
                max_notfull_depth=max(notfull_depths, default=0),
                min_full_depth=min(full_depths),
            )
        self.chk.ctrl(
            "HMAC-LENGTHS",
            self.ran_lengths == set(LEN_CELLS),
            ran=len(self.ran_lengths),
            cells=len(LEN_CELLS),
        )

        await self._reset_hmac()
        close_graded_window(self.logger)
        await self._narrow_write_leg()
        self.chk.obs("HMAC-DIGEST-ORDER", **self.digest_order.fields())
        self.chk.finish()

    async def _narrow_write_leg(self) -> None:
        """CHK-HMAC-NARROW-WRITE: the fixed message at byte lanes 1 to 3, plain SHA-256.

        The graded FCOV window stays closed. A bounded wait that expires is a FAIL of this
        check, then an HMAC reset.
        """
        msg = b"".join(v.to_bytes(w, "little") for (_, w), v in zip(NARROW_WRITES, NARROW_VALUES))
        golden = golden_digest(256, False, KEY_ROWS[0], None, msg)
        n_words = len(golden) // 4
        tag = dict(
            sha=256,
            len=len(msg),
            lanes_widths=",".join(f"{lane}/{w}" for lane, w in NARROW_WRITES),
        )
        await self._reset_hmac()
        await self._wr(HMAC.addr("CFG"), build_cfg(hmac_en=False, sha_bits=256, key_bits=None))
        await self._wr(HMAC_CMD, HMAC_CMD_HASH_START)
        refused: list[str] = []
        for (lane, width), value in zip(NARROW_WRITES, NARROW_VALUES):
            seq = SepAxiAccessSeq(
                "hmac_msg_narrow_wr",
                op=SepAxiOp.WRITE,
                addr=HMAC_MSG_FIFO + lane,
                wdata=value,
                length=width,
                size=AXSIZE[width],
                # The check grades the response of each write.
                allow_unverified_write_resp=True,
            )
            await self.start_seq(seq)
            if not seq.resp_ok:
                refused.append(f"{lane}/{width}/{seq.resp_code}")
        await self._wr(HMAC_CMD, HMAC_CMD_HASH_PROCESS)
        t0 = self._now_clk()
        done = False
        while True:
            if await self._rd(HMAC_INTR_STATE) & HMAC_INTR_DONE:
                done = True
                break
            if self._now_clk() - t0 > DONE_BOUND:
                break
            await ClockCycles(self.dut.clk_i, 10)
        got = [await self._rd(HMAC_DIGEST_0 + 4 * i) for i in range(n_words)] if done else []
        match = bool(got) and self.digest_order.match(got, golden)[0]
        self.chk.ok(
            "HMAC-NARROW-WRITE",
            done and not refused and match,
            **tag,
            writes=len(NARROW_WRITES),
            all_okay=int(not refused),
            refused_lane_width_resp=",".join(refused) or "-",
            digest_eq_golden=int(match),
            digest0=f"0x{got[0]:08x}" if got else "none",
            golden0=f"0x{self.digest_order.expected(golden)[0]:08x}",
            **({} if done else {"reason": "timeout", "bound": DONE_BOUND}),
        )
        await self._reset_hmac()

    # ------------------------------------------------------------------ helpers

    def _now_clk(self) -> int:
        return int(get_sim_time("ps")) // self._period_ps

    async def _trial(self, coro, **fields) -> None:
        try:
            await coro
        except _TrialTimeout as t:
            await self._timeout_fail(t, **fields)

    async def _timeout_fail(self, t: _TrialTimeout, **fields) -> None:
        self.chk.ok(t.owner, False, reason="timeout", wait=t.what, bound=t.bound, **fields)
        self.dut.hmac_fifo_drain_stall_i.value = 0
        await self._reset_hmac()

    async def _reset_hmac(self) -> None:
        """Clear SW_RESET_N bit 3, wait for the gated reset, restore, wait for an OKAY read."""
        close_graded_window(self.logger)
        dut = self.dut
        await self.swrst.park("hmac")
        for _ in range(RESET_BOUND):
            if self.rd(dut.hmac_gated_rst_n_probe_o) == 0:
                break
            await ClockCycles(dut.clk_i, 1)
        else:
            raise AssertionError(f"hmac_gated_rst_n_probe_o not active within {RESET_BOUND} clocks")
        await self.swrst.release("hmac")
        assert self.swrst.value == SW_RESET_BASELINE, f"SW_RESET_N 0x{self.swrst.value:x}"
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

    def _open(self) -> None:
        open_graded_window(TEST, self.logger)

    async def _rd(self, addr: int) -> int:
        return await self.hmac._rd(addr)

    async def _wr(self, addr: int, data: int) -> None:
        await self.hmac._wr(addr, data)

    def _msg_seq(self, n: int, value: int) -> SepAxiAccessSeq:
        return SepAxiAccessSeq(
            "hmac_msg_wr",
            op=SepAxiOp.WRITE,
            addr=HMAC_MSG_FIFO,
            wdata=value,
            length=n,
            size={4: 2, 1: 0}[n],
        )

    async def _wr_chunk(self, n: int, value: int) -> None:
        seq = self._msg_seq(n, value)
        await self.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError(f"HMAC MSG_FIFO write of {n} byte(s) not OKAY")

    async def _timed_write(self, n: int, value: int) -> int:
        """Clocks from the issue of a beat to its write response (at least 1)."""
        cap = cocotb.start_soon(capture_resp_handshake("b"))
        t0 = int(get_sim_time("ps"))
        await self._wr_chunk(n, value)
        t1 = take_handshake(cap)
        if t1 is None:
            raise AssertionError("no B handshake seen for a completed MSG_FIFO write")
        return max(1, round((t1 - t0) / self._period_ps))

    async def _status(self, phase: str, *, expect_reset: bool = False) -> dict:
        """Read STATUS and grade one sample (hmac.adoc:157-160)."""
        raw = await self._rd(HMAC_STATUS)
        st = {
            "depth": (raw & ST_DEPTH) >> ST_DEPTH_LSB,
            "full": int(bool(raw & ST_FULL)),
            "empty": int(bool(raw & ST_EMPTY)),
            "idle": int(bool(raw & ST_IDLE)),
        }
        if st["full"] and self.depth_at_full is None:
            self.depth_at_full = st["depth"]
        cond = st["empty"] == int(st["depth"] == 0) and not (st["full"] and st["empty"])
        extra = {}
        if expect_reset:
            cond = cond and st["empty"] == ST_RESET_EMPTY and st["idle"] == ST_RESET_IDLE
            extra = {"reset_empty": ST_RESET_EMPTY, "reset_idle": ST_RESET_IDLE}
        self.chk.ok(
            "HMAC-STATUS",
            cond,
            phase=phase,
            depth=st["depth"],
            full=st["full"],
            empty=st["empty"],
            idle=st["idle"],
            rsvd=f"0x{raw & ~ST_FIELDS & 0xFFFF_FFFF:x}",
            **extra,
            **{"OBS-depth_at_full": "na" if self.depth_at_full is None else self.depth_at_full},
        )
        self.chk.obs("HMAC-IDLE", phase=phase, idle=st["idle"])
        self.samples.append((phase, st["depth"], st["full"], st["empty"]))
        return st

    async def _setup(self, h: Hash) -> None:
        """CFG (sha_en = 1), the 32 KEY words of the row in HMAC mode, then hash_start."""
        await self._wr(
            HMAC.addr("CFG"), build_cfg(hmac_en=h.hmac_en, sha_bits=h.sha, key_bits=h.key_bits)
        )
        if h.hmac_en:
            for i, word in enumerate(KEY_ROWS[h.key_row]):
                await self._wr(HMAC_KEY_0 + 4 * i, word)
        await self._wr(HMAC_CMD, HMAC_CMD_HASH_START)

    async def _write_msg(
        self, ch: list[tuple[int, int]], mode: str, gap: int, rb: int, phase: str
    ) -> None:
        for i, (n, v) in enumerate(ch):
            await self._wr_chunk(n, v)
            if mode == "gap" and gap:
                await ClockCycles(self.dut.clk_i, gap)
            if (i + 1) % rb == 0:
                await self._status(phase)

    async def _finish(self, sha: int, owner: str) -> list[int]:
        """hash_process, poll hmac_done, STATUS sample, read DIGEST, W1C hmac_done."""
        await self._wr(HMAC_CMD, HMAC_CMD_HASH_PROCESS)
        t0 = self._now_clk()
        while not (await self._rd(HMAC_INTR_STATE) & HMAC_INTR_DONE):
            if self._now_clk() - t0 > DONE_BOUND:
                raise _TrialTimeout(owner, DONE_BOUND, "hmac_done")
            await ClockCycles(self.dut.clk_i, 10)
        await self._status("idle")
        digest = [await self._rd(HMAC_DIGEST_0 + 4 * i) for i in range(HMAC_DIGEST_WORDS[sha])]
        await self._wr(HMAC_INTR_STATE, HMAC_INTR_DONE)
        return digest

    def _grade_msg(self, h: Hash, msg: bytes, mode: str, digest: list[int]) -> None:
        golden = golden_digest(h.sha, h.hmac_en, KEY_ROWS[h.key_row], h.key_bits, msg)
        ok, _ = self.digest_order.match(digest, golden)
        self.chk.ok(
            "HMAC-MSG",
            ok,
            len=len(msg),
            mode=mode,
            sha=h.sha,
            hmac_en=int(h.hmac_en),
            key_bits=h.key_bits,
            **{"digest==golden": int(ok)},
            digest0=f"0x{digest[0]:08x}",
            golden0=f"0x{self.digest_order.expected(golden)[0]:08x}",
        )

    async def _drain(self, bound: int, owner: str) -> int:
        """Read STATUS until fifo_depth reads 0; return the clocks from the call. One read at least."""
        t0 = self._now_clk()
        while True:
            st = await self._status("drain")
            if st["depth"] == 0:
                return self._now_clk() - t0
            if self._now_clk() - t0 > bound:
                raise _TrialTimeout(owner, bound, "fifo_depth==0")

    async def _held_write(self, n: int, v: int):
        """Issue a beat as a task. Returns (task, seq, B-capture task, issue time in ps)."""
        cap = cocotb.start_soon(capture_resp_handshake("b"))
        seq = self._msg_seq(n, v)
        t0 = int(get_sim_time("ps"))
        task = cocotb.start_soon(self.start_seq(seq))
        return task, seq, cap, t0

    async def _wait_task(self, task, bound: int) -> bool:
        for _ in range(bound + 1):
            if task.done():
                return True
            await RisingEdge(self.dut.clk_i)
        return task.done()

    # ------------------------------------------------------------------ legs

    async def _cell_leg(self, c: Cell) -> None:
        await self._reset_hmac()
        self._open()
        await self._setup(c.h)
        await self._write_msg(chunks(c.msg, c.mode), c.mode, c.gap, c.rb, "run")
        digest = await self._finish(c.h.sha, "HMAC-MSG")
        self._grade_msg(c.h, c.msg, c.mode, digest)
        self.ran_lengths.add((c.h.sha, c.length))

    async def _probe_n(self, leg: StallLeg) -> int | None:
        """Measurement run: N, the count of writes until ``STATUS`` reads ``fifo_full`` = 1.

        The writes that complete after that read with the stall held are logged only.
        """
        dut = self.dut
        await self._reset_hmac()
        await self._setup_stalled(leg.h)
        ch = chunks(leg.probe, leg.mode)
        t_wr = await self._timed_write(*ch[0])
        count = 1
        st = await self._status("stalled")
        while not st["full"] and count < len(ch):
            await self._wr_chunk(*ch[count])
            count += 1
            st = await self._status("stalled")
        n_full = count
        if not st["full"]:
            self.chk.ctrl("HMAC-STALL-FULL", False, mode=leg.mode, writes=count, run="probe")
            dut.hmac_fifo_drain_stall_i.value = 0
            await self._reset_hmac()
            return None
        pending = None
        for _ in range(PROBE_EXTRA_MAX):
            if count >= len(ch):
                break
            task, _seq, cap, _t0 = await self._held_write(*ch[count])
            if await self._wait_task(task, 16 * t_wr):
                take_handshake(cap)
                count += 1
                continue
            pending = (task, cap)
            break
        self.chk.obs(
            "HMAC-STALL-N",
            mode=leg.mode,
            n_full=n_full,
            completed_with_stall=count,
            answered_after_full=count - n_full,
            t_wr=t_wr,
            held=int(pending is not None),
        )
        dut.hmac_fifo_drain_stall_i.value = 0
        if pending is not None:
            if not await self._wait_task(pending[0], 64 * t_wr):
                raise AssertionError(
                    f"measurement-run beat stays unanswered {64 * t_wr} clocks after the stall release"
                )
            take_handshake(pending[1])
        await self._reset_hmac()
        return n_full

    async def _setup_stalled(self, h: Hash) -> None:
        await self._wr(
            HMAC.addr("CFG"), build_cfg(hmac_en=h.hmac_en, sha_bits=h.sha, key_bits=h.key_bits)
        )
        if h.hmac_en:
            for i, word in enumerate(KEY_ROWS[h.key_row]):
                await self._wr(HMAC_KEY_0 + 4 * i, word)
        self.dut.hmac_fifo_drain_stall_i.value = 1
        await ClockCycles(self.dut.clk_i, 2)
        await self._wr(HMAC_CMD, HMAC_CMD_HASH_START)

    async def _stall_leg(self, leg: StallLeg) -> None:
        dut = self.dut
        n = await self._probe_n(leg)
        if n is None:
            return
        # The measurement run ends with an HMAC reset.
        self._open()
        await self._setup_stalled(leg.h)
        ch = chunks(leg.msg, leg.mode)
        assert len(ch) > n + BP_BEAT_BOUND, (
            f"message of {len(ch)} writes cannot hold {n} + {BP_BEAT_BOUND} writes"
        )
        # Clean write: the FIFO is empty, so the beat completes OKAY within
        # CLEAN_BOUND clocks. A beat that is held or refused here leaves the
        # held-beat check below without its control.
        task, seq, cap, t0 = await self._held_write(*ch[0])
        answered = await self._wait_task(task, CLEAN_BOUND)
        t_resp = take_handshake(cap)
        clean_ok = answered and t_resp is not None and seq.resp_ok
        t_clean = (
            max(1, round((t_resp - t0) / self._period_ps)) if t_resp is not None else CLEAN_BOUND
        )
        self.chk.ctrl(
            "HMAC-BP-CLEAN",
            clean_ok,
            mode=leg.mode,
            clean_clk=t_clean if t_resp is not None else "none",
            bound=CLEAN_BOUND,
            resp="OKAY" if seq.resp_ok else f"code{seq.resp_code}",
        )
        if not clean_ok:
            dut.hmac_fifo_drain_stall_i.value = 0
            if not answered and not await self._wait_task(task, DRAIN_BOUND):
                raise AssertionError(
                    "clean MSG_FIFO beat never answered; the single host path is blocked, "
                    "so the leaf stops"
                )
            await self._reset_hmac()
            return
        for i in range(1, n):
            await self._wr_chunk(*ch[i])
            if leg.mode == "gap" and leg.gap:
                await ClockCycles(dut.clk_i, leg.gap)
        st = await self._status("stalled")
        self.chk.ctrl("HMAC-STALL-FULL", st["full"] == 1, mode=leg.mode, writes=n, run="leg")

        # Hold window: with the stall held and fifo_full read 1, issue the next beats one at a
        # time. A beat with no write response for `hold` clocks is the held beat. The byte
        # packer in front of the FIFO can accept beats after fifo_full reads 1, and the register
        # text (hmac.adoc:159) does not state how many, so the index of the held beat is
        # log-only; the graded part is that a beat is held within BP_BEAT_BOUND beats. No other
        # access goes on the host path during a hold.
        hold = 16 * t_clean
        accepted: list[str] = []
        held = None
        no_resp_clk = None
        idx = n
        while idx < n + BP_BEAT_BOUND:
            task, seq, cap, t0 = await self._held_write(*ch[idx])
            await ClockCycles(dut.clk_i, hold)
            if not cap.done() and not task.done():
                held = (task, seq, cap, t0)
                no_resp_clk = hold
                break
            await self._wait_task(task, hold)
            t_resp = take_handshake(cap)
            no_resp_clk = None if t_resp is None else round((t_resp - t0) / self._period_ps)
            accepted.append("OKAY" if seq.resp_ok else f"code{seq.resp_code}")
            idx += 1
        dut.hmac_fifo_drain_stall_i.value = 0
        self.chk.blocked(
            "HMAC-BACKPRESSURE",
            reason="hmac.adoc:159 does not state which write after fifo_full = 1 is held; "
            "a byte packer sits in front of the FIFO",
        )
        self.chk.obs(
            "HMAC-BP-HOLD-BEAT",
            mode=leg.mode,
            n_full=n,
            hold_beat=idx + 1 if held is not None else "none",
            accepted_after_full=len(accepted),
            no_resp_clk=no_resp_clk if no_resp_clk is not None else "none",
            hold_clk=hold,
        )
        held_resp = "none"
        if held is not None:
            task, seq, cap, t0 = held
            bound = 64 * t_clean
            if not await self._wait_task(task, bound):
                self.chk.ok(
                    "HMAC-BACKPRESSURE-HOLD",
                    False,
                    mode=leg.mode,
                    reason="timeout",
                    bound=bound,
                    clean_clk=t_clean,
                )
                raise AssertionError(
                    "held MSG_FIFO beat never answered after the stall release; the single "
                    "host path is blocked, so the leaf stops"
                )
            take_handshake(cap)
            held_resp = "OKAY" if seq.resp_ok else f"code{seq.resp_code}"
            idx += 1

        await self._write_msg(ch[idx:], leg.mode, leg.gap, leg.rb, "drain")
        await self._drain(DRAIN_BOUND, "HMAC-STATUS")
        digest = await self._finish(leg.h.sha, "HMAC-MSG")
        self._grade_msg(leg.h, leg.msg, leg.mode, digest)
        golden = golden_digest(
            leg.h.sha, leg.h.hmac_en, KEY_ROWS[leg.h.key_row], leg.h.key_bits, leg.msg
        )
        no_loss, _ = self.digest_order.match(digest, golden)
        accepted_ok = all(r == "OKAY" for r in accepted)
        self.chk.ok(
            "HMAC-BACKPRESSURE-HOLD",
            held is not None and held_resp == "OKAY" and accepted_ok and no_loss,
            mode=leg.mode,
            full=st["full"],
            held=int(held is not None),
            bound=BP_BEAT_BOUND,
            hold_clk=hold,
            clean_clk=t_clean,
            accepted_resp=",".join(accepted) or "none",
            held_resp_after_release=held_resp,
            **{"digest==golden": int(no_loss)},
        )

    async def _fe_full_leg(self, leg: FeLeg) -> int | None:
        dut = self.dut
        await self._reset_hmac()
        self._open()
        await self._setup_stalled(leg.h)
        ch = chunks(leg.probe, "burst")
        st = {"full": 0}
        writes = 0
        while not st["full"] and writes < len(ch):
            await self._wr_chunk(*ch[writes])
            writes += 1
            st = await self._status("stalled")
        if not st["full"]:
            self.chk.ctrl("HMAC-STALL-FULL", False, leg="full", writes=writes)
            dut.hmac_fifo_drain_stall_i.value = 0
            await self._reset_hmac()
            return None
        d_full = st["depth"]
        dut.hmac_fifo_drain_stall_i.value = 0
        t_drain = max(1, await self._drain(DRAIN_BOUND, "HMAC-FIFOEMPTY"))
        await ClockCycles(dut.clk_i, 4 * t_drain)
        intr = await self._rd(HMAC_INTR_STATE) & INTR_FIELDS
        state = int(bool(intr & INTR_FIFO_EMPTY))
        self.chk.ok(
            "HMAC-FIFOEMPTY",
            state == 1,
            leg="full",
            full_before=1,
            state=state,
            t_drain=t_drain,
            depth_at_full=d_full,
            writes=writes,
        )
        self.t_drain = t_drain
        return d_full

    async def _fe_notfull_leg(self, leg: FeLeg, d_full: int) -> None:
        dut = self.dut
        await self._reset_hmac()
        self._open()
        await self._setup(leg.h)
        ch = chunks(leg.probe, "burst")[:2]
        self.chk.ctrl("HMAC-FE-DEPTH", d_full > len(ch), writes=len(ch), depth_at_full=d_full)
        for n, v in ch:
            await self._wr_chunk(n, v)
            await self._status("run")
        await self._drain(4 * self.t_drain, "HMAC-STATUS")
        await ClockCycles(dut.clk_i, 4 * self.t_drain)
        intr = await self._rd(HMAC_INTR_STATE) & INTR_FIELDS
        state = int(bool(intr & INTR_FIFO_EMPTY))
        self.chk.ok(
            "HMAC-FIFOEMPTY",
            state == 0,
            leg="notfull",
            full_before=0,
            state=state,
            t_drain=self.t_drain,
            writes=len(ch),
        )

    async def _wipe_leg(self, leg: WipeLeg) -> None:
        h = leg.h
        n_words = HMAC_DIGEST_WORDS[h.sha]
        await self._reset_hmac()
        self._open()
        await self._setup(h)
        await self._write_msg(chunks(leg.msg1, "burst"), "burst", 0, 8, "run")
        d1 = await self._finish(h.sha, "HMAC-WIPE")
        self._grade_msg(h, leg.msg1, "burst", d1)
        g1 = golden_digest(h.sha, True, KEY_ROWS[h.key_row], h.key_bits, leg.msg1)
        d1_ok, _ = self.digest_order.match(d1, g1)
        self.chk.ctrl(
            "HMAC-WIPE-PRE",
            d1_ok and leg.w not in d1,
            w=f"0x{leg.w:08x}",
            digest_eq_golden=int(d1_ok),
        )

        # hmac.hjson:420-425: the value overwrites the secret key and the digest; a 64-bit
        # word of SHA-384/512 holds the 32-bit value twice, so every DIGEST word reads w.
        await self._wr(HMAC_WIPE_SECRET, leg.w)
        after = [await self._rd(HMAC_DIGEST_0 + 4 * i) for i in range(n_words)]
        digest_all_w = all(x == leg.w for x in after)

        # The next HMAC writes CFG and no KEY word, so it hashes with a key of all-w words.
        await self._wr(
            HMAC.addr("CFG"), build_cfg(hmac_en=True, sha_bits=h.sha, key_bits=h.key_bits)
        )
        await self._wr(HMAC_CMD, HMAC_CMD_HASH_START)
        await self._write_msg(chunks(leg.msg2, "burst"), "burst", 0, 8, "run")
        d2 = await self._finish(h.sha, "HMAC-WIPE")
        g2 = golden_digest(h.sha, True, [leg.w] * 32, h.key_bits, leg.msg2)
        key_ok, _ = self.digest_order.match(d2, g2)
        self.chk.ok(
            "HMAC-WIPE",
            digest_all_w and key_ok,
            sha=h.sha,
            klen=h.key_bits,
            w=f"0x{leg.w:08x}",
            words=n_words,
            digest_all_w=int(digest_all_w),
            **{"key_half_digest==golden_key_w": int(key_ok)},
            digest_after0=f"0x{after[0]:08x}",
        )
