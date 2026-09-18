# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded random helpers shared by sequences and configuration objects.

Seed salting per label (so two helpers seeded from one scenario seed draw
different streams), width masks, and the directed pattern set every data-path
scan starts from. The SV-UVM twin is ``ocah_rng``: ``salted_seed``,
``bit_mask``, and the directed prefix of ``directed_patterns`` produce the
same values in both realizations for the same inputs. The random tail differs
by construction. SV draws from the seeded process RNG, Python from the
``random.Random`` the caller passes, which ``OcahSequence.rng`` seeds from the
same scenario seed.
"""

from __future__ import annotations

import random

__all__ = ["OcahRng"]

_UINT32_MASK = 0xFFFF_FFFF
# Fixed members of the directed set after all-zeros and all-ones, masked to
# the requested width; the SV twin lists the same constants in this order.
_DIRECTED_FIXED = (
    0xAAAA_AAAA_AAAA_AAAA,
    0x5555_5555_5555_5555,
    0xA5A5_5A5A_C3C3_3C3C,
    0x0123_4567_89AB_CDEF,
)


class OcahRng:
    """Static seed and pattern helpers; every random draw takes the caller's seeded RNG."""

    @staticmethod
    def salted_seed(seed: int, label: str) -> int:
        """Deterministic salt: the same label always perturbs the seed the same way.

        Arithmetic is 32-bit unsigned, as in the SV twin.
        """
        salt = sum((index + 1) * ord(char) for index, char in enumerate(label)) & _UINT32_MASK
        return (seed ^ salt) & _UINT32_MASK

    @staticmethod
    def bit_mask(width: int) -> int:
        """All-ones mask of ``width`` bits; zero for a non-positive width.

        Python integers are unbounded, so the mask is exact above the 64 bits
        the SV twin can represent.
        """
        return 0 if width <= 0 else (1 << width) - 1

    @staticmethod
    def random_pattern(width: int, rng: random.Random) -> int:
        """One random pattern of ``width`` bits from the caller's seeded RNG."""
        return rng.getrandbits(width) if width > 0 else 0

    @staticmethod
    def directed_patterns(width: int, random_count: int, rng: random.Random) -> list[int]:
        """Edge, alternating, walking-one/zero, and ``random_count`` random patterns.

        Deduplicated in insertion order. ``width`` must be at least 1.
        """
        if width < 1:
            raise ValueError(f"directed_patterns needs width >= 1, got {width}")
        mask = OcahRng.bit_mask(width)
        patterns = [0, mask]
        patterns.extend(fixed & mask for fixed in _DIRECTED_FIXED)
        for bit_pos in sorted({0, width // 4, width // 2, (3 * width) // 4, width - 1}):
            patterns.append(1 << bit_pos)
            patterns.append(mask ^ (1 << bit_pos))
        patterns.extend(OcahRng.random_pattern(width, rng) for _ in range(random_count))
        return list(dict.fromkeys(patterns))
