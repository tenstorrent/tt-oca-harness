# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Token match, mismatch shapes, hold, channel independence, no reset of the token
arrays, and retention of a SEC_DIS match over cold reset.

RAND-REP. no_cpu, real fuse sense, VCS only (the no-reset check reads X on the
unreset token flops). The image is fixed: TEST_DEV, the RMA digests of
``TOKEN_T1`` and ``TOKEN_T2``, ``TRANSIENT_RMA_EN`` at 0 and one filter-legal
disable-vector pair (``env/sep_efuse_plan.py``, ``plan_token_channel``). The seed
draws the order of the walk channels, of the 18 (shape, channel) mismatch cells
and of the independence channels, the decoy subsets, the flip positions, the swap
and byte-swap words, and every token word-write order.

Each channel hashes its eight-word array (index 7 first, no byte swap) on its own
go bit and shows Idle ``0x00``, Match ``0x15`` or Mismatch ``0x2a`` and no other
code. A go clears the held result until the new result; the leaf grades that Idle
observation relative to the hash time it measures in the first read run of the
channel. Word writes alone change no result. The RMA channels compare with their
OTP digest and read Idle until sense completes; the SEC_DIS channel compares with
the bench constant. A digest presented as a token never matches. The token arrays
have no reset, and a retained digest gives its result again after a cold reset
once the comparison prerequisites hold (``hw/sys/sep/doc/token_processing.adoc``,
sections Token Matching Mechanism and Attack Countermeasures, Token Submission;
``hw/sys/sep/doc/security_disable.adoc``, sections Token Activation, Reset
Persistence, Implementation Requirements; ``hw/ip/efuse/regs/gen/adoc/efuse_mmr.adoc``).

No graded step writes two go bits in one ``TOKEN_EOP`` write, and every SEC_DIS go
runs with ``secure_tm_req_i`` at 0. After the last check, one write sets the go bits
of a drawn channel pair; it is logged only (``OBS-TOKEN-MULTI-GO``: per channel the
code after the write and the clocks to the verdict on the comparator rails). Every graded go starts from a held code other than
its expected final code, so a go that has no effect fails. The one exception is
the second go of the go-while-busy leg, which is written to a busy channel.

Go while busy (``token_processing.adoc:107-108``, no submission queue). The leg
runs on every channel, the drawn channel first and then the other two in channel
order. On its channel the leg times a single go: T is the ``clk_i`` cycles from the B
handshake of the go to the comparator rails showing a verdict
(``token_cmp_match_{p,n}_o``, all three pairs opposite and in agreement,
``token_processing.adoc:132-133``). It then writes the right token, goes, and
writes a second go with the words unchanged so that its B handshake lands at a
drawn delay in [T/4 + T/8, 3T/4 - T/8] after the first. The verdict comes at
T after the first go (+/- 4 cycles), is Match, and the rails and every
frontdoor read hold Match to 2T + 8 cycles after the first go. A restart or a
queued second hash moves or repeats the verdict.

HMAC overlap (``token_processing.adoc:44``, each token has a dedicated SHA-256
engine). For one Match go and one Mismatch go on drawn RMA channels, keyed
HMAC-SHA256 starts with a drawn key and two message blocks are pushed, then the
token go runs with ``STATUS.hmac_idle`` 0 before the go and after the verdict
(CTRL-TOKEN-HMAC-BUSY). The rest of the message is pushed, processed, and the
DIGEST words equal HMAC-SHA256 (RFC 2104 over FIPS 180-4) of the key and the
message in the big-endian read of each word (``digest_swap`` = 0;
``env/sep_hmac_golden.py``, ``DSWAP_ORDER``). The same go with HMAC idle gives the same code (CTRL-TOKEN-HMAC-IDLE).

The Match of the right token in the walk is logged (``OBS-TOKEN-DIGEST-LAYOUT``:
no specification states the layout of the digest in the shadow words) and is the
control ``CTRL-TOKEN-DIGEST-LAYOUT`` of the hold, idle-first and later legs, which
need that held Match.

Checkers: CHK-BIND, CHK-TOKEN, CHK-TOKEN-CODES, CHK-TOKEN-HOLD, CHK-TOKEN-INDEP,
CHK-NORESET, CHK-TOKEN-RETAIN, CHK-TOKEN-PRESENSE, CHK-TOKEN-GWB, CHK-TOKEN-HMAC.
A failing hook control logs ``CHK-HOOK FAIL`` and ends the leaf.

FCOV owner window (``env/sep_fcov_gate.py``): open from the no-reset cell to
CHK-TOKEN-CODES, closed by the first FAIL or missing control, and not reopened
after it. The ``cp_go_while_busy`` and ``cp_token_hmac_overlap`` events sample only
when the leaf writes the pass label (``set_tch_overlap_pass``) after CHK-TOKEN-GWB or
CHK-TOKEN-HMAC of that leg passes. Every other sample of the leaf
(``sep_token_channel_cg``, the token-register cells of
``sep_efuse_map_geometry_cg`` and the replay cells of
``sep_sec_dis_robustness_cg``) is held with the tag of its graded step
(``set_ef_hold_tag``) and samples only when the leaf writes that tag to the pass
label (``set_ef_hold_pass``) after every check of the step passed: each walk
channel after CTRL-TOKEN-DIGEST-LAYOUT, its CHK-TOKEN line and CHK-TOKEN-HOLD, each
mismatch cell after its CHK-TOKEN line, the independence gos and the SEC_DIS go with an RMA token after
every CHK-TOKEN-INDEP line, the pre-sense cell after both CHK-TOKEN-PRESENSE lines,
the retention cell after CHK-TOKEN-RETAIN, each HMAC overlap go after
CHK-TOKEN-HMAC and its busy control, each go-while-busy leg after CHK-TOKEN-GWB and
its busy control. The settle gos that bring a channel to its held code and the
reference go of the go-while-busy leg are not graded steps; their events drop.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env.sep_chk_log import SepChkLog
from env.sep_efuse_plan import (
    CH_CHIPLET,
    CH_SEC_DIS,
    CH_SIP,
    CHANNELS,
    CODE_IDLE,
    CODE_MATCH,
    CODE_MISMATCH,
    FOREIGN_TOKEN,
    GO_MASK,
    MATCH_ADDR,
    MATCH_STATUS_MASK,
    RIGHT_TOKEN,
    T_TOKEN_CHANNEL,
    TOKEN_ARRAY_ADDR,
    TOKEN_EOP_ADDR,
    TOKEN_OTHER,
    TOKEN_T1,
    TOKEN_T2,
    TOKEN_ZERO,
    ReadRun,
    expected_digest,
    plan,
    poll_code,
    read_run,
    token_go,
    token_words,
    write_token,
)
from env.sep_efuse_test_lib import (
    SepEfuseFd,
    chk_bind,
    hook_fail,
    rst_pulse,
    sig_bits,
    tap_words,
)
from env.sep_fcov_gate import (
    close_graded_window,
    open_graded_window,
    set_ef_hold_pass,
    set_ef_hold_tag,
    set_tch_overlap_pass,
)
from env.sep_hmac_golden import DSWAP_ORDER, digest_order, hmac_sha2_bytes
from sep_base_test import sep_base_test
from seq_lib.sep_hmac_seq import (
    HMAC_CMD,
    HMAC_CMD_HASH_PROCESS,
    HMAC_CMD_HASH_START,
    HMAC_ERR_CODE,
    HMAC_INTR_DONE,
    HMAC_INTR_STATE,
    HMAC_MSG_FIFO,
    HMAC_STATUS,
    HMAC_STATUS_IDLE,
    SepHmac,
    SepHmacCfg,
)

_NAME = "sep_efuse_token_channel_rand_test"
_RUN_READS = 400
# Window multiples of W_hash reads (test parameters).
_HOLD_MULT = 4
_IND_MULT = 4
_PRE_MULT = 4
_CH_NAME = {CH_SIP: "sip", CH_CHIPLET: "chp", CH_SEC_DIS: "sdis"}
_WORD_TAP = {
    CH_SIP: "token_sip_words_o",
    CH_CHIPLET: "token_chiplet_words_o",
    CH_SEC_DIS: "token_sdis_words_o",
}
_ALLOWED = (CODE_IDLE, CODE_MATCH, CODE_MISMATCH)
# Comparator rail copy k of channel c is bit 3c+k of token_cmp_match_{p,n}_o
# (tb/sep_tb_signal_list.svh, token comparator rails).
_RAIL_IDX = {CH_SIP: 0, CH_CHIPLET: 1, CH_SEC_DIS: 2}
# Go-while-busy leg (test parameters): verdict-time tolerance and Match-hold
# margin in clk_i cycles, the edge margin of the second-go delay as a fraction
# 1/_GWB_EDGE_DIV of T, and the clock bound of every rail wait.
_GWB_TOL = 4
_GWB_SETTLE = 8
_GWB_EDGE_DIV = 8
_GWB_BOUND = 20_000
# HMAC overlap leg (test parameters): message blocks pushed before the token go
# and the drawn range of extra blocks and of the trailing words. A SHA-256
# block is 16 words (FIPS 180-4).
_HOV_BLOCK_WORDS = 16
_HOV_HEAD_BLOCKS = 2
_HOV_TAIL_BLOCKS = (0, 2)
_HOV_TAIL_WORDS = (1, 16)
_HOV_KEY_WORDS = 8
_HOV_SETTLE_CLKS = 2
_PASS_HOLD = 2  # clocks a step tag stays on the pass label
_MATCH_ADDRS = {a: ch for ch, a in MATCH_ADDR.items()}
# Token of each independence verdict change (step 9 of the contract).
_IND_CHANGE = {
    CH_SIP: (TOKEN_OTHER, CODE_MISMATCH, "other"),
    CH_CHIPLET: (TOKEN_T2, CODE_MATCH, "match"),
    CH_SEC_DIS: (TOKEN_OTHER, CODE_MISMATCH, "other"),
}


class _RailWatch:
    """Clock counter and the verdict state of one channel on the comparator rails.

    Each ``clk_i`` rising edge advances ``cyc``; ``trans`` lists (cyc, state) at
    each state change. The state is ``CODE_MATCH`` when every copy shows p 1 and
    n 0, ``CODE_MISMATCH`` when every copy shows p 0 and n 1 (all pairs opposite
    and in agreement, ``token_processing.adoc:132-133``), None for any other
    known value and -1 for an X or Z bit.
    """

    def __init__(self, ch: str) -> None:
        self.base = 3 * _RAIL_IDX[ch]
        self.cyc = 0
        self.trans: list[tuple[int, int | None]] = []
        self._stop = False
        self._task = None

    def _state(self) -> int | None:
        dut = cocotb.top
        p_bits = sig_bits(dut.token_cmp_match_p_o)
        n_bits = sig_bits(dut.token_cmp_match_n_o)
        if not set(p_bits + n_bits) <= {"0", "1"}:
            return -1
        p_v, n_v = int(p_bits, 2), int(n_bits, 2)
        p = [(p_v >> (self.base + k)) & 1 for k in range(3)]
        n = [(n_v >> (self.base + k)) & 1 for k in range(3)]
        if p == [1, 1, 1] and n == [0, 0, 0]:
            return CODE_MATCH
        if p == [0, 0, 0] and n == [1, 1, 1]:
            return CODE_MISMATCH
        return None

    async def _run(self) -> None:
        clk = cocotb.top.clk_i
        while not self._stop:
            await RisingEdge(clk)
            await ReadOnly()
            self.cyc += 1
            st = self._state()
            if not self.trans or self.trans[-1][1] != st:
                self.trans.append((self.cyc, st))

    def start(self) -> None:
        self._task = cocotb.start_soon(self._run())

    def stop(self) -> None:
        self._stop = True

    def verdict_after(self, start: int) -> tuple[int | None, int | None, int | None]:
        """(cleared, verdict cycle, verdict) of the first go issued at ``start``.

        ``cleared`` is the first cycle at or after ``start`` with no verdict on the
        rails; the verdict is the first Match or Mismatch after it. None when absent.
        """
        cleared = None
        for cyc, st in self.trans:
            if cleared is None:
                if cyc >= start and st not in (CODE_MATCH, CODE_MISMATCH):
                    cleared = cyc
            elif st in (CODE_MATCH, CODE_MISMATCH):
                return cleared, cyc, st
        return cleared, None, None

    def changes_in(self, lo: int, hi: int) -> list[tuple[int, int | None]]:
        """State changes with lo < cyc <= hi."""
        return [(c, st) for c, st in self.trans if lo < c <= hi]

    async def wait_verdict(self, start: int, bound: int) -> tuple[int | None, int | None]:
        """Wait at most ``bound`` clocks for the verdict of a go issued at ``start``."""
        clk = cocotb.top.clk_i
        for _ in range(bound):
            _c, v_cyc, v = self.verdict_after(start)
            if v_cyc is not None:
                return v_cyc, v
            await RisingEdge(clk)
        return None, None


async def _read_run_from(rd, ch: str, held: int, *, max_reads: int) -> ReadRun:
    """Read run of a graded go from the held code ``held``.

    The VPLAN read run (entry 6.23, procedure step 1) reads the match register back
    to back from the go until two consecutive reads return the same code other than
    ``0x00``. A read of ``held`` does not end the run: the run ends at two
    consecutive equal codes that are neither ``0x00`` nor ``held``, so a DUT that
    clears the held code later than one bus read after the go is not read as "no
    effect". The held code of every graded go differs from its expected final code
    by construction (``_settle`` and the step order), so the stop rule never waits
    for the expected code to change. ``final`` is None when ``max_reads`` ends the
    run with no such pair (a go with no effect); the caller fails CHK-TOKEN.
    ``w_hash`` counts every read from the go, ``n_idle`` the reads of ``0x00``.
    """
    codes: list[int] = []
    for _ in range(max_reads):
        code = (await rd(MATCH_ADDR[ch])) & MATCH_STATUS_MASK
        codes.append(code)
        if len(codes) >= 2 and code not in (CODE_IDLE, held) and codes[-2] == code:
            return ReadRun(code, len(codes), codes.count(CODE_IDLE), codes)
    return ReadRun(None, len(codes), codes.count(CODE_IDLE), codes)


def _idle_rule(run: ReadRun, held: int, n_idle_ref: int) -> tuple[bool, bool]:
    """Relative Idle rule of a read run after a go from the held code ``held``.

    No read returns a code outside {held, 0x00, final}; when held is not Idle and
    differs from the final code, no read after the first 0x00 returns held (a held
    Idle code is the 0x00 itself); when the first run of the
    channel saw 2 or more Idle reads, this run holds at least one 0x00. Returns
    (ok, idle_first_graded).
    """
    final = run.final
    codes = run.codes
    ok = final is not None and all(c in (held, CODE_IDLE, final) for c in codes)
    if ok and held != final and held != CODE_IDLE and CODE_IDLE in codes:
        first = codes.index(CODE_IDLE)
        ok = held not in codes[first + 1 :]
    graded = held != CODE_IDLE and n_idle_ref >= 2
    if graded:
        ok = ok and CODE_IDLE in codes
    return ok, graded


@pyuvm.test()
class sep_efuse_token_channel_rand_test(sep_base_test):
    """Token codes, mismatch shapes, hold, independence, no reset and retention."""

    required_evidence = (
        "CHK-BIND",
        "CHK-TOKEN",
        "CHK-TOKEN-CODES",
        "CHK-TOKEN-HOLD",
        "CHK-TOKEN-INDEP",
        "CHK-NORESET",
        "CHK-TOKEN-RETAIN",
        "CHK-TOKEN-PRESENSE",
        "CHK-TOKEN-GWB",
        "CHK-TOKEN-HMAC",
    )

    # ------------------------------------------------------------------ grading

    def _grade(self, name: str, cond: bool, **fields) -> bool:
        """``chk.ok`` that closes the FCOV window first when the check fails."""
        if not cond:
            close_graded_window(self.logger)
            self._fcov_dead = True
        return self.chk.ok(name, cond, **fields)

    def _ctrl(self, name: str, cond: bool, **fields) -> bool:
        """``chk.ctrl`` that closes the FCOV window first when the control is absent."""
        if not cond:
            close_graded_window(self.logger)
            self._fcov_dead = True
        return self.chk.ctrl(name, cond, **fields)

    def _hook_fail(self, **fields) -> None:
        close_graded_window(self.logger)
        self._fcov_dead = True
        hook_fail(self.chk, **fields)

    def _step(self) -> int:
        """Start a graded step: every later sample carries a new hold tag."""
        self._tag += 1
        set_ef_hold_tag(self._tag, self.logger)
        return self._tag

    def _resume(self, tag: int) -> None:
        """Continue graded step ``tag`` after an ungraded part."""
        set_ef_hold_tag(tag, self.logger)

    def _off(self) -> None:
        """An ungraded part (a settle go): its samples drop."""
        set_ef_hold_tag(0, self.logger)

    async def _pass(self, tag: int, ok: bool) -> None:
        """End step ``tag``; its held samples sample only when ``ok`` and no FAIL so far."""
        self._off()
        if not ok or self._fcov_dead:
            return
        set_ef_hold_pass(tag, self.logger)
        await ClockCycles(cocotb.top.clk_i, _PASS_HOLD)
        set_ef_hold_pass(0, self.logger)

    # ------------------------------------------------------------------ bus

    async def _rd(self, addr: int) -> int:
        """Frontdoor read; every match-register read is recorded for CHK-TOKEN-CODES."""
        value = await self.fd.rd(addr)
        if addr in _MATCH_ADDRS:
            self.codes_seen.append(value & MATCH_STATUS_MASK)
        return value

    async def _wr(self, addr: int, data: int) -> None:
        await self.fd.wr(addr, data)

    async def _code(self, ch: str) -> int:
        return (await self._rd(MATCH_ADDR[ch])) & MATCH_STATUS_MASK

    def _sense_done(self) -> int:
        """``sep_fuse_sense_done_o``; an X or Z raises, so it never counts as low."""
        return self.rd_known(cocotb.top.sep_fuse_sense_done_o) & 1

    def _sdis(self) -> int:
        return self.rd(cocotb.top.lcc_security_disable_probe_o, allow_unknown=True) & 1

    async def _code_presense(self, ch: str) -> tuple[int, bool]:
        """A match read with sep_fuse_sense_done_o sampled right before and after it.

        Returns (code, counted); a read with sense done high at either sample does
        not count.
        """
        before = self._sense_done()
        code = await self._code(ch)
        after = self._sense_done()
        return code, before == 0 and after == 0

    # ------------------------------------------------------------------ token steps

    async def _write(self, ch: str, token: int, label: str) -> list[int]:
        order = self.plan.draw.word_order(label)
        await write_token(self._wr, ch, token, order)
        return order

    async def _poll_until(self, ch: str, until: int) -> int | None:
        code, _n = await poll_code(self._rd, ch, max_reads=_RUN_READS, until=until)
        return code

    async def _settle(self, ch: str, token: int, target: int, label: str) -> int | None:
        """Bring ``ch`` to ``target`` with ``token``, from a held code other than target.

        When the channel already holds ``target`` it first takes the token of the
        opposite verdict, so every poll here waits for a code change.
        """
        if await self._code(ch) == target:
            if target == CODE_MATCH:
                opp, opp_code = TOKEN_OTHER, CODE_MISMATCH
            else:
                opp, opp_code = RIGHT_TOKEN[ch], CODE_MATCH
            await self._write(ch, opp, f"{label}.opp")
            await token_go(self._wr, ch)
            if await self._poll_until(ch, opp_code) != opp_code:
                return None
        await self._write(ch, token, label)
        await token_go(self._wr, ch)
        return await self._poll_until(ch, target)

    async def _graded_go(
        self,
        ch: str,
        token: int | None,
        exp: int,
        shape: str,
        label: str,
        **extra,
    ) -> tuple[ReadRun, bool]:
        """Optionally write ``token``, read the held code, go, read run, grade CHK-TOKEN.

        Returns the read run and the CHK-TOKEN result.
        """
        if token is not None:
            await self._write(ch, token, label)
        held = await self._code(ch)
        await token_go(self._wr, ch)
        run = await _read_run_from(self._rd, ch, held, max_reads=_RUN_READS)
        ref = self.n_idle_ref.get(ch, 0)
        idle_ok, graded = _idle_rule(run, held, ref)
        ok = self._grade(
            "TOKEN",
            run.final == exp and held != exp and idle_ok,
            ch=_CH_NAME[ch],
            shape=shape,
            exp=f"0x{exp:02x}",
            got="none" if run.final is None else f"0x{run.final:02x}",
            held=f"0x{held:02x}",
            idle_reads=run.n_idle,
            n_idle_ref=ref,
            idle_first_graded=int(graded),
            reads=run.w_hash,
            **extra,
        )
        return run, ok

    # ------------------------------------------------------------------ go while busy

    async def _gwb_leg(self, ch: str, pfx: str) -> None:
        """One second go on busy channel ``ch``: CTRL-TOKEN-GWB-BUSY and CHK-TOKEN-GWB.

        ``pfx`` names the draws and word orders of the leg.
        """
        dut = cocotb.top
        p = self.plan
        watch = _RailWatch(ch)
        watch.start()
        await RisingEdge(dut.clk_i)
        set_tch_overlap_pass(False, self.logger)

        # Reference single go: T from its B handshake to the rails verdict.
        await self._write(ch, TOKEN_OTHER, f"{pfx}.ref")
        i0 = watch.cyc
        await token_go(self._wr, ch)
        b0 = watch.cyc
        v0, s0 = await watch.wait_verdict(i0, _GWB_BOUND)
        ref_code = await self._poll_until(ch, CODE_MISMATCH)
        t = (v0 - b0) if v0 is not None else 0
        edge = t // _GWB_EDGE_DIV
        lo, hi = t // 4 + edge, 3 * t // 4 - edge
        if v0 is None or s0 != CODE_MISMATCH or ref_code != CODE_MISMATCH or hi <= lo:
            watch.stop()
            self._hook_fail(
                reason="gwb_reference_go",
                ch=_CH_NAME[ch],
                t=t,
                rails="none" if s0 is None else f"0x{s0:02x}",
                code="none" if ref_code is None else f"0x{ref_code:02x}",
            )
        d = p.draw.randrange(f"{pfx}.d", lo, hi + 1)

        # First go from a held Mismatch, then the second go at B1 + d.
        tag = self._step()
        await self._write(ch, RIGHT_TOKEN[ch], f"{pfx}.go")
        held = await self._code(ch)
        i1 = watch.cyc
        await token_go(self._wr, ch)
        b1 = watch.cyc
        lat = b1 - i1
        wait = b1 + d - lat - watch.cyc
        if wait > 0:
            await ClockCycles(dut.clk_i, wait)
        await token_go(self._wr, ch)
        b2 = watch.cyc
        end = b1 + 2 * t + _GWB_SETTLE

        # Frontdoor reads from the second go to past the hold end (bounded).
        polls: list[tuple[int, int]] = []
        for _ in range(_RUN_READS):
            if watch.cyc > end:
                break
            code = await self._code(ch)
            polls.append((watch.cyc, code))
        if watch.cyc <= end:
            await ClockCycles(dut.clk_i, end - watch.cyc + 1)
        final = await self._code(ch)
        polls.append((watch.cyc, final))
        await RisingEdge(dut.clk_i)
        watch.stop()

        cleared, v1, s1 = watch.verdict_after(i1)
        dt2 = b2 - b1
        busy_ok = (
            cleared is not None
            and cleared <= b2
            and (v1 is None or v1 > b2)
            and 4 * dt2 >= t
            and 4 * dt2 <= 3 * t
        )
        busy_ok = self._ctrl(
            "TOKEN-GWB-BUSY",
            busy_ok,
            ch=_CH_NAME[ch],
            t=t,
            d=d,
            dt2=dt2,
            cleared="none" if cleared is None else cleared - b1,
            verdict_at="none" if v1 is None else v1 - b1,
        )
        exp_v = b1 + t
        timing_ok = v1 is not None and abs(v1 - exp_v) <= _GWB_TOL
        late = watch.changes_in(v1, end) if v1 is not None else [(0, None)]
        hold_ok = s1 == CODE_MATCH and not late
        codes = [c for _cyc, c in polls]
        first = next((c for c in codes if c not in (CODE_IDLE, held)), None)
        polls_ok = all(c in (held, CODE_IDLE, CODE_MATCH) for c in codes) and first == CODE_MATCH
        if first == CODE_MATCH:
            k = next(i for i, c in enumerate(codes) if c == CODE_MATCH)
            polls_ok = polls_ok and all(c == CODE_MATCH for c in codes[k:])
        polls_ok = polls_ok and final == CODE_MATCH and polls[-1][0] > end
        ok = self._grade(
            "TOKEN-GWB",
            held == CODE_MISMATCH and timing_ok and hold_ok and polls_ok,
            ch=_CH_NAME[ch],
            held=f"0x{held:02x}",
            t=t,
            d=d,
            dt2=dt2,
            verdict_at="none" if v1 is None else v1 - b1,
            exp_at=exp_v - b1,
            tol=_GWB_TOL,
            rails="none" if s1 is None else f"0x{s1:02x}",
            changes_to_end=len(late),
            hold_to=end - b1,
            reads=len(codes),
            first=f"0x{first:02x}" if first is not None else "none",
            final=f"0x{final:02x}",
        )
        await self._pass(tag, ok and busy_ok)
        if ok:
            set_tch_overlap_pass(True, self.logger)
            await ClockCycles(dut.clk_i, _HOV_SETTLE_CLKS)
            set_tch_overlap_pass(False, self.logger)

    # ------------------------------------------------------------------ HMAC overlap

    async def _push(self, words: list[int]) -> None:
        for w in words:
            await self.hmac._wait_fifo_space()
            await self.hmac._wr(HMAC_MSG_FIFO, w)

    async def _hov_leg(self, ch: str, token: int, exp: int, tag: str) -> None:
        """Twin go with HMAC idle, then the go with keyed HMAC busy: CHK-TOKEN-HMAC."""
        dut = cocotb.top
        p = self.plan
        opp_tok, opp_code = (
            (TOKEN_OTHER, CODE_MISMATCH) if exp == CODE_MATCH else (RIGHT_TOKEN[ch], CODE_MATCH)
        )
        n_tail = _HOV_BLOCK_WORDS * p.draw.randrange(
            f"hov.{tag}.tail_blocks", *_HOV_TAIL_BLOCKS
        ) + p.draw.randrange(f"hov.{tag}.tail_words", *_HOV_TAIL_WORDS)
        n_head = _HOV_BLOCK_WORDS * _HOV_HEAD_BLOCKS
        key = p.draw.put(
            f"hov.{tag}.key", [p.draw.rng.getrandbits(32) for _ in range(_HOV_KEY_WORDS)]
        )
        msg = p.draw.put(
            f"hov.{tag}.msg", [p.draw.rng.getrandbits(32) for _ in range(n_head + n_tail)]
        )
        cfg = SepHmacCfg(sha_bits=256, hmac_en=True, key_bits=256, key_words=key, msg_words=msg)

        # Twin: the same go with HMAC idle.
        if await self._settle(ch, opp_tok, opp_code, f"hov.{tag}.twin_set") != opp_code:
            self._hook_fail(reason="hov_twin_held", ch=_CH_NAME[ch])
        st0 = await self.hmac._rd(HMAC_STATUS)
        await self._write(ch, token, f"hov.{tag}.twin")
        t_held = await self._code(ch)
        await token_go(self._wr, ch)
        t_run = await _read_run_from(self._rd, ch, t_held, max_reads=_RUN_READS)
        st1 = await self.hmac._rd(HMAC_STATUS)
        self._ctrl(
            "TOKEN-HMAC-IDLE",
            bool(st0 & HMAC_STATUS_IDLE)
            and bool(st1 & HMAC_STATUS_IDLE)
            and t_held != exp
            and t_run.final == exp,
            ch=_CH_NAME[ch],
            exp=f"0x{exp:02x}",
            got="none" if t_run.final is None else f"0x{t_run.final:02x}",
            status=f"0x{st0:08x},0x{st1:08x}",
        )

        # Overlap: keyed HMAC-SHA256 busy across the go and the verdict.
        if await self._settle(ch, opp_tok, opp_code, f"hov.{tag}.set") != opp_code:
            self._hook_fail(reason="hov_held", ch=_CH_NAME[ch])
        step = self._step()
        await self._write(ch, token, f"hov.{tag}")
        set_tch_overlap_pass(False, self.logger)
        await self.hmac.configure(cfg.cfg_word())
        await self.hmac.write_key(key)
        await self.hmac._wr(HMAC_CMD, HMAC_CMD_HASH_START)
        await self._push(msg[:n_head])
        st_pre = await self.hmac._rd(HMAC_STATUS)
        held = await self._code(ch)
        await token_go(self._wr, ch)
        run = await _read_run_from(self._rd, ch, held, max_reads=_RUN_READS)
        st_post = await self.hmac._rd(HMAC_STATUS)
        busy_ok = self._ctrl(
            "TOKEN-HMAC-BUSY",
            not (st_pre & HMAC_STATUS_IDLE) and not (st_post & HMAC_STATUS_IDLE),
            ch=_CH_NAME[ch],
            status_pre=f"0x{st_pre:08x}",
            status_post=f"0x{st_post:08x}",
        )
        idle_ok, _g = _idle_rule(run, held, self.n_idle_ref.get(ch, 0))
        tok_ok = run.final == exp and held != exp and idle_ok
        if not tok_ok:
            close_graded_window(self.logger)
            self._fcov_dead = True
        await self._push(msg[n_head:])
        await self.hmac._wr(HMAC_CMD, HMAC_CMD_HASH_PROCESS)
        await self.hmac._wait_done()
        digest = await self.hmac.read_digest()
        await self.hmac._wr(HMAC_INTR_STATE, HMAC_INTR_DONE)
        err = await self.hmac._rd(HMAC_ERR_CODE)
        # KEY_0 first, each KEY word big-endian (CFG.key_swap 0); each MSG_FIFO
        # word added little-endian (CFG.endian_swap 0)
        # (vendor/lowRISC/opentitan/overlay/regs/hmac/regs/gen/adoc/hmac.adoc:111-120);
        # key[1023:0] = {KEY0, KEY1, ...} puts KEY_0 first
        # (vendor/lowRISC/opentitan/upstream/hw/ip/hmac/doc/registers.md:352).
        key_bytes = b"".join(w.to_bytes(4, "big") for w in key)
        msg_bytes = b"".join(w.to_bytes(4, "little") for w in msg)
        mac = hmac_sha2_bytes(key_bytes, msg_bytes, 256)
        order = digest_order(digest, mac)
        ok = self._grade(
            "TOKEN-HMAC",
            tok_ok and order == DSWAP_ORDER[0] and err == 0,
            ch=_CH_NAME[ch],
            exp=f"0x{exp:02x}",
            got="none" if run.final is None else f"0x{run.final:02x}",
            held=f"0x{held:02x}",
            idle_reads=run.n_idle,
            msg_words=len(msg),
            head_words=n_head,
            digest="mismatch" if order is None else order,
            digest0=f"0x{digest[0]:08x}",
            err_code=f"0x{err:08x}",
        )
        await self._pass(step, ok and busy_ok)
        if ok:
            set_tch_overlap_pass(True, self.logger)
            await ClockCycles(dut.clk_i, _HOV_SETTLE_CLKS)
            set_tch_overlap_pass(False, self.logger)

    # ------------------------------------------------------------------ scenario

    async def _cold_reset_nowait(self) -> None:
        """Cold reset with no wait for sense (a retained SEC_DIS match holds sensing off)."""
        await rst_pulse(self)
        await ClockCycles(cocotb.top.clk_i, 4)

    async def run_scenario(self) -> None:
        dut = cocotb.top
        seed = self.random_seed()
        p = plan(T_TOKEN_CHANNEL, seed)
        self.plan = p
        for line in p.log_lines():
            self.logger.info("%s", line)
        self.chk = SepChkLog(self, _NAME, seed)
        self.fd = SepEfuseFd(self)
        if p.setup_fail:
            raise AssertionError(f"SETUP FAIL seed={seed} reason={p.setup_fail}")
        self.logger.info("EVIDENCE-REQUIRED seed=%d ids=%s", seed, ",".join(self.required_evidence))
        self.codes_seen: list[int] = []
        self.n_idle_ref: dict[str, int] = {}
        self._fcov_dead = False
        self._tag = 0
        self._off()
        set_ef_hold_pass(0, self.logger)
        w_hash: dict[str, int] = {}
        leg = p.leg

        await chk_bind(self.chk)

        self.write_efuse_image(p.image)
        await self.bring_up_no_cpu()
        self._set_pin(dut, "test_en_strap_i", 0)
        self.suppress_host_axi_transaction_info()
        open_graded_window(_NAME, self.logger)

        # No-reset cell: the 24 token word registers before any token write.
        await ReadOnly()
        x_words = 0
        x_detail = []
        for ch in CHANNELS:
            for k, w in enumerate(tap_words(sig_bits(getattr(dut, _WORD_TAP[ch])))):
                is_x = len(w) == 32 and all(c in "xX" for c in w)
                x_words += int(is_x)
                if not is_x:
                    x_detail.append(f"{_CH_NAME[ch]}[{k}]={w}")
        await RisingEdge(dut.clk_i)

        # Walk.
        ctl_word: int | None = None
        ctl_ok = True
        first_rma = next(ch for ch in leg["walk_order"] if ch != CH_SEC_DIS)
        for ch in leg["walk_order"]:
            tag = self._step()
            tok = RIGHT_TOKEN[ch]
            foreign = FOREIGN_TOKEN[ch]
            subset = leg["decoys"][ch]
            decoy_order = [k for k in p.draw.word_order(f"decoy.{ch}") if subset >> k & 1]
            decoy = token_words(TOKEN_OTHER)
            for i, k in enumerate(decoy_order):
                await self._wr(TOKEN_ARRAY_ADDR[ch][k], decoy[k])
                if i == 0:
                    # Control of the no-reset cell: the tap shows the word written.
                    await ClockCycles(dut.clk_i, 1)
                    await ReadOnly()
                    w = tap_words(sig_bits(getattr(dut, _WORD_TAP[ch])))[k]
                    seen = int(w, 2) if set(w) <= {"0", "1"} else None
                    await RisingEdge(dut.clk_i)
                    if ctl_word is None:
                        ctl_word = seen if seen is not None else -1
                    ctl_ok &= seen == decoy[k]
            await self._write(ch, tok, f"walk.{ch}")

            # No specification states the layout of the digest in the shadow words, so
            # the Match of the right token is logged and is a control of the later legs.
            held_w = await self._code(ch)
            await token_go(self._wr, ch)
            run = await _read_run_from(self._rd, ch, held_w, max_reads=_RUN_READS)
            self.chk.obs(
                "TOKEN-DIGEST-LAYOUT",
                ch=_CH_NAME[ch],
                final="none" if run.final is None else f"0x{run.final:02x}",
                held=f"0x{held_w:02x}",
                idle_reads=run.n_idle,
                reads=run.w_hash,
            )
            ok_walk = self._ctrl(
                "TOKEN-DIGEST-LAYOUT",
                run.final == CODE_MATCH and held_w != CODE_MATCH,
                ch=_CH_NAME[ch],
                final="none" if run.final is None else f"0x{run.final:02x}",
            )
            w_hash[ch] = run.w_hash
            self.n_idle_ref[ch] = run.n_idle
            if ch == first_rma and run.final != CODE_MATCH:
                self._hook_fail(reason="digest_staging", ch=_CH_NAME[ch], code=run.final)
            if ch == CH_SEC_DIS:
                await ClockCycles(dut.clk_i, 2)
                if run.final != CODE_MATCH or self._sdis() != 1:
                    self._hook_fail(
                        reason="sec_dis_revision_enable",
                        code=run.final,
                        secdis=self._sdis(),
                    )

            # Hold cell: words of F with no go leave the held code.
            held = run.final
            await self._write(ch, foreign, f"hold.{ch}")
            window = _HOLD_MULT * w_hash[ch]
            hold_codes = [await self._code(ch) for _ in range(window)]
            hold_ok = all(c == held for c in hold_codes)

            # Idle-first cell: go with the words of F.
            run_d, ok_d = await self._graded_go(ch, None, CODE_MISMATCH, "foreign", f"idle.{ch}.go")
            if ch == CH_SEC_DIS:
                await ClockCycles(dut.clk_i, 2)
                self.chk.obs("SDIS-AFTER-FOREIGN", secdis=self._sdis())
            ok_hold = self._grade(
                "TOKEN-HOLD",
                hold_ok and held in (CODE_MATCH, CODE_MISMATCH) and run_d.w_hash <= w_hash[ch],
                ch=_CH_NAME[ch],
                held="none" if held is None else f"0x{held:02x}",
                reads_in_window=len(hold_codes),
                all_equal=int(hold_ok),
                next_go_reads=run_d.w_hash,
                w_hash=w_hash[ch],
            )
            await self._pass(tag, ok_walk and ok_d and ok_hold)

        self._grade(
            "NORESET",
            x_words == 24 and ctl_ok and ctl_word is not None,
            arrays=3,
            x_words=x_words,
            ctl_word="none" if ctl_word is None else f"0x{ctl_word & 0xFFFF_FFFF:08x}",
            not_x=",".join(x_detail[:4]) or "none",
        )

        # Mismatch walk: 18 (shape, channel) cells.
        draws = p.draws
        for shape, ch in leg["cell_order"]:
            if await self._settle(ch, RIGHT_TOKEN[ch], CODE_MATCH, f"cell.{shape}.{ch}.set") != (
                CODE_MATCH
            ):
                self._grade("TOKEN", False, ch=_CH_NAME[ch], shape="match", reason="held_match")
                continue
            if ch == CH_SEC_DIS:
                await ClockCycles(dut.clk_i, 2)
                if self._sdis() != 1:
                    self._grade("TOKEN", False, ch="sdis", shape="match", secdis=0)
            tok = leg["shape_tokens"][(shape, ch)]
            tag = self._step()
            extra = {}
            if shape == "flip":
                name = f"flip@{draws[f'flip_pos.{ch}']}"
            elif shape == "swap":
                i, j = draws[f"swap_words.{ch}"]
                name = f"swap<{i},{j}>"
            elif shape == "byte_swap":
                name = f"bswap<{draws[f'byte_swap_word.{ch}']}>"
            elif shape == "digest":
                name = "digest_as_token"
                dig = expected_digest(ch, p.image)
                extra = {
                    "tok_eq_digest": int(tok == dig),
                    "tok_words": ",".join(f"0x{w:08x}" for w in token_words(tok)),
                    "digest_words": ",".join(f"0x{w:08x}" for w in token_words(dig)),
                }
            else:
                name = shape
            _run, ok = await self._graded_go(
                ch, tok, CODE_MISMATCH, name, f"cell.{shape}.{ch}", **extra
            )
            await self._pass(tag, ok)

        # Independence cell.
        maxw = max(w_hash.values())
        indep: list[dict] = []
        tag_ind = self._step()
        self._off()
        ind_tok_ok = True
        for c in leg["independence_order"]:
            sdis_tok, sdis_code = (
                (TOKEN_ZERO, CODE_MATCH) if c == CH_SEC_DIS else (TOKEN_OTHER, CODE_MISMATCH)
            )
            setup = {
                CH_SIP: await self._settle(CH_SIP, TOKEN_T1, CODE_MATCH, f"ind.{c}.sip"),
                CH_CHIPLET: await self._settle(
                    CH_CHIPLET, TOKEN_OTHER, CODE_MISMATCH, f"ind.{c}.chp"
                ),
                CH_SEC_DIS: await self._settle(CH_SEC_DIS, sdis_tok, sdis_code, f"ind.{c}.sdis"),
            }
            held = {ch: await self._code(ch) for ch in CHANNELS}
            self.chk.info(
                "INDEP-HELD",
                go=_CH_NAME[c],
                held=",".join(f"{_CH_NAME[ch]}:0x{v:02x}" for ch, v in held.items()),
            )
            tok, exp, shape = _IND_CHANGE[c]
            self._resume(tag_ind)
            run, ok = await self._graded_go(c, tok, exp, shape, f"ind.{c}.go")
            ind_tok_ok &= ok
            others = [ch for ch in CHANNELS if ch != c]
            at_once = {ch: await self._code(ch) for ch in others}
            later_ok = True
            for _ in range(_IND_MULT * maxw):
                for ch in others:
                    later_ok &= await self._code(ch) == held[ch]
            after = {ch: await self._code(ch) for ch in others}
            self._off()
            idle_ok, _g = _idle_rule(run, held[c], self.n_idle_ref.get(c, 0))
            indep.append(
                {
                    "go": c,
                    "ok": all(v is not None for v in setup.values())
                    and all(held[ch] != CODE_IDLE for ch in CHANNELS)
                    and run.final == exp
                    and held[c] != exp
                    and idle_ok
                    and all(at_once[ch] == held[ch] for ch in others)
                    and later_ok
                    and all(after[ch] == held[ch] for ch in others),
                    "held": ",".join(f"0x{held[ch]:02x}" for ch in others),
                    "others": ",".join(f"0x{after[ch]:02x}" for ch in others),
                }
            )

        # SEC_DIS with an RMA token.
        h = await self._settle(CH_SEC_DIS, TOKEN_ZERO, CODE_MATCH, "sdis_t1.h")
        rma_before = {ch: await self._code(ch) for ch in (CH_SIP, CH_CHIPLET)}
        self._resume(tag_ind)
        run_t1, ok = await self._graded_go(
            CH_SEC_DIS, TOKEN_T1, CODE_MISMATCH, "foreign", "sdis_t1"
        )
        ind_tok_ok &= ok
        rma_after = {ch: await self._code(ch) for ch in (CH_SIP, CH_CHIPLET)}
        self._off()
        sdis_t1 = run_t1.final
        t1_ok = h == CODE_MATCH and sdis_t1 == CODE_MISMATCH and rma_after == rma_before
        for rec in indep:
            ind_tok_ok &= self._grade(
                "TOKEN-INDEP",
                rec["ok"] and t1_ok,
                go=_CH_NAME[rec["go"]],
                held=rec["held"],
                others=rec["others"],
                sdis_t1="none" if sdis_t1 is None else f"0x{sdis_t1:02x}",
            )
        await self._pass(tag_ind, ind_tok_ok)

        for ch in (CH_SIP, CH_CHIPLET):
            if await self._code(ch) == CODE_MATCH:
                await self._write(ch, TOKEN_OTHER, f"end.{ch}")
                await token_go(self._wr, ch)
                if await self._poll_until(ch, CODE_MISMATCH) != CODE_MISMATCH:
                    raise AssertionError(f"mismatch go on {ch} did not read 0x2a")

        # Pre-sense cell.
        if await self._settle(CH_SEC_DIS, TOKEN_ZERO, CODE_MATCH, "pre.sdis") != CODE_MATCH:
            self._hook_fail(reason="pre_sense_sdis_match")
        await ClockCycles(dut.clk_i, 2)
        if self._sdis() != 1:
            self._hook_fail(reason="pre_sense_secdis", secdis=0)
        await self._cold_reset_nowait()
        tag_pre = self._step()
        for ch, tok in ((CH_SIP, TOKEN_T1), (CH_CHIPLET, TOKEN_T2)):
            await self._write(ch, tok, f"pre.{ch}")
            await token_go(self._wr, ch)
        sdis_pre, _n = await poll_code(self._rd, CH_SEC_DIS, max_reads=_RUN_READS)
        prewin = _PRE_MULT * max(w_hash[CH_SIP], w_hash[CH_CHIPLET])
        for _ in range(prewin):
            await self._code(CH_SEC_DIS)
        sdis_held = await self._code(CH_SEC_DIS)
        pre_codes: dict[str, list[int]] = {CH_SIP: [], CH_CHIPLET: []}
        for _ in range(2):
            for ch in (CH_SIP, CH_CHIPLET):
                code, counted = await self._code_presense(ch)
                if counted:
                    pre_codes[ch].append(code)
        self._off()
        sdis_drop = await self._settle(CH_SEC_DIS, TOKEN_OTHER, CODE_MISMATCH, "pre.sdis_drop")
        self._resume(tag_pre)
        await self.pulse_rst_ni()
        retained = {}
        for ch in (CH_SIP, CH_CHIPLET):
            retained[ch], _n = await poll_code(self._rd, ch, max_reads=_RUN_READS)
        post = {}
        for ch in (CH_SIP, CH_CHIPLET):
            await token_go(self._wr, ch)
            post[ch] = (await read_run(self._rd, ch, max_reads=_RUN_READS)).final
        pre_ok = True
        for ch in (CH_SIP, CH_CHIPLET):
            codes = pre_codes[ch]
            pre_ok &= self._grade(
                "TOKEN-PRESENSE",
                bool(codes)
                and all(c == CODE_IDLE for c in codes)
                and sdis_pre == CODE_MATCH
                and sdis_held == CODE_MATCH
                and sdis_drop == CODE_MISMATCH
                and retained[ch] == CODE_MATCH
                and post[ch] == CODE_MATCH,
                ch=_CH_NAME[ch],
                sense_done=0,
                sdis_held="none" if sdis_held is None else f"0x{sdis_held:02x}",
                window=prewin,
                pre=",".join(f"0x{c:02x}" for c in codes) or "none",
                counted_reads=len(codes),
                retained_post_sense="none" if retained[ch] is None else f"0x{retained[ch]:02x}",
                post="none" if post[ch] is None else f"0x{post[ch]:02x}",
            )
        await self._pass(tag_pre, pre_ok)

        # Retention cell.
        tag_ret = self._step()
        await self._write(CH_CHIPLET, TOKEN_OTHER, "ret.chp")
        await token_go(self._wr, CH_CHIPLET)
        chp_end = await self._poll_until(CH_CHIPLET, CODE_MISMATCH)
        pre_sip = await self._code(CH_SIP)
        await self._write(CH_SEC_DIS, TOKEN_ZERO, "ret.sdis")
        await token_go(self._wr, CH_SEC_DIS)
        sdis_m = await self._poll_until(CH_SEC_DIS, CODE_MATCH)
        await ClockCycles(dut.clk_i, 2)
        sdis_o = self._sdis()
        await self._cold_reset_nowait()
        counted_ok = True
        sd_pre = self._sense_done()
        sdis_ret, _n = await poll_code(self._rd, CH_SEC_DIS, max_reads=_RUN_READS)
        for _ in range(prewin):
            await self._code(CH_SEC_DIS)
        post_codes = {}
        for ch in CHANNELS:
            post_codes[ch], counted = await self._code_presense(ch)
            counted_ok &= counted
        words_ok = 0
        for ch, tok in ((CH_SIP, TOKEN_T1), (CH_CHIPLET, TOKEN_OTHER), (CH_SEC_DIS, TOKEN_ZERO)):
            exp_words = token_words(tok)
            for k, addr in enumerate(TOKEN_ARRAY_ADDR[ch]):
                before = self._sense_done()
                w = await self._rd(addr)
                after = self._sense_done()
                counted_ok &= before == 0 and after == 0
                words_ok += int(w == exp_words[k])
        sd_post = self._sense_done()
        drop = await self._settle(CH_SEC_DIS, TOKEN_OTHER, CODE_MISMATCH, "ret.sdis_drop")
        await self.pulse_rst_ni()
        post_sense, _n = await poll_code(self._rd, CH_SIP, max_reads=_RUN_READS)
        ok = self._grade(
            "TOKEN-RETAIN",
            pre_sip == CODE_MATCH
            and chp_end == CODE_MISMATCH
            and sdis_m == CODE_MATCH
            and sdis_o == 1
            and counted_ok
            and sdis_ret == CODE_MATCH
            and post_codes[CH_SIP] == CODE_IDLE
            and post_codes[CH_CHIPLET] == CODE_IDLE
            and post_codes[CH_SEC_DIS] == CODE_MATCH
            and words_ok == 24
            and drop == CODE_MISMATCH
            and post_sense == CODE_MATCH,
            pre=f"0x{pre_sip:02x}",
            sense_done_pre=sd_pre,
            sense_done_post=sd_post,
            post_reset_rma=f"0x{post_codes[CH_SIP]:02x},0x{post_codes[CH_CHIPLET]:02x}",
            post_reset_sdis=f"0x{post_codes[CH_SEC_DIS]:02x}",
            words_equal=words_ok,
            post_sense="none" if post_sense is None else f"0x{post_sense:02x}",
            counted=int(counted_ok),
            ctl_secdis=sdis_o,
        )
        await self._pass(tag_ret, ok)

        # HMAC overlap (one Match go, one Mismatch go on RMA channels), then go
        # while busy. Their draws follow every earlier draw of the leaf.
        self.hmac = SepHmac(self)
        ch_m = p.draw.choice("hov.match.ch", (CH_SIP, CH_CHIPLET))
        ch_x = p.draw.choice("hov.mismatch.ch", (CH_SIP, CH_CHIPLET))
        await self._hov_leg(ch_m, RIGHT_TOKEN[ch_m], CODE_MATCH, "match")
        await self._hov_leg(ch_x, FOREIGN_TOKEN[ch_x], CODE_MISMATCH, "mismatch")
        ch_g = p.draw.choice("gwb.ch", CHANNELS)
        await self._gwb_leg(ch_g, "gwb")
        for ch in CHANNELS:
            if ch != ch_g:
                await self._gwb_leg(ch, f"gwb.{_CH_NAME[ch]}")

        seen = sorted(set(self.codes_seen))
        self._grade(
            "TOKEN-CODES",
            all(c in _ALLOWED for c in self.codes_seen) and len(self.codes_seen) > 0,
            allowed="00,15,2a",
            seen=",".join(f"{c:02x}" for c in seen),
            reads=len(self.codes_seen),
        )
        close_graded_window(self.logger)
        await self._multi_go()
        self.chk.finish()

    async def _multi_go(self) -> None:
        """One ``TOKEN_EOP`` write with the go bits of a drawn channel pair, logged only.

        ``OBS-TOKEN-MULTI-GO``: per channel of the pair, the code after the write and
        the clocks from the write to the verdict on the comparator rails. The
        specification does not state the result of two go bits in one write.
        """
        pairs = [(a, b) for i, a in enumerate(CHANNELS) for b in CHANNELS[i + 1 :]]
        pair = self.plan.draw.choice("multi_go.pair", pairs)
        watches = {ch: _RailWatch(ch) for ch in pair}
        for w in watches.values():
            w.start()
        await ClockCycles(cocotb.top.clk_i, 1)
        start = {ch: w.cyc for ch, w in watches.items()}
        bits = GO_MASK[pair[0]] | GO_MASK[pair[1]]
        await self.fd.wr(TOKEN_EOP_ADDR, bits)
        fields: dict = {"bits": f"0x{bits:x}"}
        for ch, w in watches.items():
            v_cyc, _v = await w.wait_verdict(start[ch], _GWB_BOUND)
            code, _n = await poll_code(self.fd.rd, ch, max_reads=_RUN_READS)
            name = _CH_NAME[ch]
            fields[f"{name}_final"] = "none" if code is None else f"0x{code:02x}"
            fields[f"{name}_cycles"] = "none" if v_cyc is None else v_cyc - start[ch]
        for w in watches.values():
            w.stop()
        self.chk.obs("TOKEN-MULTI-GO", **fields)
