# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""RMA token match vs mismatch -> LC update (standalone RANDCFG).

A matching token authorizes the LC_STATE OTP bit and the resense shows the
new lifecycle code plus the spec-derived FEAT_CTRL. A mismatch does not
match, the program is rejected, and LC/FEAT_CTRL stay at the pre-attempt
golden. Token values come from the run seed. Both SIP and CHIPLET kinds
walk match and mismatch.

Does not stretch the Phase 1 stitch e2e. Real fuse sense. Starts in PROD
so the SIP then CHIPLET walk is W1S-legal.
"""

from __future__ import annotations

import cocotb
import pyuvm

from sep_base_test import sep_base_test
from env.sep_efuse_image import SepEfuseImage
from env.sep_lcc_golden import LC_PROD, lc_state_name
from seq_lib.sep_efuse_otp_program_seq import sep_efuse_otp_program_seq
from seq_lib.sep_efuse_rma_token_seq import (
    TOKEN_RMA_CHIPLET, TOKEN_RMA_SIP, SepRmaTokenCfg, SepRmaTokenMatchSeq,
    rma_lc_bit, rma_lc_raw,
)
from seq_lib.sep_lcc_stitch_check_seq import sep_lcc_stitch_check_seq

_MAX_SENSE_CYCLES = 20_000


@pyuvm.test()
class sep_efuse_rma_token_rand_test(sep_base_test):
    """Match updates LC; mismatch does not; shadow and FEAT_CTRL vs goldens."""

    async def _check_lc(self, image: SepEfuseImage, raw: int, tag: str) -> None:
        sec_dis = int(cocotb.top.lcc_security_disable_probe_o.value) & 0x1
        seq = sep_lcc_stitch_check_seq(image, sec_dis=sec_dis)
        await self.start_seq(seq)
        assert seq.observed_lc_raw == raw, (
            f"{tag}: observed LC 0x{seq.observed_lc_raw:x} != {lc_state_name(raw)}"
        )
        self.logger.info(
            "CHK-LC-FEAT PASS: %s LC=%s FEAT_CTRL=0x%016x",
            tag, lc_state_name(raw), seq.observed_feat)

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
            "CHK-MISMATCH PASS: %s wrong token did not update LC (%s)",
            name, lc_state_name(before))

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
            name, lc_state_name(before), lc_state_name(after))

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
            "CHK-RANDCFG PASS: SIP and CHIPLET match+mismatch walked; "
            "tokens from seed %d", cfg.seed)
