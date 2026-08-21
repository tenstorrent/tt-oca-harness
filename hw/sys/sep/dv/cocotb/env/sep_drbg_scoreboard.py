# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: (c) 2024-2026 Tenstorrent Inc. All Rights Reserved.
#
# sep_drbg_scoreboard.py
#
# Cocotb scoreboard for the SEP entropy datapath CHK1..CHK5 golden-vs-probe
# comparison, ported from the reference UVM sep_drbg_scoreboard methodology.
#
# CHAINED (default): the scoreboard DRIVES deterministic per-lane noise into the
# DUT via esrc_noise_ext_i AND feeds the identical sequence into a golden chain
# (sep_entropy_golden). Because one noise source feeds both, the decorrelator
# golden aligns by construction -- no LFSR-phase reverse-engineering.
# Each CHKn expected value is the golden's output of CHKn-1; the only DUT input to
# the chain is the noise. The reference enable-sync is replicated: the golden decor's
# per-lane enable mirrors esrc_ro_enable_o each cycle, so the model only shifts on
# the cycles the DUT does.
#
# Comparison is ordered-FIFO at each DUT valid event (a stage is correct iff its
# Nth DUT item equals the golden's Nth item), with a small warmup skip for the
# decorrelator SR-fill / enable-edge transient (reference warmup_samples).
#
# strict=False (calibration): mismatches logged, test not failed, first-N pairs
# dumped for offline alignment. strict=True (sign-off): report() raises (house-rule
# section 7).

from __future__ import annotations

from collections import Counter, deque

# Largest number of 128b blocks one CSRNG Generate command can request: the glen
# field is GenBitsCtrWidth bits (csrng_pkg.sv:26, GenBitsCtrWidth = 12).
_CSRNG_MAX_GLEN = (1 << 12) - 1

import cocotb
from cocotb.triggers import RisingEdge, ReadOnly, NextTimeStep
from cocotb.utils import get_sim_time

from sep_noise_golden import SepNoiseGolden
from sep_entropy_golden import SepEntropyGolden


def _safe_int(sig):
    """Read a cocotb signal as int; return None on X/Z."""
    try:
        return int(sig.value)
    except Exception:
        return None


class _StreamResult:
    __slots__ = ("name", "width", "matches", "mismatches", "dut_items",
                 "pairs", "first_mismatch")

    def __init__(self, name, width):
        self.name = name
        self.width = width
        self.matches = 0
        self.mismatches = 0
        self.dut_items = 0
        self.pairs = []            # first N (idx, expected, actual, ok)
        self.first_mismatch = None  # (idx, expected, actual)


class SepDrbgScoreboard:
    """Chained CHK1..CHK5 comparator driven off a co-driven golden."""

    CAPTURE_N = 64    # (exp, act) pairs retained per stream for the log

    # per-stream: (golden expected-queue attr, probe width bits). The four crypto
    # EDN sinks have no golden queue here (None): the SEP EDN fans genbits to the
    # crypto leg via an arbiter, so bit-exact per-sink prediction needs the reference suite
    # AXIS1-golden-tap + arbiter-assignment trace (sep_drbg_real_sink_multi_*). Until
    # that is ported, crypto sinks run in OBSERVE mode (positive beat evidence, no
    # value compare); CHK5_km keeps its golden queue for the controlled-firmware case.
    _STREAMS = {
        "CHK1_decor":     ("expected_decor_bytes", 96),
        "CHK2_compress":  ("expected_compress_words", 32),
        "CHK3_seed":      ("expected_seed", 384),
        "CHK4_genbits":   ("expected_genbits", 128),
        "CHK5_km":        ("expected_km_words", 32),
        "CHK5_aes":       (None, 32),
        "CHK5_kmac":      (None, 32),
        "CHK5_otbn_rnd":  (None, 32),
        "CHK5_otbn_urnd": (None, 32),
    }

    # score-map name -> CHK5 stream key.
    _SINK_KEYS = {
        "km": "CHK5_km", "aes": "CHK5_aes", "kmac": "CHK5_kmac",
        "otbn_rnd": "CHK5_otbn_rnd", "otbn_urnd": "CHK5_otbn_urnd",
    }
    # crypto-EDN sink stream key -> bit/word index into the packed crypto_edn_*_o
    # probe vectors (drbg_axis_edn_adapter client order: AES,KMAC,OTBN-RND,OTBN-URND).
    _CRYPTO_SINK_IDX = {
        "CHK5_aes": 0, "CHK5_kmac": 1, "CHK5_otbn_rnd": 2, "CHK5_otbn_urnd": 3,
    }

    @staticmethod
    def _norm_mode(v, *, what):
        """Normalize a score mode: True->golden, False->disabled, or pass through
        one of golden/observe/disabled."""
        if v is True:
            return "golden"
        if v is False:
            return "disabled"
        if v in ("golden", "observe", "disabled", "membership"):
            return v
        raise ValueError(f"unsupported {what} mode: {v!r}")

    def __init__(self, dut, logger, *, strict=False, noise_mode="unbiased",
                 noise_seed_base=0x1234_5678, golden_kwargs=None, warmup=4,
                 chk2_backdoor=False, score_km=True, score_sinks=None):
        self.dut = dut
        self.log = logger
        self.strict = strict
        # CHK5 is per-sink. Each entropy sink scores in one of three modes:
        #   golden   -- bit-exact compare of the sink's EDN beats against the golden
        #               queue. Only when the consumer pull order is controlled/
        #               predictable (KM controlled firmware). NOT yet available for
        #               the crypto sinks (needs the reference arbiter-assignment trace).
        #   observe  -- require real post-mux/post-adapter beats but do not value-
        #               compare them. Use for rom_main (firmware-driven KM pull) and
        #               for every crypto sink until the multi-sink golden is ported.
        #   disabled -- the sink is not scored (idle in this test).
        #
        # The KM sink is configured via the back-compat score_km kwarg
        # (True->golden, False->disabled, or an explicit mode string). The crypto
        # sinks (aes/kmac/otbn_rnd/otbn_urnd) are configured via score_sinks, a
        # name->mode map; anything omitted defaults to disabled. A score_sinks "km"
        # entry, if given, overrides score_km.
        self.sink_mode = {name: "disabled" for name in self._SINK_KEYS}
        self.sink_mode["km"] = self._norm_mode(score_km, what="score_km")
        for name, mode in dict(score_sinks or {}).items():
            if name not in self._SINK_KEYS:
                raise ValueError(f"unknown entropy sink: {name!r} "
                                 f"(known: {sorted(self._SINK_KEYS)})")
            mode = self._norm_mode(mode, what=f"score_sinks[{name}]")
            self.sink_mode[name] = mode
        # Crypto-sink "golden" = bit-exact per-sink ROUTING: compare the sink's
        # post-adapter beats word-for-word against the AXIS1 pre-adapter golden tap
        # (which is itself chained to the CHK4 genbits golden in report()). The
        # drbg_axis_edn_adapter is round-robin, so this in-order equality only holds
        # when EXACTLY ONE crypto sink is active (the others parked -> never request,
        # so the arbiter grants the live sink every word in order). Multiple
        # concurrent crypto sinks in golden mode would need the reference suite per-endpoint
        # block-assignment trace (not ported); reject that here.
        _crypto_golden = [n for n in ("aes", "kmac", "otbn_rnd", "otbn_urnd")
                          if self.sink_mode[n] == "golden"]
        if len(_crypto_golden) > 1:
            raise NotImplementedError(
                "CHK5 golden mode for >1 concurrent crypto sink needs the reference suite "
                f"per-endpoint arbiter-assignment trace (requested: {_crypto_golden}). "
                "Use a single golden crypto sink (others parked/observe).")
        # Back-compat aliases retained for callers/reporting.
        self.km_score_mode = self.sink_mode["km"]
        self.score_km = self.km_score_mode == "golden"
        # CHK2 source: default is the AXI frontdoor FIFO_RDATA drain (fed via
        # check_fifo_frontdoor); set chk2_backdoor=True to instead score CHK2 from
        # the live entropy_stream_data_o wire-tap monitor.
        self.chk2_backdoor = chk2_backdoor
        # Minimum-evidence floor per enabled stream: a strict run FAILS if a
        # checkpoint scored fewer than this many matches (reference suite fails enabled
        # checkpoints with zero comparisons -- a stream that never fired is a
        # silent hole, not a pass). Override via set_min_matches() for a longer
        # coverage test that demands deeper streams.
        self._min_matches = {
            "CHK1_decor": 8, "CHK2_compress": 4,
            "CHK3_seed": 1, "CHK4_genbits": 1, "CHK5_km": 1,
            "CHK5_aes": 1, "CHK5_kmac": 1,
            "CHK5_otbn_rnd": 1, "CHK5_otbn_urnd": 1,
        }
        # Per-stream warmup: only CHK1 needs it (the decorrelator SR seed lands
        # mid-stream). CHK2..CHK5 are exact-chained from the CHK1-verified decor
        # samples off the whitener-accept strobe, so they match from item 0.
        self._warmup = {k: 0 for k in self._STREAMS}
        self._warmup["CHK1_decor"] = warmup

        # One noise source feeds both the DUT drive and the golden chain.
        self.noise_gen = SepNoiseGolden()
        self.noise_gen.configure(noise_mode, seed_base=noise_seed_base)
        self._gk = dict(golden_kwargs or {})
        # Scoreboard-only knob: consumed here, never forwarded to SepEntropyGolden.
        _legal = self._gk.pop("legal_gen_lengths", None)
        self.legal_gen_lengths = None if _legal is None else {int(v) for v in _legal}
        # Two golden instances, decoupled at the decorrelator boundary:
        #   golden -- the feedback SR, fed noise + seeded from live ff_stage (CHK1).
        #   chain  -- BIW/SHA/seed/DRBG/KM, fed one CHK1-verified decor sample per
        #             DUT decor-valid strobe (CHK2..CHK5). Driving the chain off the
        #             RTL's per-sample strobe (not the model's divider) keeps the
        #             SHA 16:1 block boundary aligned with the RTL by construction.
        self.golden = SepEntropyGolden(**self._gk)
        self.chain = SepEntropyGolden(**self._gk)

        # CHK4 protocol-check state (genbits FIPS flag + Generate segmentation).
        # glen is the length the SEQUENCE commands; it is not a global invariant,
        # because the other EDN endpoints raise their own requests with their own
        # lengths. Callers that know the full set can pin it via
        # golden_kwargs["legal_gen_lengths"]; otherwise segments are only bounds-
        # checked (see report()).
        self.glen = int(self._gk.get("glen", 32))
        # Default the legal set to the sequence's own commanded glen. Leaving it
        # None degraded the check to 1 <= n <= 4095, where n < 1 is structurally
        # impossible and 4095 is ~90x any block count these tests reach -- i.e.
        # unfalsifiable. No construction site passes the knob today, so without
        # this default the predicate could never reject anything.
        if self.legal_gen_lengths is None:
            self.legal_gen_lengths = {self.glen}
        self._fips_violations = 0
        self._genbits_in_gen = 0
        self._gen_lengths = Counter()   # observed blocks-per-Generate histogram

        # CHK5 per-sink ROUTING (golden crypto sink) + genbits-chain membership state.
        # axis1_q: live ordered crypto-leg AXIS1 words (popped per AES beat for the
        # in-order per-sink compare). _axis1_words/_km_words: every tapped word, for
        # the report-time membership tally against the verified-genbits multiset.
        # _genbits_words: Counter of the 32-bit slices of every CHK4-verified genbits
        # block (the golden pool both sinks must draw from).
        self._axis1_needed = any(self.sink_mode[n] == "golden"
                                 for n in ("aes", "kmac", "otbn_rnd", "otbn_urnd"))
        self.axis1_q = deque()
        self._axis1_words = []
        self._km_words = []
        # Per-crypto-sink membership stash: every post-adapter EDN word delivered to
        # each sink, tallied against the genbits-golden multiset in report(). Used
        # when >1 crypto sink is active concurrently (AES+KMAC) -- the round-robin
        # arbiter determines which word goes to which endpoint, so per-sink ORDER is
        # not golden-predictable, but each delivered word must still be a genuine
        # genbits word (stronger than observe, the multi-crypto-sink analog of the KM
        # membership case).
        self._sink_words = {n: [] for n in ("aes", "kmac", "otbn_rnd", "otbn_urnd")}
        self._genbits_words = Counter()
        self._axis1_member_hits = 0
        self._axis1_member_misses = 0
        # Contention evidence: the sim-time (ns) of every post-adapter crypto-EDN beat
        # per sink, index-aligned with _sink_words. Two sinks whose beat time-spans
        # OVERLAP were being granted EDN words during an overlapping window -- i.e. the
        # round-robin arbiter (u_axis_edn_crypto) time-multiplexed two live clients
        # (real contention), not one sink drained fully before the other. Exposed via
        # sink_beat_times(); a stricter same-cycle-req overlap does not occur with this
        # stimulus (brief req pulses separated by long AXI config), so the beat-window
        # form is the honest sufficient proof.
        self._sink_beat_times = {n: [] for n in ("aes", "kmac", "otbn_rnd", "otbn_urnd")}

        self.results = {k: _StreamResult(k, w)
                        for k, (_, w) in self._STREAMS.items()}
        self._skip = dict(self._warmup)
        self._tasks = []

    # ------------------------------------------------------------------ drive
    def start(self):
        """Fork the noise driver + per-stream monitors (after reset released)."""
        d = self.dut
        # CHK2 default = AXI frontdoor FIFO_RDATA drain (check_fifo_frontdoor),
        # the overflow-robust observation point. Only fork the live backdoor
        # wire-tap monitor (entropy_stream_data_o) when explicitly selected.
        self._tasks = [
            cocotb.start_soon(self._drive_noise()),   # CHK1 runs inline here
            # CHK3: capture the seed on the REAL CSRNG seed handshake
            # (seed_valid && es_ack), not merely seed_valid -- the value the CSRNG
            # actually accepted.
            cocotb.start_soon(self._mon_handshake_rise(
                "CHK3_seed", d.drbg_seed_valid_o, d.drbg_es_ack_o, d.drbg_es_bits_o,
                mask=(1 << 384) - 1)),
            # CHK4: golden genbits compare + protocol (FIPS flag, gen_last/glen).
            cocotb.start_soon(self._mon_genbits()),
            # CHK5: EDN->sink beats, per sink. CHK5_km is the Key Manager AXIS
            # endpoint (entropy_muxed_req[0]). The SEP EDN also drives
            # entropy_muxed_req[1] -> drbg_axis_edn_adapter -> native crypto EDN
            # clients crypto_edn[0]=AES, [1]=KMAC, [2]=OTBN-RND, [3]=OTBN-URND -- the
            # per-sink endpoints the multi-sink CHK5 covers, monitored off the packed
            # crypto_edn_*_o probe vectors (edn_req[i] && edn_ack[i] beat). Each sink
            # is forked only when its score mode is not 'disabled'; a sink that is
            # idle in a given test is simply left disabled (KM-only smoke runs only
            # CHK5_km, the OTBN KAT adds otbn_rnd/otbn_urnd, etc.).
        ]
        # AXIS1 golden tap (crypto-leg pre-adapter word stream): needed for any
        # golden crypto sink's per-sink routing compare + the genbits-chain membership.
        if self._axis1_needed:
            self._tasks.append(cocotb.start_soon(self._mon_axis1_tap()))
        # KM sink: AXIS endpoint, tvalid&&tready handshake.
        if self.km_score_mode == "golden":
            # CHK5_km golden-match -- only when the KM entropy consumption is
            # golden-predictable (controlled KM firmware); disabled for rom_main.
            self._tasks.append(cocotb.start_soon(self._mon_handshake(
                "CHK5_km", d.km_entropy_tvalid_o, d.km_entropy_tready_o,
                d.km_entropy_tdata_o, mask=0xFFFFFFFF)))
        elif self.km_score_mode == "observe":
            # CHK5_km alive mode: positive proof that KM consumed real post-mux
            # EDN words, without pretending rom_main's pull order is bit-exact
            # golden-predictable.
            self._tasks.append(cocotb.start_soon(self._mon_handshake_observed(
                "CHK5_km", d.km_entropy_tvalid_o, d.km_entropy_tready_o,
                d.km_entropy_tdata_o, mask=0xFFFFFFFF)))
        elif self.km_score_mode == "membership":
            # CHK5_km membership: rom_main's pull ORDER is firmware-driven (not
            # golden-predictable), but every word the KM consumes must still be a
            # genuine CHK4 genbits-golden word. Stash the words; the report() tally
            # checks membership in the verified-genbits multiset (stronger than observe).
            self._tasks.append(cocotb.start_soon(self._mon_km_membership()))
        # Crypto sinks: native EDN req/ack beat off the packed probe vectors.
        for key, idx in self._CRYPTO_SINK_IDX.items():
            name = key.split("_", 1)[1]  # CHK5_otbn_rnd -> otbn_rnd
            if self.sink_mode[name] == "observe":
                self._tasks.append(cocotb.start_soon(
                    self._mon_edn_sink(key, idx, observe=True)))
            elif self.sink_mode[name] == "golden":
                # Bit-exact per-sink routing: each post-adapter beat == the next
                # AXIS1 word (in-order; valid because this is the only active crypto
                # sink -> the round-robin arbiter grants it every word in order).
                self._tasks.append(cocotb.start_soon(
                    self._mon_edn_sink_golden(key, idx)))
            elif self.sink_mode[name] == "membership":
                # Per-sink membership: stash each post-adapter beat; report() checks
                # every word is a genbits-golden word. Order is arbiter-determined
                # (>1 concurrent crypto sink) so not scored -- the multi-crypto-sink
                # analog of the KM membership case.
                self._tasks.append(cocotb.start_soon(
                    self._mon_edn_sink_membership(idx, name)))
        if self.chk2_backdoor:
            self._tasks.append(cocotb.start_soon(self._mon_level(
                "CHK2_compress", d.esrc_compress_vld_o, d.esrc_compress_data_o,
                mask=0xFFFFFFFF)))

    async def _drive_noise(self):
        """Drive deterministic noise into the DUT and feed the golden chain the
        EXACT noise the decorrelator shifts, seeding the golden from the live RTL
        shift-register state so the two feedback SRs run in exact lockstep.

        The decorrelator is a FEEDBACK shift register (ff[0]=noise^ff[28]). The
        difference between two such SRs fed identical noise is a pure 29-bit
        rotation (the noise cancels), so it never decays: a wrong initial phase
        leaves a rotating difference that matches the sampled byte ff[28:21] only
        while it sits outside bits[28:21] and mismatches when it rotates in --
        exactly the intermittent CHK1 pattern seen when syncing on decor alone.
        And ff_stage resets ONLY on rst_ni (CTRL.RESET zeroes the SAMPLE, not the
        SR), with decor_bytes lagging the true SR reset by a full divider period,
        so the reset phase is not recoverable from decor_bytes.

        So: drive noise from the start, wait for the CTRL.RESET decor->0 and let
        the SR refill a few samples, then SNAPSHOT the real 12x29 ff_stage
        (esrc_decor_sr_o) and seed the golden from it. From there the golden
        free-runs the whole CHK1..CHK5 chain on the read-back esrc_noise_o."""
        d = self.dut
        d.esrc_noise_ext_i.value = 0
        state = "wait_reset"
        prev_decor = None
        prev_probe = None
        changes = 0
        while True:
            dut_decor = _safe_int(d.esrc_decor_bytes_o)
            whiten_push = _safe_int(d.esrc_whiten_push_o) or 0
            gsr = self.golden.decor_sr_word()
            changed = (dut_decor is not None and prev_decor is not None
                       and dut_decor != prev_decor)

            if state == "wait_reset":
                # CTRL.RESET (rst_n = rst_ni & ~CTRL.RESET) soft-resets the WHOLE
                # entropy_source: decorrelator SR, SHA, FIFO. decor->0 marks it.
                # Restart the decor-sample chain so its SHA starts at sample 0.
                if changed and dut_decor == 0:
                    state, changes = "wait_fill", 0
                    self.chain = SepEntropyGolden(**self._gk)
                    self._reset_results()
            elif state == "wait_fill":
                # Let the SR fully refill (>=3 samples => 29-bit SR is past its
                # fill) so the ff_stage snapshot is a live, fully-shifted state.
                if changed:
                    changes += 1
                    if changes >= 3 and prev_probe:
                        self._seed_golden(prev_probe)
                        state = "locked"
                        self.log.info(
                            "CHK1 golden seeded from live ff_stage @ decor=%024x",
                            dut_decor)
            elif state == "locked" and changed:
                # SRs are in lockstep -> gsr (golden ff[28:21]) equals the DUT's
                # registered decor sample on every decor-change cycle.
                self._record_pair("CHK1_decor", gsr, dut_decor & ((1 << 96) - 1))

            # CHK2..CHK5: feed each CHK1-verified decor sample into the chain ONLY
            # on the SHA-whitener accept strobe -- the exact words the RTL hashes.
            # The whitener drops samples during its SHA-compute/output phase (no
            # upstream backpressure), so feeding every decor-valid would misframe
            # the SHA 16:1 blocks after block 0. The held decor byte word at the
            # accept cycle is BIW-compressed into the word the whitener consumes.
            if state != "wait_reset" and whiten_push and dut_decor is not None:
                self.chain.feed_decor_sample(dut_decor)

            prev_decor = dut_decor
            prev_probe = _safe_int(d.esrc_decor_sr_o)
            shifted = _safe_int(d.esrc_noise_o) or 0
            en = _safe_int(d.esrc_ro_enable_o) or 0
            self.golden.feed_noise(shifted, enable_mask=en)
            await NextTimeStep()
            d.esrc_noise_ext_i.value = self.noise_gen.step_all()
            await RisingEdge(d.clk_i)
            await ReadOnly()

    def _seed_golden(self, sr_packed):
        """Re-create the CHK1 SR golden and seed it from the live RTL ff_stage
        snapshot. clk_divider=8 is unused by the raw-SR CHK1 compare but phase-
        aligns the model divider to the RTL's /8 downsampler for completeness."""
        self.golden = SepEntropyGolden(**self._gk)
        self.golden.seed_decor_sr(sr_packed, clk_divider=8)

    def _reset_results(self):
        """Clear per-stream stats (called at the CTRL.RESET that begins the run)."""
        self.results = {k: _StreamResult(k, w)
                        for k, (_, w) in self._STREAMS.items()}
        self._skip = dict(self._warmup)
        # Drop any pre-reset genbits/sink words so the CHK5 membership pool only
        # holds the real post-reset run (pre-reset genbits are X/garbage).
        self.axis1_q.clear()
        self._axis1_words.clear()
        self._km_words.clear()
        for words in self._sink_words.values():
            words.clear()
        for times in self._sink_beat_times.values():
            times.clear()
        self._genbits_words.clear()
        self._axis1_member_hits = 0
        self._axis1_member_misses = 0
        # Pre-reset genbits are X/garbage, so any Generate they opened is not a
        # real unterminated command -- drop the segmentation state with them.
        self._genbits_in_gen = 0
        self._gen_lengths.clear()
        self._fips_violations = 0

    # --------------------------------------------------------------- recording
    def _expected_q(self, key):
        # CHK2..CHK5 expected items come from the decor-sample-driven chain.
        return getattr(self.chain, self._STREAMS[key][0])

    def _record_pair(self, key, expected, actual):
        """Record a directly-supplied (expected, actual) pair (used by inline CHK1,
        which holds both the golden value and the probe at the compare cycle)."""
        r = self.results[key]
        r.dut_items += 1
        if self._skip[key] > 0:
            self._skip[key] -= 1
            return
        ok = (expected == actual)
        if ok:
            r.matches += 1
        else:
            r.mismatches += 1
            if r.first_mismatch is None:
                r.first_mismatch = (r.dut_items - 1, expected, actual)
        if len(r.pairs) < self.CAPTURE_N:
            r.pairs.append((r.dut_items - 1, expected, actual, ok))

    def _record(self, key, actual):
        r = self.results[key]
        q = self._expected_q(key)
        r.dut_items += 1
        if not q:
            if r.first_mismatch is None:
                r.first_mismatch = (r.dut_items - 1, None, actual)
            r.mismatches += 1
            return
        exp = q.popleft()
        if self._skip[key] > 0:          # warmup: drain but don't score
            self._skip[key] -= 1
            return
        ok = (exp == actual)
        if ok:
            r.matches += 1
        else:
            r.mismatches += 1
            if r.first_mismatch is None:
                r.first_mismatch = (r.dut_items - 1, exp, actual)
        if len(r.pairs) < self.CAPTURE_N:
            r.pairs.append((r.dut_items - 1, exp, actual, ok))

    def _record_observed(self, key, actual):
        """Record positive stream evidence without a bit-exact expected value."""
        r = self.results[key]
        r.dut_items += 1
        r.matches += 1
        if len(r.pairs) < self.CAPTURE_N:
            r.pairs.append((r.dut_items - 1, None, actual, True))

    # --------------------------------------------------------------- monitors
    async def _mon_level(self, key, vld, sig, *, mask):
        """One item per cycle the valid is high."""
        while True:
            await RisingEdge(self.dut.clk_i)
            await ReadOnly()
            if _safe_int(vld):
                v = _safe_int(sig)
                if v is not None:
                    self._record(key, v & mask)

    async def _mon_handshake(self, key, vld, rdy, sig, *, mask):
        """One item per tvalid && tready beat."""
        while True:
            await RisingEdge(self.dut.clk_i)
            await ReadOnly()
            if (_safe_int(vld) or 0) and (_safe_int(rdy) or 0):
                v = _safe_int(sig)
                if v is not None:
                    self._record(key, v & mask)

    async def _mon_handshake_observed(self, key, vld, rdy, sig, *, mask):
        """One observed item per tvalid && tready beat, with no golden compare."""
        while True:
            await RisingEdge(self.dut.clk_i)
            await ReadOnly()
            if (_safe_int(vld) or 0) and (_safe_int(rdy) or 0):
                v = _safe_int(sig)
                if v is not None:
                    self._record_observed(key, v & mask)

    async def _mon_edn_sink(self, key, idx, *, observe):
        """One item per native-EDN beat to crypto sink `idx` -- the cycle the client
        asserts edn_req and the adapter pulses edn_ack. Data = that sink's edn_bus
        word. Reads the packed crypto_edn_*_o probe vectors (bit/word `idx`)."""
        d = self.dut
        while True:
            await RisingEdge(d.clk_i)
            await ReadOnly()
            req = ((_safe_int(d.crypto_edn_req_o) or 0) >> idx) & 1
            ack = ((_safe_int(d.crypto_edn_ack_o) or 0) >> idx) & 1
            if req and ack:
                bus = _safe_int(d.crypto_edn_bus_o)
                if bus is not None:
                    v = (bus >> (32 * idx)) & 0xFFFFFFFF
                    if observe:
                        self._record_observed(key, v)
                    else:
                        self._record(key, v)

    async def _mon_axis1_tap(self):
        """Capture every accepted AXIS1 beat (crypto-leg pre-adapter word stream,
        entropy_muxed_req[1]). This is the authoritative ordered sequence the adapter
        hands to the crypto endpoints; with a single active crypto sink the sink's
        post-adapter beats equal it 1:1. Also stashed for the genbits-chain membership
        tally in report()."""
        d = self.dut
        while True:
            await RisingEdge(d.clk_i)
            await ReadOnly()
            if (_safe_int(d.axis1_tvalid_o) or 0) and (_safe_int(d.axis1_tready_o) or 0):
                w = _safe_int(d.axis1_tdata_o)
                if w is not None:
                    w &= 0xFFFFFFFF
                    self.axis1_q.append(w)
                    self._axis1_words.append(w)

    async def _mon_edn_sink_golden(self, key, idx):
        """Bit-exact per-sink ROUTING: on each post-adapter beat to crypto sink `idx`,
        the delivered word must equal the next AXIS1 golden word (in-order). An ack
        with an empty AXIS1 queue (the sink consumed a word the tap never saw) is a
        routing/ordering error -> recorded as a mismatch."""
        d = self.dut
        while True:
            await RisingEdge(d.clk_i)
            await ReadOnly()
            req = ((_safe_int(d.crypto_edn_req_o) or 0) >> idx) & 1
            ack = ((_safe_int(d.crypto_edn_ack_o) or 0) >> idx) & 1
            if req and ack:
                bus = _safe_int(d.crypto_edn_bus_o)
                if bus is None:
                    continue
                v = (bus >> (32 * idx)) & 0xFFFFFFFF
                exp = self.axis1_q.popleft() if self.axis1_q else None
                self._record_pair(key, exp, v)

    async def _mon_km_membership(self):
        """Stash every KM AXIS beat word; report() checks genbits-golden membership."""
        d = self.dut
        while True:
            await RisingEdge(d.clk_i)
            await ReadOnly()
            if (_safe_int(d.km_entropy_tvalid_o) or 0) and (_safe_int(d.km_entropy_tready_o) or 0):
                w = _safe_int(d.km_entropy_tdata_o)
                if w is not None:
                    self._km_words.append(w & 0xFFFFFFFF)

    async def _mon_edn_sink_membership(self, idx, name):
        """Stash every native-EDN beat word delivered to crypto sink `idx` (the cycle
        the client asserts edn_req and the adapter pulses edn_ack). report() checks
        each stashed word is a genbits-golden word. Used for >1 concurrent crypto
        sink (AES+KMAC), where the round-robin arbiter picks the endpoint per word so
        per-sink ORDER is not golden-predictable, but every word is genuine genbits."""
        d = self.dut
        while True:
            await RisingEdge(d.clk_i)
            await ReadOnly()
            req = ((_safe_int(d.crypto_edn_req_o) or 0) >> idx) & 1
            ack = ((_safe_int(d.crypto_edn_ack_o) or 0) >> idx) & 1
            if req and ack:
                bus = _safe_int(d.crypto_edn_bus_o)
                if bus is not None:
                    self._sink_words[name].append((bus >> (32 * idx)) & 0xFFFFFFFF)
                    self._sink_beat_times[name].append(get_sim_time("ns"))

    async def _mon_handshake_rise(self, key, a, b, sig, *, mask):
        """One item per RISING edge of (a && b) -- a req/ack handshake completing.
        Used for CHK3: the seed is captured when seed_valid && es_ack (the CSRNG
        actually accepts the presented seed), not on every cycle both are high."""
        prev = 0
        while True:
            await RisingEdge(self.dut.clk_i)
            await ReadOnly()
            hs = (_safe_int(a) or 0) and (_safe_int(b) or 0)
            if hs and not prev:
                v = _safe_int(sig)
                if v is not None:
                    self._record(key, v & mask)
            prev = hs

    async def _mon_genbits(self):
        """CHK4: compare each genbits block to the golden AND check CSRNG protocol.

        The golden is pulled ONE BLOCK PER OBSERVED BEAT, and each Generate is
        closed on the RTL's own gen_last. Genbits are demand-driven: with all
        three DRBG EDN endpoints live (KM, crypto adapter, entropy pool) a single
        seed routinely serves several Generate commands, so the command
        boundaries -- and therefore where each trailing CTR_DRBG Update lands --
        are not predictable from the seed stream alone.

        MODELLING DEPENDENCY, stated plainly: the Update BOUNDARY is taken from
        the DUT (gen_last), so a DUT that segmented wrongly would be followed by
        the golden rather than caught by it. Every block VALUE is still predicted
        independently from the (key, V) chain, so a wrong block, a missing Update
        or an extra Update all still mismatch; what the value compare cannot see
        is gen_last itself landing on the wrong beat. report() bounds-checks the
        resulting segment lengths, and a caller that knows its endpoints' request
        sizes should pin them via golden_kwargs["legal_gen_lengths"] to close the
        gap. Predicting the boundary outright would mean modelling EDN
        arbitration, or probing the commanded glen inside the vendored
        csrng_cmd_stage generate block.

        Protocol: every emitted block must carry genbits_fips_o==1.
        """
        d = self.dut
        while True:
            await RisingEdge(d.clk_i)
            await ReadOnly()
            if not (_safe_int(d.drbg_genbits_vld_o) or 0):
                continue
            v = _safe_int(d.drbg_genbits_data_o)
            if v is not None:
                # Predict this block before comparing it. Returns None only in the
                # pre-seed boot window, where _record() will flag the empty queue.
                self.chain.genbits_block()
                block = v & ((1 << 128) - 1)
                self._record("CHK4_genbits", block)
                # Pool the 4 32-bit slices of this CHK4-verified block: the golden
                # word multiset both sinks (KM + crypto AXIS1) must draw from.
                for s in range(4):
                    self._genbits_words[(block >> (32 * s)) & 0xFFFFFFFF] += 1
            if (_safe_int(d.drbg_genbits_fips_o) or 0) != 1:
                self._fips_violations += 1
            self._genbits_in_gen += 1
            if _safe_int(d.drbg_gen_last_o) or 0:
                # Trailing Update, then any reseed deferred across this command.
                self.chain.genbits_gen_last()
                self._gen_lengths[self._genbits_in_gen] += 1
                self._genbits_in_gen = 0

    # --------------------------------------------------------------- accessors
    def km_beats(self):
        """Live count of Key-Manager AXIS entropy beats tapped so far.

        The KM counterpart of sink_beats(), which covers only the crypto-EDN sinks.
        Callable mid-run to snapshot the KM leg before and after a window.
        """
        return len(self._km_words)

    def completed_generate_lengths(self):
        """Observed blocks-per-Generate histogram: {blocks_in_command: how_many_commands}.

        A command is counted only when the DUT asserts `gen_last`, and the key is the
        number of genbits beats COUNTED before that boundary -- not the commanded
        length. That is what lets a caller assert segmentation against its own stimulus
        instead of against the DUT's own `gen_last`, which would follow a wrongly
        segmenting DUT rather than catch it.

        Live: callable mid-run. Returns a copy, so a caller cannot perturb scoreboard
        state. Empty until the first command completes.
        """
        return Counter(self._gen_lengths)

    def open_generate_remaining(self):
        """Genbits beats seen so far in the Generate command still in flight (0 if none).

        Only useful for diagnostics: a run that ends with this non-zero and
        `completed_generate_lengths()` empty never saw `gen_last`, so its segmentation
        evidence does not exist rather than being weak.
        """
        return self._genbits_in_gen

    def sink_beats(self, name):
        """Public count of post-adapter crypto-EDN beats delivered to crypto sink
        `name` (aes/kmac/otbn_rnd/otbn_urnd) so far -- the membership-stash length.
        Live: callable mid-run to snapshot a sink's beat count before/after a window."""
        if name not in self._sink_words:
            raise ValueError(f"unknown crypto sink {name!r} "
                             f"(known: {sorted(self._sink_words)})")
        return len(self._sink_words[name])

    def sink_beat_times(self, name):
        """Sim-times (ns) of the post-adapter crypto-EDN beats delivered to crypto sink
        `name`, in delivery order (index-aligned with the membership word stash). Two
        sinks whose returned time-spans overlap were granted EDN words during an
        overlapping window -- positive arbiter-contention evidence (CHK-OVERLAP)."""
        if name not in self._sink_beat_times:
            raise ValueError(f"unknown crypto sink {name!r} "
                             f"(known: {sorted(self._sink_beat_times)})")
        return list(self._sink_beat_times[name])

    # --------------------------------------------------------------- tuning
    def set_min_matches(self, **mins):
        """Raise/lower the per-stream minimum-evidence floor (e.g. a longer
        coverage test demands deeper streams: set_min_matches(CHK4_genbits=32))."""
        self._min_matches.update(mins)

    # ------------------------------------------------------------- frontdoor
    def check_fifo_frontdoor(self, words):
        """Compare AXI-frontdoor-drained FIFO_RDATA words (in pop = push order) to
        the golden compressor/whitener stream (CHK2). Call once after the entropy
        run, with the words from SepEsrcFifoDrainSeq. The FIFO retains every pushed
        word until read (the DRBG taps pre-FIFO), so a post-run drain yields the
        full ordered post-whitener stream without disturbing CHK3..CHK5."""
        for w in words:
            self._record("CHK2_compress", w & 0xFFFFFFFF)
        self.log.info("CHK2 frontdoor: drained %d FIFO_RDATA words", len(words))

    # ----------------------------------------------------------------- report
    def report(self):
        """Log per-stream results; in strict mode raise on any mismatch."""
        self.log.info("==== sep_drbg_scoreboard CHK1..CHK5 report ====")
        any_fail = False

        # CHK5 genbits-chain membership (stronger than the reference suite's AXIS1-as-its-own-golden):
        # every word delivered to KM (membership mode) and every crypto-leg AXIS1 word
        # must be a genuine CHK4 genbits-golden word, drawn from the SAME verified
        # multiset -- proving the one DRBG stream partitions into the two sinks. The pool
        # is built from DUT genbits, but CHK4 (strict) fails on any genbits!=golden, so a
        # passing run guarantees pool==CTR_DRBG-golden -> the chain is to the golden, not
        # circular. Tally
        # KM then AXIS1 against a working copy (removal), so over-consumption shows as a
        # miss. KM "membership" populates the CHK5_km result here (rom_main pull order
        # is firmware-driven -> not bit-exact ORDER, but each word IS a genbits word).
        crypto_membership = [n for n in ("aes", "kmac", "otbn_rnd", "otbn_urnd")
                             if self.sink_mode[n] == "membership"]
        if self.km_score_mode == "membership" or self._axis1_needed or crypto_membership:
            pool = Counter(self._genbits_words)
            if self.km_score_mode == "membership":
                rkm = self.results["CHK5_km"]
                for w in self._km_words:
                    rkm.dut_items += 1
                    if pool[w] > 0:
                        pool[w] -= 1
                        rkm.matches += 1
                    else:
                        rkm.mismatches += 1
                        if rkm.first_mismatch is None:
                            rkm.first_mismatch = (rkm.dut_items - 1, None, w)
                self.log.info("CHK5_km membership: %d/%d KM AXIS words are genbits-golden "
                              "words (rom_main pull order is firmware-driven, not scored)",
                              rkm.matches, rkm.dut_items)
            # Per-sink crypto membership (AES/KMAC/... concurrent). KM leg and crypto
            # leg are disjoint draws from genbits, and the crypto sinks are disjoint
            # slices of the crypto-leg AXIS1 stream, so removal order does not matter.
            for name in crypto_membership:
                r = self.results[self._SINK_KEYS[name]]
                for w in self._sink_words[name]:
                    r.dut_items += 1
                    if pool[w] > 0:
                        pool[w] -= 1
                        r.matches += 1
                    else:
                        r.mismatches += 1
                        if r.first_mismatch is None:
                            r.first_mismatch = (r.dut_items - 1, None, w)
                self.log.info("CHK5_%s membership: %d/%d crypto-EDN words are genbits-"
                              "golden words (concurrent-arbiter routing order not scored)",
                              name, r.matches, r.dut_items)
            if self._axis1_needed:
                for w in self._axis1_words:
                    if pool[w] > 0:
                        pool[w] -= 1
                        self._axis1_member_hits += 1
                    else:
                        self._axis1_member_misses += 1
                self.log.info("CHK5_axis1 membership: %d/%d crypto-leg AXIS1 words are "
                              "genbits-golden words",
                              self._axis1_member_hits,
                              self._axis1_member_hits + self._axis1_member_misses)
                if self._axis1_member_misses or self._axis1_member_hits == 0:
                    self.log.error("CHK5_axis1 membership FAIL: %d crypto-leg words NOT in "
                                   "the genbits golden (or none seen) -- routing/chain broken",
                                   self._axis1_member_misses)
                    any_fail = True

        keys = ["CHK1_decor", "CHK2_compress", "CHK3_seed", "CHK4_genbits"]
        # Append every enabled CHK5 sink (km + the crypto sinks), in a stable order.
        for name, key in self._SINK_KEYS.items():
            mode = self.sink_mode[name]
            if mode in ("golden", "observe", "membership"):
                keys.append(key)
            elif name == "km":
                self.log.info("CHK5_km disabled; KM entropy consumption must be "
                              "covered functionally by the test")
        for key in keys:
            r = self.results[key]
            sink_name = key.split("_", 1)[1] if key.startswith("CHK5_") else None
            sink_md = self.sink_mode[sink_name] if sink_name is not None else None
            if sink_md == "observe":
                self.log.info("%-14s observed_beats=%d (alive mode: no bit-exact compare)",
                              r.name, r.matches)
            elif sink_md == "membership":
                self.log.info("%-14s membership match=%d/%d (each a genbits-golden word; "
                              "pull order firmware-driven, not order-scored)",
                              r.name, r.matches, r.dut_items)
            else:
                # Crypto-golden sinks have no chain queue (_STREAMS name is None) and
                # score via _record_pair (axis1 routing); show no "golden left" for them.
                qname = self._STREAMS[key][0]
                left = len(self._expected_q(key)) if qname else 0
                self.log.info("%-14s dut_items=%d match=%d mismatch=%d (golden left=%d)",
                              r.name, r.dut_items, r.matches, r.mismatches, left)
            hexw = max(1, r.width // 4)
            for (idx, exp, act, ok) in r.pairs[:12]:
                es = "----" if exp is None else f"{exp:0{hexw}x}"
                if sink_md == "observe":
                    self.log.info("    [%-2d] OBS act=%0*x", idx, hexw, act)
                else:
                    self.log.info("    [%-2d] %s exp=%s act=%0*x",
                                  idx, "OK " if ok else "XX!", es, hexw, act)
            if r.first_mismatch is not None:
                idx, exp, act = r.first_mismatch
                es = "----" if exp is None else f"{exp:0{hexw}x}"
                self.log.info("    first mismatch [%d] exp=%s act=%0*x",
                              idx, es, hexw, act)
            if r.mismatches > 0:
                any_fail = True
            # Minimum-evidence: a checkpoint that never scored (or scored too few)
            # is a silent hole -- fail it, don't pass vacuously.
            need = self._min_matches.get(key, 1)
            if r.matches < need:
                self.log.error("    %s INSUFFICIENT EVIDENCE: matches=%d < min=%d "
                               "(checkpoint never fired / under-exercised)",
                               r.name, r.matches, need)
                any_fail = True
        # Protocol checks (CHK3/CHK4 semantics, independent of value match).
        if self._fips_violations:
            self.log.error("CHK4 FIPS violation: %d genbits with genbits_fips_o != 1",
                           self._fips_violations)
            any_fail = True
        # Generate segmentation. gen_last IS a per-Generate-command terminator:
        # csrng_cmd_stage sets cmd_gen_cnt_last when the genbits down-counter
        # reaches its final beat (csrng_cmd_stage.sv:379, :447), ships it as
        # acmd_bus[16] ("glast"), and csrng_core latches it into gen_last_q at
        # acmd_sop (csrng_core.sv:750) to drive ctr_drbg_gen.req_glast_i. So each
        # Generate command ends with exactly one glast beat, and that is where its
        # single trailing Update lands.
        self.log.info("CHK4 Generate segmentation: %d completed commands, blocks/cmd %s, "
                      "%d block(s) in the open command (seq-commanded glen=%d, legal=%s)",
                      sum(self._gen_lengths.values()),
                      dict(sorted(self._gen_lengths.items())) or "{}",
                      self._genbits_in_gen, self.glen, sorted(self.legal_gen_lengths))
        # State plainly when the segmentation check had nothing to act on. These
        # runs never observe a completed Generate command -- gen_last is a level
        # held from acmd_sop and EDN's own commanded glen is larger than the block
        # count any test reaches -- so the loop below cannot fire and CHK4's
        # Update boundary is taken from the DUT unchecked. Say so rather than let
        # a silent zero read as coverage.
        if not self._gen_lengths and self.results["CHK4_genbits"].dut_items:
            self.log.info("CHK4 segmentation NOT EXERCISED: no Generate command completed "
                          "in this run (%d genbits observed), so gen_last was never seen "
                          "asserted and the trailing-Update boundary is unverified. "
                          "Closing this needs an independent probe of the commanded glen "
                          "inside csrng_cmd_stage.",
                          self.results["CHK4_genbits"].dut_items)
        # A completed command must carry a legal number of blocks. glen is a
        # GenBitsCtrWidth field, so a segment can never exceed its maximum, and a
        # zero-length segment would mean gen_last fired with no genbits at all.
        # When the caller declares the lengths its endpoints request
        # (golden_kwargs["legal_gen_lengths"]) anything else is a hard failure.
        for seg_len, count in sorted(self._gen_lengths.items()):
            bad = (seg_len < 1) or (seg_len > _CSRNG_MAX_GLEN) or (
                self.legal_gen_lengths is not None and seg_len not in self.legal_gen_lengths)
            if bad:
                self.log.error("CHK4 illegal Generate segmentation: %d command(s) emitted "
                               "%d blocks; legal=%s (max %d). gen_last landed somewhere the "
                               "commanded glen cannot explain, so the trailing CTR_DRBG "
                               "Update ran at the wrong point.",
                               count, seg_len,
                               sorted(self.legal_gen_lengths) if self.legal_gen_lengths
                               else ">=1", _CSRNG_MAX_GLEN)
                any_fail = True
        self.log.info("==== end report (strict=%s, any_fail=%s) ====",
                      self.strict, any_fail)
        if self.strict and any_fail:
            raise AssertionError(
                "sep_drbg_scoreboard: CHK1..CHK5 failure (mismatch / insufficient "
                "evidence / protocol violation)")
        return not any_fail
