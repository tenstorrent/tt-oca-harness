# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sense a diverse fuse image, so the shadow fan-out carries more than zeros.

``sep_efuse_wrapper``, ``sep_lifecycle_ctrl``, ``efuse_shadow_regs`` and
``efuse_interface_controller`` all execute their lines already;
``sep_lifecycle_ctrl`` is at 100% line and 100% condition. What none of them
moves is ``shadow_regs_i.values``: every test in the suite senses a near-blank
image, so most of the 8192 bits sit at zero for the whole run.

The image for this leaf pins the freely-writable fuse words to an alternating
``0x5555_5555`` / ``0xAAAA_AAAA`` pattern
(``env/sep_cov_efuse_diversity.py``, which also states which fields are held
back and why). Sensing it drives the rising edge on every patterned bit.
``efuse_shadow_regs`` clears the shadow array on ``rst_ni``, so the resense
that follows drives the falling edge and then the rising edge again.

The array is write-one-to-set and the bank keeps its state across reset, so a
resense cannot present the complement of a staged image: only a superset is
reachable from inside a running simulation. The bits this leaf leaves at zero
therefore need a second staged image, not a second sense.

Real fuse sense, LC TEST_DEV. The bring-up path compares the sensed shadow
against the staged image after each sense; that compare belongs to the base
class and is not a contract this leaf adds.
"""

from __future__ import annotations

import pyuvm
from env.sep_cov_efuse_diversity import SepCovEfuseDiversityCfg
from env.sep_efuse_image import SepEfuseImage
from env.sep_lcc_golden import LC_TEST_DEV
from sep_base_test import sep_base_test
from sep_reg_meta import sym

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from env.sep_axi_agent import SepAxiOp

_MAX_SENSE_CYCLES = 20_000

SHADOW_BASE = sym("SEP_EFUSE_MAP_REG_MAP_BASE_ADDR")
LCC_FEAT_CTRL = sym("SEP_LIFECYCLE_CTRL_FEAT_CTRL_REG_ADDR")

# The whole shadow aperture, one 32-bit word at a time. Reading it drives the
# shadow read multiplexer with a different value per word instead of the one
# value a blank image gives it.
SHADOW_WORDS = 256


@pyuvm.test()
class sep_cov_efuse_shadow_image_diversity_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more."""

    stimulus_only = True

    async def _walk_shadow(self, label: str) -> None:
        for word in range(SHADOW_WORDS):
            addr = SHADOW_BASE + 4 * word
            seq = SepAxiAccessSeq(
                f"shadow_rd_0x{addr:08x}",
                op=SepAxiOp.READ,
                addr=addr,
                length=4,
                size=2,
            )
            await self.start_seq(seq)
        feat = SepAxiAccessSeq(
            "feat_ctrl_rd",
            op=SepAxiOp.READ,
            addr=LCC_FEAT_CTRL,
            length=8,
            size=3,
        )
        await self.start_seq(feat)
        self.logger.info("[cov] %s: %d shadow words and FEAT_CTRL read", label, SHADOW_WORDS)

    async def run_scenario(self) -> None:
        cfg = SepCovEfuseDiversityCfg(self.random_seed())
        self.logger.info("[cov] diverse eFuse image: %s", cfg.summary())
        image: SepEfuseImage = self.select_efuse_image(
            lc_raw=LC_TEST_DEV, fixed=cfg.image_fixed()
        )
        self.write_efuse_image(image)

        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)
        await self._walk_shadow("first sense")

        # The reset inside resense returns the shadow array to zero, which is
        # the falling edge on every bit the first sense set.
        await self.resense(max_cycles=_MAX_SENSE_CYCLES)
        await self._walk_shadow("resense")
