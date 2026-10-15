# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The TRNG reset with an external source: adapter and pool clear, traffic pause and
resume, and the crypto client requests pending across the clear.

Contract (``hw/sys/sep/doc/reset_controller.adoc``, Resetting the TRNG;
``hw/sys/sep/doc/trng.adoc``, Reset and Recovery Boundaries;
``hw/sys/sep/doc/entropy_pool.adoc``):
  * While the TRNG reset is active the post-mux crypto and pool adapters and the
    pool clear, also when external inputs are selected; the pool AXI responder
    stays accessible.
  * External traffic pauses during the clear and resumes when it ends,
    independently of the internal generators.
  * A client request (AES, KMAC, OTBN RND, OTBN URND) pending during the clear gets
    no acknowledge, stays asserted and is served with fresh data afterwards.

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense``, no noise force.
Baseline ``SW_RESET_N`` = 0x36 (TRNG, KMAC, AES and OTBN released; Key Manager,
HMAC and ABR held) and ``EXT_TRNG_SRC_SEL`` = 0x6 (streams 1 and 2 external,
stream 0 internal and idle). ESRC, CSRNG and EDN stay uninitialized: every word a
client or the pool takes comes from the external stream driver
(``env/sep_ext_trng_stream.py``). A per-clock trace of this leaf reads the external
port taps, the client request, acknowledge and word probes and
``trng_reset_active_probe_o`` after each falling edge, the phase of the driver.

Randomization (``SepSeededRng`` from the run seed, drawn before the first
stimulus): the reset moment (a fraction of the pool fill time), the extra reset
hold (0 to 200 clocks), N (4 to 24 pairs), M (2 to 8 pairs), the client order of the
pre-reset leg and of the trials, the trial delay (0 to 32 clocks), the unique
non-zero beat words, the AES key row, plaintext and block count, the KMAC message,
and the OTBN read counts.

Checkers:
  CHK-XRST-POOL    a pool STATUS read issued and answered inside the clear returns
                   OKAY and fifo_level 0. Control: fifo_level = N before the reset.
  CHK-XRST-PAUSE   no transfer completes at an active external stream inside the
                   clear while the driver holds tvalid. Control: transfers before
                   and after the clear.
  CHK-XRST-RESUME  the first transfer of each active stream after the clear comes
                   within 16 x t_xfer + 64 clocks, with no internal set-up.
  CHK-XRST-STALE   after the release fifo_level = M and the M pops return the new
                   pairs in order. Control: pre_reset_level at least 1.
  CHK-XRST-CLIENT  before the reset each word a client accepts and each OTBN RND
                   word is a sent word; the AES and KMAC results equal the goldens.
  CHK-XRST-OTBN    per client: the request pending in the clear stays 1 with no
                   acknowledge; after the release it is acknowledged with words sent
                   after the clear; the results equal the goldens. Control: the
                   same client was acknowledged in the pre-reset leg.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge
from env.sep_aes_golden import aes_encrypt_words
from env.sep_chk_log import SepChkLog
from env.sep_crypto_kat_rows import AES_KEY_ROWS, KMAC_SAMPLE_KEY_ROW
from env.sep_ext_trng_stream import SepExtTrngStream
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_kmac_golden import kmac_family_words
from env.sep_reg_meta import KMAC, SEP_CPU_CTRL
from env.sep_rv32_asm import A0, ECALL, T1, addi, csrr, sw
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_monitor_life import MonitorLife
from seq_lib.sep_aes_seq import (
    AES_CTRL_SHADOWED,
    AES_KEY_LEN_256,
    AES_MODE_ECB,
    AES_OP_ENC,
    AES_PRS_RATE_PER_1,
    SepAes,
    build_aes_ctrl,
)
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_entropy_pool_seq import (
    POOL_POP,
    POOL_STATUS,
    RESP_OKAY,
    SepEntropyPool,
    pool_level,
)
from seq_lib.sep_kmac_seq import KMAC_CMD, SepKmac, SepKmacCfg
from seq_lib.sep_otbn_seq import SepOtbn

TEST = "sep_trng_ext_sink_reset_rand_test"

SEL_ADDR = SEP_CPU_CTRL.addr("EXT_TRNG_SRC_SEL")
SEL_EXT_12 = 0x6
PARKED = ("hmac", "abr")
CMD_ENTROPY_REQ = KMAC.field_mask("CMD", "entropy_req")

CLIENTS = ("aes", "kmac", "otbn_rnd", "otbn_urnd")
CLIENT_BIT = {"aes": 0, "kmac": 1, "otbn_rnd": 2, "otbn_urnd": 3}
# OTBN entropy CSRs (``vendor/lowRISC/opentitan/upstream/hw/ip/otbn/data/csr.yml``).
CSR_RND = 0xFC0
CSR_URND = 0xFC1

TRNG_RESET_CAP = 4_000
SETTLE_CAP = 20_000
OP_CAP = 400_000
TRIAL_REPEATS = 4
STATUS_AGREE_READS = 64
WORD_POOL = 20_000
# Pool-path settle: no stream-2 transfer (port or post-mux) and no pool EDN
# acknowledge for this many clocks before a graded STATUS read. A pool word takes
# about 4 clocks from the adapter to the pool (stage FIFO, endpoint, EDN handshake);
# the window is 16 x that. A word that lands later shows as a level mismatch.
POOL_QUIET = 64


def _le_words(data: bytes) -> list[int]:
    return [int.from_bytes(data[i : i + 4], "little") for i in range(0, len(data), 4)]


def _kill(task) -> None:
    """End a client task that did not finish within its bound."""
    if task.done():
        return
    stop = getattr(task, "cancel", None) or task.kill
    stop()


def otbn_csr_prog(csr: int, reads: int) -> tuple[int, ...]:
    """OTBN program: ``reads`` reads of ``csr``, each stored to DMEM word k, then ecall."""
    prog = [addi(T1, 0, 0)]
    for k in range(reads):
        prog += [csrr(A0, csr), sw(A0, T1, 4 * k)]
    return tuple(prog + [ECALL])


# ----------------------------------------------------------------------------- plan
@dataclass(frozen=True)
class Plan:
    seed: int
    offset_frac: int  # per mille of T_fill
    extra_hold: int
    n_fill: int
    m_new: int
    pre_order: tuple[str, ...]
    trial_order: tuple[str, ...]
    trial_delay: dict
    aes_row: int
    aes_pt: tuple[int, ...]
    kmac_msg: tuple[int, ...]
    rnd_reads: int
    urnd_reads: int
    fill_pairs: tuple[int, ...]
    restart_pairs: tuple[int, ...]
    new_pairs: tuple[int, ...]
    words: tuple[int, ...]

    @property
    def aes_key(self) -> list[int]:
        return _le_words(AES_KEY_ROWS[256][self.aes_row][1])

    def describe(self) -> str:
        return (
            f"offset_frac={self.offset_frac}/1000 extra_hold={self.extra_hold} "
            f"N={self.n_fill} M={self.m_new} pre_order={','.join(self.pre_order)} "
            f"trial_order={','.join(self.trial_order)} "
            f"delay={[self.trial_delay[c] for c in CLIENTS]} "
            f"aes_row={AES_KEY_ROWS[256][self.aes_row][0]} aes_blocks={len(self.aes_pt) // 4} "
            f"kmac_words={len(self.kmac_msg)} rnd_reads={self.rnd_reads} "
            f"urnd_reads={self.urnd_reads}"
        )


def draw_plan(seed: int) -> Plan:
    """Every draw of the leaf, in a fixed order, with no simulator access."""
    rng = SepSeededRng(seed)
    used: set[int] = set()

    def take(n: int) -> tuple[int, ...]:
        out = []
        while len(out) < n:
            w = rng.getrandbits(32)
            if w and w not in used:
                used.add(w)
                out.append(w)
        return tuple(out)

    offset_frac = rng.randrange(0, 1001)
    extra_hold = rng.randrange(0, 201)
    n_fill = rng.randrange(4, 25)
    m_new = rng.randrange(2, 9)
    pre = list(CLIENTS)
    rng.shuffle(pre)
    trial = list(CLIENTS)
    rng.shuffle(trial)
    delay = {c: rng.randrange(0, 33) for c in CLIENTS}
    aes_row = rng.randrange(len(AES_KEY_ROWS[256]))
    aes_pt = take(4 * rng.randrange(1, 5))
    kmac_msg = take(rng.randrange(1, 17))
    rnd_reads = rng.randrange(1, 9)
    urnd_reads = rng.randrange(1, 9)
    fill = take(n_fill)
    restart = take(64)
    new = take(m_new)
    words = take(WORD_POOL)
    return Plan(
        seed, offset_frac, extra_hold, n_fill, m_new, tuple(pre), tuple(trial), delay,
        aes_row, aes_pt, kmac_msg, rnd_reads, urnd_reads, fill, restart, new, words,
    )  # fmt: skip


# ----------------------------------------------------------------------------- trace
def _bitstr(sig) -> str:
    value = sig.value
    bits = getattr(value, "binstr", None)
    return (bits if bits is not None else str(value)).strip()


def _known(sig) -> int | None:
    bits = _bitstr(sig)
    return int(bits, 2) if bits and all(c in "01" for c in bits) else None


def _bit(v: int | None, i: int) -> int | None:
    return None if v is None else (v >> i) & 1


def _word(v: int | None, i: int) -> int | None:
    return None if v is None else (v >> (32 * i)) & 0xFFFF_FFFF


@dataclass(frozen=True)
class Row:
    """One clock, sampled after the falling edge (None = X/Z)."""

    clk: int
    ta: int | None  # trng_reset_active_probe_o
    ev: int | None  # ext_trng_tvalid_o[2:0]
    er: int | None  # ext_trng_tready_o[2:0]
    ed: int | None  # ext_trng_tdata_o[95:0]
    creq: int | None  # crypto_edn_req_o[3:0]
    cack: int | None  # crypto_edn_ack_o[3:0]
    cbus: int | None  # crypto_edn_bus_o[127:0]


class _Trace:
    """Per-clock record of the probes of this leaf (rows only between begin and end)."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.clk = 0
        self.rows: list[Row] = []
        self.recording = False
        self.ext_xfers = [0, 0, 0]
        self.stall = [0, 0, 0]
        # Clocks since the last stream-2 transfer or pool EDN acknowledge.
        self.pool_quiet = 0
        self.life = MonitorLife("EXT-SINK-RESET-TRACE", lambda: self.clk)

    def start(self) -> "_Trace":
        self.life.start(self._run())
        return self

    async def stop(self) -> None:
        await self.life.stop()

    def begin(self) -> None:
        self.rows = []
        self.recording = True

    def end(self) -> list[Row]:
        self.recording = False
        rows, self.rows = self.rows, []
        return rows

    def snapshot(self) -> list[Row]:
        return list(self.rows)

    async def _run(self) -> None:
        d = self.dut
        while True:
            await FallingEdge(d.clk_i)
            await ReadOnly()
            self.clk += 1
            ev = _known(d.ext_trng_tvalid_o)
            er = _known(d.ext_trng_tready_o)
            for i in (1, 2):
                v, r = _bit(ev, i), _bit(er, i)
                if v == 1 and r == 1:
                    self.ext_xfers[i] += 1
                    self.stall[i] = 0
                elif v == 1 and r == 0:
                    self.stall[i] += 1
                else:
                    self.stall[i] = 0
            pool_event = (
                (_bit(ev, 2) == 1 and _bit(er, 2) == 1)
                or (_known(d.axis2_tvalid_o) == 1 and _known(d.axis2_tready_o) == 1)
                or _known(d.pool_edn_ack_o) != 0
            )
            self.pool_quiet = 0 if pool_event else self.pool_quiet + 1
            if self.recording:
                self.rows.append(
                    Row(
                        self.clk,
                        _known(d.trng_reset_active_probe_o),
                        ev,
                        er,
                        _known(d.ext_trng_tdata_o),
                        _known(d.crypto_edn_req_o),
                        _known(d.crypto_edn_ack_o),
                        _known(d.crypto_edn_bus_o),
                    )
                )


def xfers(rows: list[Row], i: int) -> list[Row]:
    return [r for r in rows if _bit(r.ev, i) == 1 and _bit(r.er, i) == 1]


def acked(rows: list[Row], client: int) -> list[int | None]:
    """Words that client ``client`` accepts (its acknowledge with its word probe)."""
    return [_word(r.cbus, client) for r in rows if _bit(r.cack, client) == 1]


# ----------------------------------------------------------------------------- leaf
class _Reg(SepAxiRegDriver):
    _DRIVER_TAG = "XRST"


@pyuvm.test()
class sep_trng_ext_sink_reset_rand_test(sep_base_test):
    """Adapter and pool clear with an external source; pending client requests."""

    required_evidence = (
        "CHK-XRST-POOL",
        "CHK-XRST-PAUSE",
        "CHK-XRST-RESUME",
        "CHK-XRST-STALE",
        "CHK-XRST-CLIENT",
        "CHK-XRST-OTBN",
    )

    async def run_scenario(self) -> None:
        dut = cocotb.top
        await self.bring_up_no_cpu(park=PARKED)
        self.reg = _Reg(self)
        await self.reg._wr(SEL_ADDR, SEL_EXT_12)
        self.logger.info(
            "BASELINE sw_reset_n=0x%02x ext_trng_src_sel=0x%x", self.swrst.value, SEL_EXT_12
        )
        seed = self.random_seed()
        plan = draw_plan(seed)
        self.logger.info("PLAN seed=%d %s", seed, plan.describe())
        self.plan = plan
        self.chk = SepChkLog(self, TEST, seed)
        self.aes = SepAes(self)
        self.kmac = SepKmac(self)
        self.otbn = SepOtbn(self)
        self.pool = SepEntropyPool(self)
        self.trace = _Trace(dut).start()
        self.ext = SepExtTrngStream(dut, logger=self.logger).start(streams=(1, 2))
        self._wi = 0
        self.sent_s: set[int] = set()
        self._feeders: list = []
        self.ack_before: dict[str, int] = {}
        try:
            await self._client_leg()
            await self._pool_leg()
            await self._trials()
        finally:
            close_graded_window(self.logger)
            await self._stop_feeders()
        await self.ext.stop()
        await self.trace.stop()
        self.chk.finish()

    # --- words and feeders ----------------------------------------------------------
    def _next_word(self) -> int:
        if self._wi >= len(self.plan.words):
            raise AssertionError(f"plan word pool of {WORD_POOL} words exhausted")
        w = self.plan.words[self._wi]
        self._wi += 1
        return w

    async def _feed(self, stream: int, sink: set[int], stop: list[bool], gate=None) -> None:
        """Keep one unique word offered on ``stream`` until ``stop[0]``; ``gate()`` False
        holds back the next offer."""
        clk = cocotb.top.clk_i
        while not stop[0]:
            if self.ext.pending(stream) == 0 and (gate is None or gate()):
                w = self._next_word()
                sink.add(w)
                self.ext.send(stream, [w])
            await RisingEdge(clk)

    def _start_feeder(self, stream: int, sink: set[int], gate=None) -> list[bool]:
        stop = [False]
        task = cocotb.start_soon(self._feed(stream, sink, stop, gate))
        self._feeders.append((stop, task))
        return stop

    async def _stop_feeders(self) -> None:
        for stop, task in self._feeders:
            stop[0] = True
            if not task.done():
                await task
        self._feeders = []

    async def _silence(self, *streams: int) -> None:
        """Stop the feeders; the source drops what it holds or queues."""
        await self._stop_feeders()
        for i in streams:
            if self.ext.pending(i):
                await self.ext.source_reset(i)

    # --- waits ------------------------------------------------------------------------
    async def _until(self, pred, bound: int) -> int | None:
        for n in range(bound + 1):
            if pred():
                return n
            await RisingEdge(cocotb.top.clk_i)
        return None

    async def _wait_probe(self, want: int, what: str) -> int:
        dut = cocotb.top
        for clk in range(TRNG_RESET_CAP):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if self.rd(dut.trng_reset_active_probe_o, allow_unknown=True) == want:
                return clk
        raise AssertionError(f"{what}: no change within {TRNG_RESET_CAP} clocks")

    async def _trng_reset(self, hold: int = 0) -> None:
        """Set-up TRNG reset: bit 5 of SW_RESET_N to 0 then 1, bounded waits."""
        dut = cocotb.top
        await self.swrst.park("trng")
        await self._wait_probe(1, "trng reset rise")
        await RisingEdge(dut.clk_i)
        if hold:
            await ClockCycles(dut.clk_i, hold)
        await self.swrst.release("trng")
        await self._wait_probe(0, "trng reset fall")
        await RisingEdge(dut.clk_i)

    async def _status_settled(self) -> int:
        """STATUS after the pool path is quiet (``POOL_QUIET`` clocks with no stream-2
        transfer and no pool acknowledge, bound ``SETTLE_CAP``), then until two
        consecutive reads agree. A path that never goes quiet leaves the last level to
        the caller's compare."""
        await self._until(lambda: self.trace.pool_quiet >= POOL_QUIET, SETTLE_CAP)
        prev = -1
        for _ in range(STATUS_AGREE_READS):
            lvl = pool_level(await self.pool.status())
            if lvl == prev:
                return lvl
            prev = lvl
        return prev

    async def _settle(self, stream: int, n: int, bound: int) -> bool:
        base = self.trace.ext_xfers[stream]
        got = await self._until(lambda: self.trace.ext_xfers[stream] - base >= n, bound)
        return got is not None

    # --- client operations -------------------------------------------------------------
    async def _op(self, client: str, *, entropy_req: bool = False) -> dict:
        """Run one client operation; returns its result and its golden compare."""
        plan = self.plan
        if client == "aes":
            key = plan.aes_key
            await self.aes.wait_idle("pre-config")
            ctrl = build_aes_ctrl(
                sideload=False,
                operation=AES_OP_ENC,
                mode=AES_MODE_ECB,
                key_len=AES_KEY_LEN_256,
                reseed_rate=AES_PRS_RATE_PER_1,
            )
            await self.aes._wr(AES_CTRL_SHADOWED, ctrl)
            await self.aes._wr(AES_CTRL_SHADOWED, ctrl)
            await self.aes.wait_idle("post-config")
            await self.aes.load_key_iv(key)
            ct = await self.aes.run_blocks(list(plan.aes_pt))
            golden = aes_encrypt_words("ecb", key, list(plan.aes_pt))
            return {"result": ct, "golden_ok": ct == golden}
        if client == "kmac":
            cfg = SepKmacCfg(
                mode="kmac",
                sec=256,
                msg_words=list(plan.kmac_msg),
                outlen_bytes=32,
                key_words=_le_words(KMAC_SAMPLE_KEY_ROW[1]),
                key_bits=256,
            )
            if entropy_req:
                await self.kmac._wait_idle("pre-entropy-req")
                await self.kmac._wr(KMAC_CMD, CMD_ENTROPY_REQ)
            digest = await self.kmac.run_family(cfg, tag="xrst")
            golden = kmac_family_words(**cfg.golden_kwargs())
            return {"result": digest, "golden_ok": digest == golden}
        rnd = client == "otbn_rnd"
        reads = plan.rnd_reads if rnd else plan.urnd_reads
        await self.otbn.load_program(otbn_csr_prog(CSR_RND if rnd else CSR_URND, reads))
        await self.otbn.execute()
        words = await self.otbn.read_dmem_words(0, reads) if rnd else []
        return {"result": words, "golden_ok": True, "rnd_words": words}

    async def _client_leg(self) -> None:
        """CHK-XRST-CLIENT: every accepted word and every OTBN RND word is a sent word;
        the AES ciphertext and the KMAC digest equal their goldens."""
        open_graded_window(TEST, self.logger)
        for client in self.plan.pre_order:
            bit = CLIENT_BIT[client]
            self._start_feeder(1, self.sent_s)
            self.trace.begin()
            reason = ""
            res: dict = {"result": [], "golden_ok": False}
            try:
                res = await self._op(client)
            except AssertionError as exc:
                reason = f"timeout:{client}:{exc}"
            rows = self.trace.end()
            await self._stop_feeders()
            words = acked(rows, bit)
            checked = list(words) + list(res.get("rnd_words", []))
            members = sum(1 for w in checked if w in self.sent_s)
            self.ack_before[client] = len(words)
            fields = {
                "client": client,
                "words_in_sent_set": f"{members}/{len(checked)}",
                "acks": len(words),
                "result==golden": int(res["golden_ok"]),
            }
            if reason:
                fields["reason"] = reason
            self.chk.ok(
                "XRST-CLIENT",
                not reason and len(words) >= 1 and members == len(checked) and res["golden_ok"],
                **fields,
            )
        close_graded_window(self.logger)
        await self._silence(1)

    # --- pool leg -----------------------------------------------------------------------
    async def _pool_leg(self) -> None:
        plan = self.plan
        dut = cocotb.top
        # Step 3: pool fill from empty adapters and pool; both streams active.
        await self._trng_reset()
        self.trace.begin()
        self._start_feeder(1, self.sent_s)
        t_start = self.trace.clk
        t_xfer = None
        for k, a in enumerate(plan.fill_pairs):
            for _ in range(2):
                t_offer = self.trace.clk
                self.ext.send(2, [a])
                if not await self._settle(2, 1, SETTLE_CAP):
                    raise AssertionError(f"pool fill beat of pair {k} not taken in {SETTLE_CAP}")
                if t_xfer is None:
                    t_xfer = max(1, self.trace.clk - t_offer)
        t_fill = max(1, self.trace.clk - t_start)
        level_before = await self._status_settled()
        self.chk.obs("XRST-FILL", t_xfer=t_xfer, t_fill=t_fill, level_before=level_before)

        # Step 4: restart the beat stream on both streams, then the reset at the offset.
        restart = list(plan.restart_pairs)
        stop2 = [False]

        async def feed_pairs() -> None:
            while not stop2[0] and restart:
                a = restart.pop(0)
                for _ in range(2):
                    self.ext.send(2, [a])
                    while self.ext.pending(2) and not stop2[0]:
                        await RisingEdge(dut.clk_i)
                    if stop2[0]:
                        return

        task2 = cocotb.start_soon(feed_pairs())
        pre_reset_level = pool_level(await self.pool.status())
        offset = plan.offset_frac * t_fill // 1000
        await ClockCycles(dut.clk_i, max(1, offset))
        new = list(plan.new_pairs)
        new_s: set[int] = set()

        async def at_rise() -> None:
            await self._wait_probe(1, "trng reset rise")
            await RisingEdge(dut.clk_i)
            stop2[0] = True
            await self._stop_feeders()
            await task2
            # The source's own reset with the sink reset: held beats and any partial
            # pair are forgotten; every later beat belongs to the new pairs.
            await self.ext.source_reset(1)
            await self.ext.source_reset(2)
            self.ext.send(2, [new[0]])
            w = self._next_word()
            new_s.add(w)
            self.ext.send(1, [w])

        rise_task = cocotb.start_soon(at_rise())
        open_graded_window(TEST, self.logger)
        await self.swrst.park("trng")
        await rise_task
        # Step 6: one pool STATUS read issued and answered inside the clear.
        req_in = self.rd(dut.trng_reset_active_probe_o, allow_unknown=True)
        t_req = self.trace.clk
        read = cocotb.start_soon(self.pool.access(POOL_STATUS))
        await self._until(lambda: read.done(), SETTLE_CAP)
        resp_in = int(read.done()) and self.rd(dut.trng_reset_active_probe_o, allow_unknown=True)
        read_clk = self.trace.clk - t_req
        await ClockCycles(dut.clk_i, max(1, plan.extra_hold))
        # Step 7: release; external traffic resumes with no internal set-up.
        base = {i: self.trace.ext_xfers[i] for i in (1, 2)}
        await self.swrst.release("trng")
        await self._wait_probe(0, "trng reset fall")
        bound = 16 * t_xfer + 64
        await self._until(lambda: all(self.trace.ext_xfers[i] > base[i] for i in (1, 2)), bound)
        if not read.done():
            await read
        seq = read.result()
        close_graded_window(self.logger)
        # Step 8: the rest of the M new pairs; stream 1 offers new words too.
        self.ext.send(2, [new[0]])
        for a in new[1:]:
            self.ext.send(2, [a, a])
        for _ in range(3):
            w = self._next_word()
            new_s.add(w)
            self.ext.send(1, [w])
        done = await self._settle(2, 2 * plan.m_new - 1, SETTLE_CAP)
        rows = self.trace.end()
        level_after = await self._status_settled()
        pops = []
        bad_resp = 0
        for _ in range(plan.m_new):
            p = await self.pool.access(POOL_POP)
            bad_resp += int(p.resp_code != RESP_OKAY)
            pops.append(p.rdata & 0xFFFF_FFFF_FFFF_FFFF)
        await self._silence(1, 2)

        # CHK-XRST-POOL
        level_in_clear = pool_level(seq.rdata)
        self.chk.ctrl("XRST-POOL", level_before == plan.n_fill, level_before=level_before)
        self.chk.ok(
            "XRST-POOL",
            seq.resp_code == RESP_OKAY and level_in_clear == 0 and req_in == 1 and resp_in == 1,
            level_before=level_before, level_in_clear=level_in_clear,
            resp="OKAY" if seq.resp_code == RESP_OKAY else seq.resp_code,
            req_in_window=req_in, resp_in_window=resp_in, read_clk=read_clk,
            window_clk=sum(1 for r in rows if r.ta == 1),
        )  # fmt: skip
        # CHK-XRST-PAUSE and CHK-XRST-RESUME, per active stream.
        first_clear = next((k for k, r in enumerate(rows) if r.ta == 1), None)
        last_clear = max((k for k, r in enumerate(rows) if r.ta == 1), default=None)
        resumed: dict[int, int | None] = {1: None, 2: None}
        if last_clear is not None and last_clear + 1 < len(rows):
            t_fall = rows[last_clear + 1].clk
            for i in (1, 2):
                first = next((r.clk for r in xfers(rows[last_clear + 1 :], i)), None)
                if first is not None and first - t_fall <= bound:
                    resumed[i] = first - t_fall
        for i in (1, 2):
            if first_clear is None:
                self.chk.ok("XRST-PAUSE", False, stream=i, reason="no_clear_window_sampled")
                continue
            win = rows[first_clear : last_clear + 1]
            before = len(xfers(rows[:first_clear], i))
            after = len(xfers(rows[last_clear + 1 :], i))
            in_clear = len(xfers(win, i))
            tvalid_in = int(any(_bit(r.ev, i) == 1 for r in win))
            self.chk.ctrl("XRST-PAUSE", before >= 1 and after >= 1, stream=i, xfers_before=before,
                          xfers_after=after)  # fmt: skip
            self.chk.ok(
                "XRST-PAUSE",
                in_clear == 0 and tvalid_in == 1,
                stream=i, xfers_in_clear=in_clear, tvalid_in_clear=tvalid_in,
                clear_clk=len(win), xfers_before=before, xfers_after=after,
            )  # fmt: skip
            r = resumed[i]
            fields = {"stream": i, "resumed_clk": r if r is not None else "na", "t_xfer": t_xfer,
                      "internal_init": 0, "bound": bound}  # fmt: skip
            if r is None:
                fields["reason"] = f"timeout:resume bound={bound}"
            self.chk.ok("XRST-RESUME", r is not None, **fields)
        # CHK-XRST-STALE
        expect = [(a << 32) | a for a in plan.new_pairs]
        old = {(a << 32) | a for a in plan.fill_pairs + plan.restart_pairs}
        stale = sum(1 for p in pops if p in old)
        self.chk.ctrl("XRST-STALE", pre_reset_level >= 1, pre_reset_level=pre_reset_level)
        self.chk.ok(
            "XRST-STALE",
            done and level_after == plan.m_new and pops == expect and bad_resp == 0,
            source_reset=1, pops=len(pops), level=level_after, expect_level=plan.m_new,
            stale_pairs=stale, order_ok=int(pops == expect), bad_resp=bad_resp,
            pre_reset_level=pre_reset_level,
        )  # fmt: skip

    # --- consumer trials ----------------------------------------------------------------
    async def _trials(self) -> None:
        for client in self.plan.trial_order:
            for attempt in range(TRIAL_REPEATS + 1):
                served = await self._trial(client, attempt)
                if not served:
                    break
            else:
                self.chk.ok(
                    "XRST-OTBN",
                    False,
                    client=client,
                    reason=f"served_before_clear_in_every_trial repeats={TRIAL_REPEATS}",
                )

    async def _trial(self, client: str, attempt: int) -> bool:
        """One consumer trial. Returns True when the request was served before the clear
        (the trial does not count and repeats)."""
        plan = self.plan
        dut = cocotb.top
        bit = CLIENT_BIT[client]
        await self._silence(1)
        await self._trng_reset()
        s_trial: set[int] = set()
        urnd_first: list[str] = []
        if client == "otbn_rnd":

            def gate() -> bool:
                req = self.rd(dut.crypto_edn_req_o, allow_unknown=True)
                ack = self.rd(dut.crypto_edn_ack_o, allow_unknown=True)
                return bool(req >> 3 & 1) and not ack >> 3 & 1 and not req >> 2 & 1

            pace = _UrndPacer(self, gate)
            self._start_feeder(1, s_trial, pace.allow)
            self._feeders.append(pace.start())
        self.trace.begin()
        task = cocotb.start_soon(self._op(client, entropy_req=client == "kmac"))
        n = await self._until(
            lambda: self.rd(dut.crypto_edn_req_o, allow_unknown=True) >> bit & 1, SETTLE_CAP
        )
        if client == "otbn_rnd":
            rows = self.trace.snapshot()
            r3 = next((r.clk for r in rows if _bit(r.creq, 3) == 1), None)
            r2 = next((r.clk for r in rows if _bit(r.creq, 2) == 1), None)
            urnd_first.append(str(int(r3 is not None and (r2 is None or r3 < r2))))
            self.chk.obs("XRST-URNDFIRST", urnd_before_rnd=urnd_first[0], attempt=attempt)
        if n is None:
            self.trace.end()
            await self._stop_feeders()
            self.chk.ok("XRST-OTBN", False, client=client, reason=f"timeout:req bound={SETTLE_CAP}")
            _kill(task)
            return False
        await ClockCycles(dut.clk_i, max(1, plan.trial_delay[client]))
        await self._stop_feeders()
        self.sent_s |= s_trial
        # The graded TRNG reset: the window stays open across it.
        open_graded_window(TEST, self.logger)
        await self.swrst.park("trng")
        await self._wait_probe(1, "trng reset rise")
        rows_pre = self.trace.snapshot()
        req_k = max(
            (k for k, r in enumerate(rows_pre) if _bit(r.creq, bit) == 1 and (
                k == 0 or _bit(rows_pre[k - 1].creq, bit) != 1)),
            default=0,
        )  # fmt: skip
        served = any(_bit(r.cack, bit) == 1 for r in rows_pre[req_k:]) or (
            _bit(rows_pre[-1].creq, bit) != 1 if rows_pre else True
        )
        await RisingEdge(dut.clk_i)
        await ClockCycles(dut.clk_i, max(1, plan.extra_hold))
        await self.swrst.release("trng")
        await self._wait_probe(0, "trng reset fall")
        await RisingEdge(dut.clk_i)
        close_graded_window(self.logger)
        q: set[int] = set()
        self._start_feeder(1, q)
        t_end = None
        for _ in range(OP_CAP):
            if task.done():
                t_end = self.trace.clk
                break
            await RisingEdge(dut.clk_i)
        rows = self.trace.end()
        await self._stop_feeders()
        if served:
            self.chk.obs("XRST-SERVED", client=client, attempt=attempt, done=int(t_end is not None))
            if t_end is None:
                _kill(task)
            return True
        reason = ""
        res: dict = {"result": [], "golden_ok": False}
        if t_end is None:
            reason = f"timeout:client_done bound={OP_CAP}"
            _kill(task)
        else:
            try:
                res = task.result()
            except AssertionError as exc:
                reason = f"client_error:{exc}"
        clear = [r for r in rows if r.ta == 1]
        last_clear = max((k for k, r in enumerate(rows) if r.ta == 1), default=len(rows) - 1)
        post = rows[last_clear + 1 :]
        req_in = int(bool(clear) and all(_bit(r.creq, bit) == 1 for r in clear))
        ack_in = int(any(_bit(r.cack, bit) == 1 for r in clear))
        words = acked(post, bit)
        rnd_words = list(res.get("rnd_words", []))
        fresh = all(w in q and w not in self.sent_s for w in words) and all(
            w in q for w in rnd_words
        )
        ctrl = self.ack_before.get(client, 0)
        self.chk.ctrl("XRST-OTBN", ctrl >= 1, client=client, ctrl_ack_before=int(ctrl >= 1))
        fields = {
            "client": client,
            "req_in_clear": req_in,
            "ack_in_clear": ack_in,
            "ack_after_release": int(len(words) >= 1),
            "words_from_post_reset": int(fresh),
            "post_words": len(words),
            "rnd_words": len(rnd_words),
            "result==golden": int(res["golden_ok"]),
            "clear_clk": len(clear),
            "ctrl_ack_before": int(ctrl >= 1),
            "attempt": attempt,
        }
        if reason:
            fields["reason"] = reason
        self.chk.ok(
            "XRST-OTBN",
            not reason and req_in and not ack_in and words and fresh and res["golden_ok"],
            **fields,
        )
        return False


class _UrndPacer:
    """Offer one stream-1 beat per OTBN URND acknowledge, only while URND requests,
    URND has no acknowledge and RND does not request, so no spare word stays in the
    staging FIFO of the crypto adapter (``hw/sys/sep/doc/trng.adoc``, Distribution and
    Source Selection)."""

    def __init__(self, test, gate) -> None:
        self.test = test
        self.gate = gate
        self.outstanding = False
        self.stop_flag = [False]

    def allow(self) -> bool:
        if self.outstanding or not self.gate():
            return False
        self.outstanding = True
        return True

    async def _run(self) -> None:
        dut = cocotb.top
        while not self.stop_flag[0]:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if self.test.rd(dut.crypto_edn_ack_o, allow_unknown=True) >> 3 & 1:
                self.outstanding = False

    def start(self):
        return self.stop_flag, cocotb.start_soon(self._run())
