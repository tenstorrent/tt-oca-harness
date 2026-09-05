# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""RMA token match vs mismatch -> LC update (standalone RANDCFG).

A matching token authorizes the LC_STATE OTP bit and the resense shows the
new lifecycle code plus the spec-derived FEAT_CTRL. A mismatch does not
match, the program is rejected, and LC/FEAT_CTRL stay at the pre-attempt
golden. Token values come from the run seed. Both SIP and CHIPLET kinds
walk match and mismatch.

After that walk, the same vehicle covers the token-comparator redundancy
fault path: common-mode invert of a match (legal mismatch, no sticky),
common-mode invert of a mismatch (legal match, no sticky — the fail-open
hole), collapsed pair, two-instance disagreement, 6'b111111 on the match
status, sticky bit / IRQ survive a valid-token retry, and
``sep_internal_interrupts[39]`` (PIC source 40). Collapse and disagreement
have no frontdoor; the tb injects them on the RMA_SIP comparator rails.

Does not stretch the Phase 1 stitch e2e. Real fuse sense. Starts in PROD
so the SIP then CHIPLET walk is W1S-legal.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_axi_agent import SepAxiOp
from env.sep_efuse_image import SepEfuseImage
from env.sep_lcc_golden import LC_PROD, LC_RMA_CHIP_1, lc_state_name
from sep_base_test import sep_base_test
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_efuse_otp_program_seq import sep_efuse_otp_program_seq
from seq_lib.sep_efuse_rma_token_seq import (
    FAULT_RMA_CHIPLET,
    FAULT_RMA_SIP,
    FAULT_SEC_DISABLE,
    IRQ_TOKEN_MATCH_FAULT,
    TOKEN_CMP_INJECT_COLLAPSE,
    TOKEN_CMP_INJECT_COMMON,
    TOKEN_CMP_INJECT_COMMON_MATCH,
    TOKEN_CMP_INJECT_DISAGREE,
    TOKEN_CMP_INJECT_OFF,
    TOKEN_CMP_SEL_CHIPLET,
    TOKEN_CMP_SEL_SEC,
    TOKEN_CMP_SEL_SIP,
    TOKEN_ERROR,
    TOKEN_MATCH,
    TOKEN_MATCH_FAULT,
    TOKEN_MISMATCH,
    TOKEN_RMA_CHIPLET,
    TOKEN_RMA_SIP,
    TOKEN_SEC_DISABLE,
    SepRmaTokenCfg,
    SepRmaTokenMatchSeq,
    rma_lc_bit,
    rma_lc_raw,
)
from seq_lib.sep_lcc_stitch_check_seq import sep_lcc_stitch_check_seq

_MAX_SENSE_CYCLES = 20_000


@pyuvm.test()
class sep_efuse_rma_token_rand_test(sep_base_test):
    """Match updates LC; mismatch does not; comparator fault path both ways."""

    async def _check_lc(self, image: SepEfuseImage, raw: int, tag: str) -> None:
        sec_dis = int(cocotb.top.lcc_security_disable_probe_o.value) & 0x1
        seq = sep_lcc_stitch_check_seq(image, sec_dis=sec_dis)
        await self.start_seq(seq)
        assert seq.observed_lc_raw == raw, (
            f"{tag}: observed LC 0x{seq.observed_lc_raw:x} != {lc_state_name(raw)}"
        )
        self.logger.info(
            "CHK-LC-FEAT PASS: %s LC=%s FEAT_CTRL=0x%016x",
            tag,
            lc_state_name(raw),
            seq.observed_feat,
        )

    async def _mismatch_then_match(
        self,
        image: SepEfuseImage,
        kind: int,
        token: int,
    ) -> None:
        name = "RMA_SIP" if kind == TOKEN_RMA_SIP else "RMA_CHIPLET"
        before = image.lc_raw()
        bit = rma_lc_bit(kind)
        after = rma_lc_raw(kind)

        bad = SepRmaTokenMatchSeq(kind, token ^ 1)
        await self.start_seq(bad)
        assert bad.matched is False, f"{name} mismatch produced a match code"
        locked = sep_efuse_otp_program_seq(bit, expect_err=True)
        await self.start_seq(locked)
        assert locked.saw_err, f"{name} mismatch program did not return PROGRAM_ERR"
        await self.resense(max_cycles=_MAX_SENSE_CYCLES)
        await self._check_lc(image, before, f"{name}-mismatch")
        self.logger.info(
            "CHK-MISMATCH PASS: %s wrong token did not update LC (%s)", name, lc_state_name(before)
        )

        good = SepRmaTokenMatchSeq(kind, token)
        await self.start_seq(good)
        assert good.matched is True, f"{name} legal token did not match"
        await self.start_seq(sep_efuse_otp_program_seq(bit))
        image.set_lc_state(after)
        self.write_efuse_image(image)
        await self.resense(max_cycles=_MAX_SENSE_CYCLES)
        await self._check_lc(image, after, f"{name}-match")
        self.logger.info(
            "CHK-MATCH PASS: %s legal token updated LC %s -> %s",
            name,
            lc_state_name(before),
            lc_state_name(after),
        )

    def _irq38(self) -> int:
        return (self.rd(cocotb.top.sep_internal_interrupts_probe_o) >> IRQ_TOKEN_MATCH_FAULT) & 1

    async def _rd_fault(self) -> int:
        seq = SepAxiAccessSeq("token_fault_rd", op=SepAxiOp.READ, addr=TOKEN_MATCH_FAULT)
        await self.start_seq(seq)
        assert seq.resp_ok, "TOKEN_MATCH_FAULT read not OKAY"
        return seq.rdata

    async def _wr_fault(self, data: int) -> None:
        seq = SepAxiAccessSeq(
            "token_fault_wr",
            op=SepAxiOp.WRITE,
            addr=TOKEN_MATCH_FAULT,
            wdata=data,
            allow_unverified_write_resp=True,
        )
        await self.start_seq(seq)

    async def _present_sip(self, token: int) -> int:
        return await self._present_kind(TOKEN_RMA_SIP, token)

    async def _present_kind(self, kind: int, token: int) -> int:
        seq = SepRmaTokenMatchSeq(kind, token)
        await self.start_seq(seq)
        assert seq.match_code is not None, f"token kind {kind} match status never sampled"
        return seq.match_code

    async def _set_inject(self, mode: int, sel: int = TOKEN_CMP_SEL_SIP) -> None:
        cocotb.top.token_cmp_fault_sel_i.value = sel
        cocotb.top.token_cmp_fault_inject_i.value = mode
        await ClockCycles(cocotb.top.clk_i, 2)

    async def _token_fault_path(self, cfg: SepRmaTokenCfg) -> None:
        fault = await self._rd_fault()
        irq = self._irq38()
        assert fault == 0 and irq == 0, (
            f"fault path baseline: TOKEN_MATCH_FAULT=0x{fault:x} irq38={irq}"
        )

        sip_token = cfg.sip_token
        await self._set_inject(TOKEN_CMP_INJECT_COMMON)
        code = await self._present_sip(sip_token)
        fault = await self._rd_fault()
        irq = self._irq38()
        assert code == TOKEN_MISMATCH, (
            f"common-mode invert of a match must read 6'b101010, got 0x{code:02x}"
        )
        assert fault == 0 and irq == 0, (
            f"common-mode must not set a sticky bit: FAULT=0x{fault:x} irq38={irq}"
        )
        self.logger.info(
            "CHK-COMMON-MODE PASS: all-three invert of match -> code=0x%02x, no sticky, irq38=0",
            code,
        )
        await self._set_inject(TOKEN_CMP_INJECT_OFF)

        await self._set_inject(TOKEN_CMP_INJECT_COMMON_MATCH)
        code = await self._present_sip(sip_token ^ 1)
        fault = await self._rd_fault()
        irq = self._irq38()
        assert code == TOKEN_MATCH, (
            f"common-mode invert of a mismatch must read 6'b010101, got 0x{code:02x}"
        )
        assert fault == 0 and irq == 0, (
            f"common-mode fake match must not set a sticky bit: FAULT=0x{fault:x} irq38={irq}"
        )
        self.logger.info(
            "CHK-COMMON-MODE-MATCH PASS: all-three invert of mismatch -> "
            "code=0x%02x, no sticky, irq38=0",
            code,
        )
        await self._set_inject(TOKEN_CMP_INJECT_OFF)

        await self._set_inject(TOKEN_CMP_INJECT_COLLAPSE)
        code = await self._present_sip(sip_token)
        fault = await self._rd_fault()
        irq = self._irq38()
        assert code == TOKEN_ERROR, f"collapsed pair must force 6'b111111, got 0x{code:02x}"
        assert fault & FAULT_RMA_SIP, f"collapse did not set SIP fault: 0x{fault:x}"
        assert irq == 1, "collapse did not raise sep_internal_interrupts[39]"
        self.logger.info(
            "CHK-COLLAPSE PASS: pair collapse -> code=0x%02x FAULT=0x%08x irq38=1", code, fault
        )
        self.logger.info("CHK-ERROR-CODE PASS: every match-status bit is 1 (0x%02x)", code)
        self.logger.info("CHK-IRQ-39 PASS: sep_internal_interrupts[39] (PIC source 40) asserted")
        await self._set_inject(TOKEN_CMP_INJECT_OFF)

        code = await self._present_sip(sip_token)
        fault = await self._rd_fault()
        irq = self._irq38()
        assert code == TOKEN_MATCH, f"valid retry after release must match, got 0x{code:02x}"
        assert fault & FAULT_RMA_SIP, f"sticky SIP fault cleared on retry: 0x{fault:x}"
        assert irq == 1, "irq38 dropped on a valid-token retry"
        await self._wr_fault(0)
        still = await self._rd_fault()
        assert still & FAULT_RMA_SIP, f"TOKEN_MATCH_FAULT is sw=r; write 0 left 0x{still:x}"
        self.logger.info(
            "CHK-STICKY PASS: valid retry code=0x%02x, FAULT=0x%08x irq38=1, write-0 ignored",
            code,
            still,
        )

        await self._set_inject(TOKEN_CMP_INJECT_DISAGREE)
        code = await self._present_sip(sip_token)
        fault = await self._rd_fault()
        irq = self._irq38()
        assert code == TOKEN_ERROR, f"two-instance disagree must force 6'b111111, got 0x{code:02x}"
        assert fault & FAULT_RMA_SIP, f"disagree lost the SIP sticky bit: 0x{fault:x}"
        assert irq == 1, "disagree did not keep irq38 asserted"
        self.logger.info(
            "CHK-DISAGREE PASS: instance disagree -> code=0x%02x FAULT=0x%08x irq38=1", code, fault
        )
        await self._set_inject(TOKEN_CMP_INJECT_OFF)

        await self._set_inject(TOKEN_CMP_INJECT_COLLAPSE, TOKEN_CMP_SEL_CHIPLET)
        code = await self._present_kind(TOKEN_RMA_CHIPLET, cfg.chiplet_token)
        fault = await self._rd_fault()
        assert code == TOKEN_ERROR, f"CHIPLET collapse must force 6'b111111, got 0x{code:02x}"
        assert fault & FAULT_RMA_CHIPLET, f"CHIPLET collapse did not set bit 8: FAULT=0x{fault:x}"
        await self._set_inject(TOKEN_CMP_INJECT_OFF)

        await self._set_inject(TOKEN_CMP_INJECT_COLLAPSE, TOKEN_CMP_SEL_SEC)
        code = await self._present_kind(TOKEN_SEC_DISABLE, 1)
        fault = await self._rd_fault()
        assert code == TOKEN_ERROR, f"SEC_DISABLE collapse must force 6'b111111, got 0x{code:02x}"
        assert fault & FAULT_SEC_DISABLE, (
            f"SEC_DISABLE collapse did not set bit 16: FAULT=0x{fault:x}"
        )
        await self._set_inject(TOKEN_CMP_INJECT_OFF)
        self.logger.info(
            "CHK-WHICH-TOKEN PASS: FAULT=0x%08x (SIP bit0 + CHIPLET bit8 + SEC_DISABLE bit16)",
            fault,
        )

        # LC is RMA_CHIP_1: the PROD/RMA_SIP JTAG window is off, so the fault
        # CSR is a legal JTAG read. Do not treat a PROD OKAY as coverage.
        jtag_resp, jtag_data = await self.jtag_axil_op(write=False, addr=TOKEN_MATCH_FAULT)
        assert jtag_resp == 0, f"JTAG TOKEN_MATCH_FAULT at RMA_CHIP must be OKAY, resp={jtag_resp}"
        assert jtag_data == fault, f"JTAG TOKEN_MATCH_FAULT 0x{jtag_data:x} != AXI 0x{fault:x}"
        self.logger.info("CHK-JTAG-FAULT PASS: JTAG read 0x%08x == AXI after RMA_CHIP", jtag_data)

    async def _fault_clears_on_reset(self, cfg: SepRmaTokenCfg) -> None:
        """The sticky fault bits clear on cold reset, and only on cold reset.

        The phases above prove the bits survive a retry with a valid token,
        which is the tamper-evidence property. They cannot tell that apart from
        a latch that never clears at all: a fault bit wired to a non-resettable
        flop passes every one of them. Re-sensing the part and re-reading is
        what separates the two.
        """
        fault = await self._rd_fault()
        assert fault != 0, (
            "reset-clear check needs a latched fault to start from, but "
            "TOKEN_MATCH_FAULT is already 0 -- the phases above left nothing set"
        )
        assert self._irq38() == 1, (
            "reset-clear check: a fault is latched but the interrupt is low, so "
            "the release below would prove nothing about the interrupt"
        )

        # Drop the injection first: a fault still being driven would re-latch on
        # the next comparison and the clear would be indistinguishable from a
        # failure to re-fault.
        await self._set_inject(TOKEN_CMP_INJECT_OFF)

        # Re-sense at the state the part has actually reached. The walks above
        # advanced LC_STATE to RMA_CHIPLET_1, and the LC_STATE shadow is not
        # rolled back by a re-sense -- staging a PROD image here would make the
        # backdoor shadow check compare the sensed 0x7 against an expected 0x1
        # and fail on the image, never reaching the fault-latch question.
        image = self.select_efuse_image(lc_raw=LC_RMA_CHIP_1, fixed=cfg.image_fixed())
        self.write_efuse_image(image)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)

        fault = await self._rd_fault()
        irq = self._irq38()
        assert fault == 0, (
            f"CHK-FAULT-RESET: TOKEN_MATCH_FAULT=0x{fault:08x} after cold reset, "
            "expected 0 -- the sticky latch is not reset-clearable"
        )
        assert irq == 0, (
            "CHK-FAULT-RESET: token-match-fault interrupt still asserted after "
            "cold reset, so the PIC source does not follow the latch"
        )
        self.logger.info(
            "CHK-FAULT-RESET PASS: cold reset cleared TOKEN_MATCH_FAULT and released the interrupt"
        )

    async def run_scenario(self) -> None:
        cfg = SepRmaTokenCfg(self.random_seed())
        self.logger.info("rma token RANDCFG: %s", cfg.summary())

        # t=0 OTP load is staged by cocotb/dv_sim_prestage.py via SepRmaTokenCfg.
        image = self.select_efuse_image(lc_raw=LC_PROD, fixed=cfg.image_fixed())
        self.write_efuse_image(image)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)
        await self._check_lc(image, LC_PROD, "prod-baseline")

        await self._mismatch_then_match(image, TOKEN_RMA_SIP, cfg.sip_token)
        await self._mismatch_then_match(image, TOKEN_RMA_CHIPLET, cfg.chiplet_token)

        self.logger.info(
            "CHK-RANDCFG PASS: SIP and CHIPLET match+mismatch walked; tokens from seed %d", cfg.seed
        )

        await self._token_fault_path(cfg)
        await self._fault_clears_on_reset(cfg)
