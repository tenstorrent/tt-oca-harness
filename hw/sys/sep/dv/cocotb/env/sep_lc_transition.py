# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seed-derived config for the LC_STATE shadow-write transition walk.

The walk itself is a full deterministic matrix -- every cell runs every seed, so
no contract is seed-selected. What the seed carries is the stimulus that must not
be a fixed constant:

  * the RMA_SIP / RMA_CHIPLET tokens and their OTP digests (delegated to
    ``SepRmaTokenCfg``, so this walk and the token RANDCFG cannot drift), and
  * the ``nuisance`` pattern written into LC_STATE bytes 1..3 alongside the
    lifecycle nibble. Byte 0 is the differentially encoded lifecycle state and
    bytes 1..3 are ordinary set-only shadow bytes
    (``hw/ip/efuse/rtl/efuse_shadow_regs.sv``); driving them with seed data
    proves the byte-0 special case does not leak into its neighbours and that
    the neighbours do not disturb the lifecycle nibble.

``dv_sim_prestage.py`` loads this module to stage the t=0 hex; the test builds
the same ``SepLcTransitionCfg(seed)`` as its golden. Do not switch the stream to
``random.Random`` -- that would desynchronize the two processes.

Not a CSPRNG: the stream is predictable from the seed by design. It never leaves
the simulation.
"""

from __future__ import annotations

from sep_rma_token import SepRmaTokenCfg
from sep_seeded_rng import SepSeededRng

# Pinned non-zero disable vectors, so every decoded FEAT_CTRL in the walk is a
# different non-trivial value and no golden check can pass vacuously. Same
# vectors the lifecycle stitch walk uses.
SIP_DIS = 0x0F0F_0F0F_0F0F_0F0F
SYS_DIS = 0x00FF_00FF_00FF_00FF


class SepLcTransitionCfg:
    """Single source of truth for the walk's image pins and write patterns."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        # Tokens first, from the shared config, so the digests this pins into OTP
        # are exactly the ones SepRmaTokenMatchSeq will present.
        self.tokens = SepRmaTokenCfg(seed)
        rng = SepSeededRng(seed)
        # Bytes 1..3 of the LC_STATE shadow word. Two patterns, each with a
        # unique bit, so OR-merge (a|b) differs from overwrite (b). Byte 0
        # stays clear so it never collides with the lifecycle nibble.
        raw1 = rng.getrandbits(24)
        raw2 = rng.getrandbits(24)
        self.nuisance = ((raw1 | 0x01) & ~0x02) << 8
        self.nuisance2 = ((raw2 | 0x02) & ~0x01) << 8

    def image_fixed(self) -> dict[str, int]:
        """``select_efuse_image(fixed=...)`` pins that match this config.

        ``TRANSIENT_RMA_EN`` is 0: the APB shadow-write path is the mechanism
        under test, and the transient path would otherwise move LC_STATE on a
        token match with no write at all. The transient group re-pins it to 1
        for its own sense.
        """
        return {
            **self.tokens.image_fixed(),
            "SIP_DIS": SIP_DIS,
            "SYS_DIS": SYS_DIS,
        }

    def summary(self) -> str:
        return (
            f"seed={self.seed} nuisance=0x{self.nuisance:08x} "
            f"nuisance2=0x{self.nuisance2:08x} {self.tokens.summary()}"
        )
