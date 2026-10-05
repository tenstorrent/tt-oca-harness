# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2024-2026 Tenstorrent USA, Inc.
"""Cocotb scoreboard for the SEP entropy datapath CHK1..CHK5 golden-vs-probe comparison.

The scoreboard drives deterministic per-lane noise into esrc_noise_ext_i and feeds the
same sequence into a golden chain (sep_entropy_golden), so the decorrelator golden is
aligned by construction. Each CHKn expected value is the golden output of CHKn-1, and
the golden decorrelator shifts a lane only on cycles esrc_ro_enable_o enables it.

Each stage compares its Nth DUT item to the golden's Nth item, after a short CHK1 warmup
for the decorrelator SR-fill / enable-edge transient.

strict=False logs mismatches and dumps the first N pairs; strict=True makes report() raise.
"""

from __future__ import annotations

from collections import Counter, deque

import cocotb
from cocotb.triggers import NextTimeStep, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from models.entropy_noise_model import EntropyNoiseModel
from sep_entropy_golden import SepEntropyGolden
from sep_spec_tables import CRYPTO_EDN_SINKS


def _safe_int(sig):
    """Read a cocotb signal as int; return None on X/Z."""
    try:
        return int(sig.value)
    except Exception:
        return None


def _fmt_word(val, hexw: int) -> str:
    """Hex word for the report log; X/Z stays visible instead of throwing."""
    return "X/Z" if val is None else f"{val:0{hexw}x}"


class _StreamResult:
    __slots__ = ("name", "width", "matches", "mismatches", "dut_items", "pairs", "first_mismatch")

    def __init__(self, name, width):
        self.name = name
        self.width = width
        self.matches = 0
        self.mismatches = 0
        self.dut_items = 0
        self.pairs = []  # first N (idx, expected, actual, ok)
        self.first_mismatch = None  # (idx, expected, actual)


class SepDrbgScoreboard:
    """Chained CHK1..CHK5 comparator driven off a co-driven golden."""

    CAPTURE_N = 64  # (exp, act) pairs retained per stream for the log

    # per-stream: (golden expected-queue attr, probe width bits). Crypto-EDN
    # sinks have no chain queue here (None): routing compares each post-adapter
    # beat to the AXIS1 word the adapter granted that cycle. CHK5_km keeps its
    # own golden queue for the controlled-firmware case.
    _STREAMS = {
        "CHK1_decor": ("expected_decor_bytes", 96),
        "CHK2_compress": ("expected_compress_words", 32),
        "CHK3_seed": ("expected_seed", 384),
        "CHK4_genbits": ("expected_genbits", 128),
        "CHK5_km": ("expected_km_words", 32),
        "CHK5_aes": (None, 32),
        "CHK5_kmac": (None, 32),
        "CHK5_otbn_rnd": (None, 32),
        "CHK5_otbn_urnd": (None, 32),
        "CHK5_pool": (None, 32),
    }

    # score-map name -> CHK5 stream key.
    _SINK_KEYS = {
        "km": "CHK5_km",
        "aes": "CHK5_aes",
        "kmac": "CHK5_kmac",
        "otbn_rnd": "CHK5_otbn_rnd",
        "otbn_urnd": "CHK5_otbn_urnd",
        "pool": "CHK5_pool",
    }
    # Packed-probe index from the DV-owned sink table. Consuming tests bind
    # each name with a single-client beat delta before any concurrent fork.
    _CRYPTO_SINK_IDX = {f"CHK5_{name}": i for i, name in enumerate(CRYPTO_EDN_SINKS)}

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

    def __init__(
        self,
        dut,
        logger,
        *,
        strict=False,
        noise_mode="unbiased",
        noise_seed_base=0x1234_5678,
        golden_kwargs=None,
        warmup=4,
        chk2_backdoor=False,
        score_km=True,
        score_sinks=None,
    ):
        self.dut = dut
        self.log = logger
        self.strict = strict
        # CHK5 is per-sink. Each entropy sink scores in one of:
        #   golden     -- bit-exact. Crypto sinks compare each post-adapter beat
        #                 to the AXIS1 word granted that cycle (one or more live
        #                 clients). KM compares against its controlled-firmware
        #                 queue.
        #   membership -- every delivered word is a CHK4 genbits word; order is
        #                 not scored (firmware-driven KM pull).
        #   observe    -- require real beats, no value compare (rom_main).
        #   disabled   -- the sink is not scored (idle in this test).
        #
        # The KM sink is configured via the score_km kwarg
        # (True->golden, False->disabled, or an explicit mode string). The crypto
        # sinks (aes/kmac/otbn_rnd/otbn_urnd) and the entropy-pool sink (pool,
        # EDN endpoint [2]) are configured via score_sinks; omitted sinks default
        # disabled. A score_sinks "km" entry, if given, overrides score_km.
        self.sink_mode = {name: "disabled" for name in self._SINK_KEYS}
        self.sink_mode["km"] = self._norm_mode(score_km, what="score_km")
        for name, mode in dict(score_sinks or {}).items():
            if name not in self._SINK_KEYS:
                raise ValueError(
                    f"unknown entropy sink: {name!r} (known: {sorted(self._SINK_KEYS)})"
                )
            mode = self._norm_mode(mode, what=f"score_sinks[{name}]")
            self.sink_mode[name] = mode
        # Crypto-sink "golden" = bit-exact ROUTING: each post-adapter beat equals
        # the AXIS1 word the adapter granted that cycle. One monitor owns axis1_q
        # so N live golden sinks cannot steal words from each other. A same-cycle
        # dual grant is a fail (prim_arbiter_ppc is one-hot). Single-sink golden
        # is the N=1 case of the same rule.
        # Aliases read by callers and report().
        self.km_score_mode = self.sink_mode["km"]
        self.score_km = self.km_score_mode == "golden"
        # CHK2 source: default is the AXI frontdoor FIFO_RDATA drain (fed via
        # check_fifo_frontdoor); set chk2_backdoor=True to instead score CHK2 from
        # the live entropy_stream_data_o wire-tap monitor.
        self.chk2_backdoor = chk2_backdoor
        # Minimum matches per enabled stream; a strict run fails a checkpoint below it,
        # because a stream that never fired is a hole, not a pass. See set_min_matches().
        self._min_matches = {
            "CHK1_decor": 8,
            "CHK2_compress": 4,
            "CHK3_seed": 1,
            "CHK4_genbits": 1,
            "CHK5_km": 1,
            "CHK5_aes": 1,
            "CHK5_kmac": 1,
            "CHK5_otbn_rnd": 1,
            "CHK5_otbn_urnd": 1,
            "CHK5_pool": 1,
        }
        # Per-stream warmup: only CHK1 needs it (the decorrelator SR seed lands
        # mid-stream). CHK2..CHK5 are exact-chained from the CHK1-verified decor
        # samples off the whitener-accept strobe, so they match from item 0.
        self._warmup = {k: 0 for k in self._STREAMS}
        self._warmup["CHK1_decor"] = warmup

        # One noise source feeds both the DUT drive and the golden chain.
        self.noise_gen = EntropyNoiseModel()
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
        # lengths. Callers that know the full set pin it via
        # golden_kwargs["legal_gen_lengths"]; otherwise the set is the sequence's
        # own glen (see report()).
        self.glen = int(self._gk.get("glen", 32))
        # Default the legal set to the sequence's own commanded glen, so the
        # segmentation check in report() is always an exact membership test.
        if self.legal_gen_lengths is None:
            self.legal_gen_lengths = {self.glen}
        self._fips_violations = 0
        # Post-adapter EDN FIPS (tb_top pool_edn_fips_o / crypto_edn_fips_o).
        # Distinct from CHK4 genbits_fips_o: these prove the axis-edn adapter
        # forwarded tuser onto the native EDN beat the sink actually took.
        self._pool_fips_ok = 0
        self._pool_fips_bad = 0
        self._crypto_fips_ok = 0
        self._crypto_fips_bad = 0
        self._genbits_in_gen = 0
        self._gen_lengths = Counter()  # observed blocks-per-Generate histogram

        # CHK5 per-sink ROUTING (golden crypto sink) + genbits-chain membership state.
        # axis1_q: live ordered crypto-leg AXIS1 words (popped once per granted
        # post-adapter beat). _axis1_words/_km_words: every tapped word, for
        # the report-time membership tally against the verified-genbits multiset.
        # _genbits_words: Counter of the 32-bit slices of every CHK4-verified genbits
        # block (the golden pool both sinks must draw from).
        self._axis1_needed = any(
            self.sink_mode[n] == "golden" for n in ("aes", "kmac", "otbn_rnd", "otbn_urnd")
        )
        # Pool is the sole client of mux-leg [2], so golden routing is AXIS2==pool
        # native beats in order (the AXIS1/AES analog).
        self._axis2_needed = self.sink_mode["pool"] == "golden"
        self.axis1_q = deque()
        self._axis1_words = []
        self.axis2_q = deque()
        self._axis2_words = []
        self._km_words = []
        self._pool_words = []
        # Per-crypto-sink beat stash: every post-adapter EDN word + sim-time, used
        # by sink_beats() / sink_beat_times() and by membership tally in report().
        self._sink_words = {n: [] for n in ("aes", "kmac", "otbn_rnd", "otbn_urnd")}
        self._genbits_words = Counter()
        self._axis1_member_hits = 0
        self._axis1_member_misses = 0
        self._axis2_member_hits = 0
        self._axis2_member_misses = 0
        # Granted/accepted beat whose packed data probe is X/Z. That is a
        # malformed routed beat, not "didn't happen" -- report() fails on it.
        self._xz_routed_beats = 0
        # Scored beat (CHK2/CHK3/CHK4) whose data is X/Z, per checker. Same rule:
        # an unresolvable value on a valid beat is a failure, not a skipped beat.
        self._xz_scored_beats: dict[str, int] = {}
        # Adapter-protocol violation on the crypto-EDN leg: a same-cycle dual
        # grant, or an ack with an empty AXIS1 queue. The offending client may be
        # one this test does not score, so the per-sink results cannot carry it --
        # report() fails on this counter instead.
        self._routing_protocol_fails = 0
        # Contention evidence: the sim-time (ns) of every post-adapter crypto-EDN beat
        # per sink, index-aligned with _sink_words. Two sinks whose beat time-spans
        # OVERLAP were being granted EDN words during an overlapping window -- i.e. the
        # round-robin arbiter (u_axis_edn_crypto_s3c_scan) served two live clients
        # (real contention), not one sink drained fully before the other. Exposed via
        # sink_beat_times(). Same-cycle request overlap does not occur with this
        # stimulus (brief req pulses separated by long AXI config), so contention is
        # measured on beat windows.
        self._sink_beat_times = {n: [] for n in ("aes", "kmac", "otbn_rnd", "otbn_urnd")}

        self.results = {k: _StreamResult(k, w) for k, (_, w) in self._STREAMS.items()}
        self._skip = dict(self._warmup)
        self._tasks = []
        # Live runtime flag (not a one-shot fork decision). CHK5 sink / AXIS1
        # monitors are forked from start() but skip every cycle until
        # enable_chk5() — typically after the ESRC seed, before EDN enable —
        # so wait_seed_ready is not paying for packed-probe reads.
        self.chk5_enable = False

    # ------------------------------------------------------------------ drive
    def start(self):
        """Fork the noise driver + per-stream monitors (after reset released)."""
        d = self.dut
        # CHK2 default = AXI frontdoor FIFO_RDATA drain (check_fifo_frontdoor),
        # the overflow-robust observation point. Only fork the live backdoor
        # wire-tap monitor (entropy_stream_data_o) when explicitly selected.
        self._tasks = [
            cocotb.start_soon(self._drive_noise()),  # CHK1 runs inline here
            # CHK3: capture the seed on the REAL CSRNG seed handshake
            # (seed_valid && es_ack), not merely seed_valid -- the value the CSRNG
            # actually accepted.
            cocotb.start_soon(
                self._mon_handshake_rise(
                    "CHK3_seed",
                    d.drbg_seed_valid_o,
                    d.drbg_es_ack_o,
                    d.drbg_es_bits_o,
                    mask=(1 << 384) - 1,
                )
            ),
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
        if self._axis2_needed:
            self._tasks.append(cocotb.start_soon(self._mon_axis2_tap()))
        # KM sink: AXIS endpoint, tvalid&&tready handshake.
        if self.km_score_mode == "golden":
            # CHK5_km golden-match -- only when the KM entropy consumption is
            # golden-predictable (controlled KM firmware); disabled for rom_main.
            self._tasks.append(
                cocotb.start_soon(
                    self._mon_handshake(
                        "CHK5_km",
                        d.km_entropy_tvalid_o,
                        d.km_entropy_tready_o,
                        d.km_entropy_tdata_o,
                        mask=0xFFFFFFFF,
                    )
                )
            )
        elif self.km_score_mode == "observe":
            # CHK5_km alive mode: positive proof that KM consumed real post-mux
            # EDN words, without pretending rom_main's pull order is bit-exact
            # golden-predictable.
            self._tasks.append(
                cocotb.start_soon(
                    self._mon_handshake_observed(
                        "CHK5_km",
                        d.km_entropy_tvalid_o,
                        d.km_entropy_tready_o,
                        d.km_entropy_tdata_o,
                        mask=0xFFFFFFFF,
                    )
                )
            )
        elif self.km_score_mode == "membership":
            # CHK5_km membership: rom_main's pull ORDER is firmware-driven (not
            # golden-predictable), but every word the KM consumes must still be a
            # genuine CHK4 genbits-golden word. Stash the words; the report() tally
            # checks membership in the verified-genbits multiset (stronger than observe).
            self._tasks.append(cocotb.start_soon(self._mon_km_membership()))
        # Crypto sinks: native EDN req/ack beat off the packed probe vectors.
        # Golden sinks share one routing monitor so N live clients pop AXIS1
        # in grant order instead of racing on axis1_q.
        golden_sinks = []
        for key, idx in self._CRYPTO_SINK_IDX.items():
            name = key.split("_", 1)[1]  # CHK5_otbn_rnd -> otbn_rnd
            if self.sink_mode[name] == "observe":
                self._tasks.append(cocotb.start_soon(self._mon_edn_sink(key, idx, observe=True)))
            elif self.sink_mode[name] == "golden":
                golden_sinks.append((idx, key, name))
            elif self.sink_mode[name] == "membership":
                # Per-sink membership: stash each post-adapter beat; report()
                # checks every word is a genbits-golden word. Use when the
                # pull order is not grant-predictable (firmware-driven).
                self._tasks.append(cocotb.start_soon(self._mon_edn_sink_membership(idx, name)))
        if golden_sinks:
            self._tasks.append(cocotb.start_soon(self._mon_edn_sinks_routed(golden_sinks)))
        # Pool sink (EDN endpoint [2]): one native client behind u_axis_edn_pool_s3c_scan.
        if self.sink_mode["pool"] == "observe":
            self._tasks.append(
                cocotb.start_soon(
                    self._mon_handshake_observed(
                        "CHK5_pool",
                        d.pool_edn_req_o,
                        d.pool_edn_ack_o,
                        d.pool_edn_bus_o,
                        mask=0xFFFFFFFF,
                        fips_check=self._note_pool_fips,
                    )
                )
            )
        elif self.sink_mode["pool"] == "golden":
            self._tasks.append(cocotb.start_soon(self._mon_pool_edn_golden()))
        elif self.sink_mode["pool"] == "membership":
            self._tasks.append(cocotb.start_soon(self._mon_pool_edn_membership()))
        if self.chk2_backdoor:
            self._tasks.append(
                cocotb.start_soon(
                    self._mon_level(
                        "CHK2_compress",
                        d.esrc_compress_vld_o,
                        d.esrc_compress_data_o,
                        mask=0xFFFFFFFF,
                    )
                )
            )

    def enable_chk5(self) -> None:
        """Arm CHK5 monitors. Call after the seed, before EDN enable."""
        self.chk5_enable = True
        self.log.info("CHK5 armed (sink monitors live from this cycle)")

    async def _drive_noise(self):
        """Drive deterministic noise into the DUT and feed the golden chain the
        EXACT noise the decorrelator shifts, seeding the golden from the live RTL
        shift-register state so the two feedback SRs run in exact lockstep.

        The decorrelator is a FEEDBACK shift register (ff[0]=noise^ff[28]). The
        difference between two such SRs fed identical noise is a pure 29-bit
        rotation (the noise cancels), so it never decays: a wrong initial phase
        leaves a rotating difference that matches the sampled byte ff[28:21] only
        while it sits outside bits[28:21] and mismatches when it rotates in --
        an intermittent CHK1 mismatch if the golden is synced on decor alone.
        The full TRNG reset resets ff_stage through the entropy-source rst_ni.
        Detect the bring-up pulse from the explicit gated-reset probe. Ignore
        the initial asserted level at cold reset: first observe release, then
        the software-controlled TRNG reset assertion.

        So: drive noise from the start, wait for the TRNG reset, then seed from
        the pre-edge 12x29 ff_stage snapshot on the first valid decor sample
        whose bytes prove that snapshot's phase. From there the golden free-runs
        the whole CHK1..CHK5 chain on the read-back esrc_noise_o."""
        d = self.dut
        d.esrc_noise_ext_i.value = 0
        state = "wait_release"
        prev_decor = None
        prev_probe = None
        while True:
            dut_decor = _safe_int(d.esrc_decor_bytes_o)
            decor_valid = _safe_int(d.esrc_decor_valid_o) or 0
            whiten_push = _safe_int(d.esrc_whiten_push_o) or 0
            gsr = self.golden.decor_sr_word()
            changed = dut_decor is not None and prev_decor is not None and dut_decor != prev_decor

            trng_rst_n = _safe_int(d.trng_gated_rst_n_probe_o)
            if state == "wait_release":
                if trng_rst_n == 1:
                    state = "wait_reset"
            elif state == "wait_reset":
                # The coordinated TRNG reset resets the complete entropy_source:
                # decorrelator SR, SHA, FIFO, and CSRs.
                # Restart the decor-sample chain so its SHA starts at sample 0.
                if trng_rst_n == 0:
                    state = "wait_deassert"
                    self.chain = SepEntropyGolden(**self._gk)
                    self._reset_results()
            elif state == "wait_deassert":
                if trng_rst_n == 1:
                    state = "wait_fill"
            elif state == "wait_fill":
                # entropy_byte_sample_o captures the pre-edge ff_stage. The
                # previous cycle's probe is that exact state; require its byte
                # projection to match before locking the free-running golden.
                if decor_valid and prev_probe is not None and dut_decor is not None:
                    self._seed_golden(prev_probe)
                    if self.golden.decor_sr_word() == dut_decor:
                        state = "locked"
                        self.log.info(
                            "CHK1 golden seeded from live ff_stage @ decor=%024x", dut_decor
                        )
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
            if state in ("wait_fill", "locked") and whiten_push and dut_decor is not None:
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
        snapshot; clk_divider=8 phase-aligns the model divider with the RTL /8
        downsampler."""
        self.golden = SepEntropyGolden(**self._gk)
        self.golden.seed_decor_sr(sr_packed, clk_divider=8)

    def _reset_results(self):
        """Clear per-stream stats (called at the TRNG reset that begins the run)."""
        self.results = {k: _StreamResult(k, w) for k, (_, w) in self._STREAMS.items()}
        self._skip = dict(self._warmup)
        # Drop any pre-reset genbits/sink words so the CHK5 membership pool only
        # holds the real post-reset run (pre-reset genbits are X/garbage).
        self.axis1_q.clear()
        self._axis1_words.clear()
        self.axis2_q.clear()
        self._axis2_words.clear()
        self._km_words.clear()
        self._pool_words.clear()
        for words in self._sink_words.values():
            words.clear()
        for times in self._sink_beat_times.values():
            times.clear()
        self._genbits_words.clear()
        self._axis1_member_hits = 0
        self._axis1_member_misses = 0
        self._axis2_member_hits = 0
        self._axis2_member_misses = 0
        self._xz_routed_beats = 0
        self._xz_scored_beats = {}
        self._routing_protocol_fails = 0
        # Pre-reset genbits are X/garbage, so any Generate they opened is not a
        # real unterminated command -- drop the segmentation state with them.
        self._genbits_in_gen = 0
        self._gen_lengths.clear()
        self._fips_violations = 0
        self._pool_fips_ok = 0
        self._pool_fips_bad = 0
        self._crypto_fips_ok = 0
        self._crypto_fips_bad = 0

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
        # An absent side is never a match: an X/Z bus with a same-cycle dual grant
        # records (None, None), and a bare ``expected == actual`` would score that
        # as a compare with nothing compared -- satisfying a beat floor with no
        # evidence. A pair is a match only when both sides are present.
        ok = expected is not None and actual is not None and expected == actual
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
        if self._skip[key] > 0:  # warmup: drain but don't score
            self._skip[key] -= 1
            return
        ok = exp == actual
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

    def _note_xz_routed(self, where: str) -> None:
        """A completed handshake whose packed data is X/Z. Fail in report()."""
        self._xz_routed_beats += 1
        self.log.error(
            "CHK5 ROUTING FAIL: %s completed a beat with X/Z packed data "
            "(unobservable, not 'didn't happen')",
            where,
        )

    def _note_xz_scored(self, key: str) -> None:
        """A valid beat on a scored stream whose data is X/Z. Fail in report()."""
        self._xz_scored_beats[key] = self._xz_scored_beats.get(key, 0) + 1
        self.log.error("%s FAIL: a valid beat carried X/Z data (unscorable)", key)

    # --------------------------------------------------------------- monitors
    async def _mon_level(self, key, vld, sig, *, mask):
        """One item per cycle the valid is high."""
        while True:
            await RisingEdge(self.dut.clk_i)
            await ReadOnly()
            if _safe_int(vld):
                v = _safe_int(sig)
                if v is None:
                    self._note_xz_scored(key)
                else:
                    self._record(key, v & mask)

    async def _mon_handshake(self, key, vld, rdy, sig, *, mask):
        """One item per tvalid && tready beat."""
        while True:
            await RisingEdge(self.dut.clk_i)
            if not self.chk5_enable:
                continue
            await ReadOnly()
            if (_safe_int(vld) or 0) and (_safe_int(rdy) or 0):
                v = _safe_int(sig)
                if v is None:
                    self._note_xz_routed(key)
                    continue
                if key == "CHK5_km":
                    self._km_words.append(v & 0xFFFFFFFF)
                self._record(key, v & mask)

    async def _mon_handshake_observed(self, key, vld, rdy, sig, *, mask, fips_check=None):
        """One observed item per tvalid && tready beat, with no golden compare."""
        while True:
            await RisingEdge(self.dut.clk_i)
            if not self.chk5_enable:
                continue
            await ReadOnly()
            if (_safe_int(vld) or 0) and (_safe_int(rdy) or 0):
                if fips_check is not None:
                    fips_check()
                v = _safe_int(sig)
                if v is None:
                    self._note_xz_routed(key)
                    continue
                if key == "CHK5_km":
                    self._km_words.append(v & 0xFFFFFFFF)
                self._record_observed(key, v & mask)

    def _note_pool_fips(self) -> None:
        """Sample pool_edn_fips_o on a completed pool EDN beat."""
        if (_safe_int(self.dut.pool_edn_fips_o) or 0) == 1:
            self._pool_fips_ok += 1
        else:
            self._pool_fips_bad += 1

    def _note_crypto_fips(self, idx: int) -> None:
        """Sample crypto_edn_fips_o[idx] on a completed crypto-EDN beat."""
        vec = _safe_int(self.dut.crypto_edn_fips_o) or 0
        if ((vec >> idx) & 1) == 1:
            self._crypto_fips_ok += 1
        else:
            self._crypto_fips_bad += 1

    async def _mon_edn_sink(self, key, idx, *, observe):
        """One item per native-EDN beat to crypto sink `idx` -- the cycle the client
        asserts edn_req and the adapter pulses edn_ack. Data = that sink's edn_bus
        word. Reads the packed crypto_edn_*_o probe vectors (bit/word `idx`)."""
        d = self.dut
        while True:
            await RisingEdge(d.clk_i)
            if not self.chk5_enable:
                continue
            await ReadOnly()
            req = ((_safe_int(d.crypto_edn_req_o) or 0) >> idx) & 1
            ack = ((_safe_int(d.crypto_edn_ack_o) or 0) >> idx) & 1
            if req and ack:
                self._note_crypto_fips(idx)
                bus = _safe_int(d.crypto_edn_bus_o)
                if bus is None:
                    self._note_xz_routed(key)
                    continue
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
            if not self.chk5_enable:
                continue
            await ReadOnly()
            if (_safe_int(d.axis1_tvalid_o) or 0) and (_safe_int(d.axis1_tready_o) or 0):
                w = _safe_int(d.axis1_tdata_o)
                if w is None:
                    self._note_xz_routed("AXIS1")
                    continue
                w &= 0xFFFFFFFF
                self.axis1_q.append(w)
                self._axis1_words.append(w)

    async def _mon_axis2_tap(self):
        """Capture every accepted AXIS2 beat (entropy-pool pre-adapter word stream,
        entropy_muxed_req[2]). Sole client of u_axis_edn_pool_s3c_scan, so pool native beats
        equal this stream 1:1. Also stashed for the genbits-chain membership tally."""
        d = self.dut
        while True:
            await RisingEdge(d.clk_i)
            if not self.chk5_enable:
                continue
            await ReadOnly()
            if (_safe_int(d.axis2_tvalid_o) or 0) and (_safe_int(d.axis2_tready_o) or 0):
                w = _safe_int(d.axis2_tdata_o)
                if w is None:
                    self._note_xz_routed("AXIS2")
                    continue
                w &= 0xFFFFFFFF
                self.axis2_q.append(w)
                self._axis2_words.append(w)

    async def _mon_pool_edn_golden(self):
        """Bit-exact pool ROUTING: each post-adapter pool beat equals the next AXIS2
        word (in-order; the adapter has one client)."""
        d = self.dut
        while True:
            await RisingEdge(d.clk_i)
            if not self.chk5_enable:
                continue
            await ReadOnly()
            req = _safe_int(d.pool_edn_req_o) or 0
            ack = _safe_int(d.pool_edn_ack_o) or 0
            if req and ack:
                self._note_pool_fips()
                bus = _safe_int(d.pool_edn_bus_o)
                if bus is None:
                    self._note_xz_routed("CHK5_pool")
                    exp = self.axis2_q.popleft() if self.axis2_q else None
                    self._record_pair("CHK5_pool", exp, None)
                    continue
                v = bus & 0xFFFFFFFF
                exp = self.axis2_q.popleft() if self.axis2_q else None
                self._record_pair("CHK5_pool", exp, v)

    async def _mon_pool_edn_membership(self):
        """Stash every pool native-EDN beat; report() checks genbits-golden membership."""
        d = self.dut
        while True:
            await RisingEdge(d.clk_i)
            if not self.chk5_enable:
                continue
            await ReadOnly()
            req = _safe_int(d.pool_edn_req_o) or 0
            ack = _safe_int(d.pool_edn_ack_o) or 0
            if req and ack:
                self._note_pool_fips()
                bus = _safe_int(d.pool_edn_bus_o)
                if bus is None:
                    self._note_xz_routed("CHK5_pool membership")
                    continue
                self._pool_words.append(bus & 0xFFFFFFFF)

    def _stash_sink_beat(self, name, word):
        """Record one post-adapter beat for sink_beats() / sink_beat_times()."""
        self._sink_words[name].append(word)
        self._sink_beat_times[name].append(get_sim_time("ns"))

    async def _mon_edn_sinks_routed(self, sinks):
        """Bit-exact CHK5 ROUTING for one or more crypto sinks.

        Every adapter grant consumes the next AXIS1 word, including grants to
        clients this test does not score (OTBN wipe, parked-but-still-live
        endpoints). Scoring only the named golden sinks and leaving those
        other acks unpopped assigns the wrong AXIS1 word to AES/KMAC.

        A same-cycle dual grant is a routing fail: prim_arbiter_ppc grants
        one client per beat. An ack with an empty AXIS1 queue is a mismatch
        (the sink took a word the tap never saw).
        """
        golden_by_idx = {idx: (key, name) for idx, key, name in sinks}
        idx_name = {idx: key.split("_", 1)[1] for key, idx in self._CRYPTO_SINK_IDX.items()}
        d = self.dut
        while True:
            await RisingEdge(d.clk_i)
            if not self.chk5_enable:
                continue
            await ReadOnly()
            reqs = _safe_int(d.crypto_edn_req_o) or 0
            acks = _safe_int(d.crypto_edn_ack_o) or 0
            granted = [idx for idx in range(4) if ((reqs >> idx) & 1) and ((acks >> idx) & 1)]
            if not granted:
                continue
            bus = _safe_int(d.crypto_edn_bus_o)
            if bus is None:
                names = [idx_name[idx] for idx in granted]
                self._note_xz_routed(f"crypto-EDN grant {names}")
                if len(granted) == 1:
                    exp = self.axis1_q.popleft() if self.axis1_q else None
                    idx = granted[0]
                    self._note_crypto_fips(idx)
                    if idx in golden_by_idx:
                        key, _name = golden_by_idx[idx]
                        self._record_pair(key, exp, None)
                else:
                    for idx in granted:
                        self._note_crypto_fips(idx)
                        if idx in golden_by_idx:
                            key, _name = golden_by_idx[idx]
                            self._record_pair(key, None, None)
                continue
            if len(granted) > 1:
                names = [idx_name[idx] for idx in granted]
                self._routing_protocol_fails += 1
                self.log.error(
                    "CHK5 ROUTING FAIL: same-cycle dual crypto-EDN grant %s "
                    "(adapter must grant one client per AXIS1 beat)",
                    names,
                )
                for idx in granted:
                    self._note_crypto_fips(idx)
                    v = (bus >> (32 * idx)) & 0xFFFFFFFF
                    if idx in golden_by_idx:
                        key, name = golden_by_idx[idx]
                        self._stash_sink_beat(name, v)
                        self._record_pair(key, None, v)
                continue
            idx = granted[0]
            self._note_crypto_fips(idx)
            v = (bus >> (32 * idx)) & 0xFFFFFFFF
            exp = self.axis1_q.popleft() if self.axis1_q else None
            if idx in golden_by_idx:
                key, name = golden_by_idx[idx]
                self._stash_sink_beat(name, v)
                self._record_pair(key, exp, v)
            elif exp is None:
                self._routing_protocol_fails += 1
                self.log.error(
                    "CHK5 ROUTING FAIL: %s acked with empty AXIS1 "
                    "(unscored client consumed a word the tap never saw)",
                    idx_name[idx],
                )

    async def _mon_km_membership(self):
        """Stash every KM AXIS beat word; report() checks genbits-golden membership."""
        d = self.dut
        while True:
            await RisingEdge(d.clk_i)
            if not self.chk5_enable:
                continue
            await ReadOnly()
            if (_safe_int(d.km_entropy_tvalid_o) or 0) and (_safe_int(d.km_entropy_tready_o) or 0):
                w = _safe_int(d.km_entropy_tdata_o)
                if w is None:
                    self._note_xz_routed("CHK5_km membership")
                    continue
                self._km_words.append(w & 0xFFFFFFFF)

    async def _mon_edn_sink_membership(self, idx, name):
        """Stash every native-EDN beat word delivered to crypto sink `idx` (the cycle
        the client asserts edn_req and the adapter pulses edn_ack). report() checks
        each stashed word is a genbits-golden word. Use when the pull order is
        not grant-scored (firmware-driven)."""
        d = self.dut
        while True:
            await RisingEdge(d.clk_i)
            if not self.chk5_enable:
                continue
            await ReadOnly()
            req = ((_safe_int(d.crypto_edn_req_o) or 0) >> idx) & 1
            ack = ((_safe_int(d.crypto_edn_ack_o) or 0) >> idx) & 1
            if req and ack:
                self._note_crypto_fips(idx)
                bus = _safe_int(d.crypto_edn_bus_o)
                if bus is None:
                    self._note_xz_routed(f"CHK5_{name} membership")
                    continue
                self._stash_sink_beat(name, (bus >> (32 * idx)) & 0xFFFFFFFF)

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
                if v is None:
                    self._note_xz_scored(key)
                else:
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

        MODELLING DEPENDENCY: the Update BOUNDARY is taken from
        the DUT (gen_last), so a DUT that segmented wrongly would be followed by
        the golden rather than caught by it. Every block VALUE is still predicted
        independently from the (key, V) chain, so a wrong block, a missing Update
        or an extra Update all still mismatch; what the value compare cannot see
        is gen_last itself landing on the wrong beat. report() checks each segment
        length against legal_gen_lengths (the sequence glen unless the caller pins
        the full set via golden_kwargs["legal_gen_lengths"]).

        Protocol: every emitted block must carry genbits_fips_o==1.
        """
        d = self.dut
        while True:
            await RisingEdge(d.clk_i)
            await ReadOnly()
            if not (_safe_int(d.drbg_genbits_vld_o) or 0):
                continue
            v = _safe_int(d.drbg_genbits_data_o)
            if v is None:
                self._note_xz_scored("CHK4_genbits")
            else:
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

    def km_words(self):
        """The Key-Manager AXIS entropy words tapped so far, in beat order.

        Populated in every CHK5_km mode (golden, observe, membership), so a caller
        can compare a word the KM firmware later stored to KM SRAM against the
        word the DUT actually delivered on the AXIS endpoint. Returns a copy.
        """
        return list(self._km_words)

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
            raise ValueError(f"unknown crypto sink {name!r} (known: {sorted(self._sink_words)})")
        return len(self._sink_words[name])

    def sink_beat_times(self, name):
        """Sim-times (ns) of the post-adapter crypto-EDN beats delivered to crypto sink
        `name`, in delivery order (index-aligned with the membership word stash). Two
        sinks whose returned time-spans overlap were granted EDN words during an
        overlapping window -- positive arbiter-contention evidence (CHK-OVERLAP)."""
        if name not in self._sink_beat_times:
            raise ValueError(
                f"unknown crypto sink {name!r} (known: {sorted(self._sink_beat_times)})"
            )
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

        # CHK5 membership: KM (membership mode) and crypto-leg AXIS1 words must come from
        # the verified genbits multiset, and removal from a working copy shows
        # over-consumption as a miss. The pool is DUT genbits, so it is golden only when
        # CHK4 passes.
        crypto_membership = [
            n for n in ("aes", "kmac", "otbn_rnd", "otbn_urnd") if self.sink_mode[n] == "membership"
        ]
        pool_membership = self.sink_mode["pool"] == "membership"
        if (
            self.km_score_mode == "membership"
            or self._axis1_needed
            or self._axis2_needed
            or crypto_membership
            or pool_membership
        ):
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
                self.log.info(
                    "CHK5_km membership: %d/%d KM AXIS words are genbits-golden "
                    "words (rom_main pull order is firmware-driven, not scored)",
                    rkm.matches,
                    rkm.dut_items,
                )
            # Per-sink crypto membership. Those words are slices of the crypto-leg
            # AXIS1 stream. When a golden crypto sink is also live the AXIS1 tally
            # below removes every AXIS1 beat from `pool`; scoring membership against
            # the same Counter would double-count (AES golden + KMAC membership
            # would miss the KMAC beats a second time). Membership-only (no AXIS1
            # tap) still removes from the shared pool so over-consumption vs KM /
            # pool still shows.
            member_pool = (
                (Counter(self._genbits_words) if self._axis1_needed else pool)
                if crypto_membership
                else pool
            )
            for name in crypto_membership:
                r = self.results[self._SINK_KEYS[name]]
                for w in self._sink_words[name]:
                    r.dut_items += 1
                    if member_pool[w] > 0:
                        member_pool[w] -= 1
                        r.matches += 1
                    else:
                        r.mismatches += 1
                        if r.first_mismatch is None:
                            r.first_mismatch = (r.dut_items - 1, None, w)
                self.log.info(
                    "CHK5_%s membership: %d/%d crypto-EDN words are genbits-"
                    "golden words (concurrent-arbiter routing order not scored)",
                    name,
                    r.matches,
                    r.dut_items,
                )
            if self._axis1_needed:
                for w in self._axis1_words:
                    if pool[w] > 0:
                        pool[w] -= 1
                        self._axis1_member_hits += 1
                    else:
                        self._axis1_member_misses += 1
                self.log.info(
                    "CHK5_axis1 membership: %d/%d crypto-leg AXIS1 words are genbits-golden words",
                    self._axis1_member_hits,
                    self._axis1_member_hits + self._axis1_member_misses,
                )
                if self._axis1_member_misses or self._axis1_member_hits == 0:
                    self.log.error(
                        "CHK5_axis1 membership FAIL: %d crypto-leg words NOT in "
                        "the genbits golden (or none seen) -- routing/chain broken",
                        self._axis1_member_misses,
                    )
                    any_fail = True
            if pool_membership:
                r = self.results["CHK5_pool"]
                for w in self._pool_words:
                    r.dut_items += 1
                    if pool[w] > 0:
                        pool[w] -= 1
                        r.matches += 1
                    else:
                        r.mismatches += 1
                        if r.first_mismatch is None:
                            r.first_mismatch = (r.dut_items - 1, None, w)
                self.log.info(
                    "CHK5_pool membership: %d/%d pool EDN words are genbits-golden words",
                    r.matches,
                    r.dut_items,
                )
            if self._axis2_needed:
                for w in self._axis2_words:
                    if pool[w] > 0:
                        pool[w] -= 1
                        self._axis2_member_hits += 1
                    else:
                        self._axis2_member_misses += 1
                self.log.info(
                    "CHK5_axis2 membership: %d/%d pool-leg AXIS2 words are genbits-golden words",
                    self._axis2_member_hits,
                    self._axis2_member_hits + self._axis2_member_misses,
                )
                if self._axis2_member_misses or self._axis2_member_hits == 0:
                    self.log.error(
                        "CHK5_axis2 membership FAIL: %d pool-leg words NOT in "
                        "the genbits golden (or none seen) -- routing/chain broken",
                        self._axis2_member_misses,
                    )
                    any_fail = True

        keys = ["CHK1_decor", "CHK2_compress", "CHK3_seed", "CHK4_genbits"]
        # Append every enabled CHK5 sink (km + the crypto sinks), in a stable order.
        for name, key in self._SINK_KEYS.items():
            mode = self.sink_mode[name]
            if mode in ("golden", "observe", "membership"):
                keys.append(key)
            elif name == "km":
                self.log.info(
                    "CHK5_km disabled; KM entropy consumption must be "
                    "covered functionally by the test"
                )
        for key in keys:
            r = self.results[key]
            sink_name = key.split("_", 1)[1] if key.startswith("CHK5_") else None
            sink_md = self.sink_mode[sink_name] if sink_name is not None else None
            if sink_md == "observe":
                self.log.info(
                    "%-14s observed_beats=%d (alive mode: no bit-exact compare)", r.name, r.matches
                )
            elif sink_md == "membership":
                self.log.info(
                    "%-14s membership match=%d/%d (each a genbits-golden word; "
                    "pull order firmware-driven, not order-scored)",
                    r.name,
                    r.matches,
                    r.dut_items,
                )
            else:
                # Crypto-golden sinks have no chain queue (_STREAMS name is None) and
                # score via _record_pair (axis1 routing); show no "golden left" for them.
                qname = self._STREAMS[key][0]
                left = len(self._expected_q(key)) if qname else 0
                self.log.info(
                    "%-14s dut_items=%d match=%d mismatch=%d (golden left=%d)",
                    r.name,
                    r.dut_items,
                    r.matches,
                    r.mismatches,
                    left,
                )
            hexw = max(1, r.width // 4)
            for idx, exp, act, ok in r.pairs[:12]:
                es = "----" if exp is None else _fmt_word(exp, hexw)
                if sink_md == "observe":
                    self.log.info("    [%-2d] OBS act=%s", idx, _fmt_word(act, hexw))
                else:
                    self.log.info(
                        "    [%-2d] %s exp=%s act=%s",
                        idx,
                        "OK " if ok else "XX!",
                        es,
                        _fmt_word(act, hexw),
                    )
            if r.first_mismatch is not None:
                idx, exp, act = r.first_mismatch
                es = "----" if exp is None else _fmt_word(exp, hexw)
                self.log.info(
                    "    first mismatch [%d] exp=%s act=%s", idx, es, _fmt_word(act, hexw)
                )
            if r.mismatches > 0:
                any_fail = True
            # Minimum-evidence: a checkpoint that never scored (or scored too few)
            # is a silent hole -- fail it, don't pass vacuously.
            need = self._min_matches.get(key, 1)
            if r.matches < need:
                self.log.error(
                    "    %s INSUFFICIENT EVIDENCE: matches=%d < min=%d "
                    "(checkpoint never fired / under-exercised)",
                    r.name,
                    r.matches,
                    need,
                )
                any_fail = True
        if self._xz_routed_beats:
            self.log.error(
                "CHK5 ROUTING FAIL: %d accepted beat(s) had X/Z packed data", self._xz_routed_beats
            )
            any_fail = True
        for key, n in sorted(self._xz_scored_beats.items()):
            self.log.error("%s FAIL: %d valid beat(s) carried X/Z data", key, n)
            any_fail = True
        if self._routing_protocol_fails:
            self.log.error(
                "CHK5 ROUTING FAIL: %d crypto-EDN adapter-protocol violation(s) "
                "(dual grant, or ack with empty AXIS1)",
                self._routing_protocol_fails,
            )
            any_fail = True
        # Protocol checks (CHK3/CHK4 semantics, independent of value match).
        if self._fips_violations:
            self.log.error(
                "CHK4 FIPS violation: %d genbits with genbits_fips_o != 1", self._fips_violations
            )
            any_fail = True
        pool_fips_n = self._pool_fips_ok + self._pool_fips_bad
        if pool_fips_n:
            if self._pool_fips_bad:
                self.log.error(
                    "CHK5_pool FIPS FAIL: %d/%d beats with pool_edn_fips_o != 1",
                    self._pool_fips_bad,
                    pool_fips_n,
                )
                any_fail = True
            else:
                self.log.info(
                    "CHK5_pool FIPS PASS: %d beats with pool_edn_fips_o=1", self._pool_fips_ok
                )
        crypto_fips_n = self._crypto_fips_ok + self._crypto_fips_bad
        if crypto_fips_n:
            if self._crypto_fips_bad:
                self.log.error(
                    "CHK5 crypto FIPS FAIL: %d/%d beats with crypto_edn_fips_o != 1",
                    self._crypto_fips_bad,
                    crypto_fips_n,
                )
                any_fail = True
            else:
                self.log.info(
                    "CHK5 crypto FIPS PASS: %d beats with crypto_edn_fips_o=1", self._crypto_fips_ok
                )
        # Generate segmentation: csrng_cmd_stage marks the final genbits beat of each
        # Generate as glast (acmd_bus[16]) and csrng_core drives it to req_glast_i, so
        # each command ends with exactly one gen_last beat, where its trailing Update lands.
        self.log.info(
            "CHK4 Generate segmentation: %d completed commands, blocks/cmd %s, "
            "%d block(s) in the open command (seq-commanded glen=%d, legal=%s)",
            sum(self._gen_lengths.values()),
            dict(sorted(self._gen_lengths.items())) or "{}",
            self._genbits_in_gen,
            self.glen,
            sorted(self.legal_gen_lengths),
        )
        # A run in which no Generate command completes (gen_last is a level held
        # from acmd_sop, and an EDN-commanded glen above the run's block count never
        # terminates) gives the loop below nothing to check, so CHK4's Update
        # boundary is taken from the DUT unchecked. Log that rather than let a
        # silent zero read as coverage.
        if not self._gen_lengths and self.results["CHK4_genbits"].dut_items:
            self.log.info(
                "CHK4 segmentation NOT EXERCISED: no Generate command completed "
                "in this run (%d genbits observed), so gen_last was never seen "
                "asserted and the trailing-Update boundary is unverified. "
                "Closing this needs an independent probe of the commanded glen "
                "inside csrng_cmd_stage.",
                self.results["CHK4_genbits"].dut_items,
            )
        # A completed command must carry one of the legal block counts (the
        # caller's declared lengths, else the sequence's own commanded glen),
        # and never zero, which would mean gen_last fired with no genbits at all.
        for seg_len, count in sorted(self._gen_lengths.items()):
            if seg_len < 1 or seg_len not in self.legal_gen_lengths:
                self.log.error(
                    "CHK4 illegal Generate segmentation: %d command(s) emitted "
                    "%d blocks; legal=%s. gen_last landed somewhere the "
                    "commanded glen cannot explain, so the trailing CTR_DRBG "
                    "Update ran at the wrong point.",
                    count,
                    seg_len,
                    sorted(self.legal_gen_lengths),
                )
                any_fail = True
        self.log.info("==== end report (strict=%s, any_fail=%s) ====", self.strict, any_fail)
        if self.strict and any_fail:
            raise AssertionError(
                "sep_drbg_scoreboard: CHK1..CHK5 failure (mismatch / insufficient "
                "evidence / protocol violation)"
            )
        return not any_fail
