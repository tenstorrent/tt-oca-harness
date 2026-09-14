# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
constrained_random.py — IP-agnostic constrained-random utilities for cocotb TBs.

cocotb has no SystemVerilog-style constraint solver, so randomization here is
plain ``random.Random(seed)`` with constraints enforced *in code* (ordered
generate + clamp + rejection sampling + weighting). This covers ranges,
exclusion sets, ordering dependencies and biasing — none of which need a
SAT/SMT solver — so this module is dependency-free.

This module contains IP-independent randomization primitives; I3C-specific
generators are provided by ``i3c_rand``.

Usage
-----
    from env.constrained_random import RandMgr, in_range, weighted, rand_bytes, banded

    r = RandMgr()                       # logs the resolved seed
    n   = in_range(r, 1, 256, corners=[1, 2, 256])
    sz  = weighted(r, [("small", 7), ("large", 1)])
    ln  = banded(r, [((1, 8), 7), ((9, 64), 2), ((65, 256), 1)])
    pay = rand_bytes(r, n)

Seed resolution (highest priority first):
    +seed=<n>            cocotb / explicit plusarg
    +ntb_random_seed=<n> UVM-style plusarg (when present)
    SEED=<n>             environment variable
    regression sim dir   parse ``.seed.<N>`` from cwd name, or ``uvm_seed:``
                         from the dumped sim yaml in cwd
    built-in default     local reproducibility (0xC0FFEE)
"""

import os
import random
import re
from pathlib import Path

try:
    import cocotb
except ImportError:  # allow standalone import (self-test / unit use)
    cocotb = None


def _plusargs():
    """cocotb plusargs dict, or {} when not running under the cocotb runtime."""
    pa = getattr(cocotb, "plusargs", None) if cocotb is not None else None
    return pa if pa else {}


def _log(msg):
    """Log via cocotb when live, else print (standalone use)."""
    if cocotb is not None and getattr(cocotb, "plusargs", None) is not None:
        try:
            cocotb.log.info(msg)
            return
        except Exception:
            pass
    print(msg)


def _parse_int(s):
    """Parse hex (``0x..``) or decimal int from str/int."""
    if isinstance(s, int):
        return s
    if s is True or s is None:
        return None
    return int(str(s), 0)


def _seed_from_sim_dir():
    """Recover a regression runner's per-run uvm_seed when +seed/SEED were not plumbed.

    The runner names the sim directory ``<test>.seed.<uvm_seed><rid>`` and dumps
    ``uvm_seed:`` into ``<test>.yaml`` in that directory. Pure-cocotb tests do
    not get ``+ntb_random_seed=`` (that plusarg is only emitted when
    ``uvm_testname`` is set), so this fallback is the reliable bridge.
    """
    try:
        cwd = Path.cwd()
    except OSError:
        return None

    m = re.search(r"\.seed\.(\d+)", cwd.name)
    if m:
        return int(m.group(1))

    for yml in sorted(cwd.glob("*.yaml")):
        try:
            for line in yml.read_text().splitlines():
                if line.startswith("uvm_seed:"):
                    val = line.split(":", 1)[1].strip().strip("'\"")
                    if val and val != "random":
                        return int(val, 0)
        except (OSError, ValueError):
            continue
    return None


# ---------------------------------------------------------------------------
# Seed management
# ---------------------------------------------------------------------------
DEFAULT_SEED = 0xC0FFEE


def resolve_seed(default=DEFAULT_SEED):
    """Resolve the run seed (see module docstring for priority order)."""
    pa = _plusargs()
    for key in ("seed", "ntb_random_seed"):
        parsed = _parse_int(pa.get(key))
        if parsed is not None:
            return parsed
    env = os.environ.get("SEED")
    if env:
        return int(env, 0)
    sim_dir = _seed_from_sim_dir()
    if sim_dir is not None:
        return sim_dir
    return default


class RandMgr:
    """A seeded RNG that proxies ``random.Random`` and logs its seed.

    Use it anywhere a ``random.Random`` is expected; it simply resolves and
    records the seed for reproducibility, then delegates everything else.
    """

    def __init__(self, seed=None, name="rand"):
        self.seed = resolve_seed() if seed is None else seed
        self.rng = random.Random(self.seed)
        _log(
            f"[{name}] random seed = 0x{self.seed:08X} "
            f"(override with +seed=<n> plusarg or SEED=<n> env)"
        )

    def __getattr__(self, attr):
        # Delegate randint/choice/choices/random/shuffle/sample/... to the RNG.
        rng = self.__dict__.get("rng")
        if rng is not None:
            return getattr(rng, attr)
        raise AttributeError(attr)


# ---------------------------------------------------------------------------
# Constraint primitives
# ---------------------------------------------------------------------------
def in_range(rng, lo, hi, *, exclude=(), corners=(), corner_w=0.30):
    """Uniform int in ``[lo, hi]`` excluding *exclude*, with corner-biasing.

    With probability *corner_w*, return a legal value from *corners* (boundary /
    interesting values) instead of a uniform draw — this fills boundary bins
    that uniform sampling reaches only rarely.
    """
    if lo > hi:
        raise ValueError(f"in_range: empty range [{lo}, {hi}]")
    excl = set(exclude)
    if corners and rng.random() < corner_w:
        cand = [c for c in corners if lo <= c <= hi and c not in excl]
        if cand:
            return rng.choice(cand)
    for _ in range(1000):  # rejection sampling (ranges are small)
        v = rng.randint(lo, hi)
        if v not in excl:
            return v
    raise ValueError(f"in_range({lo},{hi}) exhausted with exclude={excl}")


def weighted(rng, choices):
    """Pick one value from ``[(value, weight), ...]`` by relative weight.

    Weights are relative (need not sum to anything): ``[(a,6),(b,4)]`` ==
    ``[(a,60),(b,40)]`` == 60%/40%.
    """
    vals = [c[0] for c in choices]
    wts = [c[1] for c in choices]
    return rng.choices(vals, weights=wts, k=1)[0]


def banded(rng, bands):
    """Weighted segmented range: pick a band by weight, then a uniform value in it.

    *bands* = ``[((lo, hi), weight), ...]``. Handy for "small/medium/large"
    distributions:
        banded(rng, [((1,8), 7), ((9,64), 2), ((65,256), 1)])
    """
    lo, hi = weighted(rng, [(b[0], b[1]) for b in bands])
    return rng.randint(lo, hi)


def rand_bytes(rng, n):
    """A list of *n* random bytes (0..0xFF)."""
    return [rng.randint(0, 0xFF) for _ in range(n)]


# ---------------------------------------------------------------------------
# Standalone self-test: `python constrained_random.py`
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    r = RandMgr(seed=0x1234, name="selftest")

    for _ in range(3000):
        v = in_range(r, 1, 256, exclude={128}, corners=[1, 256])
        assert 1 <= v <= 256 and v != 128

        sz = weighted(r, [("s", 7), ("l", 1)])
        assert sz in ("s", "l")

        b = banded(r, [((1, 8), 7), ((9, 64), 2), ((65, 256), 1)])
        assert 1 <= b <= 256

        assert len(rand_bytes(r, 4)) == 4

    # weight bias sanity (~0.6 write)
    cnt = sum(1 for _ in range(5000) if weighted(r, [("w", 6), ("r", 4)]) == "w")
    ratio = cnt / 5000
    assert 0.55 < ratio < 0.65, ratio
    print(f"constrained_random self-test PASSED (weight bias={ratio:.2f})")
