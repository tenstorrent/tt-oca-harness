# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The crypto-EDN adapter grants clients that request at once by round robin, and every client is served.

``sep_crypto_edn_multisink_arbitration_test`` proves AES and KMAC complete and
that their beat time-spans overlap. It cannot create a same-cycle dual
``edn_req``: AES/KMAC masking reseeds are short pulses separated by AXI
configuration. This test holds AES (crypto_edn[0]), KMAC (crypto_edn[1]) and
OTBN URND (crypto_edn[3]) with ``edn_req`` high *before* EDN is enabled, then
brings up the real entropy chain so ``prim_arbiter_ppc`` inside
``drbg_axis_edn_adapter`` has to grant all three. KMAC requests EDN once
``CFG_SHADOWED.entropy_ready`` is set in EDN mode ("Once the
!!CFG_SHADOWED.entropy_ready bit is set after reset, the module requests fresh
entropy from EDN for reseeding the internal PRNG.", kmac.hjson:527).
CHK-NO-STARVE grades sharing between AES and URND. The ``edn_ack`` order at the
client ports is logged only (``INFO-EDN-GRANT-SEQ``): the distribution figure of
``hw/sys/sep/doc/trng.adoc`` (``sep-trng-distribution.svg``) shows the arbiter
filling a one-entry FIFO per client, so that order is not the arbitration order.
CHK-EDN-ARB-RR grades the arbitration order on the arbiter taps.

While the three requests are held, ``EXT_TRNG_SRC_SEL`` selects the external
stream for the crypto path (its reset value) and the external stream driver
offers single words on stream 1, each one followed by its grant. Two rounds of
six words are gated: each word is offered only when every client of the round
requests at the arbiter. Round 1 is AES, KMAC and URND. Then words are offered
on request until no client requests, so OTBN completes its post-reset secure
wipe on external words, an OTBN program blocks on the RND CSR, and AES
(``TRIGGER.PRNG_RESEED``) and KMAC (``CMD.entropy_req``) request a reseed. Round
2 is AES, KMAC and OTBN RND. In each round, from the second word on, the client
granted the previous word requests again while the other two have requested
since that grant, so the round-robin rule decides every later grant. Words are
then offered until no client requests and OTBN is idle; AES and KMAC request a
reseed again and OTBN starts the RND program again, which holds URND, so AES,
KMAC and URND are held at the EDN enable. ``SepEsrcConfigSeq`` then selects the
internal DRBG. The external words are a fixed sequence, so this window does not
depend on the seed.

The grant monitor starts only after the ESRC seed is ready so the dual-req
window is not sampled during ``wait_seed_ready``. CHK1..CHK4 stay bit-exact
on that bring-up.

After the EDN enable OTBN RND (crypto_edn[2]) is driven again as its own client
-- a program that reads RND four times -- for routing and consume, and a keyed
KMAC digest follows on the KMAC client.

Four crypto sinks are live (AES, KMAC, OTBN URND and OTBN RND) plus the entropy
pool, so CHK5 is five-sink ROUTING: each post-adapter beat equals the AXIS1 word
the adapter granted that cycle.

Checkers:
  CHK-DUAL-REQ     AES and URND hold crypto_edn_req high together.
  CHK-KMAC-REQ     after the CFG_SHADOWED write, KMAC holds crypto_edn_req high
                   together with AES and URND (kmac.hjson:527).
  CHK-NO-STARVE    both requesting clients get edn_ack.
  CHK-RND-REQ      OTBN raises its RND request bit.
  CHK-RND-CONSUME  the RND CSR reads retire with ERR_BITS=0 (rnd_rep_chk_fail,
                   a chance outcome, is logged only); OTBN
                   theory_of_operation.md:137 states ERR_BITS 0 for a
                   successful run. The stored words are logged as
                   INFO-RND-WORDS.
  CHK-KMAC-CLIENT  a keyed KMAC-256 on the KMAC client matches the Keccak golden.
  CHK-FOUR-CLIENT  all four adapter clients are granted in one run.
  CHK1..CHK4, CHK-ROUTING  bit-exact entropy golden and five-sink routing.
  CHK-EDN-ARB-RR   the client arbiter is round-robin ("distributes words to
                   native clients 0 = AES, 1 = KMAC, 2 = OTBN RND, 3 = OTBN URND,
                   using round-robin arbitration", ``hw/sys/sep/doc/trng.adoc``
                   :92-93): from the external-stream words to the end of the KMAC
                   client, on
                   the request and grant vectors of the arbiter, no client k is
                   granted again while another client j has requested on every
                   clock since the previous grant of k and has not been granted.
                   Every grant is one-hot and inside the request vector, and no
                   sample has an X or Z bit. The check claims no initial pointer
                   and no bound beyond that. Control
                   (``CTRL-EDN-ARB-RR-ARMED``): the rule decided at least two
                   grants, and the arbiter passed over the lowest-index requester
                   at one of them and the highest-index requester at another; the
                   rule decided a grant to OTBN RND and a grant at which OTBN RND
                   was barred. A grant is decided by the rule when another
                   requesting client k is barred on that clock (a client j
                   requested at the previous grant of k and on every clock since,
                   and has not been granted). The gated rounds create the barred
                   clients: from the second word of a round on, the client
                   granted the previous word is barred. Any arbiter that passes
                   the check then grants all three clients of a round among words
                   one to three and again from word four, so KMAC takes a decided
                   grant that is neither the lowest nor the highest index, and
                   RND takes a decided grant and is barred at the next word. A
                   fixed-priority arbiter, with RND at either end or in the
                   middle, grants a barred client at word two and fails the check.
                   The verdict is taken after CHK-ROUTING, so a FAIL does not hide
                   the other checks.

Probes: ``tb_top.crypto_edn_req_o`` / ``crypto_edn_ack_o`` (observation
ports), ``edn_crypto_arb_req_o`` / ``edn_crypto_arb_gnt_o`` (client arbiter
request and grant). Drive: external TRNG stream 1 (``env/sep_ext_trng_stream.py``).
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, NextTimeStep, ReadOnly, RisingEdge
from env.sep_drbg_scoreboard import SepDrbgScoreboard
from env.sep_ext_trng_stream import SepExtTrngStream
from env.sep_kmac_golden import kmac_family_words
from sep_base_test import sep_base_test
from sep_reg_meta import KMAC, OTBN
from seq_lib.sep_aes_seq import AES_TRIGGER, AES_TRIGGER_PRNG_RESEED, SepAes
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_esrc_bringup_seq import (
    EXT_TRNG_ALL_EXTERNAL,
    EXT_TRNG_SRC_SEL,
    GENERATORS_OFF,
    GENERATORS_ON,
    SepEntropyCfg,
    SepEsrcConfigSeq,
    SepEsrcEnableEdnSeq,
    SepEsrcEnableGeneratorsSeq,
)
from seq_lib.sep_kmac_seq import KMAC_CFG_SHADOWED, KMAC_CMD, SepKmac, SepKmacCfg
from seq_lib.sep_otbn_seq import (
    OTBN_ADDR_STATUS,
    OTBN_DMEM_RND_BASE,
    OTBN_RND_PROG,
    OTBN_RND_READS,
    OTBN_STATUS_IDLE,
    SepOtbn,
)

# ERR_BITS.rnd_rep_chk_fail (otbn.hjson ERR_BITS bit 6).
_M_ERR_RND_REP = OTBN.field_mask("ERR_BITS", "rnd_rep_chk_fail")
# KMAC CMD.entropy_req: a manual reseed of the KMAC PRNG in EDN mode (kmac.hjson).
_KMAC_CMD_ENTROPY_REQ = KMAC.field_mask("CMD", "entropy_req")

_AES_BIT = 0
_KMAC_BIT = 1
_RND_BIT = 2
_URND_BIT = 3
_ALL_CLIENTS = (_AES_BIT, _KMAC_BIT, _RND_BIT, _URND_BIT)
_BOTH = (1 << _AES_BIT) | (1 << _URND_BIT)
_HELD = _BOTH | (1 << _KMAC_BIT)
_RND_HELD = (1 << _AES_BIT) | (1 << _KMAC_BIT) | (1 << _RND_BIT)
# Grants decided by the round-robin rule that CTRL-EDN-ARB-RR-ARMED needs.
_ARB_DECIDED_MIN = 2
# Single words on external stream 1. A gated round is two rounds of its three
# clients; each client seeds a PRNG, or fills a 256-bit RND word, from more than
# two EDN words, so all three still request after the round.
_EXT_STREAM = 1
_EXT_ROUND_WORDS = 6
# Odd, so the word sequence step * n has no repeat and no two RND beats are equal.
_EXT_WORD_STEP = 0x9E3779B9
_EXT_STEP_CYCLES = 20_000
# A run of clocks with no client request that ends an ungated feed, and the
# bounds on the ungated words and on the feeds that wait for OTBN idle.
_EXT_QUIET_CYCLES = 5_000
_EXT_FEED_MAX = 256
_EXT_IDLE_TRIES = 8
_RND_REQ_CYCLES = 200_000

# KMAC-256 keyed cell for the KMAC adapter client. Fixed, because this leaf
# grades arbitration and routing; the KMAC value matrix is walked by
# sep_kmac_mode_strength_rand_test.
_KMAC_KEY = (
    0x00010203,
    0x04050607,
    0x08090A0B,
    0x0C0D0E0F,
    0x10111213,
    0x14151617,
    0x18191A1B,
    0x1C1D1E1F,
)
_KMAC_MSG = [0x00010203, 0x04050607, 0x08090A0B, 0x0C0D0E0F]
_KMAC_S = b"crypto EDN four-client"
# Non-vacuity floors for the sinks whose full stimulus this leaf cannot
# derive. They are above one, so a sink that took nothing fails, and below the
# observed traffic, so a seed change does not trip them. They are NOT
# starvation bounds -- see the floor block in run_scenario for what does and
# does not bound each sink.
_KMAC_MIN_BEATS = 4
_POOL_MIN_BEATS = 16
# One OTBN RND CSR read pulls a 256-bit EDN word, i.e. eight 32-bit beats, so the
# RND routing floor is OTBN_RND_READS x this -- the sink's whole stimulus.
_EDN_BEATS_PER_RND_READ = 8
_DUAL_REQ_CYCLES = 50_000
# Enough consecutive grants to log the grant order, and the floor below
# which the sample says nothing. Literals, so the asserts do not move with the
# collection loop.
_GRANT_SAMPLE_TARGET = 16
_GRANT_MIN_SAMPLES = 4
_GRANT_POLLS = 200_000
_GRANT_POLL_CYCLES = 20


def _req() -> int:
    try:
        return int(cocotb.top.crypto_edn_req_o.value)
    except ValueError:
        return 0


def _ack() -> int:
    try:
        return int(cocotb.top.crypto_edn_ack_o.value)
    except ValueError:
        return 0


def _known(sig) -> int | None:
    """The value of ``sig``, or None when a bit is X or Z."""
    value = sig.value
    bits = str(getattr(value, "binstr", value)).strip()
    return int(bits, 2) if bits and all(c in "01" for c in bits) else None


async def _wait_arb_req(dut, mask: int, what: str) -> None:
    """Wait until every bit of ``mask`` is set on the client arbiter request vector.

    Samples in the read-only phase after each rising edge and returns in the next
    time step, so the caller may write signals.
    """
    for _ in range(_EXT_STEP_CYCLES):
        await RisingEdge(dut.clk_i)
        await ReadOnly()
        req = _known(dut.edn_crypto_arb_req_o)
        if req is not None and req & mask == mask:
            await NextTimeStep()
            return
    raise AssertionError(
        f"CTRL-EDN-ARB-RR-ARMED absent: arbiter requests 0x{mask:x} not all high within "
        f"{_EXT_STEP_CYCLES} clocks {what} "
        f"(edn_crypto_arb_req_o={dut.edn_crypto_arb_req_o.value})"
    )


class _ArbGrantLog:
    """Request and grant vectors of the crypto-EDN client arbiter, per clock, and
    the round-robin rule on them.

    Samples after each rising edge in the read-only phase. A clock counts as a grant
    when the grant vector is non-zero; ``contended`` counts those with two or more
    request bits set. ``onehot_in_req`` stays 1 while every grant is one-hot and
    inside the request vector. ``xz`` counts clocks with an X or Z on either vector.

    ``waiting[k]`` holds the clients that requested at the last grant of k and on
    every known clock since, and were not granted since. A grant to k with
    ``waiting[k]`` non-zero is a violation. A requesting client c other than the
    granted one with ``waiting[c]`` non-zero is barred: the rule decided that
    grant. ``decided`` counts those grants; ``decided_not_low`` and
    ``decided_not_high`` count the ones that did not go to the lowest-index or the
    highest-index requester; ``decided_to[c]`` counts the ones to client c and
    ``decided_barred[c]`` the ones at which client c was barred. An X or Z clock
    empties ``waiting``, so no rule spans it.
    """

    def __init__(self, dut) -> None:
        self.dut = dut
        self.grants = 0
        self.contended = 0
        self.onehot_in_req = 1
        self.xz = 0
        self.decided = 0
        self.decided_not_low = 0
        self.decided_not_high = 0
        self.decided_to = [0] * len(_ALL_CLIENTS)
        self.decided_barred = [0] * len(_ALL_CLIENTS)
        self.violations = 0
        self.first_violation = "none"
        self.waiting = [0] * len(_ALL_CLIENTS)
        self.first: list[str] = []
        self.run = True
        self.task = cocotb.start_soon(self._run())

    def _step(self, req: int, gnt: int) -> None:
        self.waiting = [w & req for w in self.waiting]
        if gnt == 0:
            return
        self.grants += 1
        if bin(req).count("1") >= 2:
            self.contended += 1
        onehot = gnt & (gnt - 1) == 0
        if not onehot or gnt & ~req:
            self.onehot_in_req = 0
        if len(self.first) < _GRANT_SAMPLE_TARGET:
            idx = str(gnt.bit_length() - 1) if onehot else f"g0x{gnt:x}"
            self.first.append(f"0x{req:x}:{idx}")
        if not onehot:
            return
        k = gnt.bit_length() - 1
        barred = [c for c in _ALL_CLIENTS if c != k and req >> c & 1 and self.waiting[c]]
        if barred:
            self.decided += 1
            self.decided_not_low += int(gnt != req & -req)
            self.decided_not_high += int(k != req.bit_length() - 1)
            self.decided_to[k] += 1
            for c in barred:
                self.decided_barred[c] += 1
        if self.waiting[k]:
            self.violations += 1
            if self.first_violation == "none":
                self.first_violation = (
                    f"grant={self.grants}:client{k}:waiting=0x{self.waiting[k]:x}:req=0x{req:x}"
                )
        self.waiting = [w & ~gnt for w in self.waiting]
        self.waiting[k] = req & ~gnt

    async def _run(self) -> None:
        dut = self.dut
        while self.run:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            req = _known(dut.edn_crypto_arb_req_o)
            gnt = _known(dut.edn_crypto_arb_gnt_o)
            if req is None or gnt is None:
                self.xz += 1
                self.waiting = [0] * len(_ALL_CLIENTS)
                continue
            self._step(req, gnt)

    def line(self) -> str:
        return (
            f"grants={self.grants} contended={self.contended} "
            f"onehot_in_req={self.onehot_in_req} xz={self.xz} decided={self.decided} "
            f"decided_not_low={self.decided_not_low} "
            f"decided_not_high={self.decided_not_high} "
            f"decided_rnd={self.decided_to[_RND_BIT]} "
            f"rnd_barred={self.decided_barred[_RND_BIT]} "
            f"violations={self.violations} first_violation={self.first_violation} "
            f"first=[{','.join(self.first)}]"
        )


async def _next_arb_req(dut) -> int:
    """The first non-zero client arbiter request vector within ``_EXT_QUIET_CYCLES``
    clocks, or 0. Returns in the time step after the sample, so the caller may
    write signals.
    """
    for _ in range(_EXT_QUIET_CYCLES):
        await RisingEdge(dut.clk_i)
        await ReadOnly()
        req = _known(dut.edn_crypto_arb_req_o)
        if req:
            await NextTimeStep()
            return req
    await NextTimeStep()
    return 0


class _ExtFeed:
    """Single words on external stream 1, each followed by the grant it causes."""

    def __init__(self, dut, ext: SepExtTrngStream, arb: _ArbGrantLog) -> None:
        self.dut = dut
        self.ext = ext
        self.arb = arb
        self.sent = 0

    async def word(self, what: str) -> None:
        granted = self.arb.grants
        self.sent += 1
        self.ext.send(_EXT_STREAM, [(_EXT_WORD_STEP * self.sent) & 0xFFFFFFFF])
        await self.ext.wait_sent(_EXT_STREAM, bound=_EXT_STEP_CYCLES)
        for _ in range(_EXT_STEP_CYCLES):
            if self.arb.grants > granted:
                return
            await RisingEdge(self.dut.clk_i)
        raise AssertionError(
            f"CTRL-EDN-ARB-RR-ARMED absent: external word {what} was accepted and "
            f"the arbiter granted nothing ({self.arb.line()})"
        )

    async def gated(self, mask: int, what: str) -> None:
        """Offer ``_EXT_ROUND_WORDS`` words, each only when every client of ``mask``
        requests, then wait for those requests once more."""
        for n in range(_EXT_ROUND_WORDS):
            await _wait_arb_req(self.dut, mask, f"before {what} word {n}")
            await self.word(f"{what} {n}")
        await _wait_arb_req(self.dut, mask, f"after the last {what} word")

    async def until(self, stop: int, what: str) -> int:
        """Offer one word per request until a client of ``stop`` requests or no
        client requests for ``_EXT_QUIET_CYCLES`` clocks. Returns that request
        vector, 0 when the feed ended quiet."""
        for n in range(_EXT_FEED_MAX):
            req = await _next_arb_req(self.dut)
            if req == 0 or req & stop:
                return req
            await self.word(f"{what} {n}")
        raise AssertionError(
            f"CTRL-EDN-ARB-RR-ARMED absent: a client still requests after "
            f"{_EXT_FEED_MAX} external words {what} ({self.arb.line()})"
        )

    async def until_idle(self, otbn: SepOtbn, what: str) -> None:
        """Feed until no client requests and OTBN ``STATUS`` reads IDLE."""
        for _ in range(_EXT_IDLE_TRIES):
            await self.until(0, what)
            if await otbn._rd(OTBN_ADDR_STATUS) == OTBN_STATUS_IDLE:
                return
        raise AssertionError(
            f"CTRL-EDN-ARB-RR-ARMED absent: OTBN not IDLE after {_EXT_IDLE_TRIES} "
            f"quiet feeds {what} ({self.arb.line()})"
        )


@pyuvm.test()
class sep_crypto_edn_round_robin_grant_test(sep_base_test):
    """Clients that request together are granted by round robin; all four clients are served."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        await self.bring_up_no_cpu()

        # OTBN is released at cold reset (SW_RESET_N reset 0x7E). Without EDN it
        # parks in UrndRefresh with crypto_edn_req[3] held.
        for _ in range(_DUAL_REQ_CYCLES):
            if _req() & (1 << _URND_BIT):
                break
            await RisingEdge(dut.clk_i)
        else:
            raise AssertionError(
                f"OTBN URND edn_req never asserted (crypto_edn_req_o=0x{_req():x})"
            )

        aes = SepAes(self)
        await aes._wr(AES_TRIGGER, AES_TRIGGER_PRNG_RESEED)

        dual_seen = None
        for _ in range(_DUAL_REQ_CYCLES):
            req = _req()
            if (req & _BOTH) == _BOTH:
                dual_seen = req
                break
            await RisingEdge(dut.clk_i)
        assert dual_seen is not None, (
            "CHK-DUAL-REQ FAIL: AES and OTBN URND edn_req were never high in the "
            f"same cycle (last crypto_edn_req_o=0x{_req():x})"
        )
        self.logger.info(
            "CHK-DUAL-REQ PASS: crypto_edn_req bits 0x%x (AES bit %d + URND bit %d)",
            dual_seen,
            _AES_BIT,
            _URND_BIT,
        )

        kmac = SepKmac(self)
        kmac_cfg = SepKmacCfg(
            mode="kmac",
            sec=256,
            msg_words=list(_KMAC_MSG),
            outlen_bytes=32,
            key_words=list(_KMAC_KEY),
            key_bits=256,
            s=_KMAC_S,
        )
        # The digest run below writes the same CFG_SHADOWED word, so the PRNG
        # configuration latched here is the one it uses.
        kmac_word = kmac_cfg.cfg_word()
        await kmac._wr(KMAC_CFG_SHADOWED, kmac_word)
        await kmac._wr(KMAC_CFG_SHADOWED, kmac_word)
        held_seen = None
        for _ in range(_DUAL_REQ_CYCLES):
            req = _req()
            if (req & _HELD) == _HELD:
                held_seen = req
                break
            await RisingEdge(dut.clk_i)
        assert held_seen is not None, (
            "CHK-KMAC-REQ FAIL: after CFG_SHADOWED with entropy_mode=edn_mode and "
            "entropy_ready=1, KMAC edn_req was never high together with AES and URND "
            f"(last crypto_edn_req_o=0x{_req():x})"
        )
        self.logger.info(
            "CHK-KMAC-REQ PASS: crypto_edn_req bits 0x%x (AES, KMAC and URND held)",
            held_seen,
        )

        # Start the arbiter sampler, then supply single words on the external
        # stream while the three requests are held.
        arb = _ArbGrantLog(dut)
        await SepAxiRegDriver(self)._wr(EXT_TRNG_SRC_SEL, EXT_TRNG_ALL_EXTERNAL)
        ext = SepExtTrngStream(dut, logger=self.logger).start(streams=(_EXT_STREAM,))
        feed = _ExtFeed(dut, ext, arb)
        await feed.gated(_HELD, "AES/KMAC/URND")
        self.logger.info("INFO-EDN-ARB-EXT round=held words=%d %s", feed.sent, arb.line())

        # RND requests only while an OTBN program is blocked on the RND CSR, and
        # OTBN executes only after its post-reset secure wipe, which reseeds URND.
        otbn = SepOtbn(self)
        await feed.until_idle(otbn, "to the OTBN post-reset wipe")
        await otbn.load_program(OTBN_RND_PROG)
        await otbn.start_execute()
        req = await feed.until(1 << _RND_BIT, "to the RND request")
        if not req & (1 << _RND_BIT):
            raise AssertionError(
                "CTRL-EDN-ARB-RR-ARMED absent: OTBN RND never requested at the arbiter "
                f"after EXECUTE ({arb.line()})"
            )
        await aes._wr(AES_TRIGGER, AES_TRIGGER_PRNG_RESEED)
        await kmac._wr(KMAC_CMD, _KMAC_CMD_ENTROPY_REQ)
        await feed.gated(_RND_HELD, "AES/KMAC/RND")
        self.logger.info("INFO-EDN-ARB-EXT round=rnd words=%d %s", feed.sent, arb.line())
        await feed.until_idle(otbn, "to the end of the RND program")

        # Hold AES, KMAC and URND again for the EDN enable: the EXECUTE reseeds URND.
        await aes._wr(AES_TRIGGER, AES_TRIGGER_PRNG_RESEED)
        await kmac._wr(KMAC_CMD, _KMAC_CMD_ENTROPY_REQ)
        await otbn.load_program(OTBN_RND_PROG)
        await otbn.start_execute()
        await _wait_arb_req(dut, _HELD, "after the external words")
        await ext.stop()
        self.logger.info("INFO-EDN-ARB-EXT round=end words=%d %s", feed.sent, arb.line())

        # Same entropy bring-up as the other no_cpu consumers, split so the
        # grant monitor is not running during wait_seed_ready.
        cfg = SepEntropyCfg()
        self.entropy_cfg = cfg
        self.drbg_sb = SepDrbgScoreboard(
            dut,
            self.logger,
            strict=True,
            golden_kwargs=cfg.golden_kwargs(),
            chk2_backdoor=cfg.chk2_backdoor,
            score_km=False,
            score_sinks={
                "aes": "golden",
                "otbn_urnd": "golden",
                "otbn_rnd": "golden",
                "kmac": "golden",
                # The entropy FIFO pulls mux endpoint [2] from reset, so the pool
                # is a live fifth endpoint throughout and is scored rather than
                # left unclaimed while four crypto clients are loading the DRBG.
                "pool": "golden",
            },
        )
        self.drbg_sb.start()
        await self.assert_noise_force_active()
        await self.start_seq(SepEsrcConfigSeq("esrc_config", cfg=cfg))
        await self.drbg_sb.grade_ro_enable(self, GENERATORS_OFF)
        await self.start_seq(SepEsrcEnableGeneratorsSeq("esrc_enable_gens"))
        if not await self.wait_seed_ready():
            await self.report_entropy_stall()
            raise AssertionError("ESRC never produced a seed (drbg_seed_valid_o)")
        await self.drbg_sb.grade_ro_enable(self, GENERATORS_ON)
        self.start_fifo_drain()
        self.drbg_sb.enable_chk5()

        grants: list[int] = []
        dual_grants: list[int] = []
        # Which adapter clients were granted anywhere in the run. `grants` is the
        # AES/URND dual-request sample and records only those two bits; CHK-FOUR-CLIENT
        # needs every client, including the two driven later.
        acked = {"mask": 0}

        async def _monitor() -> None:
            prev_ack = 0
            while True:
                await RisingEdge(dut.clk_i)
                req = _req()
                ack = _ack()
                for bit in _ALL_CLIENTS:
                    mask = 1 << bit
                    rising = (ack & mask) and not (prev_ack & mask)
                    if not rising:
                        continue
                    acked["mask"] |= mask
                    if bit in (_AES_BIT, _URND_BIT) and (req & mask):
                        grants.append(bit)
                        if (req & _BOTH) == _BOTH:
                            dual_grants.append(bit)
                prev_ack = ack

        # The three clients are still held (EDN has not been enabled). Start the
        # grant sampler, then enable EDN so the adapter has to pick.
        cocotb.start_soon(_monitor())
        await self.start_seq(SepEsrcEnableEdnSeq("esrc_enable_edn"))

        # Collect grants for a fixed budget; the asserts below decide.
        for _ in range(_GRANT_POLLS):
            if len(grants) >= _GRANT_SAMPLE_TARGET:
                break
            await ClockCycles(dut.clk_i, _GRANT_POLL_CYCLES)
        assert len(grants) >= _GRANT_MIN_SAMPLES, (
            f"CHK-NO-STARVE FAIL: only {len(grants)} post-adapter grants observed in "
            f"{_GRANT_POLLS} polls of {_GRANT_POLL_CYCLES} cycles, need "
            f"{_GRANT_MIN_SAMPLES} to judge sharing "
            f"(grants={grants[:16]} dual_grants={dual_grants[:16]})"
        )

        assert _AES_BIT in grants and _URND_BIT in grants, (
            f"CHK-NO-STARVE FAIL: a requesting client got no edn_ack (grants={grants})"
        )
        self.logger.info(
            "CHK-NO-STARVE PASS: both clients acked (AES grants=%d URND grants=%d)",
            grants.count(_AES_BIT),
            grants.count(_URND_BIT),
        )

        # The round-robin arbiter fills a one-entry FIFO per client (the
        # sep-trng-distribution.svg figure of hw/sys/sep/doc/trng.adoc), so the
        # edn_ack order at the client ports is not the arbitration order.
        alt_pairs = 0
        for a, b in zip(grants, grants[1:]):
            if a == b:
                break
            alt_pairs += 1
        self.logger.info(
            "INFO-EDN-GRANT-SEQ graded=none alt_pairs=%d grants=%s dual_grants=%s",
            alt_pairs,
            grants[:16],
            dual_grants[:12],
        )

        # --- OTBN RND, the fourth adapter client -----------------------------
        # The RND program started before the EDN enable ends on internal words;
        # the next run is the routing and consume proof of RND.
        await otbn.wait_idle("post-held-rnd-prog", timeout=8_000)
        await otbn.load_program(OTBN_RND_PROG)
        await otbn.start_execute()

        rnd_req_seen = False
        for _ in range(_RND_REQ_CYCLES):
            if _req() & (1 << _RND_BIT):
                rnd_req_seen = True
                break
            await RisingEdge(dut.clk_i)
        assert rnd_req_seen, (
            "CHK-RND-REQ FAIL: OTBN RND never raised crypto_edn_req bit "
            f"{_RND_BIT} while a program was blocked on the RND CSR "
            f"(last crypto_edn_req_o=0x{_req():x}). Without this request "
            "CHK5_otbn_rnd cannot fail."
        )
        self.logger.info(
            "CHK-RND-REQ PASS: OTBN raised crypto_edn_req bit %d (RND) (crypto_edn_req_o=0x%x)",
            _RND_BIT,
            _req(),
        )

        await otbn.wait_idle("post-rnd-prog", timeout=20_000)
        rnd_err = await otbn.read_errbits()
        # rnd_rep_chk_fail (two equal EDN words) is a chance outcome: logged, not graded.
        rnd_err_graded = rnd_err & ~_M_ERR_RND_REP
        assert rnd_err_graded == 0, (
            f"CHK-RND-CONSUME FAIL: OTBN RND program ERR_BITS=0x{rnd_err:08x}, "
            "expected 0 without rnd_rep_chk_fail"
        )
        rnd_words = await otbn.read_dmem_words(OTBN_DMEM_RND_BASE, OTBN_RND_READS)
        self.logger.info(
            "CHK-RND-CONSUME PASS: %d RND CSR reads retired with ERR_BITS=0x%x "
            "(0 without rnd_rep_chk_fail)",
            OTBN_RND_READS,
            rnd_err,
        )
        # No text states the value or the distinctness of the stored words; the
        # bit-exact routing proof is CHK5_otbn_rnd at the adapter.
        self.logger.info(
            "INFO-RND-WORDS rnd_rep_chk_fail=%d distinct=%d words=%s",
            int(bool(rnd_err & _M_ERR_RND_REP)),
            len(set(rnd_words)),
            [f"0x{w:08x}" for w in rnd_words],
        )

        # --- KMAC digest on the KMAC client ----------------------------------
        # A keyed KMAC digest makes the KMAC client a value-checked consumer, so
        # all four clients are live, value-checked consumers in one run.
        kmac_golden = kmac_family_words(**kmac_cfg.golden_kwargs())
        kmac_digest = await kmac.run_family(kmac_cfg, tag="KMAC-fourth-client")
        assert kmac_digest == kmac_golden, (
            "CHK-KMAC-CLIENT FAIL: KMAC digest does not match the Keccak golden "
            f"(got {[f'0x{w:08x}' for w in kmac_digest]}, "
            f"want {[f'0x{w:08x}' for w in kmac_golden]}). A KMAC that took EDN "
            "beats but produced the wrong digest is not a working client."
        )
        await kmac.check_status_clean("EOT")
        self.logger.info(
            "CHK-KMAC-CLIENT PASS: the KMAC adapter client completed a keyed "
            "KMAC-256 matching the Keccak golden"
        )

        # --- CHK-FOUR-CLIENT --------------------------------------------------
        # Every adapter client was granted at some point in this run. The
        # ``_monitor`` grant list ``grants`` holds only AES and URND, so this is
        # taken from the per-client ack bits the monitor accumulated across the
        # whole run.
        acked_mask = acked["mask"]
        missing = [b for b in _ALL_CLIENTS if not (acked_mask & (1 << b))]
        assert not missing, (
            f"CHK-FOUR-CLIENT FAIL: adapter client bit(s) {missing} were never "
            f"granted (acked_mask=0x{acked_mask:x}). drbg_axis_edn_adapter fans out "
            "to AES, KMAC, OTBN RND and OTBN URND, and this leaf drives all four."
        )
        self.logger.info(
            "CHK-FOUR-CLIENT PASS: all four adapter clients were granted in one run "
            "(acked_mask=0x%x)",
            acked_mask,
        )

        arb.run = False
        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        # Routing floors, and exactly what each one is worth.
        #
        # An unobserved beat creates no scoreboard item, so zero mismatches
        # does NOT catch a sink that routed a few beats correctly and then
        # starved. Only a floor catches that -- and a floor only catches it if
        # it is independent of the thing it bounds.
        #
        #   RND   the one real bound: derived from this test's own stimulus,
        #         OTBN_RND_READS CSR reads of _EDN_BEATS_PER_RND_READ beats
        #         each. A DUT that routed part of that and starved fails it.
        #   AES,  non-vacuity floors only. They are constants: above zero, so a
        #   URND  sink that took nothing fails, and below the traffic every
        #   KMAC, seed produces, so a seed change does not trip them. They do
        #   pool  NOT bound their sink's full stimulus.
        #
        # The floors are constants. The scoreboard scores one item per
        # req && ack cycle on the same ports the grant monitor counts, so a
        # grant-derived floor would hold by construction. The grant counts are
        # logged below as diagnostics.
        #
        # What still carries each unbounded sink: AES and URND by CHK-NO-STARVE
        # on the grant stream; KMAC by CHK-KMAC-CLIENT, whose
        # digest cannot match the Keccak golden if its masking reseed was short.
        # The pool has nothing else here, and deriving its floor needs the
        # EDN-beats-per-pool-seed ratio -- a design fact this test does not own.
        self.drbg_sb.set_min_matches(
            CHK5_aes=_GRANT_MIN_SAMPLES,
            CHK5_otbn_urnd=_GRANT_MIN_SAMPLES,
            CHK5_otbn_rnd=OTBN_RND_READS * _EDN_BEATS_PER_RND_READ,
            CHK5_kmac=_KMAC_MIN_BEATS,
            CHK5_pool=_POOL_MIN_BEATS,
        )
        self.logger.info(
            "INFO-ROUTING-FLOORS: rnd>=%d (derived from stimulus); aes>=%d "
            "urnd>=%d kmac>=%d pool>=%d (non-vacuity only, NOT starvation "
            "bounds). Diagnostic, not a floor: %d AES and %d URND grants were "
            "observed on crypto_edn_ack_o.",
            OTBN_RND_READS * _EDN_BEATS_PER_RND_READ,
            _GRANT_MIN_SAMPLES,
            _GRANT_MIN_SAMPLES,
            _KMAC_MIN_BEATS,
            _POOL_MIN_BEATS,
            grants.count(_AES_BIT),
            grants.count(_URND_BIT),
        )
        assert self.drbg_sb.report()
        ra = self.drbg_sb.results["CHK5_aes"]
        ru = self.drbg_sb.results["CHK5_otbn_urnd"]
        rr = self.drbg_sb.results["CHK5_otbn_rnd"]
        rk = self.drbg_sb.results["CHK5_kmac"]
        rp = self.drbg_sb.results["CHK5_pool"]
        self.logger.info(
            "CHK-ROUTING PASS: CHK5_aes match=%d, CHK5_otbn_urnd match=%d, "
            "CHK5_otbn_rnd match=%d and CHK5_kmac match=%d equal the AXIS1 "
            "grant-order stream, and CHK5_pool match=%d equals the AXIS2 stream "
            "(mismatch=0 on all five)",
            ra.matches,
            ru.matches,
            rr.matches,
            rk.matches,
            rp.matches,
        )

        # --- CHK-EDN-ARB-RR, graded last ----------------------------------------
        armed = (
            arb.decided >= _ARB_DECIDED_MIN
            and arb.decided_not_low >= 1
            and arb.decided_not_high >= 1
            and arb.decided_to[_RND_BIT] >= 1
            and arb.decided_barred[_RND_BIT] >= 1
        )
        assert armed, (
            f"CTRL-EDN-ARB-RR-ARMED absent: need {_ARB_DECIDED_MIN} grants decided "
            "by the round-robin rule, one not to the lowest-index requester, one "
            "not to the highest-index requester, one to OTBN RND and one with OTBN "
            f"RND barred ({arb.line()})"
        )
        self.logger.info("CTRL-EDN-ARB-RR-ARMED seen: %s", arb.line())
        assert arb.violations == 0 and arb.onehot_in_req == 1 and arb.xz == 0, (
            f"CHK-EDN-ARB-RR FAIL: {arb.line()}"
        )
        self.logger.info("CHK-EDN-ARB-RR PASS: %s", arb.line())
