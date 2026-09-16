# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP DRBG noise-source golden model.

This model is the SINGLE SOURCE of entropy noise for the cocotb env: each
cycle cocotb calls ``step_all()`` once, drives the returned 12-bit word into
the DUT noise inputs, AND feeds the identical word into the decorrelator
golden. Because the PRNG state lives only in this object and advances exactly
one bit per lane per ``step_all()`` call, the DUT and the golden chain consume
an identical noise sequence by construction.

Per-lane noise model:
  1. If stuck_en      -> return stuck_val (prev_bit also latched to stuck_val)
  2. draw r_corr = xorshift32(state) % PROB_SCALE; if r_corr < p_corr
                      -> return prev_bit (correlation: repeat last bit)
  3. else draw r_ind = xorshift32(state) % PROB_SCALE; bit = (r_ind < p_bias)
  4. update prev_bit, return bit

PROB_SCALE = 1_000_000, so p_bias / p_corr are probabilities scaled to 1e6
(e.g. p_bias=800_000 -> P(bit==1)=0.80). MAX_LANES = 12.

Mode vocabulary (see configure()):
  "unbiased" / "bias50"  -> p_bias=500_000, p_corr=0            (fair coin)
  "biasNN"               -> p_bias=NN*10_000, p_corr=0          (NN = percent 0..100)
                            e.g. "bias80" -> p_bias=800_000  -> 80% ones
                                 "bias20" -> p_bias=200_000  -> 20% ones
  "corrNN"               -> p_corr=NN*10_000, p_bias=500_000    (NN = percent 0..100)
                            e.g. "corr95" -> p_corr=950_000  -> 95% repeat-prev
  "stuck0" / "stuck1"    -> stuck_en=1, stuck_val=0 / 1         (stuck-at fault)

  The "NN" in biasNN / corrNN is parsed generically as an integer percent in
  [0, 100] and multiplied by 10_000 to land on the PROB_SCALE grid; this
  uses ``noise_p_bias = percent * PROB_SCALE / 100``.

Per-lane modes: configure() takes either a single mode string (applied to all
12 lanes) or a list/dict of per-lane modes, so a fault (e.g. stuck0) can be
injected on a subset of lanes while the rest stay unbiased.
"""

MAX_LANES = 12
PROB_SCALE = 1_000_000


def xorshift32(s: int) -> int:
    """Advance the 32-bit xorshift PRNG.

    s ^= s << 13;
    s ^= s >> 17;
    s ^= s << 5;
    if (s == 0) s = 1;   /* Avoid zero state */
    """
    s ^= (s << 13) & 0xFFFFFFFF
    s ^= s >> 17
    s ^= (s << 5) & 0xFFFFFFFF
    s &= 0xFFFFFFFF
    if s == 0:
        s = 1
    return s


class _LaneCfg:
    """Per-lane noise configuration (p_bias, p_corr, stuck_en, stuck_val)."""

    __slots__ = ("p_bias", "p_corr", "stuck_en", "stuck_val")

    def __init__(self, p_bias=PROB_SCALE // 2, p_corr=0, stuck_en=0, stuck_val=0):
        self.p_bias = p_bias
        self.p_corr = p_corr
        self.stuck_en = stuck_en
        self.stuck_val = stuck_val


def parse_mode(mode: str) -> _LaneCfg:
    """Map a human mode name to a _LaneCfg. See module docstring for vocab."""
    m = mode.strip().lower()
    if m in ("unbiased", "bias50"):
        return _LaneCfg(p_bias=500_000, p_corr=0)
    if m == "stuck0":
        return _LaneCfg(stuck_en=1, stuck_val=0)
    if m == "stuck1":
        return _LaneCfg(stuck_en=1, stuck_val=1)
    if m.startswith("bias"):
        nn = int(m[len("bias") :])
        if not 0 <= nn <= 100:
            raise ValueError(f"biasNN percent out of range [0,100]: {mode}")
        return _LaneCfg(p_bias=nn * 10_000, p_corr=0)
    if m.startswith("corr"):
        nn = int(m[len("corr") :])
        if not 0 <= nn <= 100:
            raise ValueError(f"corrNN percent out of range [0,100]: {mode}")
        return _LaneCfg(p_bias=500_000, p_corr=nn * 10_000)
    raise ValueError(f"unknown noise mode: {mode!r}")


class SepNoiseGolden:
    """Deterministic per-lane noise generator.

    Each lane owns a xorshift32 PRNG state and previous bit. Lane
    configurations default to unbiased.
    """

    MAX_LANES = MAX_LANES
    PROB_SCALE = PROB_SCALE

    def __init__(self):
        self._state = [0] * MAX_LANES
        self._prev = [0] * MAX_LANES
        self._cfg = [_LaneCfg() for _ in range(MAX_LANES)]

    # ---------------------------------------------------------------- core
    def init_lane(self, lane: int, seed: int) -> None:
        """Set state to the seed, or ``lane + 1`` when the seed is zero."""
        if lane < 0 or lane >= MAX_LANES:
            return
        seed &= 0xFFFFFFFF
        self._state[lane] = seed if seed != 0 else (lane + 1)
        self._prev[lane] = 0

    def reset_all(self) -> None:
        """Clear every PRNG state and previous bit.

        A subsequent bit() on a lane that
        was never re-init'd would feed 0 into xorshift32, which maps 0->0->1.
        Always init_lane() (or configure(), which inits) before stepping.
        """
        for i in range(MAX_LANES):
            self._state[i] = 0
            self._prev[i] = 0

    def bit(self, lane, p_bias, p_corr, stuck_en, stuck_val) -> int:
        """Return one bit and advance the selected lane's state."""
        if lane < 0 or lane >= MAX_LANES:
            return 0

        # Stuck-at mode.
        if stuck_en:
            self._prev[lane] = 1 if stuck_val else 0
            return self._prev[lane]

        # Clamp probabilities.
        if p_bias > PROB_SCALE:
            p_bias = PROB_SCALE
        if p_corr > PROB_SCALE:
            p_corr = PROB_SCALE

        # Keep the previous bit with probability p_corr.
        self._state[lane] = xorshift32(self._state[lane])
        r_corr = self._state[lane] % PROB_SCALE
        if r_corr < p_corr:
            result = self._prev[lane]
        else:
            # Generate an independent biased bit.
            self._state[lane] = xorshift32(self._state[lane])
            r_ind = self._state[lane] % PROB_SCALE
            result = 1 if r_ind < p_bias else 0

        self._prev[lane] = result
        return result

    def get_state(self, lane: int) -> int:
        """Return lane PRNG state for debug or replay."""
        if lane < 0 or lane >= MAX_LANES:
            return 0
        return self._state[lane]

    # ------------------------------------------------------------ mode layer
    def configure(self, mode, seed_base: int = 0x1234_5678) -> None:
        """Configure all lanes' noise modes and (re)seed their PRNGs.

        ``mode`` may be:
          * a single mode string -> applied to every lane.
          * a list of mode strings (len <= MAX_LANES) -> per-lane; missing
            tail lanes default to "unbiased".
          * a dict {lane_index: mode_string} -> only those lanes overridden,
            the rest are "unbiased". Lets faults hit a subset of lanes.

        Each lane is seeded with (seed_base + lane) so lanes are decorrelated
        yet fully reproducible. seed_base==0 would make lane 0 use its
        (lane+1) fallback per init_lane().
        """
        modes = self._normalize_modes(mode)
        for lane in range(MAX_LANES):
            self._cfg[lane] = parse_mode(modes[lane])
            self.init_lane(lane, (seed_base + lane) & 0xFFFFFFFF)

    @staticmethod
    def _normalize_modes(mode):
        if isinstance(mode, str):
            return [mode] * MAX_LANES
        if isinstance(mode, dict):
            modes = ["unbiased"] * MAX_LANES
            for lane, mstr in mode.items():
                if not 0 <= lane < MAX_LANES:
                    raise ValueError(f"lane index out of range: {lane}")
                modes[lane] = mstr
            return modes
        if isinstance(mode, (list, tuple)):
            if len(mode) > MAX_LANES:
                raise ValueError(f"too many lane modes: {len(mode)} > {MAX_LANES}")
            modes = list(mode) + ["unbiased"] * (MAX_LANES - len(mode))
            return modes
        raise TypeError(f"mode must be str/list/dict, got {type(mode)}")

    def step_all(self) -> int:
        """Advance every lane one bit; pack into a 12-bit int (lane i -> bit i).

        Deterministic: exactly one bit() per lane per call, using each lane's
        configured mode. This is the per-cycle noise word cocotb drives into
        the DUT and feeds into the decorrelator golden.
        """
        word = 0
        for lane in range(MAX_LANES):
            c = self._cfg[lane]
            b = self.bit(lane, c.p_bias, c.p_corr, c.stuck_en, c.stuck_val)
            word |= (b & 1) << lane
        return word


# ===========================================================================
# Self-test (plain python3, no simulator):
#   cd .../dv/cocotb/env && python3 sep_noise_golden.py
# ===========================================================================
if __name__ == "__main__":
    # (1) xorshift32 KAT — first 5 outputs from two known seeds, computed
    #     directly from the exact algorithm.
    s = 1
    seq = []
    for _ in range(5):
        s = xorshift32(s)
        seq.append(s)
    expect_seed1 = [0x42021, 0x4080601, 0x9DCCA8C5, 0x1255994F, 0x8EF917D1]
    assert seq == expect_seed1, f"xorshift32 seed=1 KAT mismatch: {[hex(x) for x in seq]}"

    s = 0x12345678
    seq = []
    for _ in range(5):
        s = xorshift32(s)
        seq.append(s)
    expect_seed2 = [0x87985AA5, 0x155B24A3, 0x4820F4C4, 0x81B3AC98, 0x703A0788]
    assert seq == expect_seed2, f"xorshift32 seed=0x12345678 KAT mismatch: {[hex(x) for x in seq]}"
    print("  (1) xorshift32 KAT ......... PASS")

    N = 200_000

    def ones_fraction(mode):
        g = SepNoiseGolden()
        g.configure(mode)
        ones = 0
        for _ in range(N):
            if g.bit(
                0, g._cfg[0].p_bias, g._cfg[0].p_corr, g._cfg[0].stuck_en, g._cfg[0].stuck_val
            ):
                ones += 1
        return ones / N

    # (2) bias fractions
    f80 = ones_fraction("bias80")
    f20 = ones_fraction("bias20")
    f50 = ones_fraction("bias50")
    assert abs(f80 - 0.80) < 0.01, f"bias80 ones-fraction {f80:.4f} not ~0.80"
    assert abs(f20 - 0.20) < 0.01, f"bias20 ones-fraction {f20:.4f} not ~0.20"
    assert abs(f50 - 0.50) < 0.01, f"bias50 ones-fraction {f50:.4f} not ~0.50"
    print(f"  (2) bias fractions ......... PASS (80->{f80:.4f} 20->{f20:.4f} 50->{f50:.4f})")

    # (3) correlation: repeat-rate = P(bit == prev_bit)
    def repeat_rate(mode):
        g = SepNoiseGolden()
        g.configure(mode)
        c = g._cfg[0]
        prev = g.bit(0, c.p_bias, c.p_corr, c.stuck_en, c.stuck_val)
        same = 0
        for _ in range(N):
            cur = g.bit(0, c.p_bias, c.p_corr, c.stuck_en, c.stuck_val)
            if cur == prev:
                same += 1
            prev = cur
        return same / N

    r90 = repeat_rate("corr90")
    r0 = repeat_rate("corr0")  # p_corr=0 -> independent unbiased -> ~0.50 repeat
    assert r90 > 0.90, f"corr90 repeat-rate {r90:.4f} not > 0.90"
    assert abs(r0 - 0.50) < 0.01, f"corr0 repeat-rate {r0:.4f} not ~0.50 (independent)"
    print(f"  (3) correlation ............ PASS (corr90 repeat->{r90:.4f} corr0->{r0:.4f})")

    # (4) stuck-at: every bit is the stuck value
    for mode, val in (("stuck0", 0), ("stuck1", 1)):
        g = SepNoiseGolden()
        g.configure(mode)
        c = g._cfg[0]
        for _ in range(1000):
            b = g.bit(0, c.p_bias, c.p_corr, c.stuck_en, c.stuck_val)
            assert b == val, f"{mode}: got {b}, expected {val}"
    print("  (4) stuck-at ............... PASS")

    # (5) reproducibility: same seed+mode -> identical step_all() stream.
    g1 = SepNoiseGolden()
    g1.configure("bias80", seed_base=0xCAFEBABE)
    g2 = SepNoiseGolden()
    g2.configure("bias80", seed_base=0xCAFEBABE)
    stream1 = [g1.step_all() for _ in range(5000)]
    stream2 = [g2.step_all() for _ in range(5000)]
    assert stream1 == stream2, "reproducibility: identical config produced different streams"
    # Different seed_base -> different stream (sanity that seed actually matters)
    g3 = SepNoiseGolden()
    g3.configure("bias80", seed_base=0x0BADF00D)
    stream3 = [g3.step_all() for _ in range(5000)]
    assert stream1 != stream3, "seed_base had no effect on the stream"
    print("  (5) reproducibility ........ PASS")

    # Bonus: per-lane fault injection via dict mode (subset of lanes stuck).
    g = SepNoiseGolden()
    g.configure({1: "stuck1", 3: "stuck0", 5: "bias80"})
    w = g.step_all()
    assert (w >> 1) & 1 == 1, "lane 1 should be stuck-1"
    assert (w >> 3) & 1 == 0, "lane 3 should be stuck-0"

    print("NOISE GOLDEN SELFTEST PASS")
