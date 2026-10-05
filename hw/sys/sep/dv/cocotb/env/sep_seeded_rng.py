# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seed-reproducible stimulus generator for SEP DV.

DV needs the opposite of a cryptographic generator: a failing leaf is replayed
with ``--stage sim --seed N``, so the stimulus must be a pure function of the
seed. ``secrets`` and ``random.SystemRandom`` cannot be seeded, so they cannot
express that contract.

This is SHA-256 in counter mode over the seed. It is deterministic across
hosts, Python builds, and interpreter runs -- unlike ``random.Random``, whose
stream is only guaranteed stable within a Python major version.

It is not a CSPRNG. The stream is fully predictable from the seed, which is
the entire point. Never use it for a key, token, nonce, or any value that
leaves the simulation.

A per-seed value is a function of this generator's stream, so it must never be
quoted as verification-plan evidence.
"""

import hashlib

__all__ = ["SepSeededRng"]

_BLOCK = 32  # SHA-256 digest size


class SepSeededRng:
    """Deterministic byte stream with the ``random.Random`` methods DV uses.

    Method semantics match ``random.Random`` so call sites read the same; the
    streams differ.
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

    def shuffle(self, seq) -> None:
        """Shuffle ``seq`` in place, uniform over permutations.

        Deterministic from the seed and not cryptographic: the permutation is
        predictable to anyone holding the seed.
        """
        for i in range(len(seq) - 1, 0, -1):
            j = self._below(i + 1)
            seq[i], seq[j] = seq[j], seq[i]

    def sample(self, population, k: int) -> list:
        """``k`` distinct elements of ``population``, uniform over k-subsets.

        Result order is unspecified but deterministic from the seed. Not
        cryptographic: the selection is predictable to anyone holding the seed.
        """
        pool = list(population)
        n = len(pool)
        if k < 0:
            raise ValueError("sample: k must be non-negative")
        if k > n:
            raise ValueError(f"sample: k ({k}) larger than population ({n})")
        # Partial Fisher-Yates: one bounded draw per selected element, so the
        # stream consumed depends only on k, never on collisions.
        for i in range(k):
            j = i + self._below(n - i)
            pool[i], pool[j] = pool[j], pool[i]
        return pool[:k]
