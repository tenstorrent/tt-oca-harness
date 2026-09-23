# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Reusable entropy-source decorrelator golden model.

Independent model of the 12-lane 29-stage XOR-feedback decorrelator
in ``hw/ip/entropy_source/doc/architecture.adoc``.

The decorrelator reduces serial correlation in ring-oscillator noise. Each of
12 lanes owns a 29-bit shift register (a prime length) with MSB->LSB XOR
feedback. Every ``sample_clk_div+1`` cycles, the top 8 bits are sampled (masked
by ``byte_mask``) and emitted as one entropy byte, downsampling the bit rate.

Transform per lane, per clock:
  1. SAMPLE (when clk_divider==0, BEFORE the shift -- non-blocking semantics):
         raw_byte     = (ff_stage >> 21) & 0xFF
         output_byte  = raw_byte & byte_mask
         clk_divider  = sample_clk_div
     else: clk_divider -= 1
  2. SHIFT (always, uses CURRENT/pre-edge ff_stage for feedback):
         feedback = 0 if bypass else (ff_stage >> 28) & 1
         new_bit  = noise_bit ^ feedback
         ff_stage = ((ff_stage << 1) | new_bit) & 0x1FFFFFFF

Smoke config: sample_clk_div=7 (i.e. /8 downsample,
one byte every 8 cycles), byte_mask=0xFF, bypass=0.
"""

MAX_LANES = 12
SR_LENGTH = 29
SR_MASK = (1 << SR_LENGTH) - 1  # 0x1FFFFFFF
FEEDBACK_SHIFT = SR_LENGTH - 1  # 28
SAMPLE_SHIFT = SR_LENGTH - 8  # 21


class _Lane:
    """Per-lane decorrelator state."""

    __slots__ = (
        "ff_stage",
        "clk_divider",
        "sample_clk_div",
        "byte_mask",
        "bypass",
        "enable",
        "output_byte",
        "output_valid",
        "sample_count",
    )

    def __init__(self):
        self.ff_stage = 0
        self.clk_divider = 0
        self.sample_clk_div = 0
        self.byte_mask = 0
        self.bypass = 0
        self.enable = 0
        self.output_byte = 0
        self.output_valid = 0
        self.sample_count = 0


class EntropyDecorrelatorModel:
    """Pure-Python golden model of the 12-lane DRBG entropy decorrelator."""

    def __init__(self):
        self._lanes = [_Lane() for _ in range(MAX_LANES)]

    # ----- configuration -----------------------------------------------------
    def init(self, lane, sample_clk_div, bypass, byte_mask):
        """Initialize one lane.

        sample_clk_div : reload value = actual_period - 1 (e.g. 7 for /8).
        bypass         : 1 => feedback path broken (raw shift).
        byte_mask      : 8-bit output mask.
        """
        if lane < 0 or lane >= MAX_LANES:
            return
        L = self._lanes[lane]
        L.ff_stage = 0
        L.output_byte = 0
        L.sample_clk_div = sample_clk_div & 0xFFFFFFFF
        L.clk_divider = sample_clk_div & 0xFFFFFFFF
        L.bypass = 1 if bypass else 0
        L.byte_mask = byte_mask & 0xFF
        L.enable = 1
        L.output_valid = 0
        L.sample_count = 0

    def init_all(self, sample_clk_div, bypass, byte_mask):
        """Convenience: reset + init all 12 lanes identically."""
        self.reset_all()
        for i in range(MAX_LANES):
            self.init(i, sample_clk_div, bypass, byte_mask)

    def reset_all(self):
        """Zero every lane."""
        for i in range(MAX_LANES):
            self._lanes[i] = _Lane()

    # Reference-model control API.
    def set_bypass(self, lane, bypass):
        if 0 <= lane < MAX_LANES:
            self._lanes[lane].bypass = 1 if bypass else 0

    def set_enable(self, lane, enable):
        if 0 <= lane < MAX_LANES:
            self._lanes[lane].enable = 1 if enable else 0
            if not enable:
                self._lanes[lane].output_valid = 0

    # ----- stepping ----------------------------------------------------------
    def step(self, lane, noise_bit):
        """Advance one lane by one clock."""
        if lane < 0 or lane >= MAX_LANES:
            return
        L = self._lanes[lane]

        L.output_valid = 0
        if not L.enable:
            return

        # Sample before shifting so the pre-edge state is observed.
        if L.clk_divider == 0:
            raw_byte = (L.ff_stage >> SAMPLE_SHIFT) & 0xFF
            L.output_byte = raw_byte & L.byte_mask
            L.output_valid = 1
            L.clk_divider = L.sample_clk_div
            L.sample_count += 1
        else:
            L.clk_divider -= 1

        # Shift using the current register state.
        nb = 1 if noise_bit else 0
        feedback = 0 if L.bypass else ((L.ff_stage >> FEEDBACK_SHIFT) & 1)
        new_bit = nb ^ feedback
        L.ff_stage = ((L.ff_stage << 1) | new_bit) & SR_MASK

    def step_all(self, noise_bits_12):
        """Step all 12 lanes; noise_bits_12 is a packed int, bit i -> lane i."""
        bits = noise_bits_12 & 0xFFFFFFFF
        for i in range(MAX_LANES):
            self.step(i, (bits >> i) & 1)

    # ----- queries -----------------------------------------------------------
    def output_valid(self, lane):
        if lane < 0 or lane >= MAX_LANES:
            return 0
        return 1 if self._lanes[lane].output_valid else 0

    def get_output(self, lane):
        if lane < 0 or lane >= MAX_LANES:
            return 0
        return self._lanes[lane].output_byte & 0xFF

    def get_all_outputs(self):
        """Pack all 12 output bytes: lane0 in [7:0] .. lane11 in [95:88].

        Returns a 96-bit Python int.
        """
        out = 0
        for i in range(MAX_LANES):
            out |= (self._lanes[i].output_byte & 0xFF) << (i * 8)
        return out

    # Reference-model observation API.
    def get_sample_count(self, lane):
        if lane < 0 or lane >= MAX_LANES:
            return 0
        return self._lanes[lane].sample_count

    def get_sr(self, lane):
        if lane < 0 or lane >= MAX_LANES:
            return 0
        return self._lanes[lane].ff_stage

    def set_sr(self, lane, ff_stage):
        """Seed one lane's 29-bit shift register from the live RTL state.

        ``ff_stage`` resets only on the hardware rst_ni, and its reset edge is
        not observable from the sampled output (decor_bytes lags it by a divider
        period). The scoreboard snapshots the real RTL ff_stage via a probe and
        seeds it here, so the feedback SR (whose state never flushes) runs in
        exact lockstep from a known cycle instead of an unknowable reset phase.
        """
        if 0 <= lane < MAX_LANES:
            self._lanes[lane].ff_stage = ff_stage & SR_MASK

    def set_divider(self, lane, clk_divider):
        """Phase-align one lane's downsample divider to the RTL (for the sampled
        CHK2..CHK5 chain): set so the golden's next valid byte lands on the same
        cycle the RTL emits its next decor sample."""
        if 0 <= lane < MAX_LANES:
            self._lanes[lane].clk_divider = clk_divider & 0xFFFFFFFF


# =============================================================================
# Self-test (run with plain Python; no cocotb or simulator).
# =============================================================================
def _independent_oracle_step(
    ff_stage, clk_divider, sample_clk_div, byte_mask, bypass, noise_bit, sample_after_shift=False
):
    """Independent re-implementation of the per-clock step, returning the new state.

    It does not call the class, so it serves as an oracle. ``sample_after_shift=True``
    inverts the sample/shift order so the self-test can show the ordering matters.
    """
    output_valid = 0
    output_byte = 0

    def do_sample(src_ff, divider):
        raw = (src_ff >> SAMPLE_SHIFT) & 0xFF
        return (raw & byte_mask), sample_clk_div
        # divider reload handled by caller

    if not sample_after_shift:
        # ---- RTL ordering: SAMPLE then SHIFT ----
        if clk_divider == 0:
            raw = (ff_stage >> SAMPLE_SHIFT) & 0xFF
            output_byte = raw & byte_mask
            output_valid = 1
            clk_divider = sample_clk_div
        else:
            clk_divider -= 1
        fb = 0 if bypass else ((ff_stage >> FEEDBACK_SHIFT) & 1)
        new_bit = (1 if noise_bit else 0) ^ fb
        ff_stage = ((ff_stage << 1) | new_bit) & SR_MASK
    else:
        # ---- WRONG ordering: SHIFT then SAMPLE (blocking-like) ----
        fb = 0 if bypass else ((ff_stage >> FEEDBACK_SHIFT) & 1)
        new_bit = (1 if noise_bit else 0) ^ fb
        ff_stage = ((ff_stage << 1) | new_bit) & SR_MASK
        if clk_divider == 0:
            raw = (ff_stage >> SAMPLE_SHIFT) & 0xFF
            output_byte = raw & byte_mask
            output_valid = 1
            clk_divider = sample_clk_div
        else:
            clk_divider -= 1

    return ff_stage, clk_divider, output_valid, output_byte


def _selftest():
    # --- Test 1: /8 valid cadence across all 12 lanes for a few hundred cycles ---
    dut = EntropyDecorrelatorModel()
    dut.init_all(sample_clk_div=7, bypass=0, byte_mask=0xFF)

    # Deterministic per-lane noise: lane i toggles on a different period.
    def noise_word(cyc):
        w = 0
        for ln in range(MAX_LANES):
            bit = (cyc >> (ln % 5)) & 1
            w |= bit << ln
        return w

    N_CYCLES = 400
    valid_cycles = {ln: [] for ln in range(MAX_LANES)}
    for cyc in range(N_CYCLES):
        dut.step_all(noise_word(cyc))
        for ln in range(MAX_LANES):
            if dut.output_valid(ln):
                valid_cycles[ln].append(cyc)

    for ln in range(MAX_LANES):
        vc = valid_cycles[ln]
        assert len(vc) >= 2, f"lane {ln}: too few valid pulses ({len(vc)})"
        deltas = [vc[k + 1] - vc[k] for k in range(len(vc) - 1)]
        assert all(d == 8 for d in deltas), f"lane {ln}: valid cadence not /8: deltas={deltas}"
    # With init clk_divider=7, first sample is at cycle 7, then every 8.
    for ln in range(MAX_LANES):
        assert valid_cycles[ln][0] == 7, (
            f"lane {ln}: first valid at {valid_cycles[ln][0]}, expected 7"
        )

    # --- Test 2: hand-traced oracle for a SHORT known ~40-bit noise pattern ---
    # Drive lane 0 with a known noise sequence; compare class vs independent
    # oracle state cycle by cycle, including the first sampled byte.
    noise_pattern = [
        1,
        0,
        1,
        1,
        0,
        0,
        1,
        0,
        1,
        1,
        1,
        0,
        0,
        1,
        0,
        1,
        0,
        0,
        1,
        1,
        0,
        1,
        1,
        0,
        1,
        0,
        1,
        1,
        0,
        0,
        1,
        1,
        0,
        0,
        1,
        0,
        1,
        0,
        1,
        1,
    ]  # 40 bits
    g = EntropyDecorrelatorModel()
    g.init(0, sample_clk_div=7, bypass=0, byte_mask=0xFF)

    # Oracle state mirror
    o_ff = 0
    o_div = 7
    first_sample = None
    first_sample_cyc = None
    for cyc, nb in enumerate(noise_pattern):
        g.step(0, nb)
        o_ff, o_div, o_valid, o_byte = _independent_oracle_step(
            o_ff, o_div, 7, 0xFF, 0, nb, sample_after_shift=False
        )
        assert g.get_sr(0) == o_ff, (
            f"cyc {cyc}: class ff_stage {g.get_sr(0):#x} != oracle {o_ff:#x}"
        )
        assert g.output_valid(0) == o_valid, (
            f"cyc {cyc}: valid mismatch class={g.output_valid(0)} oracle={o_valid}"
        )
        if o_valid:
            assert g.get_output(0) == o_byte, (
                f"cyc {cyc}: byte mismatch class={g.get_output(0):#x} oracle={o_byte:#x}"
            )
            if first_sample is None:
                first_sample = o_byte
                first_sample_cyc = cyc

    assert first_sample_cyc == 7, f"first sample at cyc {first_sample_cyc}, expected 7"
    # Hand-trace the first sampled byte literally: at cyc 7, sample reads the
    # ff_stage value present at the START of cyc 7 (i.e. after 7 shifts from
    # cycles 0..6), masked to bits [28:21]. With only 7 bits shifted in, the
    # top bits are still 0, so the first byte must be 0x00.
    assert first_sample == 0x00, (
        f"first sampled byte {first_sample:#x} != 0x00 (only 7 bits shifted, top bits 0)"
    )

    # --- Test 3: prove the non-blocking ordering MATTERS ---
    # Build a pattern long enough that the sampled byte is nonzero, then show
    # the WRONG (sample-after-shift) ordering produces a different byte.
    long_pattern = [(0xA5C3 >> (i % 16)) & 1 for i in range(64)]

    # correct ordering via class
    gc = EntropyDecorrelatorModel()
    gc.init(0, sample_clk_div=7, bypass=0, byte_mask=0xFF)
    correct_bytes = []
    for nb in long_pattern:
        gc.step(0, nb)
        if gc.output_valid(0):
            correct_bytes.append(gc.get_output(0))

    # wrong ordering via oracle (sample_after_shift=True)
    w_ff, w_div = 0, 7
    wrong_bytes = []
    for nb in long_pattern:
        w_ff, w_div, w_valid, w_byte = _independent_oracle_step(
            w_ff, w_div, 7, 0xFF, 0, nb, sample_after_shift=True
        )
        if w_valid:
            wrong_bytes.append(w_byte)

    assert correct_bytes != wrong_bytes, (
        "sample-before-shift and sample-after-shift produced identical byte "
        "streams -- ordering test is not discriminating!\n"
        f"  correct={[hex(b) for b in correct_bytes]}\n"
        f"  wrong  ={[hex(b) for b in wrong_bytes]}"
    )

    # --- Test 4: get_all_outputs framing (lane0 in [7:0]) ---
    f = EntropyDecorrelatorModel()
    f.init_all(sample_clk_div=7, bypass=0, byte_mask=0xFF)
    for i in range(MAX_LANES):
        f._lanes[i].output_byte = (0x10 + i) & 0xFF
    packed = f.get_all_outputs()
    for i in range(MAX_LANES):
        lane_byte = (packed >> (i * 8)) & 0xFF
        assert lane_byte == ((0x10 + i) & 0xFF), (
            f"framing: lane {i} byte {lane_byte:#x} != {0x10 + i:#x}"
        )
    assert (packed & 0xFF) == 0x10, "lane0 must occupy bits [7:0]"

    print("DECOR GOLDEN SELFTEST PASS")


if __name__ == "__main__":
    _selftest()
