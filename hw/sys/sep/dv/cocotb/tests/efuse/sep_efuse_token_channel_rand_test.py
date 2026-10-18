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

No step writes two go bits in one ``TOKEN_EOP`` write, and every SEC_DIS go runs
with ``secure_tm_req_i`` at 0. Every graded go starts from a held code other than
its expected final code, so a go that has no effect fails.

Checkers: CHK-BIND, CHK-TOKEN, CHK-TOKEN-CODES, CHK-TOKEN-HOLD, CHK-TOKEN-INDEP,
CHK-NORESET, CHK-TOKEN-RETAIN, CHK-TOKEN-PRESENSE. A failing hook control logs
``CHK-HOOK FAIL`` and ends the leaf.
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
    MATCH_ADDR,
    MATCH_STATUS_MASK,
    RIGHT_TOKEN,
    T_TOKEN_CHANNEL,
    TOKEN_ARRAY_ADDR,
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
from env.sep_fcov_gate import close_graded_window, open_graded_window
from sep_base_test import sep_base_test

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
_MATCH_ADDRS = {a: ch for ch, a in MATCH_ADDR.items()}
# Token of each independence verdict change (step 9 of the contract).
_IND_CHANGE = {
    CH_SIP: (TOKEN_OTHER, CODE_MISMATCH, "other"),
    CH_CHIPLET: (TOKEN_T2, CODE_MATCH, "match"),
    CH_SEC_DIS: (TOKEN_OTHER, CODE_MISMATCH, "other"),
}


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
    )

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
    ) -> ReadRun:
        """Optionally write ``token``, read the held code, go, read run, grade CHK-TOKEN."""
        if token is not None:
            await self._write(ch, token, label)
        held = await self._code(ch)
        await token_go(self._wr, ch)
        run = await _read_run_from(self._rd, ch, held, max_reads=_RUN_READS)
        ref = self.n_idle_ref.get(ch, 0)
        idle_ok, graded = _idle_rule(run, held, ref)
        self.chk.ok(
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
        return run

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

            run = await self._graded_go(ch, None, CODE_MATCH, "match", f"walk.{ch}.go")
            w_hash[ch] = run.w_hash
            self.n_idle_ref[ch] = run.n_idle
            if ch == first_rma and run.final != CODE_MATCH:
                hook_fail(self.chk, reason="digest_staging", ch=_CH_NAME[ch], code=run.final)
            if ch == CH_SEC_DIS:
                await ClockCycles(dut.clk_i, 2)
                if run.final != CODE_MATCH or self._sdis() != 1:
                    hook_fail(
                        self.chk,
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
            run_d = await self._graded_go(ch, None, CODE_MISMATCH, "foreign", f"idle.{ch}.go")
            if ch == CH_SEC_DIS:
                await ClockCycles(dut.clk_i, 2)
                self.chk.obs("SDIS-AFTER-FOREIGN", secdis=self._sdis())
            self.chk.ok(
                "TOKEN-HOLD",
                hold_ok and held in (CODE_MATCH, CODE_MISMATCH) and run_d.w_hash <= w_hash[ch],
                ch=_CH_NAME[ch],
                held="none" if held is None else f"0x{held:02x}",
                reads_in_window=len(hold_codes),
                all_equal=int(hold_ok),
                next_go_reads=run_d.w_hash,
                w_hash=w_hash[ch],
            )

        self.chk.ok(
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
                self.chk.ok("TOKEN", False, ch=_CH_NAME[ch], shape="match", reason="held_match")
                continue
            if ch == CH_SEC_DIS:
                await ClockCycles(dut.clk_i, 2)
                if self._sdis() != 1:
                    self.chk.ok("TOKEN", False, ch="sdis", shape="match", secdis=0)
            tok = leg["shape_tokens"][(shape, ch)]
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
            await self._graded_go(ch, tok, CODE_MISMATCH, name, f"cell.{shape}.{ch}", **extra)

        # Independence cell.
        maxw = max(w_hash.values())
        indep: list[dict] = []
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
            self.chk.obs(
                "INDEP-HELD",
                go=_CH_NAME[c],
                held=",".join(f"{_CH_NAME[ch]}:0x{v:02x}" for ch, v in held.items()),
            )
            tok, exp, shape = _IND_CHANGE[c]
            run = await self._graded_go(c, tok, exp, shape, f"ind.{c}.go")
            others = [ch for ch in CHANNELS if ch != c]
            at_once = {ch: await self._code(ch) for ch in others}
            later_ok = True
            for _ in range(_IND_MULT * maxw):
                for ch in others:
                    later_ok &= await self._code(ch) == held[ch]
            after = {ch: await self._code(ch) for ch in others}
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
        run_t1 = await self._graded_go(CH_SEC_DIS, TOKEN_T1, CODE_MISMATCH, "foreign", "sdis_t1")
        rma_after = {ch: await self._code(ch) for ch in (CH_SIP, CH_CHIPLET)}
        sdis_t1 = run_t1.final
        t1_ok = h == CODE_MATCH and sdis_t1 == CODE_MISMATCH and rma_after == rma_before
        for rec in indep:
            self.chk.ok(
                "TOKEN-INDEP",
                rec["ok"] and t1_ok,
                go=_CH_NAME[rec["go"]],
                held=rec["held"],
                others=rec["others"],
                sdis_t1="none" if sdis_t1 is None else f"0x{sdis_t1:02x}",
            )

        for ch in (CH_SIP, CH_CHIPLET):
            if await self._code(ch) == CODE_MATCH:
                await self._write(ch, TOKEN_OTHER, f"end.{ch}")
                await token_go(self._wr, ch)
                if await self._poll_until(ch, CODE_MISMATCH) != CODE_MISMATCH:
                    raise AssertionError(f"mismatch go on {ch} did not read 0x2a")

        # Pre-sense cell.
        if await self._settle(CH_SEC_DIS, TOKEN_ZERO, CODE_MATCH, "pre.sdis") != CODE_MATCH:
            hook_fail(self.chk, reason="pre_sense_sdis_match")
        await ClockCycles(dut.clk_i, 2)
        if self._sdis() != 1:
            hook_fail(self.chk, reason="pre_sense_secdis", secdis=0)
        await self._cold_reset_nowait()
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
        sdis_drop = await self._settle(CH_SEC_DIS, TOKEN_OTHER, CODE_MISMATCH, "pre.sdis_drop")
        await self.pulse_rst_ni()
        retained = {}
        for ch in (CH_SIP, CH_CHIPLET):
            retained[ch], _n = await poll_code(self._rd, ch, max_reads=_RUN_READS)
        post = {}
        for ch in (CH_SIP, CH_CHIPLET):
            await token_go(self._wr, ch)
            post[ch] = (await read_run(self._rd, ch, max_reads=_RUN_READS)).final
        for ch in (CH_SIP, CH_CHIPLET):
            codes = pre_codes[ch]
            self.chk.ok(
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

        # Retention cell.
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
        self.chk.ok(
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

        seen = sorted(set(self.codes_seen))
        self.chk.ok(
            "TOKEN-CODES",
            all(c in _ALLOWED for c in self.codes_seen) and len(self.codes_seen) > 0,
            allowed="00,15,2a",
            seen=",".join(f"{c:02x}" for c in seen),
            reads=len(self.codes_seen),
        )
        close_graded_window(self.logger)
        self.chk.finish()
