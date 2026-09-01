# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seed-derived RMA tokens and SHA-256 digests.

The OTP image pins ``RMA_*_TOKEN_DIGEST`` to these values. The test presents
the matching token (or token^1) through the eFuse MMR. Digest is SHA-256 over
the 32-byte big-endian token, the same transform the stitch walk uses.

``dv_sim_prestage.py`` loads this module to stage the t=0 hex; the test
builds the same ``SepRmaTokenCfg(seed)`` as its golden. Do not switch the
stream to ``random.Random`` — that would desynchronize the two processes.
"""

from __future__ import annotations

import hashlib

from sep_seeded_rng import SepSeededRng


def token_digest(token: int) -> int:
    digest = hashlib.sha256(token.to_bytes(32, "big")).digest()
    return int.from_bytes(digest, "big")


def _draw_token(rng: SepSeededRng) -> int:
    return rng.getrandbits(256) | 1


class SepRmaTokenCfg:
    """Single source of truth: seed-derived tokens; both match and mismatch walk."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)
        self.sip_token = _draw_token(rng)
        self.chiplet_token = _draw_token(rng)
        if self.chiplet_token == self.sip_token:
            self.chiplet_token ^= 1 << 8
        self.sip_digest = token_digest(self.sip_token)
        self.chiplet_digest = token_digest(self.chiplet_token)

    def image_fixed(self) -> dict[str, int]:
        """``select_efuse_image(fixed=...)`` pins that match this config."""
        return {
            "RMA_SIP_TOKEN_DIGEST": self.sip_digest,
            "RMA_CHIPLET_TOKEN_DIGEST": self.chiplet_digest,
            "TRANSIENT_RMA_EN": 0,
        }

    def summary(self) -> str:
        return (
            f"seed={self.seed} sip_token=0x{self.sip_token:064x} "
            f"chiplet_token=0x{self.chiplet_token:064x}"
        )
