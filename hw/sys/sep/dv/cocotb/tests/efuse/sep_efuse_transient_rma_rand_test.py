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

Leg B (TEST_DEV image with the enable at 0): a program of ``LC_STATE`` bit 1 with
only RMA_CHIPLET matched changes no bank bit and issues no program command; the
same program with RMA_SIP matched lands. A program of bit 2 with only RMA_SIP
matched is refused (a control of the open refusal, ``role=control``); with
RMA_CHIPLET matched it lands. After each resense the shadow byte is
``{~r, r}`` with r the raw nibble OR the programmed bit (``otp_fuse_controller.adoc``,
sections Fuse Programming and RMA Authorization, Shadow Register Updates and
Test-Mode Protection).

Time: the window W is a multiple of the sense time the leaf measures, at least
256 clocks. Every program wait lasts the full W with no early exit. The window
control programs a free spare bit and must land inside W, so a "never" wait of
W is as long as a landing wait. Every match ends with a mismatch go on its
channel before the next cold reset and before a later SIP step.

Checkers: CHK-TRANSIENT, CHK-TRANSIENT-NOBURN, CHK-TRANSIENT-RESET (every
leaf); CHK-PROG-LC (leg B). A failing hook control logs ``CHK-HOOK FAIL`` and
ends the leaf.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env.sep_chk_log import SepChkLog
from env.sep_efuse_bank_watch import SepShimCmdMonitor
from env.sep_efuse_image import lc_encode
from env.sep_efuse_plan import (
    CH_CHIPLET,
    CH_SIP,
    CODE_MATCH,
    CODE_MISMATCH,
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
    sig_bits,
)
from env.sep_fcov_gate import close_graded_window, open_graded_window
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
_LC_BIT1 = bit_address("LC_STATE", 0, 1)
_LC_BIT2 = bit_address("LC_STATE", 0, 2)
_PG = "EFUSE_PROGRAM_CTRL"
_PG_BUSY = EFUSE_INTERFACE_CTRL.field_mask(_PG, "program_busy")
_PG_DONE = EFUSE_INTERFACE_CTRL.field_mask(_PG, "program_done")
_PG_STATUS = EFUSE_INTERFACE_CTRL.field_mask(_PG, "program_status")
_CH_NAME = {CH_SIP: "sip", CH_CHIPLET: "chp"}
_SCRIPT_CH = {"SIP": CH_SIP, "CHIPLET": CH_CHIPLET}


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
        return raw | 0b0010
    if ch == CH_CHIPLET and cls == ST_RMA_SIP:
        return raw | 0b0100
    return raw


@pyuvm.test()
class sep_efuse_transient_rma_rand_test(sep_base_test):
    """Transient RMA shadow update, no burn, reset restore and the LC_STATE program gate."""

    required_evidence = ("CHK-TRANSIENT", "CHK-TRANSIENT-NOBURN", "CHK-TRANSIENT-RESET")

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
        dropped before the direct read, so the read interface reaches the bank.
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
        word = await direct_word(self, bit_addr // 32)
        return {
            "cmd": own,
            "cmd_all": every,
            "status": status,
            "busy": int(bool(pctl & _PG_BUSY)),
            "done": int(bool(pctl & _PG_DONE)),
            "pstatus": int(bool(pctl & _PG_STATUS)),
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
        seed_fields = {
            "en": en,
            "start": start,
            "script": "_then_".join(leg["script"]),
            "leg_b": int(leg_b),
        }
        for line in p.log_lines(**seed_fields):
            self.logger.info("%s", line)
        self.chk = SepChkLog(self, _NAME, seed)
        self.fd = SepEfuseFd(self)
        if p.setup_fail:
            raise AssertionError(f"SETUP FAIL seed={seed} reason={p.setup_fail}")
        if leg_b:
            self.required_evidence = (*type(self).required_evidence, "CHK-PROG-LC")
        self.logger.info("EVIDENCE-REQUIRED seed=%d ids=%s", seed, ",".join(self.required_evidence))

        raw0 = p.lc_raw & 0xF
        staged_word = p.image.words[_LC_WORD] & 0xFFFF_FFFF
        staged_byte = lc_encode(raw0)
        staged_feat = feat_ctrl_profile(raw0, p.sip_dis, p.sys_dis)
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
        self.logger.info(
            "TIME seed=%d t_sense=%d w_cycles=%d mult=%d", seed, t_sense, self.w, _W_MULT
        )
        self.shim = SepShimCmdMonitor(dut).start()
        await ClockCycles(dut.clk_i, 2)

        # Window control: a free spare bit lands inside W, and its command shows.
        spare = leg["spare"]
        ctl = await self._program(spare["addr"])
        landed = ctl["busy"] == 0 and ctl["done"] == 1 and ctl["bit"] == 1
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
        if ctl["cmd"] < 1:
            hook_fail(
                self.chk, reason="window_control_cmd", bit_addr=spare["addr"], cmds=ctl["cmd"]
            )
        self.chk.ctrl("WINDOW-CTL", True, bit_addr=spare["addr"], cmds=ctl["cmd"], w_cycles=self.w)
        log_line(self.logger, "OBS-WINDOW-CTL", seed, w_cycles=self.w, landed=1)
        spare_word = field_word(spare["field"]) + spare["word"]
        self.golden.words[spare_word] = ctl["word"]
        set_shadow_golden(self, self.golden)

        # ---------------------------------------------------------- leg A
        open_graded_window(_NAME, self.logger)
        base = await self._lc_and_feat()
        self.chk.obs(
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
                # A CHIPLET match ends before a later SIP step.
                pre_reset_codes[CH_CHIPLET] = await self._mismatch(CH_CHIPLET, f"a{k}.chp_end")
                held[CH_CHIPLET] = False
            code = await self._match(ch, f"a{k}.{_CH_NAME[ch]}")
            held[ch] = code == CODE_MATCH
            await ClockCycles(dut.clk_i, self.w)
            got = await self._lc_and_feat()
            raw = _transient_next(raw, ch, en)
            exp_byte = lc_encode(raw)
            exp_feat = feat_ctrl_profile(raw, p.sip_dis, p.sys_dis)
            ok = (
                code == CODE_MATCH
                and got["word"] & 0xFF == exp_byte
                and got["probe_lc"] is not None
                and got["probe_lc"] & 0xFF == exp_byte
                and got["feat"] == exp_feat.value
                and got["probe_feat"] == exp_feat.value
            )
            self.chk.ok(
                "TRANSIENT",
                ok,
                en=en,
                start=start,
                step=k,
                tok=_CH_NAME[ch],
                code="none" if code is None else f"0x{code:02x}",
                exp_byte=f"0x{exp_byte:02x}",
                got_byte=f"0x{got['word'] & 0xFF:02x}",
                probe_byte="x" if got["probe_lc"] is None else f"0x{got['probe_lc'] & 0xFF:02x}",
                exp_feat=f"0x{exp_feat.value:016x}",
                got_feat=f"0x{got['feat']:016x}",
                probe_feat="x" if got["probe_feat"] is None else f"0x{got['probe_feat']:016x}",
                exp_state=lc_state_class(raw),
                profile=exp_feat.log(),
            )
        shadow_pre_reset = got["word"] & 0xFF
        for ch in (CH_SIP, CH_CHIPLET):
            if await self.fd.match(ch) == CODE_MATCH:
                pre_reset_codes[ch] = await self._mismatch(ch, f"a.end.{_CH_NAME[ch]}")
                held[ch] = False
        lc_otp = await direct_word(self, _LC_WORD)
        burn_cmds = self.shim.programs_since(burn_mark)
        self.chk.ok(
            "TRANSIENT-NOBURN",
            lc_otp == staged_word and not burn_cmds and ctl["bit"] == 1 and ctl["cmd"] >= 1,
            lc_otp_word=f"0x{lc_otp:08x}",
            staged_word=f"0x{staged_word:08x}",
            ctl_spare_bit=ctl["bit"],
            ctl_cmd=int(ctl["cmd"] >= 1),
            prog_cmds_in_window=len(burn_cmds),
        )

        await self.pulse_rst_ni()
        after = await self._lc_and_feat()
        codes_ok = all(c == CODE_MISMATCH for c in pre_reset_codes.values())
        updated = raw != raw0
        self.chk.ok(
            "TRANSIENT-RESET",
            codes_ok
            and after["word"] & 0xFF == staged_byte
            and after["feat"] == staged_feat.value
            and after["probe_feat"] == staged_feat.value
            and (not updated or shadow_pre_reset != staged_byte),
            pre_reset_codes=",".join(
                f"{_CH_NAME[c]}:{'none' if v is None else f'0x{v:02x}'}"
                for c, v in pre_reset_codes.items()
            )
            or "none",
            staged_byte=f"0x{staged_byte:02x}",
            got_byte=f"0x{after['word'] & 0xFF:02x}",
            exp_feat=f"0x{staged_feat.value:016x}",
            got_feat=f"0x{after['feat']:016x}",
            updated=int(updated),
            shadow_pre_reset=f"0x{shadow_pre_reset:02x}",
        )

        if leg_b:
            await self._leg_b(seed, staged_word)
        close_graded_window(self.logger)
        await self.shim.stop()
        self.chk.finish()

    async def _leg_b(self, seed: int, staged_word: int) -> None:
        """Program authorization of LC_STATE bits 1 and 2 (TEST_DEV, enable 0)."""
        shadow0 = await self.fd.rd(shadow_addr("LC_STATE"))

        # Bit 1 with only RMA_CHIPLET matched: refused.
        await self._match(CH_CHIPLET, "b1.chp")
        ref1 = await self._program(_LC_BIT1)
        shadow_ref1 = await self.fd.rd(shadow_addr("LC_STATE"))
        await self._mismatch(CH_CHIPLET, "b1.chp_end")

        # Bit 1 with RMA_SIP matched: lands.
        await self._match(CH_SIP, "b1.sip")
        own1 = await self._program(_LC_BIT1)
        shadow_own1 = await self.fd.rd(shadow_addr("LC_STATE"))
        sip_end = await self._mismatch(CH_SIP, "b1.sip_end")
        chp_code = await self.fd.match(CH_CHIPLET)
        otp1 = staged_word | (1 << 1)
        if own1["bit"] == 1:
            self._golden_with(own1["word"])
        await self.pulse_rst_ni()
        sense1 = await self.fd.rd(shadow_addr("LC_STATE"))
        r1 = (staged_word & 0xF) | 0b0010
        exp1 = lc_encode(r1)
        own1_ok = (
            own1["cmd"] >= 1
            and own1["busy"] == 0
            and own1["done"] == 1
            and own1["word"] == otp1
            and shadow_own1 == shadow0
            and sense1 & 0xFF == exp1
            and sip_end == CODE_MISMATCH
            and chp_code == CODE_MISMATCH
        )
        self.chk.ok(
            "PROG-LC",
            ref1["cmd"] == 0 and ref1["word"] == staged_word and shadow_ref1 == shadow0 and own1_ok,
            bit=1,
            match="other_only",
            role="new",
            shim_cmd=ref1["cmd"],
            w_cycles=self.w,
            lc_otp_word=f"0x{ref1['word']:08x}",
            landed=ref1["bit"],
            busy=ref1["busy"],
            done=ref1["done"],
            shadow_pre=f"0x{shadow0 & 0xFF:02x}",
            shadow_after_sense="na",
            exp_after_sense="na",
            state_after_sense="na",
            ctl_own_landed=int(own1_ok),
        )
        self.chk.ok(
            "PROG-LC",
            own1_ok,
            bit=1,
            match="own",
            role="new",
            shim_cmd=int(own1["cmd"] >= 1),
            w_cycles=self.w,
            lc_otp_word=f"0x{own1['word']:08x}",
            landed=own1["bit"],
            shadow_pre=f"0x{shadow_own1 & 0xFF:02x}",
            shadow_after_sense=f"0x{sense1 & 0xFF:02x}",
            exp_after_sense=f"0x{exp1:02x}",
            state_after_sense=lc_state_class(r1),
        )

        # Bit 2 with only RMA_SIP matched: refused (control of the open refusal).
        await self._match(CH_SIP, "b2.sip")
        chp_held = await self.fd.match(CH_CHIPLET)
        self.chk.obs("PROG-LC-CHP", chp_code=f"0x{chp_held:02x}")
        close_graded_window(self.logger)
        ref2 = await self._program(_LC_BIT2)
        open_graded_window(_NAME, self.logger)
        shadow_ref2 = await self.fd.rd(shadow_addr("LC_STATE"))

        # Bit 2 with RMA_CHIPLET matched: lands.
        await self._match(CH_CHIPLET, "b2.chp")
        own2 = await self._program(_LC_BIT2)
        shadow_own2 = await self.fd.rd(shadow_addr("LC_STATE"))
        sip_end2 = await self._mismatch(CH_SIP, "b2.sip_end")
        chp_end2 = await self._mismatch(CH_CHIPLET, "b2.chp_end")
        otp2 = otp1 | (1 << 2)
        if own2["bit"] == 1:
            self._golden_with(own2["word"])
        await self.pulse_rst_ni()
        sense2 = await self.fd.rd(shadow_addr("LC_STATE"))
        r2 = 0b0110
        exp2 = lc_encode(r2)
        own2_ok = (
            own2["cmd"] >= 1
            and own2["busy"] == 0
            and own2["done"] == 1
            and own2["word"] == otp2
            and shadow_own2 == sense1
            and sense2 & 0xFF == exp2
            and sip_end2 == CODE_MISMATCH
            and chp_end2 == CODE_MISMATCH
        )
        self.chk.ok(
            "PROG-LC",
            chp_held != CODE_MATCH
            and ref2["cmd"] == 0
            and ref2["word"] == otp1
            and shadow_ref2 == sense1
            and own2_ok,
            bit=2,
            match="other_only",
            role="control",
            shim_cmd=ref2["cmd"],
            w_cycles=self.w,
            lc_otp_word=f"0x{ref2['word']:08x}",
            landed=ref2["bit"],
            busy=ref2["busy"],
            done=ref2["done"],
            chp_code=f"0x{chp_held:02x}",
            shadow_pre=f"0x{sense1 & 0xFF:02x}",
            shadow_after_sense="na",
            exp_after_sense="na",
            state_after_sense="na",
            ctl_own_landed=int(own2_ok),
        )
        self.chk.ok(
            "PROG-LC",
            own2_ok,
            bit=2,
            match="own",
            role="new",
            shim_cmd=int(own2["cmd"] >= 1),
            w_cycles=self.w,
            lc_otp_word=f"0x{own2['word']:08x}",
            landed=own2["bit"],
            shadow_pre=f"0x{shadow_own2 & 0xFF:02x}",
            shadow_after_sense=f"0x{sense2 & 0xFF:02x}",
            exp_after_sense=f"0x{exp2:02x}",
            state_after_sense=lc_state_class(r2),
        )
