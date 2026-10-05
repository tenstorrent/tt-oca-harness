# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2024-2026 Tenstorrent USA, Inc.
#
# sep_entropy_golden.py
#
# End-to-end SEP entropy-datapath golden FACADE. Chains the five self-tested
# stage models into one stream-oriented model that a
# cocotb scoreboard can compare against DUT probes:
#
#   noise (12b/cyc)  ->  decorrelator (96b/decor-valid)
#                     ->  BIW compress (32b/decor-valid)
#                     ->  SHA-256 conditioner (whitening: 16:1 -> 8x32b digest)
#                     ->  seed accumulate (12 words -> 384b es_bits)
#                     ->  CTR_DRBG instantiate+generate (glen x 128b genbits)
#                     ->  EDN->KM slice (each 128b block -> 4x32b beats)
#
# This module REUSES the stage models verbatim; it does not reimplement them:
#   EntropyNoiseModel      (standalone self-test noise source)
#   EntropyDecorrelatorModel (12-lane 29b SR decorrelator)
#   EntropyBiwModel        (12 bytes -> 32b BIW word)
#   EntropySha256Model     (16x32b -> 8x32b digest)
#   sep_ctr_drbg_golden.SepCtrDrbgGolden (AES-256 no-df CTR_DRBG)
#
# In simulation, SepDrbgScoreboard does not use these internal sources for the
# DUT/golden correlation. It drives tb_top.esrc_noise_ext_i directly and calls
# feed_noise() / feed_decor_sample() from DUT-observed strobes, so the DUT and
# golden consume the same externally-driven raw-noise sequence.
#
# Inter-stage framing (matches the reference scoreboard):
#   - sample_clk_div=7 (/8): each lane emits a byte every 8 cycles; the 12 lane
#     bytes pack into a 96b decor word (lane0 -> [7:0]) on a decor-valid event.
#   - one BIW 32b word per decor-valid event (out[0] -> word[31:24]).
#   - whitening ON: 16 BIW words -> one SHA block -> 8x32b digest words.
#   - seed: accumulate 12 consecutive 32b compressor-output words (post-SHA when
#     whitening) -> 384b es_bits (word0 -> bits[31:0]). ``ingress_skip`` words are
#     dropped before seed accumulation. It defaults to 0: the seed adapter takes
#     one 32-bit word per valid cycle directly from the entropy source, with no
#     upstream routing or distribution FIFO (hw/ip/drbg/doc/architecture.adoc,
#     Seed Assembly), so no word is absorbed ahead of the packer.
#   - CTR_DRBG: first 384b seed -> instantiate; generate glen 128b blocks.
#   - EDN->KM: each 128b block -> 4x32b beats, LSW-first
#     beat0=block[31:0], beat1=[63:32], beat2=[95:64], beat3=[127:96].
#     (Documented; scoreboard confirms against the DUT probe and may flip to
#     MSW-first via ``km_word_order``.)

from collections import deque

from models.entropy_conditioning_model import (
    EntropyBiwModel,
    EntropySha256Model,
)
from models.entropy_decorrelator_model import (
    MAX_LANES,
    EntropyDecorrelatorModel,
)
from models.entropy_noise_model import EntropyNoiseModel
from sep_ctr_drbg_golden import BLOCK_LEN, SEED_LEN, SepCtrDrbgGolden

SEED_WORDS = SEED_LEN // 32  # 12 compressor words make one 384b seed
KM_BEATS_PER_BLOCK = BLOCK_LEN // 32  # 4 x 32b beats per 128b genbits block


class SepEntropyGolden:
    """End-to-end SEP entropy golden facade (stream-oriented).

    Drive with ``step_cycle()`` once per DUT clock. Expected items accumulate
    on per-stage queues a scoreboard pops as the matching DUT probe events fire:

      expected_decor_bytes    96b decor word, one per decor-valid
      expected_compress_words 32b compressor-output word (post-SHA when
                              whitening), one per produced word
      expected_seed           384b es_bits seed, one per seed
      expected_genbits        128b genbits block, one per genbits_block() call
      expected_km_words       32b KM beat, KM_BEATS_PER_BLOCK per genbits block

    The decor/compress/seed stages are pure stream models: step_cycle() fills
    them ahead of the DUT. Genbits are different -- they are DEMAND-driven, so
    the scoreboard pulls them one at a time with genbits_block() and closes each
    Generate command with genbits_gen_last() on the observed gen_last strobe.
    """

    def __init__(
        self,
        *,
        sample_clk_div=7,
        byte_mask=0xFF,
        bypass=False,
        sha_whitening=True,
        glen=32,
        ingress_skip=0,
        noise_model_mode="unbiased",
        noise_seed_base=0x1234_5678,
        km_word_order="lsw",
    ):
        self.sample_clk_div = sample_clk_div
        self.byte_mask = byte_mask & 0xFF
        self.bypass = bool(bypass)
        self.sha_whitening = bool(sha_whitening)
        self.glen = glen
        self.ingress_skip = ingress_skip
        if km_word_order not in ("lsw", "msw"):
            raise ValueError("km_word_order must be 'lsw' or 'msw'")
        self.km_word_order = km_word_order

        # --- standalone self-test noise source ----------------------------
        self._noise = EntropyNoiseModel()
        self._noise.configure(noise_model_mode, seed_base=noise_seed_base)

        # --- stage models -------------------------------------------------
        self._decor = EntropyDecorrelatorModel()
        self._decor.init_all(
            sample_clk_div=sample_clk_div, bypass=self.bypass, byte_mask=self.byte_mask
        )
        self._sha = EntropySha256Model(16) if self.sha_whitening else None
        self._drbg = SepCtrDrbgGolden()

        # --- accumulators -------------------------------------------------
        self._ingress_seen = 0  # compressor words observed (for skip)
        self._seed_words = []  # accumulating 12 words for current seed
        self._seed_done = False  # first seed instantiated?
        self._generate_active = False  # a Generate command is in flight
        self._reseed_pending = None  # seed held until the in-flight gen_last

        # --- expected-item queues ----------------------------------------
        self.expected_decor_bytes = deque()
        self.expected_compress_words = deque()
        self.expected_seed = deque()
        self.expected_genbits = deque()
        self.expected_km_words = deque()

        # --- running counters (diagnostics / self-test) ------------------
        self.cycle = 0
        self.n_decor_valid = 0
        self.n_compress_words = 0
        self.n_seeds = 0
        self.n_genbits = 0
        self.n_km_words = 0
        self.n_generates = 0  # Generate commands finalized (gen_last)

    def seed_decor_sr(self, sr_packed, clk_divider=None):
        """Seed the independent golden SR from a live ff_stage snapshot.

        The architecture names a 29-stage feedback SR that is not
        software-visible, so the reset phase has no frontdoor. A wrong
        phase never flushes -- it rotates. The snapshot is chain-of-custody
        for the starting state, not a transcribed golden. The transform
        itself comes from entropy_source architecture.adoc.
        """
        for lane in range(MAX_LANES):
            self._decor.set_sr(lane, (sr_packed >> (29 * lane)) & 0x1FFFFFFF)
            if clk_divider is not None:
                self._decor.set_divider(lane, clk_divider)

    def decor_sr_word(self):
        """The raw 12-lane decorrelator SR byte word RIGHT NOW (ff[28:21] per lane,
        lane0 in [7:0]) -- the value the DUT samples when its divider fires. The
        scoreboard compares this to esrc_decor_bytes_o at each DUT decor-change
        cycle, sidestepping the model's own divider phase (CHK1)."""
        w = 0
        for lane in range(MAX_LANES):
            w |= ((self._decor.get_sr(lane) >> 21) & 0xFF) << (8 * lane)
        return w

    # ----------------------------------------------------------------- drive
    def step_cycle(self):
        """Advance one DUT cycle using the INTERNAL noise source (standalone use):
        steps the SR and, when its own divider fires, drives the chain. (In sim the
        scoreboard instead calls feed_noise + feed_decor_sample off RTL strobes.)"""
        self.feed_noise(self._noise.step_all())
        if self._decor.output_valid(0):
            self.feed_decor_sample(self._decor.get_all_outputs())

    def feed_noise(self, noise, enable_mask=0xFFF):
        """Advance ONLY the decorrelator shift register one DUT cycle (CHK1). The
        scoreboard drives the same noise into the DUT through tb_top.esrc_noise_ext_i
        and seeds this SR from the live RTL ff_stage, so golden and DUT evolve in
        lockstep.

        The post-decorrelator chain (CHK2..CHK5) is driven SEPARATELY by
        feed_decor_sample() off the DUT's per-sample decor-valid strobe -- this
        decouples the SHA 16:1 block boundary from the model's own divider phase,
        so the conditioner aligns with the RTL by construction.

        enable_mask mirrors the DUT per-lane decorrelator enable (esrc_ro_enable_o)
        so the golden only shifts on the cycles the DUT does."""
        self.cycle += 1
        for lane in range(MAX_LANES):
            self._decor.set_enable(lane, (enable_mask >> lane) & 1)
        self._decor.step_all(noise)

    def feed_decor_sample(self, decor_word):
        """Drive the post-decorrelator chain with ONE CHK1-verified 96b decor
        sample (lane0 in [7:0]), taken at a DUT decor-valid strobe. Enqueues the
        CHK2..CHK5 expected items: BIW compress -> SHA-256 whitening -> seed
        accumulate -> CTR_DRBG instantiate/generate -> EDN/KM beats. Because it is
        called once per DUT decor-valid (every sample, including repeated SR-fill
        zeros), the golden's SHA consumes exactly the RTL's BIW-word sequence."""
        decor_word &= (1 << 96) - 1
        self.expected_decor_bytes.append(decor_word)
        self.n_decor_valid += 1

        # BIW compress: 12 lane-bytes -> one 32b word.
        biw_word = EntropyBiwModel.compress_from_packed(decor_word)

        # Conditioning: whitening ON feeds BIW into SHA; the compressor-output
        # words the scoreboard sees are the post-SHA digest words (8 per block).
        if self.sha_whitening:
            if self._sha.push_word(biw_word):
                for w in self._sha.get_digest_words():  # word[0] first
                    self._consume_compress_word(w)
        else:
            self._consume_compress_word(biw_word)

    # --------------------------------------------------------- internal chain
    def _consume_compress_word(self, word):
        """One compressor-output 32b word: enqueue, honor ingress skip, seed-acc."""
        word &= 0xFFFFFFFF
        self.expected_compress_words.append(word)
        self.n_compress_words += 1

        # Words dropped ahead of the seed packer (0 for this DRBG, see the header).
        if self._ingress_seen < self.ingress_skip:
            self._ingress_seen += 1
            return

        # Accumulate 12 words -> 384b seed (word0 -> bits[31:0]).
        self._seed_words.append(word)
        if len(self._seed_words) < SEED_WORDS:
            return

        seed = 0
        for i, w in enumerate(self._seed_words):
            seed |= (w & 0xFFFFFFFF) << (32 * i)  # word0 -> [31:0]
        self._seed_words = []
        self.expected_seed.append(seed)
        self.n_seeds += 1

        self._run_drbg(seed)

    def _run_drbg(self, seed):
        """Apply a seed to the CTR_DRBG state. Produces no blocks.

        Genbits are NOT generated here. How many blocks a seed yields, and where
        each Generate's trailing Update lands, is decided by EDN endpoint
        demand: with all three DRBG EDN endpoints live (KM, crypto adapter,
        entropy pool) a single seed routinely serves more than one Generate
        command. Blocks are therefore produced lazily by genbits_block(), and
        the command boundary is taken from the observed gen_last strobe via
        genbits_gen_last(). See SepCtrDrbgGolden.generate_one().
        """
        if not self._seed_done:
            self._drbg.instantiate(seed)
            self._seed_done = True
            return

        # CSRNG processes a Reseed BETWEEN Generate commands. If a Generate is
        # in flight the new Key/V must not take effect until it finalizes --
        # applying it early would corrupt every remaining block of that command.
        if self._generate_active:
            self._reseed_pending = seed
        else:
            self._drbg.reseed(seed)

    # ------------------------------------------------- demand-driven genbits
    def genbits_block(self):
        """Produce the next predicted 128b genbits block (and its KM beats).

        Called once per observed RTL genbits beat. Returns None before the first
        seed has instantiated the DRBG -- the pre-model boot window, where no
        prediction can exist.
        """
        if not self._seed_done:
            return None
        self._generate_active = True
        blk = self._drbg.generate_one() & ((1 << BLOCK_LEN) - 1)
        self.expected_genbits.append(blk)
        self.n_genbits += 1
        for beat in self._km_beats(blk):
            self.expected_km_words.append(beat)
            self.n_km_words += 1
        return blk

    def genbits_gen_last(self):
        """RTL marked the end of a Generate command: run the single trailing
        Update, then apply any reseed deferred while the command was in flight."""
        if not self._seed_done:
            return
        self._drbg.generate_done()
        self._generate_active = False
        self.n_generates += 1
        if self._reseed_pending is not None:
            self._drbg.reseed(self._reseed_pending)
            self._reseed_pending = None

    def _km_beats(self, block):
        """Slice a 128b genbits block into 4x32b KM beats.

        LSW-first (default): beat0=block[31:0] .. beat3=block[127:96].
        MSW-first: beat0=block[127:96] .. beat3=block[31:0].
        """
        words = [(block >> (32 * i)) & 0xFFFFFFFF for i in range(KM_BEATS_PER_BLOCK)]
        if self.km_word_order == "lsw":
            return words
        return list(reversed(words))


# ===========================================================================
# Offline self-test (plain python3, NO simulator):
#   cd .../dv/cocotb/env && python3 sep_entropy_golden.py
# ===========================================================================
if __name__ == "__main__":
    GLEN = 32
    # hw/ip/drbg/doc/architecture.adoc: no distribution FIFO ahead of the packer.
    INGRESS = 0

    g = SepEntropyGolden(
        sample_clk_div=7,
        byte_mask=0xFF,
        bypass=False,
        sha_whitening=True,
        glen=GLEN,
        ingress_skip=INGRESS,
    )

    # ----- Run enough cycles to produce >= 2 seeds (so reseed path exercises) -----
    # words/seed accounting (whitening): need (ingress_skip + N*12) post-SHA
    # digest words; each SHA block yields 8 words and consumes 16 BIW words; each
    # BIW word costs one decor-valid (= 8 cycles). For 2 seeds:
    #   words_needed = ingress_skip + 2*12 = 36 digest words
    #   sha_blocks   = ceil(36/8) = 5 -> 80 BIW words -> 80 decor-valids
    #   cycles       = ~ (80+1)*8 plus startup; run generously.
    TARGET_SEEDS = 2
    max_cycles = 200_000
    while g.n_seeds < TARGET_SEEDS and g.cycle < max_cycles:
        g.step_cycle()
    assert g.n_seeds >= TARGET_SEEDS, f"only {g.n_seeds} seeds after {g.cycle} cycles"

    # ----- (a) decor-valid cadence is /8 -----
    # First valid at cycle 8 (init clk_divider=7 -> 7 decrements then sample),
    # every 8 thereafter. We count: total decor-valids over elapsed cycles.
    assert g.n_decor_valid >= 1, "no decor-valid events"
    # Timing-cadence proof on a fresh model: collect the cycle indices of valids.
    probe = SepEntropyGolden()
    valids = []
    for c in range(1, 200):
        probe.step_cycle()
        if probe._decor.output_valid(0):
            valids.append(c)
    deltas = [valids[i + 1] - valids[i] for i in range(len(valids) - 1)]
    assert valids and valids[0] == 8, f"first decor-valid at {valids[0]}, expected 8"
    assert all(d == 8 for d in deltas), f"decor-valid interval is not 8 cycles: {deltas}"

    # ----- (b) seed produced after the right number of compressor words -----
    # With whitening + ingress_skip, the FIRST seed completes exactly when the
    # (ingress_skip + 12)-th post-SHA digest word arrives.
    assert g.n_compress_words >= INGRESS + SEED_WORDS, "too few compressor words"

    # ----- (c) genbits are demand-driven; (d) 4 KM beats/block -----
    # Seeds alone produce no blocks: the scoreboard pulls them. Pull one
    # full Generate's worth and close the command, as the RTL gen_last would.
    assert g.n_genbits == 0, f"seeds must not self-generate: {g.n_genbits} blocks appeared unpulled"
    for _ in range(GLEN):
        assert g.genbits_block() is not None, "genbits_block() returned None after a seed"
    g.genbits_gen_last()
    assert g.n_genbits == GLEN, f"pulled {g.n_genbits} blocks, expected {GLEN}"
    assert g.n_generates == 1, f"{g.n_generates} Generates finalized, expected 1"
    assert g.n_km_words == g.n_genbits * KM_BEATS_PER_BLOCK, (
        f"km words {g.n_km_words} != genbits*4 {g.n_genbits * 4}"
    )

    # (c2) The per-block path must reproduce the monolithic generate() bit for
    # bit -- same block values, same trailing Update, same resulting state.
    # This is the property the demand-driven model rests on.
    ref = SepCtrDrbgGolden()
    ref.instantiate(g.expected_seed[0])
    lazy = SepCtrDrbgGolden()
    lazy.instantiate(g.expected_seed[0])
    ref_blocks = ref.generate(GLEN)
    lazy_blocks = [lazy.generate_one() for _ in range(GLEN)]
    lazy.generate_done()
    assert lazy_blocks == ref_blocks, "generate_one() stream != generate() stream"
    assert (lazy.key, lazy.v, lazy.reseed_counter) == (ref.key, ref.v, ref.reseed_counter), (
        "generate_done() left a different CTR_DRBG state than generate()"
    )

    # KM beats really reconstruct the genbits block (LSW-first).
    blk0 = g.expected_genbits[0]
    km0 = [g.expected_km_words[i] for i in range(4)]
    recon = 0
    for i, w in enumerate(km0):  # beat0 -> [31:0]
        recon |= (w & 0xFFFFFFFF) << (32 * i)
    assert recon == blk0, f"KM beats don't reconstruct genbits block: {recon:032x} != {blk0:032x}"

    # ----- reference hexes (fixed seed = EntropyNoiseModel default config) -----
    seed0 = g.expected_seed[0]
    print("ENTROPY GOLDEN FACADE SELFTEST PASS")
    print(
        f"  per-stage counts @ {g.cycle} cycles: "
        f"decor_valid={g.n_decor_valid} compress_words={g.n_compress_words} "
        f"seeds={g.n_seeds} genbits={g.n_genbits} km_words={g.n_km_words}"
    )
    print(f"  first seed (384b)    = {seed0:096x}")
    print(f"  first genbits (128b) = {blk0:032x}")
    print(
        "  first 4 KM words     = "
        + " ".join(f"{w:08x}" for w in km0)
        + f"  (order={g.km_word_order})"
    )
