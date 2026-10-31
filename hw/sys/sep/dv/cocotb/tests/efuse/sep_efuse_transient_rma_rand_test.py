# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A token match updates the LC_STATE shadow with TRANSIENT_RMA_EN = 1, burns no fuse,
and a program of LC_STATE bit 1 or 2 lands only with its own channel matched.

RAND-REP. no_cpu, real fuse sense. The seed draws one t=0 image: the pair
(TRANSIENT_RMA_EN, start state), the X bit of an RMA start state and the
disable-vector pair (``env/sep_efuse_plan.py``, ``plan_transient_rma``; the
pre-sim hook stages the same image). It also draws the token script, the spare
bit of the window control and every token word-write order.

Leg A (every leaf): each script step presents ``TOKEN_T1`` on RMA_SIP or
``TOKEN_T2`` on RMA_CHIPLET, waits for Match ``0x15`` and a window W, and reads the
``LC_STATE`` shadow and ``FEAT_CTRL``. With the enable at 1 a SIP match sets bit 1
from TEST_DEV and PROD, a CHIPLET match sets bit 2 when bit 1 is set, and INVALID
stays INVALID; with the enable at 0 the shadow never changes
(``hw/sys/sep/doc/otp_fuse_controller.adoc``, section Fuse Fields, rows
``LC_STATE`` and ``TRANSIENT_RMA_EN``; ``hw/sys/sep/doc/token_processing.adoc``,
section Post Token Matching Handling). ``FEAT_CTRL`` follows the profile table
for the new state (``hw/sys/sep/doc/lifecycle_controller.adoc``, section
Per-LC-state Feature Control Profile). The OTP ``LC_STATE`` word stays the staged
word, and no program command reaches the post-guard port during the script. A
cold reset restores the sensed state.

Leg S (enable 1, start TEST_DEV or PROD): an RMA_CHIPLET match is held while
``TOKEN_T1`` matches on RMA_SIP. The chiplet path has priority and needs
RMA_SIP already set, so the SIP match does not fall through: after W the
``LC_STATE`` shadow, its probe and ``FEAT_CTRL`` keep the start state, with both
channels at Match before and after W (``otp_fuse_controller.adoc``, row
``TRANSIENT_RMA_EN``). The script ends both matches. A lone SIP match right
after it lands RMA_SIP without a reset (CHK-TRANSIENT-AFTER-BLOCK): the update
follows each token match (``otp_fuse_controller.adoc:232-238``) and the block
covers only a SIP match made while the chiplet match is held. The DUT keeps the
start state, so this check is expected to fail until the RTL ticket on the
once-per-reset transient update flags is fixed (#3527). A cold reset
follows; the twin then presents the
SIP match alone from the sensed start state and lands RMA_SIP, and a second
cold reset restores the sensed state. The lone SIP match and the cold reset
after it run with the graded coverage window closed.

Every ``LC_STATE`` shadow read is graded as the whole 32-bit word: ``{~r, r}``
in bits [7:0] and 0 in the reserved bits [31:8]
(``hw/sys/sep/regs/gen/adoc/blocks/sep_efuse_map.adoc``, register ``LC_STATE``).

Leg B (TEST_DEV image with the enable at 0): a program of ``LC_STATE`` bit 1 with
only RMA_CHIPLET matched changes no bank bit and issues no program command; the
same program with RMA_SIP matched lands. A program of bit 2 with only RMA_SIP
matched is refused (a control of the open refusal, ``role=control``); with
RMA_CHIPLET matched it lands.

Last step, starts PROD and TEST_DEV without leg B: a program of bit 2 with RMA_CHIPLET
matched (CTRL-PROG-LC-ORDER-MATCH) and bit 1 clear is logged as OBS-PROG-LC-ORDER
(the OTP word, the program commands within W and the status bits), not graded:
the specification texts disagree on whether that program needs bit 1 in the
pre-write state. It runs with the graded coverage window closed. After each resense the shadow byte is
``{~r, r}`` with r the raw nibble OR the programmed bit (``otp_fuse_controller.adoc``,
sections Fuse Programming and RMA Authorization, Shadow Register Updates and
Test-Mode Protection). Every match and mismatch go of leg B must reach its code
(``0x15`` or ``0x2a``) inside the bounded poll; a go that does not fails
CHK-PROG-LC and ends the leaf before the program it sets up is graded.

Time: the window W is a multiple of the sense time the leaf measures, at least
256 clocks. Every program wait lasts the full W with no early exit. The window
control programs a free spare bit and must land inside W, so a "never" wait of
W is as long as a landing wait. Every match ends with a mismatch go on its
channel before the next cold reset. In leg A a CHIPLET match also ends before
a later SIP step; leg S holds it on purpose.

Checkers: CHK-TRANSIENT, CHK-TRANSIENT-NOBURN, CHK-TRANSIENT-RESET (every
leaf); CHK-TRANSIENT-SIMUL (leg S); CHK-PROG-LC (leg B). Controls: CTRL-WINDOW-CTL,
CTRL-TRANSIENT-EN (the sensed ``TRANSIENT_RMA_EN`` shadow equals the staged
enable, every leaf), CTRL-PROG-LC-ORDER-MATCH. A failing hook control
logs ``CHK-HOOK FAIL`` and ends the leaf. A match that does not end with its
Mismatch go before a cold reset ends the leaf at that control or check: the
next sense would load the transient state, and the graded failure is the
leaf verdict.

FCOV (owner ``sep_efuse_transient_rma_rand_test``): the graded window opens
after the window control and stays open to the end of the leaf, except for the
lone SIP match of leg S and its cold reset and the bit-2 control program of
leg B. The sampler holds each legal outcome of ``x_transient``,
``cp_simultaneous_match``, ``cp_reset_restore`` and ``x_lc_prog_gate`` as
pending, and samples it only on the rise of its bit of the pass label
``tr_pass``, which the leaf writes after the check that grades that outcome
passes (CHK-TRANSIENT, CHK-TRANSIENT-SIMUL, CHK-TRANSIENT-RESET, CHK-PROG-LC).
The first failed check or control closes the window for the rest of the leaf,
which drops every pending outcome.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env.sep_chk_log import SepChkLog
from env.sep_efuse_bank_watch import SepShimCmdMonitor
from env.sep_efuse_image import LC_FIELD_MASK, LC_RAW_WIDTH, lc_encode
from env.sep_efuse_plan import (
    CH_CHIPLET,
    CH_SIP,
    CODE_MATCH,
    CODE_MISMATCH,
    NARROW_USED,
    PROGRAM_CTRL_ADDR,
    RIGHT_TOKEN,
    ST_PROD,
    ST_RMA_SIP,
    ST_TEST_DEV,
    STATUS_ADDR,
    T_TRANSIENT,
    TOKEN_OTHER,
    bit_address,
    feat_ctrl_profile,
    field_word,
    lc_state_class,
    plan,
    poll_code,
    program_ctrl_word,
    shadow_addr,
    token_go,
    write_token,
)
from env.sep_efuse_test_lib import (
    SenseClock,
    SepEfuseFd,
    direct_word,
    hook_fail,
    log_line,
    probe_word,
    set_shadow_golden,
    shadow_word,
    sig_bits,
)
from env.sep_fcov_gate import (
    TR_PASS_PROG_LC,
    TR_PASS_RESET,
    TR_PASS_SIMUL,
    TR_PASS_TRANSIENT,
    close_graded_window,
    open_graded_window,
    set_transient_pass,
)
from sep_base_test import sep_base_test
from sep_reg_meta import EFUSE_INTERFACE_CTRL

_NAME = "sep_efuse_transient_rma_rand_test"
# Test parameters (the contract leaves them open). W = _W_MULT x the measured sense
# time, and never below _W_MIN (the x_transient outcome window of the sampler).
_W_MULT = 2
_W_MIN = 256
_SENSE_BOUND = 100_000
_POLL_READS = 400
_LC_WORD = field_word("LC_STATE")
_EN_MASK = NARROW_USED["TRANSIENT_RMA_EN"]
# Raw LC_STATE bits a token match sets (otp_fuse_controller.adoc:216-224;
# lifecycle_controller.adoc:88-90): bit 1 with an RMA_SIP match, bit 2 with an
# RMA_CHIPLET match from a state with bit 1 set.
_LC_SIP_BIT = 1
_LC_CHP_BIT = 2
_LC_RAW_MASK = (1 << LC_RAW_WIDTH) - 1
_LC_BIT1 = bit_address("LC_STATE", 0, _LC_SIP_BIT)
_LC_BIT2 = bit_address("LC_STATE", 0, _LC_CHP_BIT)
_PG = "EFUSE_PROGRAM_CTRL"
_PG_BUSY = EFUSE_INTERFACE_CTRL.field_mask(_PG, "program_busy")
_PG_DONE = EFUSE_INTERFACE_CTRL.field_mask(_PG, "program_done")
_PG_STATUS = EFUSE_INTERFACE_CTRL.field_mask(_PG, "program_status")
_PG_CTL = (
    EFUSE_INTERFACE_CTRL.field_mask(_PG, "efuse_addr")
    | EFUSE_INTERFACE_CTRL.field_mask(_PG, "efuse_data")
    | EFUSE_INTERFACE_CTRL.field_mask(_PG, "efuse_program_go")
    | EFUSE_INTERFACE_CTRL.field_mask(_PG, "efuse_program_read_back")
    | EFUSE_INTERFACE_CTRL.field_mask(_PG, "program_enable")
)
_ST = "EFUSE_INTERFACE_CTRL_STATUS"
_REQ_ERR = EFUSE_INTERFACE_CTRL.field_mask(_ST, "efuse_req_error")
_REQ_ERR_CLR = EFUSE_INTERFACE_CTRL.field_mask(_ST, "efuse_req_error_clear")
_CH_NAME = {CH_SIP: "sip", CH_CHIPLET: "chp"}
_SCRIPT_CH = {"SIP": CH_SIP, "CHIPLET": CH_CHIPLET}
# Leg S runs from the two start states a SIP match updates with the enable at 1.
_LEG_S_STARTS = ("TEST_DEV", "PROD")


def _hex2(code: int | None) -> str:
    return "none" if code is None else f"0x{code:02x}"


def _lc_word(raw: int) -> int:
    """Whole LC_STATE shadow word for raw state ``raw``: ``{~raw, raw}`` in [7:0], 0 in
    the reserved bits [31:8] (``regs/gen/adoc/blocks/sep_efuse_map.adoc:164-165``)."""
    return lc_encode(raw)


def _transient_next(raw: int, ch: str, enable: int) -> int:
    """Raw state after a match on ``ch`` (otp_fuse_controller.adoc, rows LC_STATE and
    TRANSIENT_RMA_EN; token_processing.adoc, Post Token Matching Handling).

    Enable 0: no change. Enable 1: a SIP match sets bit 1 from TEST_DEV and PROD; a
    CHIPLET match sets bit 2 when bit 1 is set (RMA_SIP); every other state, INVALID
    included, keeps its code.
    """
    if not enable:
        return raw
    cls = lc_state_class(raw)
    if ch == CH_SIP and cls in (ST_TEST_DEV, ST_PROD):
        return raw | (1 << _LC_SIP_BIT)
    if ch == CH_CHIPLET and cls == ST_RMA_SIP:
        return raw | (1 << _LC_CHP_BIT)
    return raw


@pyuvm.test()
class sep_efuse_transient_rma_rand_test(sep_base_test):
    """Transient RMA shadow update, no burn, reset restore and the LC_STATE program gate."""

    required_evidence = ("CHK-TRANSIENT", "CHK-TRANSIENT-NOBURN", "CHK-TRANSIENT-RESET")

    # ------------------------------------------------------------------ grading

    def _close_window(self) -> None:
        """Close the graded coverage window for the rest of the leaf."""
        if not self.window_dead:
            close_graded_window(self.logger)
            self.window_dead = True

    def _reopen_window(self) -> None:
        """Reopen the window after an ungraded step, unless a check already failed."""
        if not self.window_dead:
            open_graded_window(_NAME, self.logger)

    async def _label(self, bit: int) -> None:
        """Raise pass label ``bit`` for two clocks, unless a check already failed.

        Call it only after the check that grades the outcome of ``bit`` passed.
        """
        if self.window_dead:
            return
        set_transient_pass(bit, self.logger)
        await ClockCycles(cocotb.top.clk_i, 2)
        set_transient_pass(0, self.logger)

    def _stop_if_held(self, check: str, codes: dict[str, int | None], **fields: object) -> None:
        """End the leaf when a match did not end with its Mismatch go before a cold reset.

        With a match held the next sense loads the transient state, so the
        reset would fail the base post-sense shadow compare before the leaf
        verdict. The FAIL of ``check`` is the verdict instead.
        """
        if all(c == CODE_MISMATCH for c in codes.values()):
            return
        self._grade(
            check,
            False,
            reason="match_held_at_reset",
            end_codes=",".join(f"{k}:{_hex2(v)}" for k, v in codes.items()),
            **fields,
        )
        self.chk.finish()

    def _grade(self, name: str, cond: bool, **fields: object) -> bool:
        """``SepChkLog.ok``; a FAIL closes the window before it is recorded."""
        if not cond:
            self._close_window()
        return self.chk.ok(name, cond, **fields)

    def _ctrl(self, name: str, cond: bool, **fields: object) -> bool:
        """``SepChkLog.ctrl``; a missing control closes the window before it is recorded."""
        if not cond:
            self._close_window()
        return self.chk.ctrl(name, cond, **fields)

    def _grade_transient(
        self,
        step: int | str,
        ch: str,
        code: int | None,
        raw: int,
        got: dict[str, int | None],
        name: str = "TRANSIENT",
    ) -> bool:
        """CHK-<name>: Match code, whole LC_STATE word, its probe and FEAT_CTRL for ``raw``."""
        p = self.plan
        exp_word = _lc_word(raw)
        exp_feat = feat_ctrl_profile(raw, p.sip_dis, p.sys_dis)
        probe_byte = None if got["probe_lc"] is None else got["probe_lc"] & LC_FIELD_MASK
        ok = (
            code == CODE_MATCH
            and got["word"] == exp_word
            and probe_byte == lc_encode(raw)
            and got["feat"] == exp_feat.value
            and got["probe_feat"] == exp_feat.value
        )
        return self._grade(
            name,
            ok,
            en=self.en,
            start=self.start,
            step=step,
            tok=_CH_NAME[ch],
            code=_hex2(code),
            exp_word=f"0x{exp_word:08x}",
            got_word=f"0x{got['word']:08x}",
            probe_byte="x" if probe_byte is None else f"0x{probe_byte:02x}",
            exp_feat=f"0x{exp_feat.value:016x}",
            got_feat=f"0x{got['feat']:016x}",
            probe_feat="x" if got["probe_feat"] is None else f"0x{got['probe_feat']:016x}",
            exp_state=lc_state_class(raw),
            profile=exp_feat.log(),
        )

    def _grade_reset(
        self,
        leg: str,
        codes: dict[str, int | None],
        after: dict[str, int | None],
        updated: bool,
        pre_reset_word: int,
    ) -> bool:
        """CHK-TRANSIENT-RESET: after a cold reset the sense restores the staged state.

        Every match of the leg ended with a Mismatch go before the reset; the whole
        LC_STATE word, its probe, FEAT_CTRL and its probe equal the staged state; and
        when the leg updated the shadow, the byte before the reset differs from the
        staged byte (otp_fuse_controller.adoc:9-11, :232-234).
        """
        p = self.plan
        raw0 = p.lc_raw & _LC_RAW_MASK
        exp_word = _lc_word(raw0)
        staged_byte = lc_encode(raw0)
        staged_feat = feat_ctrl_profile(raw0, p.sip_dis, p.sys_dis)
        probe_byte = None if after["probe_lc"] is None else after["probe_lc"] & LC_FIELD_MASK
        pre_byte = pre_reset_word & LC_FIELD_MASK
        ok = (
            all(c == CODE_MISMATCH for c in codes.values())
            and after["word"] == exp_word
            and probe_byte == staged_byte
            and after["feat"] == staged_feat.value
            and after["probe_feat"] == staged_feat.value
            and (not updated or pre_byte != staged_byte)
        )
        return self._grade(
            "TRANSIENT-RESET",
            ok,
            leg=leg,
            pre_reset_codes=",".join(f"{k}:{_hex2(v)}" for k, v in codes.items()) or "none",
            exp_word=f"0x{exp_word:08x}",
            got_word=f"0x{after['word']:08x}",
            probe_byte="x" if probe_byte is None else f"0x{probe_byte:02x}",
            exp_feat=f"0x{staged_feat.value:016x}",
            got_feat=f"0x{after['feat']:016x}",
            probe_feat="x" if after["probe_feat"] is None else f"0x{after['probe_feat']:016x}",
            updated=int(updated),
            shadow_pre_reset=f"0x{pre_byte:02x}",
        )

    # ------------------------------------------------------------------ steps

    async def _lc_and_feat(self) -> dict[str, int | None]:
        """Frontdoor LC_STATE shadow word and FEAT_CTRL, with both probes."""
        word = await self.fd.rd(shadow_addr("LC_STATE"))
        feat = await self.fd.feat_ctrl()
        await ReadOnly()
        dut = cocotb.top
        probe_lc = probe_word(sig_bits(dut.efuse_shadow_probe_o), _LC_WORD)
        probe_feat_bits = sig_bits(dut.lcc_feat_ctrl_probe_o)
        probe_feat = int(probe_feat_bits, 2) if set(probe_feat_bits) <= {"0", "1"} else None
        await RisingEdge(dut.clk_i)
        return {"word": word, "feat": feat, "probe_lc": probe_lc, "probe_feat": probe_feat}

    async def _present(self, ch: str, token: int, until: int, label: str) -> int | None:
        """Write ``token`` to ``ch`` in a drawn word order, go, poll until ``until``.

        Returns the code, or None when the bounded poll ends first. The code before
        every go of this leaf differs from ``until``, so a go that has no effect
        times the poll out.
        """
        order = self.plan.draw.word_order(label)
        await write_token(self.fd.wr, ch, token, order)
        await token_go(self.fd.wr, ch)
        code, _n = await poll_code(self.fd.rd, ch, max_reads=_POLL_READS, until=until)
        return code

    async def _match(self, ch: str, label: str) -> int | None:
        code = await self._present(ch, RIGHT_TOKEN[ch], CODE_MATCH, label)
        if ch not in self.staging_seen:
            # The first Match read of each channel is the control of the digest staging.
            if code != CODE_MATCH:
                self._close_window()
                hook_fail(
                    self.chk,
                    reason="digest_staging",
                    ch=_CH_NAME[ch],
                    code="none" if code is None else code,
                )
            self.staging_seen.add(ch)
        return code

    async def _mismatch(self, ch: str, label: str) -> int | None:
        return await self._present(ch, TOKEN_OTHER, CODE_MISMATCH, label)

    async def _program(self, bit_addr: int) -> dict[str, int]:
        """Program one bit with the full W wait, then read status and the OTP word.

        Two writes: enable, data and address, then the same with the go bit. The
        command record runs from the go write to the end of W. ``program_enable`` is
        dropped before the direct read, so the read interface reaches the bank. A
        refused program sets the sticky ``efuse_req_error``, which holds off every
        later read and program request until software writes
        ``efuse_req_error_clear`` (``efuse_interface_ctrl.adoc``); the flag is
        returned (logged, not graded) and cleared before the direct read. The
        software-written fields of ``EFUSE_PROGRAM_CTRL`` (sw=rw) read back before the
        disable write equal the go write (``go_landed``), so the go reached the
        register even when the program is refused.
        """
        await self.fd.wr(PROGRAM_CTRL_ADDR, program_ctrl_word(bit_addr, go=0))
        mark = self.shim.mark()
        await self.fd.wr(PROGRAM_CTRL_ADDR, program_ctrl_word(bit_addr, go=1))
        await ClockCycles(cocotb.top.clk_i, self.w)
        own = len(self.shim.programs_since(mark, address=bit_addr))
        every = len(self.shim.programs_since(mark))
        status = await self.fd.rd(STATUS_ADDR)
        pctl = await self.fd.rd(PROGRAM_CTRL_ADDR)
        await self.fd.wr(PROGRAM_CTRL_ADDR, 0)
        req_err = int(bool(status & _REQ_ERR))
        if req_err:
            await self.fd.wr(STATUS_ADDR, _REQ_ERR_CLR)
        word = await direct_word(self, bit_addr // 32)
        return {
            "cmd": own,
            "cmd_all": every,
            "status": status,
            "busy": int(bool(pctl & _PG_BUSY)),
            "done": int(bool(pctl & _PG_DONE)),
            "pstatus": int(bool(pctl & _PG_STATUS)),
            "go_landed": int(pctl & _PG_CTL == program_ctrl_word(bit_addr, go=1)),
            "req_err": req_err,
            "word": word,
            "bit": (word >> (bit_addr % 32)) & 1,
        }

    def _golden_with(self, otp_word: int) -> None:
        """Make the post-sense golden carry the current OTP LC_STATE word and spare bit."""
        self.golden.words[_LC_WORD] = otp_word
        set_shadow_golden(self, self.golden)

    # ------------------------------------------------------------------ scenario

    async def run_scenario(self) -> None:
        dut = cocotb.top
        seed = self.random_seed()
        p = plan(T_TRANSIENT, seed)
        self.plan = p
        leg = p.leg
        en = int(leg["enable"])
        start = leg["start"]
        script = [_SCRIPT_CH[s] for s in leg["script"]]
        leg_b = bool(leg["leg_b"])
        leg_s = en == 1 and start in _LEG_S_STARTS
        self.en = en
        self.start = start
        self.window_dead = False
        seed_fields = {
            "en": en,
            "start": start,
            "script": "_then_".join(leg["script"]),
            "leg_b": int(leg_b),
            "leg_s": int(leg_s),
        }
        for line in p.log_lines(**seed_fields):
            self.logger.info("%s", line)
        self.chk = SepChkLog(self, _NAME, seed)
        self.fd = SepEfuseFd(self)
        if p.setup_fail:
            raise AssertionError(f"SETUP FAIL seed={seed} reason={p.setup_fail}")
        if leg_b:
            self.required_evidence = (*type(self).required_evidence, "CHK-PROG-LC")
        if leg_s:
            self.required_evidence = (
                *type(self).required_evidence,
                "CHK-TRANSIENT-SIMUL",
                "CHK-TRANSIENT-AFTER-BLOCK",
            )
        self.logger.info("EVIDENCE-REQUIRED seed=%d ids=%s", seed, ",".join(self.required_evidence))

        raw0 = p.lc_raw & _LC_RAW_MASK
        staged_word = p.image.words[_LC_WORD] & 0xFFFF_FFFF
        staged_byte = lc_encode(raw0)
        self.staging_seen: set[str] = set()
        self.golden = type(p.image)()
        self.golden.words = list(p.image.words)

        # The image staged before the first reset is the one the pre-sim hook wrote.
        self.write_efuse_image(p.image)
        sense = SenseClock(self).start()
        await self.release_no_cpu_reset()
        # secure_tm_req_i stays 0 for the whole leaf.
        self._set_pin(dut, "test_en_strap_i", 0)
        await self.wait_fuse_sense(max_cycles=_SENSE_BOUND)
        if sense.clocks is None:
            sense.stop()
            raise AssertionError("the sense clock did not see the sep_fuse_sense_done_o rise")
        t_sense = sense.clocks
        self.w = max(_W_MULT * t_sense, _W_MIN)
        log_line(self.logger, "INFO-TIME", seed, t_sense=t_sense, w_cycles=self.w, mult=_W_MULT)
        self.shim = SepShimCmdMonitor(dut).start()
        await ClockCycles(dut.clk_i, 2)

        # Window control: a free spare bit lands inside W, and its command shows.
        spare = leg["spare"]
        ctl = await self._program(spare["addr"])
        landed = ctl["busy"] == 0 and ctl["done"] == 1 and ctl["bit"] == 1
        ctl_seen = landed and ctl["cmd"] == 1 and ctl["cmd_all"] == 1
        self.chk.ctrl(
            "WINDOW-CTL",
            ctl_seen,
            bit_addr=spare["addr"],
            busy=ctl["busy"],
            done=ctl["done"],
            bit=ctl["bit"],
            cmds=ctl["cmd"],
            cmds_all=ctl["cmd_all"],
            w_cycles=self.w,
        )
        if not landed:
            hook_fail(
                self.chk,
                reason="window_control",
                bit_addr=spare["addr"],
                busy=ctl["busy"],
                done=ctl["done"],
                bit=ctl["bit"],
                w_cycles=self.w,
            )
        if not ctl_seen:
            hook_fail(
                self.chk,
                reason="window_control_cmd",
                bit_addr=spare["addr"],
                cmds=ctl["cmd"],
                cmds_all=ctl["cmd_all"],
            )
        log_line(self.logger, "INFO-WINDOW-CTL", seed, w_cycles=self.w, landed=1)
        spare_word = field_word(spare["field"]) + spare["word"]
        self.golden.words[spare_word] = ctl["word"]
        set_shadow_golden(self, self.golden)

        # Every CHK-TRANSIENT cell rests on the staged enable: the sensed shadow shows it.
        en_shadow = shadow_word(self, field_word("TRANSIENT_RMA_EN")) & _EN_MASK
        if not self._ctrl("TRANSIENT-EN", en_shadow == en, staged=en, shadow=en_shadow):
            hook_fail(self.chk, reason="transient_rma_en_shadow", staged=en, shadow=en_shadow)

        # ---------------------------------------------------------- leg A
        open_graded_window(_NAME, self.logger)
        base = await self._lc_and_feat()
        self.chk.info(
            "TRANSIENT-BASE",
            word=f"0x{base['word']:08x}",
            feat=f"0x{base['feat']:016x}",
            staged_byte=f"0x{staged_byte:02x}",
        )
        raw = raw0
        held: dict[str, bool] = {CH_SIP: False, CH_CHIPLET: False}
        pre_reset_codes: dict[str, int | None] = {}
        burn_mark = self.shim.mark()
        for k, ch in enumerate(script, start=1):
            if ch == CH_SIP and held[CH_CHIPLET]:
                # Leg A: a CHIPLET match ends before a later SIP step.
                pre_reset_codes[_CH_NAME[CH_CHIPLET]] = await self._mismatch(
                    CH_CHIPLET, f"a{k}.chp_end"
                )
                held[CH_CHIPLET] = False
            code = await self._match(ch, f"a{k}.{_CH_NAME[ch]}")
            held[ch] = code == CODE_MATCH
            await ClockCycles(dut.clk_i, self.w)
            got = await self._lc_and_feat()
            raw = _transient_next(raw, ch, en)
            if self._grade_transient(k, ch, code, raw, got):
                await self._label(TR_PASS_TRANSIENT)
        shadow_pre_reset = got["word"]
        for ch in (CH_SIP, CH_CHIPLET):
            if await self.fd.match(ch) == CODE_MATCH:
                pre_reset_codes[_CH_NAME[ch]] = await self._mismatch(ch, f"a.end.{_CH_NAME[ch]}")
                held[ch] = False
        lc_otp = await direct_word(self, _LC_WORD)
        burn_cmds = self.shim.programs_since(burn_mark)
        self._grade(
            "TRANSIENT-NOBURN",
            lc_otp == staged_word and not burn_cmds and ctl["bit"] == 1 and ctl["cmd"] == 1,
            lc_otp_word=f"0x{lc_otp:08x}",
            staged_word=f"0x{staged_word:08x}",
            ctl_spare_bit=ctl["bit"],
            ctl_cmd=ctl["cmd"],
            prog_cmds_in_window=len(burn_cmds),
        )

        # The leg-A reset runs in the window: cp_reset_restore holds the restore
        # at the sense rise, and CHK-TRANSIENT-RESET releases it.
        self._stop_if_held("TRANSIENT-RESET", pre_reset_codes, leg="a")
        await self.pulse_rst_ni()
        after = await self._lc_and_feat()
        if self._grade_reset("a", pre_reset_codes, after, raw != raw0, shadow_pre_reset):
            await self._label(TR_PASS_RESET)

        if leg_s:
            await self._simul(raw0)
            await self._twin_reset(raw0)
        else:
            self.chk.info("TRANSIENT-SIMUL-SKIP", en=en, start=start)
        if leg_b:
            await self._leg_b(seed, staged_word)
        close_graded_window(self.logger)
        await self._prog_order(raw0, staged_word, leg_b)
        await self.shim.stop()
        self.chk.finish()

    async def _prog_order(self, raw0: int, staged_word: int, leg_b: bool) -> None:
        """OBS-PROG-LC-ORDER: a program of bit 2 with RMA_CHIPLET matched and bit 1 clear.

        Logged, not graded: the specification does not settle whether the OTP program
        of bit 2 needs bit 1 in the pre-write state. ``otp_fuse_controller.adoc`` (row
        ``LC_STATE``) and ``lifecycle_controller.adoc`` say bit 2 requires bit 1;
        ``token_processing.adoc`` (Post Token Matching Handling) and
        ``otp_fuse_controller.adoc`` (Fuse Programming and RMA Authorization) gate
        the fuse program on the token match only. The line logs the OTP word, the
        program commands within W and the status bits. CTRL-PROG-LC-ORDER-MATCH
        shows the RMA_CHIPLET match. It runs last, with the graded window closed,
        because a landed bit changes every later state. It runs from PROD and
        TEST_DEV (bit 1 clear, a legal state); a leg-B leaf has set bit 1 by then
        and logs ``INFO-PROG-LC-ORDER-SKIP``.
        """
        if leg_b or self.start not in (ST_PROD, ST_TEST_DEV) or (raw0 >> _LC_SIP_BIT) & 1:
            self.chk.info("PROG-LC-ORDER-SKIP", start=self.start, leg_b=int(leg_b))
            return
        code = await self._match(CH_CHIPLET, "o.chp")
        self._ctrl("PROG-LC-ORDER-MATCH", code == CODE_MATCH, chp_code=_hex2(code))
        r = await self._program(_LC_BIT2)
        end = await self._mismatch(CH_CHIPLET, "o.chp_end")
        self.chk.obs(
            "PROG-LC-ORDER",
            start=self.start,
            bit=2,
            chp_code=_hex2(code),
            shim_cmd=r["cmd"],
            shim_cmd_all=r["cmd_all"],
            w_cycles=self.w,
            lc_otp_word=f"0x{r['word']:08x}",
            staged_otp_word=f"0x{staged_word:08x}",
            landed=r["bit"],
            busy=r["busy"],
            done=r["done"],
            req_err=r["req_err"],
            program_status=r["pstatus"],
            chp_end=_hex2(end),
        )

    async def _simul(self, raw0: int) -> None:
        """Leg S: an RMA_SIP match while an RMA_CHIPLET match is held.

        From TEST_DEV or PROD with the enable at 1, a CHIPLET match changes nothing
        (CHK-TRANSIENT ``step=simul_chp``). The SIP match that follows while the
        CHIPLET match is held does not fall through to RMA_SIP: after W the whole
        LC_STATE word, its probe and FEAT_CTRL keep the start state
        (otp_fuse_controller.adoc:232-238). Both channels read Match after the SIP
        match and the CHIPLET channel still reads Match after W, in the same line, so
        a script that never held both cannot pass. SIP ends first, then CHIPLET;
        an end go that does not reach Mismatch ends the leaf before the cold
        reset of the twin script.
        """
        dut = cocotb.top
        p = self.plan
        tag = "s1"
        chp = await self._match(CH_CHIPLET, f"{tag}.chp")
        await ClockCycles(dut.clk_i, self.w)
        got = await self._lc_and_feat()
        if self._grade_transient(
            "simul_chp", CH_CHIPLET, chp, _transient_next(raw0, CH_CHIPLET, 1), got
        ):
            await self._label(TR_PASS_TRANSIENT)

        sip = await self._match(CH_SIP, f"{tag}.sip")
        chp_held = await self.fd.match(CH_CHIPLET)
        sip_held = await self.fd.match(CH_SIP)
        await ClockCycles(dut.clk_i, self.w)
        got = await self._lc_and_feat()
        chp_after_w = await self.fd.match(CH_CHIPLET)
        held = {
            "chp_go": chp,
            "sip_go": sip,
            "chp_held": chp_held,
            "sip_held": sip_held,
            "chp_after_w": chp_after_w,
        }
        held_ok = all(c == CODE_MATCH for c in held.values())
        held_fields = {k: _hex2(v) for k, v in held.items()}
        self._ctrl("TRANSIENT-SIMUL-HELD", held_ok, **held_fields)
        exp_raw = raw0
        exp_word = _lc_word(exp_raw)
        exp_feat = feat_ctrl_profile(exp_raw, p.sip_dis, p.sys_dis)
        probe_byte = None if got["probe_lc"] is None else got["probe_lc"] & LC_FIELD_MASK
        ok = self._grade(
            "TRANSIENT-SIMUL",
            held_ok
            and got["word"] == exp_word
            and probe_byte == lc_encode(exp_raw)
            and got["feat"] == exp_feat.value
            and got["probe_feat"] == exp_feat.value,
            start=self.start,
            **held_fields,
            w_cycles=self.w,
            exp_word=f"0x{exp_word:08x}",
            got_word=f"0x{got['word']:08x}",
            probe_byte="x" if probe_byte is None else f"0x{probe_byte:02x}",
            exp_feat=f"0x{exp_feat.value:016x}",
            got_feat=f"0x{got['feat']:016x}",
            probe_feat="x" if got["probe_feat"] is None else f"0x{got['probe_feat']:016x}",
            exp_state=lc_state_class(exp_raw),
        )
        if ok:
            await self._label(TR_PASS_SIMUL)
        sip_end = await self._mismatch(CH_SIP, f"{tag}.sip_end")
        chp_end = await self._mismatch(CH_CHIPLET, f"{tag}.chp_end")
        ends_ok = sip_end == CODE_MISMATCH and chp_end == CODE_MISMATCH
        self._ctrl(
            "TRANSIENT-SIMUL-END",
            ends_ok,
            sip_end=_hex2(sip_end),
            chp_end=_hex2(chp_end),
        )
        if not ends_ok:
            self.chk.finish()

    async def _twin_reset(self, raw0: int) -> None:
        """SIP match alone, then a cold reset, graded by CHK-TRANSIENT-RESET.

        First, right after the simultaneous script, a lone SIP match must land
        RMA_SIP without a reset (CHK-TRANSIENT-AFTER-BLOCK,
        ``otp_fuse_controller.adoc:232-238``). Its Mismatch go must reach its code (CTRL-TRANSIENT-AFTER-BLOCK-END; a
        missing end ends the leaf there), and a cold reset follows, both with
        the window closed. The window opens again after that reset. Then the
        twin SIP match lands RMA_SIP from the sensed start state (CHK-TRANSIENT
        ``step=simul_twin``); after its Mismatch go a cold reset restores the
        staged state (CHK-TRANSIENT-RESET ``leg=simul``), so that reset always
        follows a transient update.
        """
        dut = cocotb.top
        tag = "t1"
        close_graded_window(self.logger)
        obs_sip = await self._match(CH_SIP, f"{tag}.obs_sip")
        await ClockCycles(dut.clk_i, self.w)
        obs = await self._lc_and_feat()
        self._grade_transient(
            "after_block",
            CH_SIP,
            obs_sip,
            _transient_next(raw0, CH_SIP, 1),
            obs,
            name="TRANSIENT-AFTER-BLOCK",
        )
        obs_end = await self._mismatch(CH_SIP, f"{tag}.obs_sip_end")
        if not self._ctrl(
            "TRANSIENT-AFTER-BLOCK-END",
            obs_end == CODE_MISMATCH,
            sip_end=_hex2(obs_end),
        ):
            self.chk.finish()
        await self.pulse_rst_ni()
        self._reopen_window()
        twin = await self._match(CH_SIP, f"{tag}.sip")
        await ClockCycles(dut.clk_i, self.w)
        got = await self._lc_and_feat()
        if self._grade_transient("simul_twin", CH_SIP, twin, _transient_next(raw0, CH_SIP, 1), got):
            await self._label(TR_PASS_TRANSIENT)
        pre_reset_word = got["word"]
        codes = {"twin_sip": await self._mismatch(CH_SIP, f"{tag}.sip_end")}
        self._stop_if_held("TRANSIENT-RESET", codes, leg="simul")
        await self.pulse_rst_ni()
        after = await self._lc_and_feat()
        if self._grade_reset("simul", codes, after, True, pre_reset_word):
            await self._label(TR_PASS_RESET)

    def _leg_b_code(self, step: str, code: int | None, want: int) -> None:
        """Grade the code a leg B match or mismatch go reaches.

        The program authorization that follows a go is graded only after the go
        reaches its code. A bounded poll that ends first, or a different code,
        fails CHK-PROG-LC and ends the leaf, so no refusal is graded against a
        channel state other than the one the step sets up.
        """
        self.leg_b_codes.append(f"{step}:{'none' if code is None else f'0x{code:02x}'}")
        if code != want:
            self._grade(
                "PROG-LC",
                False,
                step=step,
                exp_code=f"0x{want:02x}",
                code="none" if code is None else f"0x{code:02x}",
                w_cycles=self.w,
            )
            self.chk.finish()

    async def _leg_b(self, seed: int, staged_word: int) -> None:
        """Program authorization of LC_STATE bits 1 and 2 (TEST_DEV, enable 0)."""
        self.leg_b_codes: list[str] = []
        shadow0 = await self.fd.rd(shadow_addr("LC_STATE"))

        # Bit 1 with only RMA_CHIPLET matched: refused.
        self._leg_b_code("b1.chp", await self._match(CH_CHIPLET, "b1.chp"), CODE_MATCH)
        ref1 = await self._program(_LC_BIT1)
        shadow_ref1 = await self.fd.rd(shadow_addr("LC_STATE"))
        self._leg_b_code(
            "b1.chp_end", await self._mismatch(CH_CHIPLET, "b1.chp_end"), CODE_MISMATCH
        )

        # Bit 1 with RMA_SIP matched: lands.
        self._leg_b_code("b1.sip", await self._match(CH_SIP, "b1.sip"), CODE_MATCH)
        own1 = await self._program(_LC_BIT1)
        shadow_own1 = await self.fd.rd(shadow_addr("LC_STATE"))
        sip_end = await self._mismatch(CH_SIP, "b1.sip_end")
        chp_code = await self.fd.match(CH_CHIPLET)
        otp1 = staged_word | (1 << _LC_SIP_BIT)
        if own1["bit"] == 1:
            self._golden_with(own1["word"])
        await self.pulse_rst_ni()
        sense1 = await self.fd.rd(shadow_addr("LC_STATE"))
        r1 = (staged_word & _LC_RAW_MASK) | (1 << _LC_SIP_BIT)
        exp1 = _lc_word(r1)
        own1_ok = (
            own1["cmd"] >= 1
            and own1["busy"] == 0
            and own1["done"] == 1
            and own1["word"] == otp1
            and shadow_own1 == shadow0
            and sense1 == exp1
            and sip_end == CODE_MISMATCH
            and chp_code == CODE_MISMATCH
        )
        ref1_graded = self._grade(
            "PROG-LC",
            ref1["go_landed"] == 1
            and ref1["cmd"] == 0
            and ref1["cmd_all"] == 0
            and ref1["word"] == staged_word
            and shadow_ref1 == shadow0
            and own1_ok,
            bit=1,
            match="other_only",
            role="new",
            go_landed=ref1["go_landed"],
            shim_cmd=ref1["cmd"],
            shim_cmd_all=ref1["cmd_all"],
            w_cycles=self.w,
            lc_otp_word=f"0x{ref1['word']:08x}",
            landed=ref1["bit"],
            busy=ref1["busy"],
            done=ref1["done"],
            req_err=ref1["req_err"],
            shadow_pre=f"0x{shadow0 & LC_FIELD_MASK:02x}",
            shadow_after_sense="na",
            exp_after_sense="na",
            state_after_sense="na",
            ctl_own_landed=int(own1_ok),
            go_codes=",".join(self.leg_b_codes),
        )
        own1_graded = self._grade(
            "PROG-LC",
            own1_ok,
            bit=1,
            match="own",
            role="new",
            shim_cmd=int(own1["cmd"] >= 1),
            w_cycles=self.w,
            lc_otp_word=f"0x{own1['word']:08x}",
            landed=own1["bit"],
            shadow_pre=f"0x{shadow_own1 & LC_FIELD_MASK:02x}",
            shadow_after_sense=f"0x{sense1:08x}",
            exp_after_sense=f"0x{exp1:08x}",
            state_after_sense=lc_state_class(r1),
            sip_end=f"0x{sip_end:02x}" if sip_end is not None else "none",
            chp_code=f"0x{chp_code:02x}",
            go_codes=",".join(self.leg_b_codes),
        )
        # Both bit-1 programs (other channel refused, own channel landed) are
        # graded above; the label releases their x_lc_prog_gate cells.
        if ref1_graded and own1_graded:
            await self._label(TR_PASS_PROG_LC)

        # Bit 2 with only RMA_SIP matched: refused (control of the open refusal).
        self._leg_b_code("b2.sip", await self._match(CH_SIP, "b2.sip"), CODE_MATCH)
        chp_held = await self.fd.match(CH_CHIPLET)
        self.chk.info("PROG-LC-CHP", chp_code=f"0x{chp_held:02x}")
        close_graded_window(self.logger)
        ref2 = await self._program(_LC_BIT2)
        self._reopen_window()
        shadow_ref2 = await self.fd.rd(shadow_addr("LC_STATE"))

        # Bit 2 with RMA_CHIPLET matched: lands.
        self._leg_b_code("b2.chp", await self._match(CH_CHIPLET, "b2.chp"), CODE_MATCH)
        own2 = await self._program(_LC_BIT2)
        shadow_own2 = await self.fd.rd(shadow_addr("LC_STATE"))
        sip_end2 = await self._mismatch(CH_SIP, "b2.sip_end")
        chp_end2 = await self._mismatch(CH_CHIPLET, "b2.chp_end")
        otp2 = otp1 | (1 << _LC_CHP_BIT)
        if own2["bit"] == 1:
            self._golden_with(own2["word"])
        await self.pulse_rst_ni()
        sense2 = await self.fd.rd(shadow_addr("LC_STATE"))
        r2 = r1 | (1 << _LC_CHP_BIT)
        exp2 = _lc_word(r2)
        own2_ok = (
            own2["cmd"] >= 1
            and own2["busy"] == 0
            and own2["done"] == 1
            and own2["word"] == otp2
            and shadow_own2 == sense1
            and sense2 == exp2
            and sip_end2 == CODE_MISMATCH
            and chp_end2 == CODE_MISMATCH
        )
        ref2_graded = self._grade(
            "PROG-LC",
            chp_held != CODE_MATCH
            and ref2["go_landed"] == 1
            and ref2["cmd"] == 0
            and ref2["cmd_all"] == 0
            and ref2["word"] == otp1
            and shadow_ref2 == sense1
            and own2_ok,
            bit=2,
            match="other_only",
            role="control",
            go_landed=ref2["go_landed"],
            shim_cmd=ref2["cmd"],
            shim_cmd_all=ref2["cmd_all"],
            w_cycles=self.w,
            lc_otp_word=f"0x{ref2['word']:08x}",
            landed=ref2["bit"],
            busy=ref2["busy"],
            done=ref2["done"],
            req_err=ref2["req_err"],
            chp_code=f"0x{chp_held:02x}",
            shadow_pre=f"0x{sense1 & LC_FIELD_MASK:02x}",
            shadow_after_sense="na",
            exp_after_sense="na",
            state_after_sense="na",
            ctl_own_landed=int(own2_ok),
            go_codes=",".join(self.leg_b_codes),
        )
        own2_graded = self._grade(
            "PROG-LC",
            own2_ok,
            bit=2,
            match="own",
            role="new",
            shim_cmd=int(own2["cmd"] >= 1),
            w_cycles=self.w,
            lc_otp_word=f"0x{own2['word']:08x}",
            landed=own2["bit"],
            shadow_pre=f"0x{shadow_own2 & LC_FIELD_MASK:02x}",
            shadow_after_sense=f"0x{sense2:08x}",
            exp_after_sense=f"0x{exp2:08x}",
            state_after_sense=lc_state_class(r2),
            sip_end=f"0x{sip_end2:02x}" if sip_end2 is not None else "none",
            chp_end=f"0x{chp_end2:02x}" if chp_end2 is not None else "none",
            go_codes=",".join(self.leg_b_codes),
        )
        # The bit-2 control and the own-channel program are graded above; the
        # label releases the bit-2 own-landed x_lc_prog_gate cell.
        if ref2_graded and own2_graded:
            await self._label(TR_PASS_PROG_LC)
