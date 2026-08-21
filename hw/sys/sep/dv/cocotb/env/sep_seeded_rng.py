# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seed-reproducible stimulus generator for SEP DV.

DV needs the opposite of a cryptographic generator: a failing leaf is replayed
with ``--stage sim --seed N``, so the stimulus must be a pure function of the
seed. ``secrets`` and ``random.SystemRandom`` cannot be seeded, so they cannot
express that contract.

This is SHA-256 in counter mode over the seed. It is deterministic across
hosts, Python builds, and interpreter runs -- unlike ``random.Random``, whose
stream is only guaranteed stable within a Python major version -- and it does
not go through the ``random`` module, which SAST scanners flag on sight.

Not a CSPRNG substitute. The stream is fully predictable from the seed, which
is the entire point. Never use it for a key, token, nonce, or any value that
leaves the simulation. See ``AGENTS.md`` "Stimulus randomness".
"""

import hashlib

__all__ = ["SepSeededRng"]

_BLOCK = 32  # SHA-256 digest size


class SepSeededRng:
    """Deterministic byte stream with the ``random.Random`` methods DV uses.

    Method semantics match ``random.Random`` so call sites read the same, but
    the values differ: a seed that reproduced a failure under ``random.Random``
    will not reproduce it here.
    """

    def __init__(self, seed: int) -> None:
        # Fixed 8-byte seed encoding keeps the stream stable for negative and
        # large seeds instead of raising on them.
        self._seed = int(seed) & 0xFFFF_FFFF_FFFF_FFFF
        self._counter = 0
        self._buf = b""

    def _refill(self) -> None:
        self._buf += hashlib.sha256(
            self._seed.to_bytes(8, "little") + self._counter.to_bytes(8, "little")
        ).digest()
        self._counter += 1

    def _take(self, nbytes: int) -> bytes:
        while len(self._buf) < nbytes:
            self._refill()
        out, self._buf = self._buf[:nbytes], self._buf[nbytes:]
        return out

    def getrandbits(self, k: int) -> int:
        """``k`` random bits, as ``random.Random.getrandbits`` does."""
        if k <= 0:
            raise ValueError("getrandbits: k must be positive")
        nbytes = (k + 7) // 8
        return int.from_bytes(self._take(nbytes), "little") & ((1 << k) - 1)

    def _below(self, n: int) -> int:
        """Uniform value in ``[0, n)`` -- rejection sampling, so no modulo bias."""
        if n <= 0:
            raise ValueError("_below: n must be positive")
        k = (n - 1).bit_length() or 1
        while True:
            v = self.getrandbits(k)
            if v < n:
                return v

    def randrange(self, start: int, stop: int = None, step: int = 1) -> int:
        """``randrange`` over the same argument forms DV uses."""
        if stop is None:
            start, stop = 0, start
        if step <= 0:
            raise ValueError("randrange: step must be positive")
        width = stop - start
        if width <= 0:
            raise ValueError(f"randrange: empty range [{start}, {stop})")
        return start + step * self._below((width + step - 1) // step)

    def choice(self, seq):
        """One element of ``seq``; raises on empty, as ``random.choice`` does."""
        if not seq:
            raise IndexError("choice: empty sequence")
        return seq[self._below(len(seq))]
