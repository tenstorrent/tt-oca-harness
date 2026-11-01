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

Source exclusivity (each fault cell): at every rise of vector bit 39 (PIC source
40) after the inject, every other bit of ``sep_internal_interrupts`` keeps its
value of one clock before (``hw/sys/sep/doc/interrupts.adoc:22-23`` bit ``i`` is
PIC source ``i + 1``; ``:33-34`` slots 1-43 are individually assigned; ``:219-224``
source 40 is the OR of the three sticky ``TOKEN_MATCH_FAULT`` bits). The six bits
with an unstated idle level are not compared (``env/sep_bit_watch.pic_vector_watch``).
The token fault raises no other source, so no bit is exempt for the same clock. A
cell with no rise of bit 39 fails.

Checkers: CHK-BIND, CHK-FAULT-CELL, CHK-SRC40-EXCL, CHK-FAULT-STICKY,
CHK-FAULT-NO-W1C, CHK-FAULT-RESET, CHK-LATCH-FREEZE. Controls: CTRL-SEC-DIS-MATCH
(code ``0x15`` and ``security_disable_o`` 1) and CTRL-SEC-DIS-DROP (code ``0x2a``
and ``security_disable_o`` 0), before each cell that uses the SEC_DIS channel. A
common-mode cell logs the N/A line of the three fault-only checkers. A failing hook control logs
``CHK-HOOK FAIL`` and ends the leaf.

FCOV: the graded window is open only over a graded step, from right before its DUT
step to its last check: the inject of a fault or common-mode cell to CHK-FAULT-CELL
and CHK-SRC40-EXCL; the retry to CHK-FAULT-STICKY; the write of ones to
CHK-FAULT-NO-W1C; the cold reset to CHK-FAULT-RESET; the test-enable inject of a
freeze cell to CHK-LATCH-FREEZE. Held phases, the SEC_DIS control, inject release,
the Match clean-up and the token array log read run with the window closed. Every
legal sample of ``sep_token_fault_cg`` and the error sample of
``sep_token_channel_cg.cp_code`` is held with the tag of its step
(``set_ef_hold_tag``) and samples only when the leaf writes that tag to the pass
label (``set_ef_hold_pass``) after every check of the step passed. An illegal value
samples at the event. ``sep_sec_dis_activation_cg.x_verdict_out`` (error) and
``sep_pic_source_map_cg.cp_src_exclusive_other`` (s40) sample at the event: each
compare is the compare of its check. The first FAIL closes the window and keeps it
closed for the rest of the leaf.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, NextTimeStep, ReadOnly, RisingEdge
from env.sep_axi_agent import SepAxiOp
from env.sep_bit_watch import SepVecWatch, VecMark, VecWatchNoRiseError, pic_vector_watch
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
from env.sep_fabric_common import RESP_NAME
from env.sep_fcov_gate import (
    close_graded_window,
    open_graded_window,
    set_ef_hold_pass,
    set_ef_hold_tag,
)
from env.sep_spec_tables import agg_from_pic
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
# Vector bit of PIC source 40, Token match fault (hw/sys/sep/doc/interrupts.adoc:22-23,
# :219-220).
_PIC40 = agg_from_pic("Token match fault")
# Clocks a step tag stays on the pass label.
_PASS_HOLD = 2
# Graded steps of one cell; the hold tag of a step is cell index * 4 + step + 1.
_STEP_CELL = 0
_STEP_STICKY = 1
_STEP_NO_W1C = 2
_STEP_RESET = 3
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
# A write of 1 to each flag of TOKEN_MATCH_FAULT.
_W1C_ALL = _FAULT_MASK
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
        "CHK-SRC40-EXCL",
        "CHK-FAULT-STICKY",
        "CHK-FAULT-NO-W1C",
        "CHK-FAULT-RESET",
        "CHK-LATCH-FREEZE",
    )

    # ------------------------------------------------------------------ grading

    def _grade(self, name: str, cond: bool, **fields) -> bool:
        """Grade one check; the first FAIL closes the graded window for the rest of the leaf."""
        if not cond:
            close_graded_window(self.logger)
            self.graded_fail = True
        return self.chk.ok(name, cond, **fields)

    async def _open_step(self, step: int) -> int:
        """At the next ``clk_i`` edge, open the graded window and the hold tag of ``step``.

        Returns the tag of ``step`` of the current cell. After a FAIL the window
        stays closed and the tag stays 0.
        """
        await RisingEdge(cocotb.top.clk_i)
        tag = 4 * self.cell_idx + step + 1
        if not self.graded_fail:
            set_ef_hold_tag(tag, self.logger)
            open_graded_window(_NAME, self.logger)
        return tag

    async def _close_step(self, tag: int, ok: bool) -> None:
        """End step ``tag``: its held samples sample only when ``ok`` and no FAIL so far.

        The pass label holds the tag for ``_PASS_HOLD`` clocks with the window still
        open, then the window closes.
        """
        await RisingEdge(cocotb.top.clk_i)
        set_ef_hold_tag(0, self.logger)
        if ok and not self.graded_fail:
            set_ef_hold_pass(tag, self.logger)
            await ClockCycles(cocotb.top.clk_i, _PASS_HOLD)
            set_ef_hold_pass(0, self.logger)
        close_graded_window(self.logger)

    def _check_src40(
        self, vec: SepVecWatch, mark: VecMark, ch: str, kind: str, copy: int | None
    ) -> bool:
        """CHK-SRC40-EXCL: at each rise of bit 39 after ``mark`` every other bit keeps its value.

        The compared bits are the whole vector except bit 39 and the six bits with
        an unstated idle level; no bit is exempt for the same clock. A cell with no
        rise of bit 39 fails.
        """
        try:
            rises = vec.rises_since(mark, "s40")
            smears = vec.smears_since(mark, "s40")
        except VecWatchNoRiseError:
            rises, smears = [], []
        first = rises[0] if rises else None
        moved = 0
        for _clk, m in smears:
            moved |= m
        return self._grade(
            "SRC40-EXCL",
            bool(rises) and not smears,
            ch=_CH_NAME[ch],
            kind=kind,
            copy="na" if copy is None else copy,
            rises=len(rises),
            rise_clk=",".join(str(r.clk) for r in rises) or "none",
            moved=f"0x{moved:011x}",
            smear_clk=",".join(str(c) for c, _m in smears) or "none",
            before="none" if first is None else f"0x{first.before:011x}",
            after="none" if first is None else f"0x{first.after:011x}",
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
        """Write ``token``, go, poll until ``until``.

        A code that already equals ``until`` before the go fails the leaf, so a go
        with no effect cannot pass the poll.
        """
        order = self.plan.draw.word_order(label)
        await write_token(self.fd.wr, ch, token, order)
        pre = await self.fd.match(ch)
        if pre == until:
            hook_fail(
                self.chk,
                reason="code_before_go_equals_until",
                ch=_CH_NAME[ch],
                label=label,
                code=f"0x{pre:02x}",
            )
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
        for name, token, step, want, want_sdis in (
            ("SEC-DIS-MATCH", TOKEN_ZERO, "zero", CODE_MATCH, 1),
            ("SEC-DIS-DROP", TOKEN_OTHER, "other", CODE_MISMATCH, 0),
        ):
            code = await self._present_until(CH_SEC_DIS, token, want, f"{label}.{step}")
            await ClockCycles(cocotb.top.clk_i, 2)
            sdis = self._sdis()
            if not self.chk.ctrl(
                name,
                code == want and sdis == want_sdis,
                label=label,
                code="none" if code is None else f"0x{code:02x}",
                exp=f"0x{want:02x}",
                secdis=sdis,
                exp_secdis=want_sdis,
            ):
                hook_fail(self.chk, reason=name.lower().replace("-", "_"), code=code, secdis=sdis)
            if want_sdis:
                self.sdis_ctl_seen = True

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
        vec = pic_vector_watch({"s40": _PIC40}).start()
        pre_flags = await self._faults()
        await ReadOnly()
        pre_pic = self._pic40()
        pre_sdis = self._sdis()
        await RisingEdge(dut.clk_i)

        tag = await self._open_step(_STEP_CELL)
        mark = vec.mark()
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
        cell_ok = self._grade(
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
        if not cm:
            cell_ok = self._check_src40(vec, mark, ch, kind, copy) and cell_ok
        await vec.stop()
        await self._close_step(tag, cell_ok)

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
        tag = await self._open_step(_STEP_STICKY)
        retry = await self._present_until(ch, retry_token, retry_exp, f"{label}.retry")
        flags_r = await self._faults()
        await ReadOnly()
        pic_r = self._pic40()
        await RisingEdge(dut.clk_i)
        ok = self._grade(
            "FAULT-STICKY",
            retry == retry_exp and flags_r == _FAULT_BIT[ch] and pic_r == 1 and flags == exp_flags,
            held=f"0x{held_code:02x}",
            pre_retry=f"0x{pre_retry:02x}",
            retry_exp=f"0x{retry_exp:02x}",
            retry_res="none" if retry is None else f"0x{retry:02x}",
            flags=f"0x{flags_r:x}",
            pic40=pic_r,
        )
        await self._close_step(tag, ok)

        flags_before = flags_r
        tag = await self._open_step(_STEP_NO_W1C)
        wr = await self.fd.access(
            SepAxiOp.WRITE, TOKEN_MATCH_FAULT_ADDR, _W1C_ALL, unverified_write=True
        )
        # The write must complete and decode: TOKEN_MATCH_FAULT lies inside the
        # decoded extent of the eFuse token registers, and DECERR is the answer past
        # that extent (hw/sys/sep/regs/gen/adoc/memory_map.adoc, eFuse Token
        # Registers row). No document states the in-extent write code, so the code
        # is logged and only DECERR fails.
        wr_done = int(not wr.timed_out)
        wr_resp = RESP_NAME.get(-1 if wr.timed_out else int(wr.resp_code), str(wr.resp_code))
        await ClockCycles(dut.clk_i, _WR_SETTLE)
        flags_w = await self._faults()
        await ReadOnly()
        pic_w = self._pic40()
        await RisingEdge(dut.clk_i)
        ok = self._grade(
            "FAULT-NO-W1C",
            flags_before & _FAULT_BIT[ch]
            and flags_w == flags_before
            and pic_w == 1
            and wr_done
            and wr_resp != "DECERR",
            wr=f"0x{_W1C_ALL:x}",
            wr_done=wr_done,
            wr_resp=wr_resp,
            flags_before=f"0x{flags_before:x}",
            flags=f"0x{flags_w:x}",
            pic40=pic_w,
        )
        await self._close_step(tag, ok)

        await self._end_match(ch, f"{label}.end")
        tag = await self._open_step(_STEP_RESET)
        await self.pulse_rst_ni()
        flags_z = await self._faults()
        await ReadOnly()
        pic_z = self._pic40()
        await RisingEdge(dut.clk_i)
        ok = self._grade(
            "FAULT-RESET",
            flags_z == 0 and pic_z == 0 and flags_w == _FAULT_BIT[ch] and pic_w == 1,
            flags=f"0x{flags_z:x}",
            pic40=pic_z,
            words_logged=1,
            pre_reset_flags=f"0x{flags_w:x}",
            pre_reset_pic40=pic_w,
        )
        await self._close_step(tag, ok)
        words = [await self.fd.rd(a) for a in TOKEN_ARRAY_ADDR[ch]]
        self.chk.obs(
            "FAULT-RESET-WORDS",
            ch=_CH_NAME[ch],
            words=",".join(f"0x{w:08x}" for w in words),
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
        self.chk.info(
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

        tag = await self._open_step(_STEP_CELL)
        await RisingEdge(dut.clk_i)
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
        ok = self._grade(
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
        await self._close_step(tag, ok)

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
        self.graded_fail = False
        self.cell_idx = 0

        self.write_efuse_image(p.image)
        await self.bring_up_no_cpu()
        self._set_pin(dut, "test_en_strap_i", 0)
        self._release_inject()

        try:
            for idx, cell in enumerate(order):
                self.cell_idx = idx
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
        finally:
            set_ef_hold_tag(0, self.logger)
            close_graded_window(self.logger)
        if not self.sdis_ctl_seen:
            hook_fail(self.chk, reason="no_sec_dis_control")
        self.chk.finish()
