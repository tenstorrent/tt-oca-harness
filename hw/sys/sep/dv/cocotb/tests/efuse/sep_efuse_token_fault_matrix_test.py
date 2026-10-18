# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Token comparator faults on each copy, sticky flags, no write-one-to-clear, reset
clear, common-mode flips and the digest latch freeze.

RAND-REP. no_cpu, real fuse sense. The image is TEST_DEV with the RMA digests of
``TOKEN_T1`` and ``TOKEN_T2``, ``TRANSIENT_RMA_EN`` at 0 and a seed-drawn
disable-vector pair (``env/sep_efuse_plan.py``, ``plan_token_fault``; the pre-sim
hook stages the same image). The seed draws one fault cell per channel (kind,
comparator copy and, on an RMA channel, the held phase), the order of the eight
cells and every token word-write order.

Fault cell (one per channel): a collapsed pair or a disagreeing copy, injected
while the held result is non-Idle, forces ``0x3f``, sets the channel flag of
``TOKEN_MATCH_FAULT`` and the PIC source 40 request, and never raises
``security_disable_o``. A retry with the token of the opposite verdict returns
that verdict while the flag and the request stay set; a write of 1 to each flag
clears nothing; a cold reset clears both (``hw/sys/sep/doc/token_processing.adoc``,
sections Matching Logic Countermeasures and Token Submission;
``hw/ip/efuse/regs/gen/adoc/efuse_mmr.adoc``, ``TOKEN_MATCH_FAULT``;
``hw/sys/sep/doc/interrupts.adoc``, row Token match fault). The comparator rail
taps show the injected kind on the copy of the cell only (hook control).

Common-mode cells (RMA_CHIPLET, held Match and held Mismatch): a unanimous legal
flip inverts the held result with no flag and no request.

Freeze cells (each channel): with the test enable at the digest latch, the
retained digest and its valid bit keep their values through a token operation;
after the release the same token replaces the digest with the value it gave
without the freeze. The comparison is relative, because the specification states
no latch layout. No result code is graded under the freeze.

Checkers: CHK-BIND, CHK-FAULT-CELL, CHK-FAULT-STICKY, CHK-FAULT-NO-W1C,
CHK-FAULT-RESET, CHK-LATCH-FREEZE. A common-mode cell logs the N/A line of the
three fault-only checkers. A failing hook control logs ``CHK-HOOK FAIL`` and ends
the leaf.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, NextTimeStep, ReadOnly, RisingEdge
from env.sep_axi_agent import SepAxiOp
from env.sep_chk_log import SepChkLog
from env.sep_efuse_plan import (
    CH_CHIPLET,
    CH_SEC_DIS,
    CH_SIP,
    CODE_ERROR,
    CODE_MATCH,
    CODE_MISMATCH,
    RIGHT_TOKEN,
    T_TOKEN_FAULT,
    TOKEN_ARRAY_ADDR,
    TOKEN_MATCH_FAULT_ADDR,
    TOKEN_OTHER,
    TOKEN_T1,
    TOKEN_T2,
    TOKEN_ZERO,
    plan,
    poll_code,
    token_go,
    token_go_op,
    token_words,
    write_token,
)
from env.sep_efuse_test_lib import SepEfuseFd, chk_bind, hook_fail, sig_bits
from env.sep_fcov_gate import close_graded_window, open_graded_window
from sep_base_test import sep_base_test
from sep_reg_meta import EFUSE_MMR
from seq_lib.sep_efuse_rma_token_seq import (
    TOKEN_CMP_INJECT_COLLAPSE,
    TOKEN_CMP_INJECT_COMMON,
    TOKEN_CMP_INJECT_COMMON_MATCH,
    TOKEN_CMP_INJECT_DISAGREE,
    TOKEN_CMP_INJECT_OFF,
    TOKEN_CMP_SEL_CHIPLET,
    TOKEN_CMP_SEL_SEC,
    TOKEN_CMP_SEL_SIP,
)

_NAME = "sep_efuse_token_fault_matrix_test"
_POLL_READS = 400
# Clocks a go may take until the digest valid bit falls and rises again.
_HASH_BOUND = 4_000
# Freeze window: _FREEZE_MULT x the measured hash time, at least _FREEZE_MIN clocks
# (test parameters).
_FREEZE_MULT = 4
_FREEZE_MIN = 64
# Clocks after a TOKEN_MATCH_FAULT write before the next access (the write-effect
# settle of the coverage sampler is 8 clocks).
_WR_SETTLE = 16
_PIC40 = 39
_W1C_ALL = 0x0001_0101
_CH_NAME = {CH_SIP: "sip", CH_CHIPLET: "chp", CH_SEC_DIS: "sdis"}
_CH_INDEX = {CH_SIP: 0, CH_CHIPLET: 1, CH_SEC_DIS: 2}
_CMP_SEL = {
    CH_SIP: TOKEN_CMP_SEL_SIP,
    CH_CHIPLET: TOKEN_CMP_SEL_CHIPLET,
    CH_SEC_DIS: TOKEN_CMP_SEL_SEC,
}
_FAULT_BIT = {
    CH_SIP: EFUSE_MMR.field_mask("TOKEN_MATCH_FAULT", "rma_sip_token_fault"),
    CH_CHIPLET: EFUSE_MMR.field_mask("TOKEN_MATCH_FAULT", "rma_chiplet_token_fault"),
    CH_SEC_DIS: EFUSE_MMR.field_mask("TOKEN_MATCH_FAULT", "secure_disable_token_fault"),
}
_FAULT_MASK = _FAULT_BIT[CH_SIP] | _FAULT_BIT[CH_CHIPLET] | _FAULT_BIT[CH_SEC_DIS]
# Digest latch probes and test-enable inject of each channel (tb_top).
_LATCH = {
    CH_SIP: ("token_digest_sticky_o", "token_digest_valid_o", "token_digest_test_en_o"),
    CH_CHIPLET: (
        "token_digest_chiplet_sticky_o",
        "token_digest_chiplet_valid_o",
        "token_digest_chiplet_test_en_o",
    ),
    CH_SEC_DIS: (
        "token_digest_sdis_sticky_o",
        "token_digest_sdis_valid_o",
        "token_digest_sdis_test_en_o",
    ),
}
_TE_INJECT = {
    CH_SIP: "token_digest_test_en_inject_i",
    CH_CHIPLET: "token_digest_chiplet_test_en_inject_i",
    CH_SEC_DIS: "token_digest_sdis_test_en_inject_i",
}
# Token B of a freeze cell: a mismatch token of the channel, other than TOKEN_OTHER.
_FREEZE_B = {CH_SIP: TOKEN_T2, CH_CHIPLET: TOKEN_T1, CH_SEC_DIS: TOKEN_T1}
# Cell label of the plan -> (kind, channel).
_CELLS = {
    "fault_sip": ("fault", CH_SIP),
    "fault_chiplet": ("fault", CH_CHIPLET),
    "fault_sec_dis": ("fault", CH_SEC_DIS),
    "common_match": ("cm_match", CH_CHIPLET),
    "common_mismatch": ("cm_mismatch", CH_CHIPLET),
    "freeze_sip": ("freeze", CH_SIP),
    "freeze_chiplet": ("freeze", CH_CHIPLET),
    "freeze_sec_dis": ("freeze", CH_SEC_DIS),
}


def _pair(p: int, n: int, ch: str, copy: int) -> tuple[int, int]:
    i = 3 * _CH_INDEX[ch] + copy
    return (p >> i) & 1, (n >> i) & 1


def _rail_ok(kind: str, copy: int, pairs: list[tuple[int, int]]) -> tuple[bool, int | None]:
    """Hook control of a collapse or disagree cell; returns (ok, odd copy seen).

    Collapse: the copy of the cell has p == n and the other two copies hold legal
    pairs. Disagree: every copy holds a legal pair and the copy of the cell is the
    minority copy; the copy-0 cell expects copy 0 at Mismatch (0, 1) and copies 1
    and 2 at Match (1, 0).
    """
    legal = [p != n for p, n in pairs]
    if kind == "collapse":
        collapsed = [i for i in range(3) if not legal[i]]
        odd = collapsed[0] if len(collapsed) == 1 else None
        return odd == copy, odd
    if not all(legal):
        return False, None
    odd = None
    for i in range(3):
        others = [pairs[j] for j in range(3) if j != i]
        if others[0] == others[1] and pairs[i] != others[0]:
            odd = i
    ok = odd == copy
    if copy == 0:
        ok = ok and pairs == [(0, 1), (1, 0), (1, 0)]
    return ok, odd


@pyuvm.test()
class sep_efuse_token_fault_matrix_test(sep_base_test):
    """Comparator copy faults, common-mode flips and the digest latch freeze."""

    required_evidence = (
        "CHK-BIND",
        "CHK-FAULT-CELL",
        "CHK-FAULT-STICKY",
        "CHK-FAULT-NO-W1C",
        "CHK-FAULT-RESET",
        "CHK-LATCH-FREEZE",
    )

    # ------------------------------------------------------------------ bus

    async def _faults(self) -> int:
        return (await self.fd.rd(TOKEN_MATCH_FAULT_ADDR)) & _FAULT_MASK

    def _pic40(self) -> int:
        return (self.rd(cocotb.top.sep_internal_interrupts_probe_o) >> _PIC40) & 1

    def _sdis(self) -> int:
        return self.rd(cocotb.top.lcc_security_disable_probe_o) & 1

    def _latch(self, ch: str) -> tuple[int | None, int | None, int | None]:
        """(digest, valid, test_en) of the digest latch of ``ch``; None for an X value."""
        dut = cocotb.top
        out = []
        for name in _LATCH[ch]:
            b = sig_bits(getattr(dut, name))
            out.append(int(b, 2) if b and set(b) <= {"0", "1"} else None)
        return out[0], out[1], out[2]

    # ------------------------------------------------------------------ token steps

    async def _watch_hash(self, ch: str) -> int | None:
        """Clocks until the digest valid bit of ``ch`` falls and rises again (a start
        clears digest validity, token_processing.adoc, Token Submission)."""
        dut = cocotb.top
        name = _LATCH[ch][1]
        fell = False
        for n in range(1, _HASH_BOUND + 1):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            v = sig_bits(getattr(dut, name))
            if v != "1":
                fell = True
            elif fell:
                return n
        return None

    async def _present_settled(self, ch: str, token: int, label: str) -> tuple[int | None, int]:
        """Write ``token`` to ``ch``, go, wait until the new digest is valid, then poll.

        Returns (code, hash clocks). The valid watcher starts before the go, so the
        poll reads the result of this go and not a code held from an earlier one.
        """
        order = self.plan.draw.word_order(label)
        await write_token(self.fd.wr, ch, token, order)
        watch = cocotb.start_soon(self._watch_hash(ch))
        await token_go(self.fd.wr, ch)
        clocks = await watch
        await NextTimeStep()
        if clocks is None:
            return None, _HASH_BOUND
        code, _n = await poll_code(self.fd.rd, ch, max_reads=_POLL_READS)
        return code, clocks

    async def _present_until(self, ch: str, token: int, until: int, label: str) -> int | None:
        """Write ``token``, go, poll until ``until``; the code before the go differs."""
        order = self.plan.draw.word_order(label)
        await write_token(self.fd.wr, ch, token, order)
        await token_go(self.fd.wr, ch)
        code, _n = await poll_code(self.fd.rd, ch, max_reads=_POLL_READS, until=until)
        return code

    async def _end_match(self, ch: str, label: str) -> None:
        """A channel that holds a Match takes TOKEN_OTHER, a go and a poll (0x2a)."""
        if await self.fd.match(ch) == CODE_MATCH:
            code = await self._present_until(ch, TOKEN_OTHER, CODE_MISMATCH, label)
            if code != CODE_MISMATCH:
                raise AssertionError(f"{label}: mismatch go on {ch} read {code}, want 0x2a")

    async def _sec_dis_control(self, label: str) -> None:
        """SEC_DIS match then mismatch before a cell that uses the SEC_DIS channel.

        The match must raise security_disable_o (the revision-enable assumption and
        the control of every "never" check on it); the mismatch drops it.
        """
        close_graded_window(self.logger)
        code = await self._present_until(CH_SEC_DIS, TOKEN_ZERO, CODE_MATCH, f"{label}.zero")
        await ClockCycles(cocotb.top.clk_i, 2)
        sdis = self._sdis()
        if code != CODE_MATCH or sdis != 1:
            hook_fail(self.chk, reason="sec_dis_match", code=code, secdis=sdis)
        self.sdis_ctl_seen = True
        code = await self._present_until(CH_SEC_DIS, TOKEN_OTHER, CODE_MISMATCH, f"{label}.other")
        await ClockCycles(cocotb.top.clk_i, 2)
        sdis = self._sdis()
        if code != CODE_MISMATCH or sdis != 0:
            hook_fail(self.chk, reason="sec_dis_drop", code=code, secdis=sdis)
        open_graded_window(_NAME, self.logger)

    def _drive_inject(self, ch: str, pattern: int, copy: int) -> None:
        dut = cocotb.top
        dut.token_cmp_fault_sel_i.value = _CMP_SEL[ch]
        dut.token_cmp_fault_copy_i.value = copy
        dut.token_cmp_fault_inject_i.value = pattern

    def _release_inject(self) -> None:
        dut = cocotb.top
        dut.token_cmp_fault_inject_i.value = TOKEN_CMP_INJECT_OFF
        dut.token_cmp_fault_sel_i.value = 0
        dut.token_cmp_fault_copy_i.value = 0

    async def _sdis_watch(self, stop: list[bool], seen: list[int]) -> None:
        """Record every clock on which security_disable_o is 1 until ``stop[0]``."""
        dut = cocotb.top
        while not stop[0]:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if sig_bits(dut.lcc_security_disable_probe_o) != "0":
                seen[0] += 1

    # ------------------------------------------------------------------ cells

    async def _fault_like_cell(self, ch: str, kind: str, copy: int | None, held: str) -> None:
        """Collapse, disagree or common-mode cell on ``ch`` (steps 4 to 10)."""
        dut = cocotb.top
        seed = self.leaf_seed
        cm = kind.startswith("cm_")
        label = f"{kind}.{_CH_NAME[ch]}"
        held_token = RIGHT_TOKEN[ch] if held == "match" else TOKEN_OTHER
        held_exp = CODE_MATCH if held == "match" else CODE_MISMATCH
        held_code, _clk = await self._present_settled(ch, held_token, f"{label}.held")
        if held_code != held_exp:
            # The held phase is the first comparison of the cell; a wrong verdict is a
            # staging or setup failure, not a fault response.
            hook_fail(self.chk, reason="held_result", ch=_CH_NAME[ch], held=held_code, exp=held_exp)
        pre_flags = await self._faults()
        await ReadOnly()
        pre_pic = self._pic40()
        pre_sdis = self._sdis()
        await RisingEdge(dut.clk_i)

        if cm:
            pattern = TOKEN_CMP_INJECT_COMMON if held == "match" else TOKEN_CMP_INJECT_COMMON_MATCH
        else:
            pattern = TOKEN_CMP_INJECT_COLLAPSE if kind == "collapse" else TOKEN_CMP_INJECT_DISAGREE
        stop = [False]
        sdis_seen = [0]
        watch = cocotb.start_soon(self._sdis_watch(stop, sdis_seen))
        self._drive_inject(ch, pattern, copy or 0)
        await ClockCycles(dut.clk_i, 3)
        await ReadOnly()
        p_rail = int(sig_bits(dut.token_cmp_match_p_o), 2)
        n_rail = int(sig_bits(dut.token_cmp_match_n_o), 2)
        pairs = [_pair(p_rail, n_rail, ch, i) for i in range(3)]
        rail_copy: int | None = None
        if not cm:
            ok_rail, rail_copy = _rail_ok(kind, copy or 0, pairs)
            if not ok_rail:
                await RisingEdge(dut.clk_i)
                self._release_inject()
                hook_fail(
                    self.chk,
                    reason="rail_pattern",
                    ch=_CH_NAME[ch],
                    kind=kind,
                    copy=copy,
                    rails=",".join(f"{p}{n}" for p, n in pairs),
                )
        await RisingEdge(dut.clk_i)

        res = held_code
        for _ in range(_POLL_READS):
            res = await self.fd.match(ch)
            if res != held_code:
                break
        flags = await self._faults()
        await ReadOnly()
        pic = self._pic40()
        sdis = self._sdis()
        await RisingEdge(dut.clk_i)

        if cm:
            exp = CODE_MISMATCH if held == "match" else CODE_MATCH
            exp_flags = 0
            exp_pic = 0
        else:
            exp = CODE_ERROR
            exp_flags = _FAULT_BIT[ch]
            exp_pic = 1
        others = flags & ~_FAULT_BIT[ch] & _FAULT_MASK
        stop[0] = True
        await watch
        await NextTimeStep()
        self.chk.ok(
            "FAULT-CELL",
            pre_flags == 0
            and pre_pic == 0
            and pre_sdis == 0
            and res == exp
            and flags == exp_flags
            and pic == exp_pic
            and sdis == 0
            and sdis_seen[0] == 0,
            ch=_CH_NAME[ch],
            kind=kind,
            copy="na" if copy is None else copy,
            rail_copy="na" if rail_copy is None else rail_copy,
            role="new",
            held=f"0x{held_code:02x}",
            res=f"0x{res:02x}",
            exp=f"0x{exp:02x}",
            flags=f"0x{flags:x}",
            exp_flags=f"0x{exp_flags:x}",
            pic40=pic,
            secdis=sdis,
            secdis_clocks_high=sdis_seen[0],
            others=f"0x{others:x}",
            pre_flags=f"0x{pre_flags:x}",
            pre_pic40=pre_pic,
            rails=",".join(f"{p}{n}" for p, n in pairs),
        )

        self._release_inject()
        await ClockCycles(dut.clk_i, 3)
        if cm:
            for chk in ("FAULT-STICKY", "FAULT-NO-W1C", "FAULT-RESET"):
                self.logger.info("CHK-%s N/A seed=%d kind=%s", chk, seed, kind)
            await self._end_match(ch, f"{label}.end")
            return

        pre_retry = await self.fd.match(ch)
        if held == "match":
            retry_token, retry_exp = TOKEN_OTHER, CODE_MISMATCH
        else:
            retry_token, retry_exp = RIGHT_TOKEN[ch], CODE_MATCH
        retry = await self._present_until(ch, retry_token, retry_exp, f"{label}.retry")
        flags_r = await self._faults()
        await ReadOnly()
        pic_r = self._pic40()
        await RisingEdge(dut.clk_i)
        self.chk.ok(
            "FAULT-STICKY",
            retry == retry_exp and flags_r == _FAULT_BIT[ch] and pic_r == 1 and flags == exp_flags,
            held=f"0x{held_code:02x}",
            pre_retry=f"0x{pre_retry:02x}",
            retry_exp=f"0x{retry_exp:02x}",
            retry_res="none" if retry is None else f"0x{retry:02x}",
            flags=f"0x{flags_r:x}",
            pic40=pic_r,
        )

        flags_before = flags_r
        await self.fd.access(
            SepAxiOp.WRITE, TOKEN_MATCH_FAULT_ADDR, _W1C_ALL, unverified_write=True
        )
        await ClockCycles(dut.clk_i, _WR_SETTLE)
        flags_w = await self._faults()
        await ReadOnly()
        pic_w = self._pic40()
        await RisingEdge(dut.clk_i)
        self.chk.ok(
            "FAULT-NO-W1C",
            flags_before & _FAULT_BIT[ch] and flags_w == flags_before and pic_w == 1,
            wr=f"0x{_W1C_ALL:x}",
            flags_before=f"0x{flags_before:x}",
            flags=f"0x{flags_w:x}",
            pic40=pic_w,
        )

        await self._end_match(ch, f"{label}.end")
        await self.pulse_rst_ni()
        flags_z = await self._faults()
        await ReadOnly()
        pic_z = self._pic40()
        await RisingEdge(dut.clk_i)
        words = [await self.fd.rd(a) for a in TOKEN_ARRAY_ADDR[ch]]
        self.chk.obs(
            "FAULT-RESET-WORDS",
            ch=_CH_NAME[ch],
            words=",".join(f"0x{w:08x}" for w in words),
        )
        self.chk.ok(
            "FAULT-RESET",
            flags_z == 0 and pic_z == 0 and flags_w == _FAULT_BIT[ch] and pic_w == 1,
            flags=f"0x{flags_z:x}",
            pic40=pic_z,
            words_logged=1,
            pre_reset_flags=f"0x{flags_w:x}",
            pre_reset_pic40=pic_w,
        )

    async def _freeze_cell(self, ch: str) -> None:
        """Freeze cell on ``ch`` (steps 11 to 13)."""
        dut = cocotb.top
        label = f"freeze.{_CH_NAME[ch]}"
        tok_b = _FREEZE_B[ch]
        code_b, hash_b = await self._present_settled(ch, tok_b, f"{label}.b")
        await ReadOnly()
        dig_b, val_b, _te = self._latch(ch)
        await RisingEdge(dut.clk_i)
        code_a, hash_a = await self._present_settled(ch, TOKEN_OTHER, f"{label}.a")
        await ReadOnly()
        dig_a, val_a, _te = self._latch(ch)
        await RisingEdge(dut.clk_i)
        window = max(_FREEZE_MULT * max(hash_a, hash_b), _FREEZE_MIN)
        self.chk.obs(
            "FREEZE-REF",
            ch=_CH_NAME[ch],
            code_b=code_b,
            code_a=code_a,
            hash_clocks=f"{hash_b},{hash_a}",
            window=window,
        )
        if val_b != 1 or val_a != 1 or dig_a is None or dig_b is None or dig_a == dig_b:
            hook_fail(
                self.chk,
                reason="latch_reference",
                ch=_CH_NAME[ch],
                valid_b=val_b,
                valid_a=val_a,
                differ=int(dig_a != dig_b),
            )

        getattr(dut, _TE_INJECT[ch]).value = 1
        await ClockCycles(dut.clk_i, 2)
        await ReadOnly()
        _d, _v, te = self._latch(ch)
        await RisingEdge(dut.clk_i)
        if te != 1:
            getattr(dut, _TE_INJECT[ch]).value = 0
            hook_fail(self.chk, reason="test_enable", ch=_CH_NAME[ch], test_en=te)
        order = self.plan.draw.word_order(f"{label}.frozen")
        resp_ok = True
        for addr, word in zip(
            [TOKEN_ARRAY_ADDR[ch][k] for k in order], [token_words(tok_b)[k] for k in order]
        ):
            seq = await self.fd.access(SepAxiOp.WRITE, addr, word)
            resp_ok &= bool(seq.resp_ok)
        go = await self.fd.access(SepAxiOp.WRITE, *token_go_op(ch))
        resp_ok &= bool(go.resp_ok)
        changed = 0
        for _ in range(window):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            d, v, _te = self._latch(ch)
            if d != dig_a or v != val_a:
                changed += 1
        await RisingEdge(dut.clk_i)
        dig_f, val_f, _te = self._latch(ch)
        readback = [await self.fd.rd(a) for a in TOKEN_ARRAY_ADDR[ch]]
        rb_ok = readback == token_words(tok_b)

        getattr(dut, _TE_INJECT[ch]).value = 0
        await ClockCycles(dut.clk_i, 2)
        await token_go(self.fd.wr, ch)
        dig_r = None
        for _ in range(window):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            d, v, _te = self._latch(ch)
            if v == 1 and d is not None and d != dig_a:
                dig_r = d
                break
        await RisingEdge(dut.clk_i)
        # The release go hashes token B again, so the channel holds a Mismatch.
        await poll_code(self.fd.rd, ch, max_reads=_POLL_READS)
        self.chk.ok(
            "LATCH-FREEZE",
            changed == 0
            and dig_f == dig_a
            and val_f == val_a
            and resp_ok
            and rb_ok
            and dig_r == dig_b,
            ch=_CH_NAME[ch],
            role="control" if ch == CH_SIP else "new",
            digest_before=f"0x{dig_a:064x}",
            digest_frozen="x" if dig_f is None else f"0x{dig_f:064x}",
            valid_before=val_a,
            valid_frozen="x" if val_f is None else val_f,
            digest_after_release="none" if dig_r is None else f"0x{dig_r:064x}",
            digest_b=f"0x{dig_b:064x}",
            frozen_changes=changed,
            window=window,
            resp_ok=int(resp_ok),
            readback_b=int(rb_ok),
        )

    # ------------------------------------------------------------------ scenario

    async def run_scenario(self) -> None:
        dut = cocotb.top
        seed = self.random_seed()
        self.leaf_seed = seed
        p = plan(T_TOKEN_FAULT, seed)
        self.plan = p
        for line in p.log_lines():
            self.logger.info("%s", line)
        self.chk = SepChkLog(self, _NAME, seed)
        self.fd = SepEfuseFd(self)
        if p.setup_fail:
            raise AssertionError(f"SETUP FAIL seed={seed} reason={p.setup_fail}")
        self.logger.info("EVIDENCE-REQUIRED seed=%d ids=%s", seed, ",".join(self.required_evidence))
        faults = p.leg["faults"]
        order = p.leg["cell_order"]

        await chk_bind(self.chk)
        self.sdis_ctl_seen = False

        self.write_efuse_image(p.image)
        await self.bring_up_no_cpu()
        self._set_pin(dut, "test_en_strap_i", 0)
        self._release_inject()
        open_graded_window(_NAME, self.logger)

        for cell in order:
            kind, ch = _CELLS[cell]
            if ch == CH_SEC_DIS:
                await self._sec_dis_control(f"ctl.{cell}")
            if kind == "fault":
                f = faults[ch]
                await self._fault_like_cell(ch, f["kind"], f["copy"], f["held"])
            elif kind == "freeze":
                await self._freeze_cell(ch)
            else:
                held = kind.removeprefix("cm_")
                await self._fault_like_cell(ch, kind, None, held)

        close_graded_window(self.logger)
        if not self.sdis_ctl_seen:
            hook_fail(self.chk, reason="no_sec_dis_control")
        self.chk.finish()
