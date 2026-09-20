# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The CHIPLET arm of the transient-RMA lifecycle path.

With ``TRANSIENT_RMA_EN`` set in the sensed image, ``efuse_shadow_regs`` moves
the lifecycle nibble on a token match alone, with no bus write of
``LC_STATE``. The branch has two arms and a latch for each: the SIP arm sets
raw bit 1 and ``sop_state_change_completed``, and the CHIPLET arm sets raw
bit 2 and ``chiplet_state_change_completed``, the latter only while
``lc_state_cur[1]`` already holds. The existing transient-RMA stimulus
presents the SIP token, so the CHIPLET arm and its latch have never run.

The stimulus reaches the SIP state first, because the CHIPLET arm is gated on
it:

1. sense an image whose ``TRANSIENT_RMA_EN`` bit is set and whose RMA digests
   come from the seeded token config;
2. present the matching SIP token over the eFuse MMR, then access the
   ``LC_STATE`` shadow word, which is the APB request the arm is evaluated
   on;
3. present the matching CHIPLET token and access ``LC_STATE`` again, which is
   the CHIPLET arm with ``lc_state_cur[1]`` now set.

Real fuse sense: the arm reads the sensed ``TRANSIENT_RMA_EN`` bit and the
sensed token digests.
"""

from __future__ import annotations

import pyuvm
from env.sep_axi_agent import SepAxiOp
from env.sep_efuse_image import SepEfuseImage
from env.sep_lcc_golden import LC_PROD
from env.sep_rma_token import SepRmaTokenCfg
from sep_base_test import sep_base_test
from sep_reg_meta import sym

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_efuse_rma_token_seq import (
    TOKEN_RMA_CHIPLET,
    TOKEN_RMA_SIP,
    SepRmaTokenMatchSeq,
)

_MAX_SENSE_CYCLES = 20_000

LC_STATE_SHADOW = sym("SEP_EFUSE_MAP_LC_STATE_REG_ADDR")
LCC_FEAT_CTRL = sym("SEP_LIFECYCLE_CTRL_FEAT_CTRL_REG_ADDR")


def transient_rma_image_fixed(seed: int) -> dict[str, int]:
    """Image pins for this leaf: the seeded RMA digests, transient RMA enabled.

    ``dv_sim_prestage`` stages the same dictionary at time zero, so the OTP the
    DUT senses is the image the golden is built from.
    """
    fixed = SepRmaTokenCfg(seed).image_fixed()
    # SepRmaTokenCfg pins this clear for the token RANDCFG; the transient path
    # is exactly the case where it is set.
    fixed["TRANSIENT_RMA_EN"] = 1
    return fixed


@pyuvm.test()
class sep_cov_efuse_transient_rma_chiplet_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more."""

    stimulus_only = True

    async def _touch_lc_state(self, label: str) -> None:
        """Read the LC_STATE shadow word; the read is the APB request the arm sees."""
        seq = SepAxiAccessSeq(
            f"lc_state_rd_{label}",
            op=SepAxiOp.READ,
            addr=LC_STATE_SHADOW,
            length=4,
            size=2,
        )
        await self.start_seq(seq)
        feat = SepAxiAccessSeq(
            f"feat_ctrl_rd_{label}",
            op=SepAxiOp.READ,
            addr=LCC_FEAT_CTRL,
            length=8,
            size=3,
        )
        await self.start_seq(feat)
        self.logger.info(
            "[cov] %s: LC_STATE word 0x%08x, FEAT_CTRL 0x%016x",
            label,
            seq.rdata,
            feat.rdata,
        )

    async def run_scenario(self) -> None:
        cfg = SepRmaTokenCfg(self.random_seed())
        self.logger.info("[cov] transient-RMA tokens: %s", cfg.summary())
        image: SepEfuseImage = self.select_efuse_image(
            lc_raw=LC_PROD, fixed=transient_rma_image_fixed(self.random_seed())
        )
        self.write_efuse_image(image)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)
        await self._touch_lc_state("after sense")

        # SIP first: the CHIPLET arm is gated on lc_state_cur[1].
        await self.start_seq(SepRmaTokenMatchSeq(TOKEN_RMA_SIP, cfg.sip_token))
        await self._touch_lc_state("after SIP token")

        await self.start_seq(SepRmaTokenMatchSeq(TOKEN_RMA_CHIPLET, cfg.chiplet_token))
        await self._touch_lc_state("after CHIPLET token")
