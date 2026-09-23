# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
i3c_rand.py — I3C-specific constrained-random layer for the I3C block TB.

Thin domain layer on top of the IP-agnostic core in
``constrained_random.py`` (same directory): it re-exports the generic seed /
constraint primitives and adds I3C protocol-specific generators and a
declarative transaction object.

Generic primitives (seed mgmt, in_range, weighted, banded, rand_bytes) live in
that core; only the I3C knowledge (reserved addresses, MWL/MRL, threshold
reachability, IBI, transfers) lives here.

Example
-------
    from env.i3c_rand import RandMgr, I3CTransfer, do_transfer, rand_i3c_addr

    r = RandMgr()                       # logs the seed
    await ctrl.setmwl(256, dat_idx=0)
    for _ in range(r.randint(4, 10)):
        t = I3CTransfer().randomize(r, mwl=256)
        await do_transfer(ctrl, tgt, t)  # drives + self-checks
"""

# Re-export the generic core so tests can `from env.i3c_rand import RandMgr, ...`.
from .constrained_random import (
    RandMgr,
    banded,
    in_range,
    rand_bytes,
    resolve_seed,
    weighted,
)

__all__ = [
    # re-exported generic
    "RandMgr",
    "resolve_seed",
    "in_range",
    "weighted",
    "banded",
    "rand_bytes",
    # i3c domain
    "I3C_RESERVED_ADDR",
    "rand_i3c_addr",
    "rand_len",
    "rand_threshold",
    "len_for_threshold",
    "rand_mwl",
    "rand_mrl",
    "rand_ibi_mdb",
    "rand_ibi_payload",
    "I3CTransfer",
    "do_transfer",
]


# ---------------------------------------------------------------------------
# I3C domain generators
# ---------------------------------------------------------------------------
# Reserved I3C addresses that must never be used as a target dynamic/static
# address (broadcast 0x7E, single-bit-error neighbours, low reserved group).
I3C_RESERVED_ADDR = frozenset(
    {
        0x00,
        0x01,
        0x02,
        0x3E,
        0x5E,
        0x6E,
        0x76,
        0x7A,
        0x7C,
        0x7E,
        0x7F,
    }
)


def rand_i3c_addr(rng, exclude=()):
    """A legal 7-bit I3C address in the typical assignable window 0x08..0x7B,
    excluding reserved addresses and any caller-supplied *exclude* set."""
    return in_range(rng, 0x08, 0x7B, exclude=(I3C_RESERVED_ADDR | set(exclude)))


def rand_len(rng, mwl, *, lo=1):
    """Transfer length in ``[lo, mwl]``, corner-biased to dword boundaries,
    odd tails and the extremes. Always honour ``length <= mwl``."""
    corners = [lo, lo + 1, lo + 2, 3, 4, 5, 8, mwl - 1, mwl]
    return in_range(rng, lo, mwl, corners=corners)


def rand_threshold(rng):
    """RX/TX FIFO threshold register value. 0..2 are reachable with the
    transfer sizes this TB uses (see :func:`len_for_threshold`)."""
    return rng.randint(0, 2)


def len_for_threshold(thr, base_len, bytes_per_entry=4):
    """Grow *base_len* so a threshold of ``1<<(thr+1)`` entries can actually fire
    (the RX-data threshold interrupt never asserts otherwise)."""
    need = (1 << (thr + 1)) * bytes_per_entry
    return max(base_len, need)


def rand_mwl(rng):
    """Random Max-Write-Length 1..4095, corner-biased."""
    return in_range(rng, 1, 4095, corners=[1, 8, 16, 64, 256, 4095])


def rand_mrl(rng):
    """Random Max-Read-Length 1..4095, corner-biased."""
    return in_range(rng, 1, 4095, corners=[1, 8, 16, 64, 256, 4095])


def rand_ibi_mdb(rng):
    """Random IBI Mandatory Data Byte (0..0xFF)."""
    return rng.randint(0, 0xFF)


def rand_ibi_payload(rng, max_size):
    """Random IBI payload: length 0..*max_size*, random bytes."""
    return rand_bytes(rng, rng.randint(0, max_size))


# ---------------------------------------------------------------------------
# Declarative constrained-random transaction object
# ---------------------------------------------------------------------------
class I3CTransfer:
    """A constrained-random private transfer.

    Fields (``dir``, ``length``, ``data``, ``dat_idx``) are filled by
    :meth:`randomize`. Ordering encodes the constraint dependencies (length is
    bounded by *mwl*; data follows length).
    """

    __slots__ = ("dir", "length", "data", "dat_idx")

    def randomize(self, rng, *, mwl=256, dat_idx=0, w_weight=6, r_weight=4, min_len=1):
        self.dir = weighted(rng, [("write", w_weight), ("read", r_weight)])
        self.length = rand_len(rng, mwl, lo=min_len)
        self.data = rand_bytes(rng, self.length)
        self.dat_idx = dat_idx
        return self

    def __repr__(self):
        return f"I3CTransfer(dir={self.dir} len={self.length} dat_idx={self.dat_idx})"


async def do_transfer(ctrl, tgt, t):
    """Drive an :class:`I3CTransfer` through the controller and self-check
    (built-in scoreboard: what we sent must equal what the peer received).

    Returns ``(ok, resp, rx)``.
    """
    if t.dir == "write":
        ok, resp, rx = await ctrl.private_write(t.data, tgt, dat_idx=t.dat_idx)
        assert ok, f"write {t.length}B failed resp=0x{resp:08X}"
        assert rx == t.data, f"write {t.length}B data mismatch"
    else:
        ok, resp, rx = await ctrl.private_read(tgt, t.data, dat_idx=t.dat_idx)
        assert ok, f"read {t.length}B failed resp=0x{resp:08X}"
        assert rx == t.data, f"read {t.length}B data mismatch"
    return ok, resp, rx


# ---------------------------------------------------------------------------
# Standalone self-test: `python i3c_rand.py` — checks the I3C constraints.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    r = RandMgr(seed=0x1234, name="i3c-selftest")

    for _ in range(2000):
        a = rand_i3c_addr(r)
        assert 0x08 <= a <= 0x7B and a not in I3C_RESERVED_ADDR, a

        mwl = rand_mwl(r)
        n = rand_len(r, mwl)
        assert 1 <= n <= mwl

        thr = rand_threshold(r)
        ln = len_for_threshold(thr, n)
        assert ln >= (1 << (thr + 1)) * 4 and ln >= n

        t = I3CTransfer().randomize(r, mwl=mwl)
        assert t.dir in ("write", "read")
        assert 1 <= t.length <= mwl and len(t.data) == t.length

    print("i3c_rand self-test PASSED (I3C constraints held, core re-exported OK)")
