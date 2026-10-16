# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Every entropy sink of a drawn set completes in one overlapping run, and the Key
Manager sampler takes the external stream when stream 0 selects it.

Contract (``hw/sys/sep/doc/trng.adoc``, Distribution and Source Selection):
  * Stream 0 goes to the Key Manager sampler, stream 1 to the crypto clients
    (round-robin), stream 2 to the pool. With the Key Manager sampler, the crypto
    sinks and the pool active in one run, every requesting sink completes its count.
  * With ``EXT_TRNG_SRC_SEL`` bit 0 set the Key Manager sampler receives the
    external stream: each word accepted at external port 0 appears unchanged and in
    order on the Key Manager stream after the mux, the external source sees the
    ready of the Key Manager ("The selected source receives the sink's ready
    signal"), and with bits 1 and 2 clear streams 1 and 2 carry the internal
    endpoint words (the selection is combinational).

Run mode: no_cpu (``lsu_stub_all_live``), real fuse sense, ``+esrc_noise_force``,
the firmware image and plusargs of the open multi-sink Key Manager test
(``rom_main``, ``+km_rom_hex=rom_main.rom.parhex``). Each seed runs two runs of the
same firmware with a ``rst_ni`` pulse between them: the internal run (one sink-set
round) and the external Key Manager run (the external stream driver
``env/sep_ext_trng_stream.py`` on stream 0). A per-clock accumulator of this leaf
reads the sink request and completion probes, the post-mux probes, the internal
DRBG endpoint tap and the external port taps after each falling edge.
After the graded external run the leaf writes bit 0 clear while the internal endpoint
of stream 0 holds tvalid, so the held external beat transfers with ready high and no
beat that the sampler sees is withdrawn before handshake.

Randomization (``SepSeededRng`` from the run seed, drawn before the first stimulus):
the sink set (all six sinks with weight 1/2, else the Key Manager sampler plus 2 to
4 of the other five), the counts (AES blocks 4 to 64, KMAC hashes 1 to 8, OTBN RND
and URND reads 1 to 8, pool pops 1 to 32, Key Manager sampler words 1 to 16), the
first-request delays (fractions of half of the shortest clean busy time), the AES
and KMAC data, the external gap pattern (gaps of 0 to 32 clocks, or one gap of 64
clocks) and the unique external beat words. The sink-set probability is a coverage
rate across seeds only; no check depends on it.

Checkers:
  CHK-MIX-SINK    every sink of the set reaches its count and completes, its tail
                  operation completes, and its probe shows words. Control
                  ``CTRL-MIX-OVERLAP``: every pair of busy windows overlaps.

Overlap by construction: in the overlapped run each unit runs its drawn operation
and then waits at a barrier. The barrier opens on the first clock on which the
request probe of every sink of the set has shown a request. After it opens, each
unit waits until the request probe of each of its sinks has been low for 16 clocks
(the pool also refills to 32 entries first) and marks that clock M. Then it runs one
tail operation that makes its sinks request again (one Key Manager generate, one AES
block, one KMAC ``CMD.entropy_req`` write, one OTBN program with one RND and one URND
read of the set, one pool pop). The tail of a sink is served only by a request that
starts after M and after the barrier clock and completes at least one word before the
request probe drops; a completion of the drawn operation cannot serve it. Every busy
window then starts at or before the barrier clock and ends after it, so every pair
overlaps. A sink whose tail request the DUT does not serve fails ``CHK-MIX-SINK``
with ``reason=timeout:tail_ack``.
  CHK-MIX-EXT-KM  with bit 0 set every beat that completes at external port 0
                  appears at ``km_entropy_*`` in order and value; the external
                  tready equals ``km_entropy_tready_o`` on every clock; ``axis1``
                  and ``axis2`` carry the internal endpoint words. Control: with bit
                  0 clear the same beats see tready 1 and ``km_entropy_*`` carries
                  the endpoint word; ``axis1`` and ``axis2`` show tvalid; with bit 0
                  set ``km_entropy_tready_o`` reads 0 on at least one clock. No
                  graded probe (request, completion, tvalid, tready, and the tdata
                  of each graded beat) reads X or Z (``xz`` = 0), and a beat with an
                  X or Z tdata is a mismatch in every compare.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, Event, FallingEdge, ReadOnly, RisingEdge
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
from seq_lib.sep_entropy_pool_seq import POOL_POP, RESP_OKAY, SepEntropyPool, pool_level
from seq_lib.sep_km_mailbox_seq import KM_DEST_AES, SepKmMailbox
from seq_lib.sep_kmac_seq import KMAC_CMD, SepKmac, SepKmacCfg
from seq_lib.sep_otbn_seq import SepOtbn
from seq_lib.sep_sw_reset_seq import SW_RESET_N_RESET_DEFAULT

TEST = "sep_drbg_sink_mix_rand_test"

SEL_ADDR = SEP_CPU_CTRL.addr("EXT_TRNG_SRC_SEL")
CMD_ENTROPY_REQ = KMAC.field_mask("CMD", "entropy_req")

SINKS = ("km", "aes", "kmac", "otbn_rnd", "otbn_urnd", "pool")
OTHERS = SINKS[1:]
# Crypto client index of crypto_edn_*_o (bit i = client i).
CLIENT_BIT = {"aes": 0, "kmac": 1, "otbn_rnd": 2, "otbn_urnd": 3}
# Engines of SW_RESET_N per sink; the pool and the sampler have none here.
ENGINE = {"aes": "aes", "kmac": "kmac", "otbn_rnd": "otbn", "otbn_urnd": "otbn"}
# Engines the leaf may park: the Key Manager firmware writes ABR registers at boot
# (``hw/ip/key_manager/approm/prod/drivers/rom_boot.c``, the ML-KEM shared-key IRQ
# enable), and an access to a domain held in reset completes with SLVERR
# (``hw/sys/sep/doc/reset_controller.adoc``, Isolation and Reset Sequencing), which the
# firmware reports as an unrecoverable fault instead of RESP_KM_READY. ABR stays
# released in both runs.
PARKABLE = ("otbn", "aes", "hmac", "kmac")
CSR_RND = 0xFC0
CSR_URND = 0xFC1
# Key Manager key size of one generate (8 words; ``key_generate`` takes size - 1).
KM_KEY_WORDS = 8
POOL_DEPTH = 32
KMAC_MSG_WORDS = 4
GAP_TABLE = 256
EXT_WORDS = 16_384
LONG_GAP = 64
SETTLE_CAP = 40_000
STATUS_READS = 64
KM_OP_TIMEOUT = 400_000
# Beats the bridge keeps queued on external port 0 across the select write (each
# transfers in one clock while bit 0 is clear; the write takes about 15 clocks).
BRIDGE_DEPTH = 4
# Clocks with every request probe of a unit low before its tail operation starts.
QUIET_CLKS = 16


def _le_words(data: bytes) -> list[int]:
    return [int.from_bytes(data[i : i + 4], "little") for i in range(0, len(data), 4)]


def _kill(task) -> None:
    if task.done():
        return
    stop = getattr(task, "cancel", None) or task.kill
    stop()


# ----------------------------------------------------------------------------- plan
@dataclass(frozen=True)
class Plan:
    seed: int
    sinks: tuple[str, ...]
    counts: dict
    delay_frac: dict  # per unit, per mille of half the shortest clean busy time
    aes_row: int
    aes_pt: tuple[int, ...]
    kmac_msgs: tuple[tuple[int, ...], ...]
    gap_pattern: str
    gaps: tuple[int, ...]
    long_at: int
    ext_words: tuple[int, ...]
    aes_tail_pt: tuple[int, ...]

    def units(self) -> tuple[str, ...]:
        """Operations of the set: OTBN RND and URND share one OTBN program."""
        out = []
        for s in self.sinks:
            u = "otbn" if s.startswith("otbn") else s
            if u not in out:
                out.append(u)
        return tuple(out)

    def describe(self) -> str:
        counts = ",".join(f"{s}={self.counts[s]}" for s in self.sinks)
        return (
            f"sinks={','.join(self.sinks)} counts={counts} "
            f"delay_frac={[self.delay_frac[u] for u in self.units()]} "
            f"aes_row={AES_KEY_ROWS[256][self.aes_row][0]} gap={self.gap_pattern} "
            f"long_at={self.long_at}"
        )


def draw_plan(seed: int) -> Plan:
    """Every draw of the leaf, in a fixed order, with no simulator access."""
    rng = SepSeededRng(seed)
    if rng.randrange(0, 2) == 0:
        sinks = SINKS
    else:
        picked = rng.sample(OTHERS, rng.randrange(2, 5))
        sinks = ("km",) + tuple(s for s in OTHERS if s in picked)
    counts = {
        "km": rng.randrange(1, 17),
        "aes": rng.randrange(4, 65),
        "kmac": rng.randrange(1, 9),
        "otbn_rnd": rng.randrange(1, 9),
        "otbn_urnd": rng.randrange(1, 9),
        "pool": rng.randrange(1, 33),
    }
    delay = {u: rng.randrange(0, 1001) for u in ("km", "aes", "kmac", "otbn", "pool")}
    aes_row = rng.randrange(len(AES_KEY_ROWS[256]))
    used: set[int] = set()

    def take(n: int) -> tuple[int, ...]:
        out = []
        while len(out) < n:
            w = rng.getrandbits(32)
            if w and w not in used:
                used.add(w)
                out.append(w)
        return tuple(out)

    aes_pt = take(4 * counts["aes"])
    kmac_msgs = tuple(take(KMAC_MSG_WORDS) for _ in range(counts["kmac"]))
    pattern = rng.choice(("random", "long"))
    gaps = tuple(rng.randrange(0, 33) for _ in range(GAP_TABLE))
    long_at = rng.randrange(1, 9)
    ext_words = take(EXT_WORDS)
    aes_tail_pt = take(4)
    return Plan(
        seed, tuple(sinks), counts, delay, aes_row, aes_pt, kmac_msgs, pattern, gaps,
        long_at, ext_words, aes_tail_pt,
    )  # fmt: skip


def otbn_prog(rnd: int, urnd: int) -> tuple[int, ...]:
    """OTBN program: RND and URND reads alternated, each stored to the next DMEM word."""
    prog = [addi(T1, 0, 0)]
    k = 0
    for i in range(max(rnd, urnd)):
        for csr, n in ((CSR_RND, rnd), (CSR_URND, urnd)):
            if i < n:
                prog += [csrr(A0, csr), sw(A0, T1, 4 * k)]
                k += 1
    return tuple(prog + [ECALL])


# ----------------------------------------------------------------------------- probes
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


@dataclass
class SinkStat:
    first_req: int | None = None
    first_ack: int | None = None
    last_ack: int | None = None
    acks: int = 0
    # Request episodes: a span of clocks with the request probe 1. ``eps`` holds the
    # closed ones as (start clock, completions inside the span).
    ep_start: int | None = None
    ep_words: int = 0
    eps: list = field(default_factory=list)
    last_req: int | None = None
    orphan_acks: int = 0

    def served(self, after: int) -> tuple[int, int] | None:
        """First request episode that starts after ``after`` and completes a word."""
        eps = list(self.eps)
        if self.ep_start is not None:
            eps.append((self.ep_start, self.ep_words))
        for start, words in eps:
            if start > after and words >= 1:
                return start, words
        return None


class _Acc:
    """Per-clock accumulator of the sink probes and, in the external run, of stream 0.

    Samples after each falling edge of ``clk_i`` in the read-only phase. Requests:
    ``km_entropy_tready_o`` (the sampler pulls), ``crypto_edn_req_o[i]``,
    ``pool_edn_req_o``. Completions: the ``km_entropy`` handshake,
    ``crypto_edn_ack_o[i]``, ``pool_edn_ack_o``.
    """

    def __init__(self, dut) -> None:
        self.dut = dut
        self.clk = 0
        self.life = MonitorLife("SINK-MIX-ACC", lambda: self.clk)
        self.reset()

    def reset(self, *, ext: bool = False) -> None:
        self.stat = {s: SinkStat() for s in SINKS}
        self.ext = ext
        self.ext_beats: list[int | None] = []
        self.km_beats: list[int | None] = []
        self.ext_not_ready = 0
        self.tready_neq = 0
        self.km_tready_low = 0
        self.km_ep_neq = 0
        self.axis_neq = [0, 0, 0]
        self.axis_valid = [0, 0, 0]
        self.xz = 0

    def start(self) -> "_Acc":
        self.life.start(self._run())
        return self

    async def stop(self) -> None:
        await self.life.stop()

    def _seen(self, sink: str, req: int | None, ack: int | None) -> None:
        st = self.stat[sink]
        if req is None or ack is None:
            self.xz += 1
            return
        if req:
            st.last_req = self.clk
            if st.first_req is None:
                st.first_req = self.clk
            if st.ep_start is None:
                st.ep_start, st.ep_words = self.clk, 0
        if ack:
            st.acks += 1
            st.last_ack = self.clk
            if st.first_ack is None:
                st.first_ack = self.clk
            if st.ep_start is None:
                st.orphan_acks += 1
            else:
                st.ep_words += 1
        if not req and st.ep_start is not None:
            st.eps.append((st.ep_start, st.ep_words))
            st.ep_start = None

    def quiet(self, sinks: list[str]) -> bool:
        """Every request probe of ``sinks`` is low and was low for ``QUIET_CLKS`` clocks."""
        for s in sinks:
            st = self.stat[s]
            if st.ep_start is not None:
                return False
            if st.last_req is not None and self.clk - st.last_req < QUIET_CLKS:
                return False
        return True

    def _x(self, v: int | None) -> int | None:
        if v is None:
            self.xz += 1
        return v

    async def _run(self) -> None:
        d = self.dut
        while True:
            await FallingEdge(d.clk_i)
            await ReadOnly()
            self.clk += 1
            kv, kr = _known(d.km_entropy_tvalid_o), _known(d.km_entropy_tready_o)
            creq, cack = _known(d.crypto_edn_req_o), _known(d.crypto_edn_ack_o)
            km_hs = None if kv is None or kr is None else kv & kr
            self._seen("km", kr, km_hs)
            for s, i in CLIENT_BIT.items():
                self._seen(s, _bit(creq, i), _bit(cack, i))
            self._seen("pool", _known(d.pool_edn_req_o), _known(d.pool_edn_ack_o))
            if not self.ext:
                continue
            # X or Z on a graded probe counts into ``xz`` and reads None, and None is
            # a mismatch in every compare below (never equal to None).
            ev = _bit(self._x(_known(d.ext_trng_tvalid_o)), 0)
            er = _bit(self._x(_known(d.ext_trng_tready_o)), 0)
            graded = kv == 1 or any(_known(v) != 0 for v in (d.axis1_tvalid_o, d.axis2_tvalid_o))
            iv = self._x(_known(d.drbg_int_tvalid_o)) if graded else None
            idata = self._x(_known(d.drbg_int_tdata_o)) if graded else None
            kd = self._x(_known(d.km_entropy_tdata_o)) if kv == 1 else None
            if ev == 1 and er == 1:
                self.ext_beats.append(_word(self._x(_known(d.ext_trng_tdata_o)), 0))
            if ev == 1 and er != 1:
                self.ext_not_ready += 1
            if km_hs == 1:
                self.km_beats.append(kd)
            if er is None or kr is None or er != kr:
                self.tready_neq += 1
            if kr == 0:
                self.km_tready_low += 1
            if kv == 1:
                self.axis_valid[0] += 1
                if _bit(iv, 0) != 1 or kd is None or idata is None or kd != _word(idata, 0):
                    self.km_ep_neq += 1
            for j, (v, dat) in enumerate(
                ((d.axis1_tvalid_o, d.axis1_tdata_o), (d.axis2_tvalid_o, d.axis2_tdata_o)), 1
            ):
                tv = self._x(_known(v))
                if tv is None:
                    self.axis_neq[j] += 1
                elif tv == 1:
                    self.axis_valid[j] += 1
                    ad = self._x(_known(dat))
                    if _bit(iv, j) != 1 or ad is None or idata is None or ad != _word(idata, j):
                        self.axis_neq[j] += 1


class _Reg(SepAxiRegDriver):
    _DRIVER_TAG = "MIX"


# ----------------------------------------------------------------------------- leaf
@pyuvm.test()
class sep_drbg_sink_mix_rand_test(sep_base_test):
    """Drawn sink set in one overlapping run; external stream into the KM sampler."""

    required_evidence = ("CHK-MIX-SINK", "CHK-MIX-EXT-KM")

    async def run_scenario(self) -> None:
        seed = self.random_seed()
        plan = draw_plan(seed)
        self.plan = plan
        image = self.select_efuse_image(lc_raw=0x1)  # LC_PROD: KM reads OTP at boot
        self.write_efuse_image(image)
        engines = {ENGINE[s] for s in plan.sinks if s in ENGINE}
        park = tuple(e for e in PARKABLE if e not in engines)
        await self.bring_up_no_cpu(park=park)
        self.logger.info("PLAN seed=%d %s", seed, plan.describe())
        self.chk = SepChkLog(self, TEST, seed)
        self.reg = _Reg(self)
        self.acc = _Acc(cocotb.top).start()
        try:
            await self._internal_run()
            await self._external_run()
        finally:
            close_graded_window(self.logger)
            if getattr(self, "drbg_sb", None) is not None:
                self.drbg_sb.stop()
        await self.acc.stop()
        self.chk.finish()

    # --- shared -----------------------------------------------------------------------
    async def _boot(self) -> None:
        """Select 0, bring up ESRC, CSRNG and EDN, boot the Key Manager firmware."""
        await self.reg._wr(SEL_ADDR, 0)
        self.logger.info("RUN sw_reset_n=0x%02x ext_trng_src_sel=0x0", self.swrst.value)
        await self.bring_up_entropy(strict=False, score_km="observe")
        if not await self.wait_genbits():
            raise AssertionError("CSRNG never produced genbits")
        self.start_fifo_drain(log_batches=False)
        self.km = SepKmMailbox(self)
        await self.swrst.release("km")
        await self.km.wait_km_ready()

    async def _end_run(self) -> None:
        await self.stop_fifo_drain()
        self.drbg_sb.stop()

    async def _until(self, pred, bound: int) -> int | None:
        for n in range(bound + 1):
            if pred():
                return n
            await RisingEdge(cocotb.top.clk_i)
        return None

    # --- sink operations ----------------------------------------------------------------
    async def _unit(self, unit: str) -> dict:
        """Run one unit of the set to its count. Returns ``ops`` and ``done``."""
        plan = self.plan
        c = plan.counts
        if unit == "km":
            ops = -(-c["km"] // KM_KEY_WORDS)
            for _ in range(ops):
                await self.km.key_generate(
                    dest=KM_DEST_AES, req_size=KM_KEY_WORDS - 1, timeout=KM_OP_TIMEOUT
                )
            return {"ops": ops, "done": True}
        if unit == "aes":
            key = _le_words(AES_KEY_ROWS[256][plan.aes_row][1])
            ctrl = build_aes_ctrl(
                sideload=False,
                operation=AES_OP_ENC,
                mode=AES_MODE_ECB,
                key_len=AES_KEY_LEN_256,
                reseed_rate=AES_PRS_RATE_PER_1,
            )
            await self.aes.wait_idle("pre-config")
            await self.aes._wr(AES_CTRL_SHADOWED, ctrl)
            await self.aes._wr(AES_CTRL_SHADOWED, ctrl)
            await self.aes.wait_idle("post-config")
            await self.aes.load_key_iv(key)
            ct = await self.aes.run_blocks(list(plan.aes_pt))
            golden = aes_encrypt_words("ecb", key, list(plan.aes_pt))
            return {"ops": len(ct) // 4, "done": True, "result==golden": int(ct == golden)}
        if unit == "kmac":
            await self.kmac._wait_idle("pre-entropy-req")
            await self.kmac._wr(KMAC_CMD, CMD_ENTROPY_REQ)
            good = 0
            for msg in plan.kmac_msgs:
                cfg = SepKmacCfg(
                    mode="kmac",
                    sec=256,
                    msg_words=list(msg),
                    outlen_bytes=32,
                    key_words=_le_words(KMAC_SAMPLE_KEY_ROW[1]),
                    key_bits=256,
                )
                digest = await self.kmac.run_family(cfg, tag="mix")
                good += int(digest == kmac_family_words(**cfg.golden_kwargs()))
            n = len(plan.kmac_msgs)
            return {"ops": n, "done": True, "result==golden": int(good == n)}
        if unit == "otbn":
            rnd = c["otbn_rnd"] if "otbn_rnd" in plan.sinks else 0
            urnd = c["otbn_urnd"] if "otbn_urnd" in plan.sinks else 0
            await self.otbn.load_program(otbn_prog(rnd, urnd))
            await self.otbn.execute()
            err = await self.otbn.read_errbits()
            return {"ops": rnd + urnd, "done": err == 0, "err_bits": err}
        # pool: the drawn number of pops after it fills.
        pops = 0
        for _ in range(c["pool"]):
            for _ in range(STATUS_READS):
                if pool_level(await self.pool.status()) >= 1:
                    break
                await ClockCycles(cocotb.top.clk_i, 16)
            seq = await self.pool.access(POOL_POP)
            pops += int(seq.resp_code == RESP_OKAY)
        return {"ops": pops, "done": pops == c["pool"]}

    async def _tail(self, unit: str) -> dict:
        """One operation of ``unit`` that makes each of its sinks request entropy again."""
        plan = self.plan
        if unit == "km":
            await self.km.key_generate(
                dest=KM_DEST_AES, req_size=KM_KEY_WORDS - 1, timeout=KM_OP_TIMEOUT
            )
            return {"done": True}
        if unit == "aes":
            key = _le_words(AES_KEY_ROWS[256][plan.aes_row][1])
            ct = await self.aes.run_blocks(list(plan.aes_tail_pt))
            golden = aes_encrypt_words("ecb", key, list(plan.aes_tail_pt))
            return {"done": True, "result==golden": int(ct == golden)}
        if unit == "kmac":
            # Manual reseed in EDN mode (kmac.hjson, CMD.entropy_req) while KMAC is idle.
            await self.kmac._wait_idle("pre-tail-entropy-req")
            await self.kmac._wr(KMAC_CMD, CMD_ENTROPY_REQ)
            return {"done": True}
        if unit == "otbn":
            rnd = int("otbn_rnd" in plan.sinks)
            urnd = int("otbn_urnd" in plan.sinks)
            await self.otbn.load_program(otbn_prog(rnd, urnd))
            await self.otbn.execute()
            err = await self.otbn.read_errbits()
            return {"done": err == 0, "err_bits": err}
        # The pool is full (32 entries) when its tail starts.
        seq = await self.pool.access(POOL_POP)
        return {"done": seq.resp_code == RESP_OKAY}

    def _sinks_of(self, unit: str) -> list[str]:
        return [
            s for s in self.plan.sinks if (s.startswith("otbn") and unit == "otbn") or s == unit
        ]

    async def _pool_full(self) -> None:
        for _ in range(STATUS_READS):
            if pool_level(await self.pool.status()) == POOL_DEPTH:
                return
            await ClockCycles(cocotb.top.clk_i, 64)
        raise AssertionError("the pool did not fill to 32 entries")

    # --- internal run -------------------------------------------------------------------
    async def _internal_run(self) -> None:
        plan = self.plan
        self.aes = SepAes(self)
        self.kmac = SepKmac(self)
        self.otbn = SepOtbn(self)
        self.pool = SepEntropyPool(self)
        await self._boot()
        units = plan.units()
        # Step 3: each unit alone; clean busy time t_s and request latency r_s.
        t_s: dict[str, int] = {}
        r_u: dict[str, int] = {}
        for unit in units:
            if unit == "pool":
                await self._pool_full()
            self.acc.reset()
            t0 = self.acc.clk
            res = await self._unit(unit)
            await ClockCycles(cocotb.top.clk_i, 16)
            for s in self._sinks_of(unit):
                st = self.acc.stat[s]
                if st.first_req is None or st.last_ack is None:
                    raise AssertionError(f"solo run of {s}: no request or no completion ({st})")
                t_s[s] = max(1, st.last_ack - st.first_req)
            reqs = [self.acc.stat[s].first_req for s in self._sinks_of(unit)]
            r_u[unit] = max(0, min(reqs) - t0)
            solo = {f"t_{s}": t_s[s] for s in self._sinks_of(unit)}
            solo.update({k: v for k, v in res.items() if k != "done"})
            self.chk.obs("MIX-SOLO", unit=unit, r_clk=r_u[unit], **solo)
        # Step 4: delays from 0 to half of the shortest clean busy time.
        half = min(t_s.values()) // 2
        delay = {u: plan.delay_frac[u] * half // 1000 for u in units}
        big_r = max(r_u.values())
        start = {u: big_r - r_u[u] + delay[u] for u in units}
        sched = {f"start_{u}": start[u] for u in units}
        self.chk.obs("MIX-SCHEDULE", half=half, r_max=big_r, **sched)
        # Step 5: every unit, each launched at its offset after a common start marker;
        # then a barrier on the request probes of every sink, then one tail operation
        # per unit, so every busy window holds the barrier clock.
        if "pool" in units:
            await self._pool_full()
        # Bounds: 16 x the clean time of the same operation in this leaf and seed.
        barrier_bound = 16 * max(start[u] + r_u[u] for u in units)
        tail_bound = {u: 16 * (r_u[u] + max(t_s[s] for s in self._sinks_of(u))) for u in units}
        self.acc.reset()
        open_graded_window(TEST, self.logger)
        results: dict[str, dict] = {}
        tails: dict[str, dict] = {}
        errors: dict[str, str] = {}
        opened = Event()
        barrier: dict[str, int | None] = {"clk": None}
        mark: dict[str, int] = {}
        stat = self.acc.stat

        async def gate() -> None:
            n = await self._until(
                lambda: all(stat[s].first_req is not None for s in plan.sinks), barrier_bound
            )
            if n is not None:
                barrier["clk"] = self.acc.clk
            opened.set()

        async def launch(unit: str) -> None:
            if start[unit]:
                await ClockCycles(cocotb.top.clk_i, start[unit])
            try:
                results[unit] = await self._unit(unit)
            except AssertionError as exc:
                errors[unit] = str(exc)
                return
            await opened.wait()
            if barrier["clk"] is None:
                errors[unit] = f"timeout:barrier bound={barrier_bound}"
                return
            sinks = self._sinks_of(unit)
            try:
                if unit == "pool":
                    await self._pool_full()
            except AssertionError as exc:
                errors[unit] = f"tail:{exc}"
                return
            # No request of the drawn operation is open or recent at the mark M, so
            # only a request that the tail operation makes can start after M.
            n = await self._until(lambda: self.acc.quiet(sinks), tail_bound[unit])
            if n is None:
                errors[unit] = f"timeout:tail_quiet bound={tail_bound[unit]}"
                return
            mark[unit] = self.acc.clk
            try:
                tails[unit] = await self._tail(unit)
            except AssertionError as exc:
                errors[unit] = f"tail:{exc}"
                return
            # Each sink of the unit shows a request that starts after M and completes a
            # word before the request probe drops.
            n = await self._until(
                lambda: all(stat[s].served(mark[unit]) is not None for s in sinks),
                tail_bound[unit],
            )
            if n is None:
                errors[unit] = f"timeout:tail_ack bound={tail_bound[unit]}"

        gate_task = cocotb.start_soon(gate())
        tasks = [cocotb.start_soon(launch(u)) for u in units]
        for t in tasks:
            await t
        await gate_task
        await ClockCycles(cocotb.top.clk_i, 16)
        close_graded_window(self.logger)
        stat = {s: self.acc.stat[s] for s in plan.sinks}
        self.chk.obs(
            "MIX-BARRIER",
            barrier_clk=barrier["clk"] if barrier["clk"] is not None else "none",
            bound=barrier_bound,
            **{f"req_{s}": stat[s].first_req for s in plan.sinks},
        )
        # Step 6: the overlap of every pair of busy windows (control).
        for a, b in combinations(plan.sinks, 2):
            sa, sb = stat[a], stat[b]
            ov = 0
            if None not in (sa.first_req, sa.last_ack, sb.first_req, sb.last_ack):
                ov = min(sa.last_ack, sb.last_ack) - max(sa.first_req, sb.first_req)
            self.chk.ctrl("MIX-OVERLAP", ov > 0, pair=f"{a},{b}", overlap_clk=max(ov, 0))
        for s in plan.sinks:
            unit = "otbn" if s.startswith("otbn") else s
            res = results.get(unit, {})
            tail = tails.get(unit, {})
            st = stat[s]
            done = unit not in errors and bool(res.get("done")) and bool(tail.get("done"))
            # AES ciphertext (drawn and tail blocks) and KMAC digests of the overlapped
            # run equal their goldens.
            golden_ok = unit not in ("aes", "kmac") or res.get("result==golden") == 1
            if unit == "aes":
                golden_ok = golden_ok and tail.get("result==golden") == 1
            need = plan.counts["km"] if s == "km" else 1
            t_clk = barrier["clk"]
            m_clk = mark.get(unit)
            srv = st.served(m_clk) if m_clk is not None else None
            tail_ok = (
                t_clk is not None
                and m_clk is not None
                and srv is not None
                and srv[0] > max(t_clk, m_clk)
                and srv[1] >= 1
            )
            fields = {
                "sink": s,
                "words": st.acks,
                "ops": res.get("ops", 0),
                "count": plan.counts[s],
                "done": int(done),
                "tail_done": int(bool(tail.get("done"))),
                "barrier_clk": t_clk if t_clk is not None else "none",
                "tail_mark_clk": m_clk if m_clk is not None else "none",
                "tail_req_clk": srv[0] if srv is not None else "none",
                "tail_words": srv[1] if srv is not None else 0,
                "orphan_acks": st.orphan_acks,
            }
            if unit in ("aes", "kmac"):
                fields["result==golden"] = res.get("result==golden", "na")
            if unit == "aes":
                fields["tail_result==golden"] = tail.get("result==golden", "na")
            if unit in errors:
                fields["reason"] = errors[unit]
            self.chk.ok("MIX-SINK", done and tail_ok and golden_ok and st.acks >= need, **fields)
        await self._end_run()

    # --- external Key Manager run --------------------------------------------------------
    async def _external_run(self) -> None:
        plan = self.plan
        dut = cocotb.top
        # Second run of the same firmware: every crypto sink engine held; the KM and
        # ABR (which the KM boot writes) released.
        self._jtag_sw_rst_hold(PARKABLE, True)
        await self.pulse_rst_ni()
        self.swrst.value = SW_RESET_N_RESET_DEFAULT
        await self.swrst.park(*PARKABLE)
        await ClockCycles(dut.clk_i, 2)
        self._jtag_sw_rst_hold(PARKABLE, False)
        await self._boot()
        self.ext = SepExtTrngStream(dut, logger=self.logger).start(streams=(0,))
        self._wi = 0
        self._gi = 0
        # Step 8: control with bit 0 clear; the beats are discarded.
        self.acc.reset(ext=True)
        ctrl = await self._km_with_beats(pattern="random")
        a_ctrl = self.acc
        c_beats = len(a_ctrl.ext_beats)
        c_not_ready = a_ctrl.ext_not_ready
        c_km_neq = a_ctrl.km_ep_neq
        c_valid = list(a_ctrl.axis_valid)
        # Step 9: bit 0 set, bits 1 and 2 clear, written under a bridge stream.
        bridge = await self._select_external()
        sel = await self.reg._rd(SEL_ADDR)
        self.acc.reset(ext=True)
        open_graded_window(TEST, self.logger)
        run = await self._km_with_beats(pattern=plan.gap_pattern, drop_held=False)
        close_graded_window(self.logger)
        a = self.acc
        order_ok = None not in a.ext_beats and None not in a.km_beats and a.ext_beats == a.km_beats
        ctrl_ok = c_beats >= 1 and c_not_ready == 0 and c_km_neq == 0 and c_valid[0] > 0
        self.chk.ctrl(
            "MIX-EXT-KM",
            ctrl_ok and ctrl["done"],
            ctrl_internal_discard=c_beats,
            ctrl_not_ready=c_not_ready,
            ctrl_km_eq=int(c_km_neq == 0),
            ctrl_km_valid_clk=c_valid[0],
        )
        self.chk.ctrl(
            "MIX-EXT-KM",
            bridge["held_at_select"] == 1 and bridge["min_pending"] >= 1,
            bridge_beats=bridge["offered"],
            bridge_min_pending=bridge["min_pending"],
            bridge_held_at_select=bridge["held_at_select"],
        )
        self.chk.ctrl(
            "MIX-EXT-KM",
            a.axis_valid[1] > 0 and a.axis_valid[2] > 0,
            ctrl_axis1_valid_clk=a.axis_valid[1],
            ctrl_axis2_valid_clk=a.axis_valid[2],
        )
        # The tready equality can catch an external tready tied high only on a
        # clock where the Key Manager tready is 0, so the window must hold one.
        self.chk.ctrl(
            "MIX-EXT-KM",
            a.km_tready_low > 0,
            ctrl_km_tready_low_clk=a.km_tready_low,
        )
        fields = {
            "beats": run["offered"],
            "xfers": len(a.ext_beats),
            "km_xfers": len(a.km_beats),
            "order_ok": int(order_ok),
            "data_ok": int(order_ok),
            "tready_eq": int(a.tready_neq == 0),
            "km_tready_low_clk": a.km_tready_low,
            "axis1_eq": int(a.axis_neq[1] == 0),
            "axis2_eq": int(a.axis_neq[2] == 0),
            "ctrl_internal_discard": c_beats,
            "ctrl_km_eq": int(c_km_neq == 0),
            "ctrl_axis1_valid_clk": a.axis_valid[1],
            "ctrl_axis2_valid_clk": a.axis_valid[2],
            "sel": f"0x{sel & SEP_CPU_CTRL.field_mask('EXT_TRNG_SRC_SEL', 'sel'):x}",
            "xz": a.xz,
        }
        if not run["done"]:
            fields["reason"] = run["reason"]
        self.chk.ok(
            "MIX-EXT-KM",
            run["done"] and len(a.ext_beats) >= 1 and order_ok and a.tready_neq == 0
            and a.axis_neq[1] == 0 and a.axis_neq[2] == 0 and a.xz == 0,
            **fields,
        )  # fmt: skip
        await self._select_internal()
        await self.ext.stop()
        await self._end_run()

    async def _select_internal(self) -> None:
        """Write ``EXT_TRNG_SRC_SEL`` = 0x0 while the internal endpoint of stream 0 holds
        tvalid 1, so that no beat that the sampler sees is withdrawn before handshake.

        The source of a stalled beat holds it (``hw/sys/sep/doc/trng.adoc``, random-data
        stream contract), and the Key Manager sampler flags a drop of ``TVALID`` while
        ``TREADY`` is low as a withdrawal (``hw/ip/key_manager/doc/architecture.adoc``,
        DRBG Sampler). An unselected internal endpoint is backpressured and retains its
        queued word, and an unselected external input receives ready high (``trng.adoc``,
        Source Selection). After this write the held external beat transfers and is
        discarded, and the sampler sees the held internal word, so ``tvalid`` at the
        sampler stays 1 across the switch. The external run is graded before this step.
        """
        dut = cocotb.top
        self.acc.ext = False

        def int_valid() -> bool:
            return _bit(_known(dut.drbg_int_tvalid_o), 0) == 1

        if await self._until(int_valid, SETTLE_CAP) is None:
            raise AssertionError(
                f"internal endpoint 0 shows no tvalid within {SETTLE_CAP} clocks; "
                "the select cannot return to it without a withdrawal"
            )
        await self.reg._wr(SEL_ADDR, 0x0)
        sel = await self.reg._rd(SEL_ADDR) & SEP_CPU_CTRL.field_mask("EXT_TRNG_SRC_SEL", "sel")
        if sel & 0x1:
            raise AssertionError(f"EXT_TRNG_SRC_SEL reads 0x{sel:x} after a write of 0x0")
        left = await self._until(lambda: self.ext.pending(0) == 0, BRIDGE_DEPTH * 4)
        if left is None:
            raise AssertionError("external port 0 keeps a beat with bit 0 clear")
        self.logger.info("EXT-RELEASE sel=0x%x held_beat_clk=%d", sel, left)

    async def _select_external(self) -> dict:
        """Write ``EXT_TRNG_SRC_SEL`` = 0x1 while external port 0 holds tvalid 1 on every clock.

        The selection is combinational with no switch handshake (``hw/sys/sep/doc/trng.adoc``,
        Source Selection). The idle Key Manager sampler holds tready 0 while the internal
        endpoint holds a queued word, so a switch to an external port with tvalid 0 is a
        withdrawal before handshake: the sampler flags a stream error and pulses the DRBG
        error source (``hw/ip/key_manager/doc/architecture.adoc``, DRBG Sampler, Errors and
        reset), and the firmware answers the next command with ``RESP_UNRECOVERABLE_FAULT``
        and fault code -8 (``drbg_err``, ``hw/ip/key_manager/doc/firmware.adoc``). The
        bridge keeps at least one unique beat queued behind the held beat from before the
        write to its response: while bit 0 is clear each beat transfers in its clock and is
        discarded (tready 1), and after the write lands the held beat stays on the port
        until the sampler takes it. The beats still queued after the write go to the
        sampler in order and are graded like every other beat.
        """
        dut = cocotb.top
        state = {"run": True, "offered": 0, "min_pending": BRIDGE_DEPTH}

        async def feed() -> None:
            while state["run"]:
                pend = self.ext.pending(0)
                state["min_pending"] = min(state["min_pending"], pend)
                if pend < BRIDGE_DEPTH:
                    n = BRIDGE_DEPTH - pend
                    self.ext.send(0, [self._next_word() for _ in range(n)])
                    state["offered"] += n
                await RisingEdge(dut.clk_i)

        self.ext.send(0, [self._next_word() for _ in range(BRIDGE_DEPTH)])
        state["offered"] = BRIDGE_DEPTH
        # The driver loads the first beat on the next rising edge; the feed starts after it.
        await ClockCycles(dut.clk_i, 2)
        task = cocotb.start_soon(feed())
        await self.reg._wr(SEL_ADDR, 0x1)
        state["run"] = False
        await task
        held = int(self.ext.pending(0) >= 1)
        self.logger.info(
            "EXT-SELECT bridge_beats=%d min_pending=%d left=%d",
            state["offered"],
            state["min_pending"],
            self.ext.pending(0),
        )
        return {
            "offered": state["offered"],
            "min_pending": state["min_pending"],
            "held_at_select": held,
        }

    def _next_word(self) -> int:
        if self._wi >= len(self.plan.ext_words):
            raise AssertionError(f"plan word pool of {EXT_WORDS} words exhausted")
        w = self.plan.ext_words[self._wi]
        self._wi += 1
        return w

    def _next_gap(self) -> int:
        g = self.plan.gaps[self._gi % GAP_TABLE]
        self._gi += 1
        return g

    async def _km_with_beats(self, *, pattern: str, drop_held: bool = True) -> dict:
        """One Key Manager generate while the driver offers unique beats on stream 0,
        one at a time, holding each until tready, until the operation ends.

        With ``drop_held`` a beat still held at the end is dropped by a source reset;
        use it only while bit 0 is clear (the port is unselected, ready high). With
        bit 0 set the held beat stays on the port for ``_select_internal``."""
        dut = cocotb.top

        async def op() -> str:
            # A firmware error answer ends the operation with a reason; it must not end
            # the leaf before the check line.
            try:
                await self.km.key_generate(
                    dest=KM_DEST_AES, req_size=KM_KEY_WORDS - 1, timeout=KM_OP_TIMEOUT
                )
            except AssertionError as exc:
                return f"km_op_error:{exc}"
            return ""

        task = cocotb.start_soon(op())
        offered = 0
        exhausted = False
        while not task.done():
            if self.ext.pending(0) == 0:
                if self._wi >= len(self.plan.ext_words):
                    exhausted = True
                else:
                    offered += 1
                    self.ext.send(0, [self._next_word()])
                    if pattern == "long":
                        gap = LONG_GAP if offered == self.plan.long_at else 0
                    else:
                        gap = self._next_gap()
                    while self.ext.pending(0) and not task.done():
                        await RisingEdge(dut.clk_i)
                    for _ in range(gap):
                        if task.done():
                            break
                        await RisingEdge(dut.clk_i)
                    continue
            await RisingEdge(dut.clk_i)
        await ClockCycles(dut.clk_i, 4)
        if drop_held and self.ext.pending(0):
            await self.ext.source_reset(0)
        reason = task.result()
        if exhausted:
            self.chk.obs("MIX-EXT-WORDS", exhausted=1, offered=offered)
        return {"done": not reason, "reason": reason, "offered": offered}
