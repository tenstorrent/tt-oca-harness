# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""HMAC byte-order swaps, context save and restore, the sha_en clear and the done line.

RAND-REP, no_cpu (``lsu_stub_all_live``, ``+skip_fuse_sense``). The leaf drives the
HMAC engine over the CPU-LSU master. Every ``CFG`` write sets ``hmac_en`` = 0 and
``sha_en`` = 1, except the ``sha_en`` clear.

Contracts (spec text, not RTL):

* ``CFG.endian_swap`` = 1 adds each multi-byte value written to ``MSG_FIFO`` in
  big-endian byte order; a one-byte write is not affected
  (vendor/lowRISC/opentitan/overlay/regs/hmac/regs/gen/adoc/hmac.adoc:120-123).
* ``CFG.digest_swap`` = 1 puts each DIGEST register value in big-endian byte order
  and does not change the register order; DIGEST_0 holds the first 4 bytes of the
  digest (hmac.adoc:116-117).
* ``CMD.hash_stop`` sets ``hmac_done`` after the current block (hmac.adoc:142).
  DIGEST_0 to DIGEST_15 and ``MSG_LENGTH_LOWER``/``MSG_LENGTH_UPPER`` are the context
  to save, and software writes them while the engine is idle; ``CMD.hash_continue``
  hashes on from them (hmac.adoc:141, :161;
  vendor/lowRISC/opentitan/upstream/hw/ip/hmac/data/hmac.hjson:365-366, :372, :386).
* ``sha_en`` = 0 clears the digest (hmac.adoc:128).
* A completed hash sets ``INTR_STATE.hmac_done`` (hmac.adoc:51); with
  ``INTR_ENABLE.hmac_done`` set (hmac.adoc:63) vector bit 17 rises, because bit i of
  the vector is PIC source i + 1 and source 18 is HMAC done
  (hw/sys/sep/doc/interrupts.adoc:23, :117-119).

The golden is the software SHA-2 model (env/sep_hmac_golden.py ``sha2_bytes``). The
message bytes of a swap cell are the AXI write lanes in write order; a multi-byte
write adds its lanes in order at ``endian_swap`` = 0 and in reverse order at 1.
DIGEST word n is the big-endian read of digest bytes 4n..4n+3 at ``digest_swap`` = 0
and its 32-bit byte swap at 1.

Checkers:
  CHK-HMAC-SWAP       per (endian_swap, digest_swap, digest size) cell: DIGEST == golden
  CHK-HMAC-DSWAP-REL  word n at digest_swap 1 == bswap32(word n at digest_swap 0)
  CHK-HMAC-CTX        split, stop, save, restore, continue == single pass == golden
  CHK-HMAC-STOP       after hash_stop: hmac_done reads 1 and STATUS.hmac_idle reads 1
  CHK-HMAC-SHAOFF     sha_en 1 -> 0 after a finished hash: every DIGEST word reads 0
  CHK-HMAC-DONE-LINE  at a graded completion with the enable set: state 1, bit 17 rises
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_axi_agent import SepAxiOp
from env.sep_bit_watch import BitWatchTimeout, SepBitWatch
from env.sep_chk_log import SepChkLog
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_hmac_golden import sha2_bytes
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import HMAC, sym
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_hmac_seq import (
    HMAC_CFG,
    HMAC_CMD,
    HMAC_CMD_HASH_PROCESS,
    HMAC_CMD_HASH_START,
    HMAC_DIGEST_0,
    HMAC_DIGEST_WORDS,
    HMAC_INTR_DONE,
    HMAC_INTR_STATE,
    HMAC_MSG_FIFO,
    HMAC_STATUS,
    HMAC_STATUS_IDLE,
    SepHmac,
    build_cfg,
)
from seq_lib.sep_sw_reset_seq import SepSwReset

TEST = "sep_hmac_swap_context_rand_test"

HMAC_CMD_HASH_STOP = HMAC.field_mask("CMD", "hash_stop")
HMAC_CMD_HASH_CONTINUE = HMAC.field_mask("CMD", "hash_continue")
HMAC_CFG_SHA_EN = HMAC.field_mask("CFG", "sha_en")
HMAC_INTR_ENABLE = HMAC.addr("INTR_ENABLE")
HMAC_INTR_ENABLE_DONE = HMAC.field_mask("INTR_ENABLE", "hmac_done")
HMAC_MSG_LENGTH_LOWER = HMAC.addr("MSG_LENGTH_LOWER")
HMAC_MSG_LENGTH_UPPER = HMAC.addr("MSG_LENGTH_UPPER")
HMAC_DIGEST_15 = sym("HMAC_DIGEST_15__REG_ADDR")
# hmac.hjson:365-366 names DIGEST_0 to DIGEST_15 as the saved hash for every digest size.
CTX_DIGEST_WORDS = 16
assert HMAC_DIGEST_15 == HMAC_DIGEST_0 + 4 * (CTX_DIGEST_WORDS - 1), "DIGEST_0..15 not contiguous"

# SW_RESET_N baseline: every crypto engine and the TRNG released, Key Manager held
# (hw/sys/sep/regs/gen/adoc/blocks/sep_reset_ctrl.adoc).
SW_RESET_N_BASELINE = 0x7E
# Vector bit 17 carries PIC source 18, HMAC done (hw/sys/sep/doc/interrupts.adoc:23, :117-119).
VEC_HMAC_DONE_BIT = 17

SHA_SIZES = (256, 384, 512)
# SHA-2 block size in bytes (FIPS 180-4): 64 for SHA-256, 128 for SHA-384 and SHA-512.
BLOCK_BYTES = {256: 64, 384: 128, 512: 128}
WIDTH_BITS = {4: 32, 2: 16, 1: 8}
AXI_SIZE = {4: 2, 2: 1, 1: 0}

# Outer limits of clean-time measurements (logged as bound=), never a contract.
OUTER_POLL_CLK = 100_000
RESET_WAIT_CLK = 2_000
POLL_GAP_CLK = 4
# Bound multipliers on clean times measured in the same seed.
STOP_BOUND_X = 3  # hash_stop done / idle wait: 3 x t_single of the trip
LINE_BOUND_X = 4  # vector rise: 4 x the clocks from the ending command to the done read
SHAOFF_BOUND_X = 4  # digest clear: 4 x the clean hash time of the cell before it


def _bswap32(w: int) -> int:
    return int.from_bytes((w & 0xFFFF_FFFF).to_bytes(4, "little"), "big")


def _digest_words(digest: bytes, sha: int, dswap: int) -> list[int]:
    words = [
        int.from_bytes(digest[4 * i : 4 * i + 4], "big") for i in range(HMAC_DIGEST_WORDS[sha])
    ]
    return [_bswap32(w) for w in words] if dswap else words


def _msg_bytes(writes: list[tuple[int, int]], endian: int) -> bytes:
    """The message the engine hashes for ``writes`` of (value, nbytes) under ``endian_swap``."""
    out = bytearray()
    for value, n in writes:
        out += value.to_bytes(n, "big" if (endian and n > 1) else "little")
    return bytes(out)


def _writes_of(data: bytes, widths: list[int]) -> list[tuple[int, int]]:
    """Split ``data`` into writes; the value of a write carries its bytes on lanes 0..n-1."""
    out, pos = [], 0
    for n in widths:
        out.append((int.from_bytes(data[pos : pos + n], "little"), n))
        pos += n
    assert pos == len(data), "write plan does not cover the message"
    return out


def _word_writes(data: bytes) -> list[tuple[int, int]]:
    """32-bit writes, then single-byte writes for a tail of fewer than 4 bytes."""
    widths = [4] * (len(data) // 4) + [1] * (len(data) % 4)
    return _writes_of(data, widths)


def _distinct_bytes(rng: SepSeededRng, n: int) -> bytes:
    """``n`` bytes from a drawn permutation of 0..255, cycled from a drawn offset."""
    perm = rng.sample(range(256), 256)
    off = rng.randrange(256)
    return bytes(perm[(off + i) % 256] for i in range(n))


@dataclass
class SwapPlan:
    sha: int
    data: bytes
    widths: list[int]
    dswap_order: dict[int, list[int]]  # endian -> order of the two digest_swap values

    def writes(self) -> list[tuple[int, int]]:
        return _writes_of(self.data, self.widths)

    def counts(self) -> dict[int, int]:
        return {b: self.widths.count(n) for n, b in WIDTH_BITS.items()}


@dataclass
class TripPlan:
    sha: int
    kind: str  # parts, split_last, first_one_block
    parts: list[bytes]
    interleave: int
    unrelated: bytes

    @property
    def message(self) -> bytes:
        return b"".join(self.parts)


@dataclass
class Plan:
    seed: int
    sha_order: list[int]
    swaps: dict[int, SwapPlan]
    trips: list[TripPlan]
    graded_events: list[int] = field(default_factory=list)


def _draw_widths(rng: SepSeededRng, length: int) -> list[int]:
    while True:
        widths, left = [], length
        while left:
            n = rng.choice([w for w in (4, 2, 1) if w <= left])
            widths.append(n)
            left -= n
        if any(n > 1 for n in widths):
            return widths


def _swap_ok(sp: SwapPlan) -> bool:
    """Filter on the golden: each endian message has a digest word that differs from its swap."""
    for endian in (0, 1):
        words = _digest_words(sha2_bytes(_msg_bytes(sp.writes(), endian), sp.sha), sp.sha, 0)
        if not any(w != _bswap32(w) for w in words) or not any(words):
            return False
    return True


def draw_plan(seed: int) -> Plan:
    """The whole plan of the seed, drawn in a fixed order with no simulator access."""
    rng = SepSeededRng(seed)
    sha_order = list(SHA_SIZES)
    rng.shuffle(sha_order)

    while True:
        swaps: dict[int, SwapPlan] = {}
        for sha in sha_order:
            while True:
                length = rng.randrange(4, 201)
                data = _distinct_bytes(rng, length)
                widths = _draw_widths(rng, length)
                order = {}
                for endian in (0, 1):
                    pair = [0, 1]
                    rng.shuffle(pair)
                    order[endian] = pair
                sp = SwapPlan(sha, data, widths, order)
                if _swap_ok(sp):
                    break
            swaps[sha] = sp
        # Every write width appears with each endian_swap value across the cells of the seed.
        if set().union(*(set(sp.widths) for sp in swaps.values())) == {4, 2, 1}:
            break

    trips: list[TripPlan] = []
    for sha in sha_order:
        blk = BLOCK_BYTES[sha]
        shapes: list[tuple[str, int]] = [("parts", k) for k in (2, 3, 4)]
        shapes.append(("split_last", rng.randrange(2, 5)))
        shapes.append(("first_one_block", 2))
        for kind, nparts in shapes:
            sizes = []
            for i in range(nparts - 1):
                sizes.append(
                    blk if kind == "first_one_block" and i == 0 else blk * rng.randrange(1, 4)
                )
            sizes.append(0 if kind == "split_last" else rng.randrange(1, blk + 1))
            data = _distinct_bytes(rng, sum(sizes))
            parts, pos = [], 0
            for s in sizes:
                parts.append(data[pos : pos + s])
                pos += s
            interleave = rng.choice([0, 1])
            unrelated = _distinct_bytes(rng, rng.randrange(1, 129))
            trips.append(TripPlan(sha, kind, parts, interleave, unrelated))

    # Completion events in run order: one per swap cell, and per trip the single pass,
    # one stop per part before the last, one unrelated hash per stop when the trip
    # interleaves, and the final process.
    n_events = 4 * len(SHA_SIZES)
    for t in trips:
        stops = len(t.parts) - 1
        n_events += 1 + stops + stops * t.interleave + 1
    graded = [1] + [rng.choice([0, 1]) for _ in range(n_events - 1)]
    return Plan(seed, sha_order, swaps, trips, graded)


class _TrialAbort(Exception):
    """A bounded wait inside a trial timed out; the owner check already logged FAIL."""


@pyuvm.test()
class sep_hmac_swap_context_rand_test(sep_base_test):
    """HMAC swap cells, context round trips, the sha_en clear and the done line."""

    required_evidence = (
        "CHK-HMAC-SWAP",
        "CHK-HMAC-DSWAP-REL",
        "CHK-HMAC-CTX",
        "CHK-HMAC-STOP",
        "CHK-HMAC-SHAOFF",
        "CHK-HMAC-DONE-LINE",
    )

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        self.dut = cocotb.top
        seed = self.random_seed()
        self.seed = seed
        self.chk = SepChkLog(self, TEST, seed)
        self.hmac = SepHmac(self)
        self.swrst = SepSwReset(self)
        self.plan = draw_plan(seed)
        self._event = 0
        self._win = False
        self._log_plan()

        # One watcher of vector bit 17 for the whole run; its clock count is the time base.
        self.vec = SepBitWatch(
            self.dut.sep_internal_interrupts_probe_o, {"hmac_done": VEC_HMAC_DONE_BIT}
        ).start()
        await ClockCycles(self.dut.clk_i, 2)

        self.swrst.value = SW_RESET_N_BASELINE
        await self.swrst.release("hmac")
        self.logger.info("SW_RESET_N baseline=0x%02x", SW_RESET_N_BASELINE)
        await self._reset_hmac()

        for sha in self.plan.sha_order:
            await self._swap_cells(self.plan.swaps[sha])
        for trip in self.plan.trips:
            try:
                await self._trip(trip)
            except _TrialAbort:
                await self._reset_hmac()

        self._window(False)
        await self.vec.stop()
        self.chk.finish()

    # ---------------------------------------------------------------- plumbing

    def _log_plan(self) -> None:
        p = self.plan
        swaps = " ".join(
            f"sha{s}:len={len(p.swaps[s].data)},"
            + ",".join(f"w{b}={c}" for b, c in p.swaps[s].counts().items())
            + f",dswap_e0={p.swaps[s].dswap_order[0]},dswap_e1={p.swaps[s].dswap_order[1]}"
            for s in p.sha_order
        )
        trips = " ".join(
            f"sha{t.sha}/{t.kind}/parts={'+'.join(str(len(x)) for x in t.parts)}"
            f"/il={t.interleave}/unrel={len(t.unrelated)}"
            for t in p.trips
        )
        self.logger.info(
            "PLAN seed=%d sha_order=%s swap=[%s] trips=[%s] events=%d graded_events=%d",
            p.seed,
            p.sha_order,
            swaps,
            trips,
            len(p.graded_events),
            sum(p.graded_events),
        )

    def _window(self, on: bool) -> None:
        if on and not self._win:
            open_graded_window(TEST, self.logger)
        elif not on and self._win:
            close_graded_window(self.logger)
        self._win = on

    async def _wr(self, addr: int, data: int) -> None:
        await self.hmac._wr(addr, data)

    async def _rd(self, addr: int) -> int:
        return await self.hmac._rd(addr)

    async def _write_fifo(self, writes: list[tuple[int, int]]) -> None:
        for value, n in writes:
            seq = SepAxiAccessSeq(
                "hmac_msg_wr",
                op=SepAxiOp.WRITE,
                addr=HMAC_MSG_FIFO,
                wdata=value,
                length=n,
                size=AXI_SIZE[n],
            )
            await self.start_seq(seq)
            if not seq.resp_ok:
                raise AssertionError(f"HMAC MSG_FIFO {8 * n}-bit write not OKAY (0x{value:x})")

    async def _read_digest(self, n: int) -> list[int]:
        return [await self._rd(HMAC_DIGEST_0 + 4 * i) for i in range(n)]

    async def _poll(self, addr: int, mask: int, want: int, bound: int) -> int | None:
        """Read ``addr`` until the masked bits equal ``want``; return the clock, None on timeout."""
        start = self.vec.clk
        while True:
            if (await self._rd(addr)) & mask == want:
                return self.vec.clk
            if self.vec.clk - start > bound:
                return None
            await ClockCycles(self.dut.clk_i, POLL_GAP_CLK)

    async def _reset_hmac(self) -> None:
        """Clear SW_RESET_N bit 3, wait for the gated reset, restore, wait for an OKAY STATUS read."""
        self._window(False)
        probe = self.dut.hmac_gated_rst_n_probe_o
        await self.swrst.park("hmac")
        for _ in range(RESET_WAIT_CLK):
            if self.rd(probe) == 0:
                break
            await ClockCycles(self.dut.clk_i, 1)
        else:
            raise AssertionError(f"HMAC gated reset did not assert within {RESET_WAIT_CLK} clocks")
        await self.swrst.release("hmac")
        for _ in range(RESET_WAIT_CLK):
            if self.rd(probe) == 1:
                break
            await ClockCycles(self.dut.clk_i, 1)
        else:
            raise AssertionError(f"HMAC gated reset did not release within {RESET_WAIT_CLK} clocks")
        start = self.vec.clk
        while True:
            seq = SepAxiAccessSeq(
                "hmac_status_rd",
                op=SepAxiOp.READ,
                addr=HMAC_STATUS,
                size=2,
                allow_ungraded_read_resp=True,
            )
            await self.start_seq(seq)
            if seq.resp_ok:
                return
            if self.vec.clk - start > RESET_WAIT_CLK:
                raise AssertionError(
                    f"HMAC STATUS gave no OKAY read within {RESET_WAIT_CLK} clocks after reset"
                )
            await ClockCycles(self.dut.clk_i, POLL_GAP_CLK)

    async def _end_hash(self, end_action, *, owner: str, bound: int, tag: str) -> int:
        """Run the command that ends a hash, wait for hmac_done and clear it.

        Returns the clock of the read that shows hmac_done. A graded completion event also grades the vector line. A timeout
        logs ``owner`` FAIL and aborts the trial.
        """
        idx = self._event
        self._event += 1
        graded = idx < len(self.plan.graded_events) and self.plan.graded_events[idx]
        before = None
        if graded:
            await self._wr(HMAC_INTR_ENABLE, HMAC_INTR_ENABLE_DONE)
            await ClockCycles(self.dut.clk_i, 2)
            before = self.vec.level("hmac_done")
        mark = self.vec.mark()
        await end_action()
        t_end = self.vec.clk
        t_done = await self._poll(HMAC_INTR_STATE, HMAC_INTR_DONE, HMAC_INTR_DONE, bound)
        if t_done is None:
            self.chk.ok(owner, False, tag=tag, reason="timeout", bound=bound)
            if graded:
                await self._wr(HMAC_INTR_ENABLE, 0)
            raise _TrialAbort
        dt = max(t_done - t_end, 1)
        if graded:
            state = (await self._rd(HMAC_INTR_STATE)) & HMAC_INTR_DONE
            line_bound = LINE_BOUND_X * dt
            try:
                await self.vec.wait_rise(mark, line_bound, "hmac_done")
                vec17 = 1
            except BitWatchTimeout:
                vec17 = 0
            self.chk.ok(
                "HMAC-DONE-LINE",
                before == 0 and state != 0 and vec17 == 1,
                event=idx,
                tag=tag,
                enable=1,
                state=int(state != 0),
                vec17_before=before,
                vec17=vec17,
                bound=line_bound,
                t_done=dt,
            )
        await self._wr(HMAC_INTR_STATE, HMAC_INTR_DONE)
        if graded:
            post = (await self._rd(HMAC_INTR_STATE)) & HMAC_INTR_DONE
            await ClockCycles(self.dut.clk_i, 2)
            self.chk.obs(
                "HMAC-DONE-FALL",
                event=idx,
                state_after_w1c=int(post != 0),
                vec17_after_w1c=self.vec.level("hmac_done"),
            )
            await self._wr(HMAC_INTR_ENABLE, 0)
        return t_done

    async def _hash_once(self, cfg: int, writes, *, owner: str, bound: int, tag: str) -> int:
        """CFG, hash_start, message, hash_process, done. Returns clocks from the start response."""
        await self._wr(HMAC_CFG, cfg)
        await self._wr(HMAC_CMD, HMAC_CMD_HASH_START)
        t0 = self.vec.clk
        await self._write_fifo(writes)

        async def _process() -> None:
            await self._wr(HMAC_CMD, HMAC_CMD_HASH_PROCESS)

        t_done = await self._end_hash(_process, owner=owner, bound=bound, tag=tag)
        return t_done - t0

    # ------------------------------------------------------------- swap cells

    async def _swap_cells(self, sp: SwapPlan) -> None:
        sha, n = sp.sha, HMAC_DIGEST_WORDS[sp.sha]
        writes = sp.writes()
        counts = sp.counts()
        regs: dict[tuple[int, int], list[int]] = {}
        last: tuple[int, list[int], int, int] | None = None
        for endian in (0, 1):
            golden0 = _digest_words(sha2_bytes(_msg_bytes(writes, endian), sha), sha, 0)
            for dswap in sp.dswap_order[endian]:
                await self._reset_hmac()
                self._window(True)
                cfg = build_cfg(hmac_en=False, sha_bits=sha, endian_swap=endian, digest_swap=dswap)
                tag = f"swap-sha{sha}-e{endian}-d{dswap}"
                try:
                    t_cell = await self._hash_once(
                        cfg, writes, owner="HMAC-SWAP", bound=OUTER_POLL_CLK, tag=tag
                    )
                except _TrialAbort:
                    last = None
                    continue
                got = await self._read_digest(n)
                exp = [_bswap32(w) for w in golden0] if dswap else golden0
                bad = [i for i in range(n) if got[i] != exp[i]]
                self.chk.ok(
                    "HMAC-SWAP",
                    not bad,
                    endian=endian,
                    dswap=dswap,
                    sha=sha,
                    len=len(sp.data),
                    w32=counts[32],
                    w16=counts[16],
                    w8=counts[8],
                    digest_eq_golden=int(not bad),
                    first_bad=bad[0] if bad else "-",
                    got0=f"0x{got[0]:08x}",
                    exp0=f"0x{exp[0]:08x}",
                    bound=OUTER_POLL_CLK,
                )
                regs[(endian, dswap)] = got
                last = (cfg, exp, t_cell, dswap)
            if (endian, 0) in regs and (endian, 1) in regs:
                w0, w1 = regs[(endian, 0)], regs[(endian, 1)]
                self.chk.ctrl(
                    "HMAC-DSWAP-VISIBLE",
                    any(w != _bswap32(w) for w in golden0),
                    sha=sha,
                    endian=endian,
                )
                mism = [i for i in range(n) if w1[i] != _bswap32(w0[i])]
                self.chk.ok(
                    "HMAC-DSWAP-REL",
                    not mism,
                    sha=sha,
                    endian=endian,
                    words=n,
                    rel="bswap32",
                    mismatches=len(mism),
                    first_bad=mism[0] if mism else "-",
                )
        sets = {tuple(v) for v in regs.values()}
        self.chk.ctrl(
            "HMAC-SWAP-SETS", len(regs) == 4 and len(sets) == 4, sha=sha, distinct=len(sets)
        )
        if last is not None:
            await self._sha_off(sha, *last)

    async def _sha_off(self, sha: int, cfg: int, exp: list[int], t_cell: int, dswap: int) -> None:
        """sha_en 1 -> 0 after the finished hash of the last swap cell clears every DIGEST word."""
        n = HMAC_DIGEST_WORDS[sha]
        before = await self._read_digest(n)
        self.chk.ctrl(
            "HMAC-SHAOFF-BEFORE",
            before == exp and any(before),
            sha=sha,
            dswap=dswap,
            nonzero=int(any(before)),
        )
        await self._wr(HMAC_CFG, cfg & ~HMAC_CFG_SHA_EN)
        bound = SHAOFF_BOUND_X * max(t_cell, 1)
        start = self.vec.clk
        after = await self._read_digest(n)
        while any(after) and self.vec.clk - start <= bound:
            await ClockCycles(self.dut.clk_i, POLL_GAP_CLK)
            after = await self._read_digest(n)
        self.chk.ok(
            "HMAC-SHAOFF",
            not any(after),
            sha=sha,
            nonzero_before=int(any(before)),
            digest_after=0 if not any(after) else f"0x{next(w for w in after if w):08x}",
            bound=bound,
            t_cell=t_cell,
        )
        await self._wr(HMAC_CFG, cfg)

    # ---------------------------------------------------------- context trips

    async def _trip(self, trip: TripPlan) -> None:
        sha, n = trip.sha, HMAC_DIGEST_WORDS[trip.sha]
        cfg = build_cfg(hmac_en=False, sha_bits=sha)
        golden = _digest_words(sha2_bytes(trip.message, sha), sha, 0)
        tag = f"ctx-sha{sha}-{trip.kind}-p{len(trip.parts)}"
        split = ",".join(str(len(p)) for p in trip.parts)

        # Single pass: the control of the trip, window closed.
        await self._reset_hmac()
        t_single = await self._hash_once(
            cfg,
            _word_writes(trip.message),
            owner="HMAC-CTX",
            bound=OUTER_POLL_CLK,
            tag=tag + "-single",
        )
        single = await self._read_digest(n)
        self.chk.ctrl("HMAC-CTX-SINGLE", single == golden, tag=tag, t_single=t_single)
        bound = STOP_BOUND_X * max(t_single, 1)

        # Split run: stop, save, restore, continue, window open.
        self._window(True)
        await self._wr(HMAC_CFG, cfg)
        await self._wr(HMAC_CMD, HMAC_CMD_HASH_START)
        last_idx = len(trip.parts) - 1
        for i, part in enumerate(trip.parts):
            writes = _word_writes(part)
            if i > 0:
                await self._wr(HMAC_CMD, HMAC_CMD_HASH_CONTINUE)
            if i == last_idx:
                await self._write_fifo(writes)

                async def _process() -> None:
                    await self._wr(HMAC_CMD, HMAC_CMD_HASH_PROCESS)

                await self._end_hash(_process, owner="HMAC-CTX", bound=bound, tag=tag)
                break
            await self._write_fifo(writes[:-1])
            done_before = (await self._rd(HMAC_INTR_STATE)) & HMAC_INTR_DONE
            self.chk.ctrl(
                "HMAC-STOP-PRE", done_before == 0, tag=tag, part=i, done_before=done_before
            )
            tail = writes[-1:]

            async def _stop(tail=tail) -> None:
                await self._wr(HMAC_CMD, HMAC_CMD_HASH_STOP)
                await self._write_fifo(tail)

            await self._end_hash(_stop, owner="HMAC-STOP", bound=bound, tag=f"{tag}-part{i}")
            t_idle = await self._poll(HMAC_STATUS, HMAC_STATUS_IDLE, HMAC_STATUS_IDLE, bound)
            if t_idle is None:
                self.chk.ok(
                    "HMAC-STOP", False, tag=tag, part=i, reason="timeout", bound=bound, idle=0
                )
                raise _TrialAbort
            self.chk.ok(
                "HMAC-STOP",
                True,
                tag=tag,
                part=i,
                done_after_stop=1,
                idle=1,
                bound=bound,
                t_single=t_single,
            )
            saved = await self._read_digest(CTX_DIGEST_WORDS)
            len_lo = await self._rd(HMAC_MSG_LENGTH_LOWER)
            len_hi = await self._rd(HMAC_MSG_LENGTH_UPPER)
            if trip.interleave:
                await self._unrelated(trip, cfg, saved, tag, i)
            if await self._poll(HMAC_STATUS, HMAC_STATUS_IDLE, HMAC_STATUS_IDLE, bound) is None:
                self.chk.ok("HMAC-CTX", False, tag=tag, part=i, reason="timeout", bound=bound)
                raise _TrialAbort
            for k, w in enumerate(saved):
                await self._wr(HMAC_DIGEST_0 + 4 * k, w)
            await self._wr(HMAC_MSG_LENGTH_LOWER, len_lo)
            await self._wr(HMAC_MSG_LENGTH_UPPER, len_hi)

        got = await self._read_digest(n)
        bad = [k for k in range(n) if got[k] != single[k] or got[k] != golden[k]]
        self.chk.ok(
            "HMAC-CTX",
            not bad,
            sha=sha,
            kind=trip.kind,
            parts=len(trip.parts),
            split=split,
            interleave=trip.interleave,
            len=len(trip.message),
            digest_eq_single_pass=int(got == single),
            digest_eq_golden=int(got == golden),
            first_bad=bad[0] if bad else "-",
            got0=f"0x{got[0]:08x}",
            exp0=f"0x{golden[0]:08x}",
        )

    async def _unrelated(
        self, trip: TripPlan, cfg: int, saved: list[int], tag: str, part: int
    ) -> None:
        """An unrelated plain hash with the same CFG between two parts, window closed."""
        n = HMAC_DIGEST_WORDS[trip.sha]
        self._window(False)
        await self._wr(HMAC_CMD, HMAC_CMD_HASH_START)
        await self._write_fifo(_word_writes(trip.unrelated))

        async def _process() -> None:
            await self._wr(HMAC_CMD, HMAC_CMD_HASH_PROCESS)

        await self._end_hash(
            _process, owner="HMAC-CTX", bound=OUTER_POLL_CLK, tag=f"{tag}-unrel{part}"
        )
        got = await self._read_digest(n)
        exp = _digest_words(sha2_bytes(trip.unrelated, trip.sha), trip.sha, 0)
        self.chk.ctrl("HMAC-CTX-UNRELATED", got == exp, tag=tag, part=part, len=len(trip.unrelated))
        self.chk.obs("HMAC-CTX-CHANGED", tag=tag, part=part, changed=int(got != saved[:n]))
        self._window(True)
