# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AES and KMAC contend at the crypto-EDN arbiter, and both compute correctly on routed DRBG words.

OCAH provenance: ``sep_drbg_real_sink_multi_rand_test`` checks simultaneous
delivery to multiple real entropy sinks.

AES (crypto_edn[0]) and KMAC (crypto_edn[1]) both pull
the shared crypto-EDN leg (drbg_axis_edn_adapter -> u_axis_edn_crypto_s3c_scan round-robin
arbiter, sep_crypto.sv) concurrently off ONE verified DRBG stream: TWO real
crypto clients contend the crypto arbiter.
`sep_drbg_real_sink_multi_km_aes_test` has AES as the sole crypto client (KMAC parked)
and uses KM (a different leg) as the second sink; the standalone AES/KMAC breadth
tests are single-engine KATs. DISTINCT from all of those -- do NOT re-prove
single-sink routing here.

The two sinks are crypto engines that share one EDN adapter at the crypto-endpoint
arbiter. No KM firmware / no
rom_main / no real fuse-sense (+skip_fuse_sense), so it follows the standalone
crypto-engine bring-up style.

CHK5 ROUTING: each AES and each KMAC post-adapter beat equals the AXIS1 word
the adapter granted that cycle. Membership of those words in the CHK4 genbits
set follows because AXIS1 is chained to genbits in report().

Budget: total genbits consumption is kept < cfg.glen=32 blocks so the CHK4
one-Generate-per-seed golden stays bit-exact (do not overrun glen). No KM boot
here, so the full 32-block budget is available for AES+KMAC; a few ops each is far
under it.

Checkers:
  CHK1..CHK4     bit-exact golden (decor/compress/seed/CTR_DRBG genbits) -- strict;
                 the correctness anchor the AXIS1 routing stream draws from.
  CHK-SINK-BIND  AES alone scores AES-named beats and the KMAC sink takes zero
                 beats, so the sink map is bound independently of adapter order.
  CHK-NONVAC     single-engine baseline: AES-alone ct == AES-256-ECB golden, and the
                 KMAC sink takes zero beats while idle (proves the both-beats check
                 is not always-true).
  CHK-BOTH-COMPLETE  under contention: every contended AES block == golden and every
                 KMAC digest == golden (both engines compute correctly while sharing
                 the arbiter).
  CHK-BOTH-BEATS every engaged crypto sink (AES, KMAC) takes real post-adapter EDN
                 beats DURING the concurrent fork (per-sink beat delta > 0).
  CHK-OVERLAP    positive arbiter-CONTENTION proof: AES's and KMAC's crypto-EDN beat
                 TIME-SPANS overlap during the fork (each was being granted words by
                 u_axis_edn_crypto_s3c_scan in an overlapping window), so neither sink
                 drained fully before the other started. This is interval-span
                 containment, not per-cycle interleaving: it does not prove the two
                 clients were granted on alternating cycles.
  CHK-ROUTING    each AES beat and each KMAC beat equals the AXIS1 word granted
                 that cycle (dual-sink bit-exact CHK5).
  CHK-MEMBERSHIP each routed word is a CHK4 genbits-golden word (AXIS1 chain).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cocotb
import pyuvm
from env.sep_aes_golden import aes256_ecb_encrypt_words
from env.sep_kmac_golden import kmac_family_words
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from seq_lib.sep_aes_seq import SepAes
from seq_lib.sep_kmac_seq import SepKmac, SepKmacCfg

# AES SW-key path: arbitrary key (the test exercises the entropy datapath + the
# arbiter, not a key contract -- same as `sep_drbg_real_sink_multi_km_aes_test`).
# Plaintext is seed-randomized.
AES_KEY = (
    0x0F0E0D0C,
    0x0B0A0908,
    0x07060504,
    0x03020100,
    0x1F1E1D1C,
    0x1B1A1918,
    0x17161514,
    0x13121110,
)
# KMAC-256 keyed cell: arbitrary 256-bit key + customization; message seed-randomized.
KMAC_KEY = (
    0x03020100,
    0x07060504,
    0x0B0A0908,
    0x0F0E0D0C,
    0x13121110,
    0x17161514,
    0x1B1A1918,
    0x1F1E1D1C,
)
KMAC_S = b"crypto EDN arbiter"

# Concurrent-window op counts. Kept small so AES+KMAC consumption stays well under
# one CSRNG Generate (cfg.glen=32 genbits blocks) -- else the bit-exact CHK4 golden
# (one Generate per seed) desyncs. No KM boot here, so the whole 32-block budget is
# for these ops.
AES_BLOCKS_FORK = 2
KMAC_OPS_FORK = 2


@dataclass
class CryptoEdnMultisinkCfg:
    """Single source for the crypto-EDN multisink arbitration seeded payload policy.

    Key material is fixed -- the test exercises the entropy datapath and the
    crypto-EDN arbiter, not a key contract -- while the seed randomizes the AES
    plaintext and the KMAC message shape/content. All resolved values are logged
    so any seeded failure is reproducible. The fork op counts are pinned and
    budget-bounded to keep total genbits consumption under one CSRNG Generate.
    """

    seed: int
    aes_key: tuple = AES_KEY
    kmac_key: tuple = KMAC_KEY
    kmac_s: bytes = KMAC_S
    aes_blocks_fork: int = AES_BLOCKS_FORK
    kmac_ops_fork: int = KMAC_OPS_FORK
    aes_pt: list = field(default_factory=list)  # resolved from seed
    kmac_msg: list = field(default_factory=list)  # resolved from seed

    @classmethod
    def randomize(cls, seed: int) -> "CryptoEdnMultisinkCfg":
        """Resolve the seeded fields from `seed` (single RNG = reproducible)."""
        rng = SepSeededRng(seed)
        return cls(
            seed=seed,
            aes_pt=[rng.getrandbits(32) for _ in range(4)],
            kmac_msg=[rng.getrandbits(32) for _ in range(rng.randrange(2, 7))],
        )

    def log_resolved(self, logger) -> None:
        """Log every resolved value so a seeded failure is reproducible."""
        logger.info(
            "crypto-EDN multisink arbitration RANDCFG resolved (seed=%d):",
            self.seed,
        )
        logger.info("  aes_pt   = %s", [hex(w) for w in self.aes_pt])
        logger.info(
            "  kmac_msg = %s (%d words)", [hex(w) for w in self.kmac_msg], len(self.kmac_msg)
        )
        logger.info("  aes_key/kmac_key = <fixed 256b>  kmac_s = %r", self.kmac_s)
        logger.info(
            "  aes_blocks_fork=%d  kmac_ops_fork=%d (pinned, budget-bounded)",
            self.aes_blocks_fork,
            self.kmac_ops_fork,
        )


@pyuvm.test()
class sep_crypto_edn_multisink_arbitration_test(sep_base_test):
    """Concurrent AES and KMAC each match their golden, and each beat routes the granted word."""

    def _aes_beats(self) -> int:
        """Live count of AES crypto-EDN post-adapter beats (public scoreboard accessor)."""
        return self.drbg_sb.sink_beats("aes")

    def _kmac_beats(self) -> int:
        """Live count of KMAC crypto-EDN post-adapter beats (public scoreboard accessor)."""
        return self.drbg_sb.sink_beats("kmac")

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()

        # Do not park OTBN/HMAC via SW_RESET_N. Holding a crypto engine in
        # reset while the crypto-EDN adapter is live wedges the AES masking reseed
        # (AES sits idle, no OUTPUT_VALID). OTBN/HMAC are
        # left released (SW_RESET_N reset 0x7E): OTBN does a one-shot post-reset
        # secure wipe then goes idle, and HMAC is not a crypto-EDN client, so AES +
        # KMAC are the sustained clients contending the arbiter (the standalone
        # AES recipe likewise leaves all crypto released and drives AES on entropy).

        # RANDCFG single source: one config object owns the seeded payload policy and logs
        # every resolved value (reproducibility). Key material fixed; seed randomizes
        # the AES plaintext + KMAC message.
        cfg = CryptoEdnMultisinkCfg.randomize(self.random_seed())
        self.logger.info("Crypto-EDN AES+KMAC arbiter contention:")
        cfg.log_resolved(self.logger)
        aes_pt = cfg.aes_pt
        kmac_msg = cfg.kmac_msg

        # Strict entropy bring-up: CHK1..CHK4 bit-exact anchors the one DRBG. Both
        # crypto sinks score CHK5 ROUTING (each post-adapter beat equals the AXIS1
        # word granted that cycle). KM leg unused.
        await self.bring_up_entropy(
            strict=True, score_km=False, score_sinks={"aes": "golden", "kmac": "golden"}
        )
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        self.start_fifo_drain()  # frontdoor CHK2 drain

        self.aes = SepAes(self)
        self.kmac = SepKmac(self)
        # Reseed the AES masking PRNG ONCE up front, BEFORE configure -- the
        # standalone AES order. Do NOT issue an explicit PRNG_RESEED between the key
        # load and an encrypt: that wedges the auto-start (AES accepts DATA_IN but
        # never asserts OUTPUT_VALID). Each `load_key_iv` kicks off its OWN key-
        # triggered reseed (spec-ordered, waits idle after the key) -- that reseed is
        # what pulls a crypto-EDN word, so re-loading the key per AES op makes AES a
        # live EDN client for the arbiter contention with no separate reseed trigger.
        await self.aes.trigger_prng_reseed()
        await self.aes.configure_ecb_enc_256(sideload=False)
        aes_golden = aes256_ecb_encrypt_words(list(cfg.aes_key), aes_pt)

        kmac_cfg = SepKmacCfg(
            mode="kmac",
            sec=256,
            msg_words=kmac_msg,
            outlen_bytes=32,
            key_words=list(cfg.kmac_key),
            key_bits=256,
            s=cfg.kmac_s,
        )
        kmac_golden = kmac_family_words(**kmac_cfg.golden_kwargs())

        # --- CHK-NONVAC: single-engine AES baseline (correct in isolation, and with
        # KMAC idle the KMAC sink takes ZERO beats -- the not-always-true evidence for
        # the both-beats check below). KMAC's KAT is proven under contention in the
        # fork (a masking engine reseeds once and would not re-pull per op, so putting
        # its first op in the fork lands its seeding beats in the contention window).
        await self.aes.load_key_iv(list(cfg.aes_key))  # key-load reseed pulls crypto-EDN
        base_ct = await self.aes.run_ecb_block(aes_pt)
        assert base_ct == aes_golden, (
            "AES baseline ct != AES-256-ECB golden:\n"
            f"  ct    ={[hex(w) for w in base_ct]}\n  golden={[hex(w) for w in aes_golden]}"
        )
        assert self._aes_beats() > 0, (
            "CHK-SINK-BIND FAIL: AES-alone produced no AES-named beats, so the "
            "sink map is not bound independently of the adapter order"
        )
        assert self._kmac_beats() == 0, (
            f"KMAC took crypto-EDN beats before it was driven "
            f"({self._kmac_beats()}) -- both-beats check would be vacuous"
        )
        self.logger.info(
            "CHK-SINK-BIND PASS: AES-alone scored %d AES beats and 0 KMAC beats",
            self._aes_beats(),
        )
        self.logger.info(
            "CHK-NONVAC PASS: AES single-engine baseline reproduces its KAT "
            "(AES-256-ECB ct==golden) with the KMAC sink idle (0 beats)"
        )

        # --- CHK-BOTH-*: AES + KMAC as CONCURRENT crypto-EDN clients ---------------
        aes_before, kmac_before = self._aes_beats(), self._kmac_beats()

        async def aes_arm():
            """AES crypto-EDN pulls: each iteration re-loads the key (its key-write
            reseed pulls a fresh crypto-EDN word) then runs an ECB block; every block's ct
            is value-checked against the golden under contention."""
            for i in range(cfg.aes_blocks_fork):
                await self.aes.load_key_iv(list(cfg.aes_key))
                ct = await self.aes.run_ecb_block(aes_pt)
                # Every fork block is compared bit-exact: ECB is stateless and the
                # key/plaintext are identical per iteration, so the expected value is
                # known for every block and each one is a contended data point.
                assert ct == aes_golden, (
                    f"AES contended block-{i} ct != golden:\n"
                    f"  ct    ={[hex(w) for w in ct]}\n"
                    f"  golden={[hex(w) for w in aes_golden]}"
                )

        async def kmac_arm():
            """KMAC crypto-EDN pulls: each keyed KMAC-256 op reseeds masking from EDN;
            digest value-checked against the Keccak golden under contention."""
            for i in range(cfg.kmac_ops_fork):
                digest = await self.kmac.run_family(kmac_cfg, tag=f"KMAC-fork{i}")
                assert digest == kmac_golden, (
                    f"KMAC contended op-{i} digest != golden:\n"
                    f"  digest={[hex(w) for w in digest]}\n"
                    f"  golden={[hex(w) for w in kmac_golden]}"
                )

        # TRUE fork: both arms run as concurrent cocotb tasks, so the AES and KMAC
        # masking-EDN pulls overlap and contend at the crypto arbiter in one window.
        aes_task = cocotb.start_soon(aes_arm())
        kmac_task = cocotb.start_soon(kmac_arm())
        await aes_task
        await kmac_task
        self.logger.info(
            "CHK-BOTH-COMPLETE PASS: under contention every AES block ct==golden AND "
            "KMAC digest==golden"
        )

        aes_after, kmac_after = self._aes_beats(), self._kmac_beats()
        assert aes_after > aes_before, (
            f"AES took no crypto-EDN beats during the concurrent fork "
            f"(beats {aes_before}->{aes_after})"
        )
        assert kmac_after > kmac_before, (
            f"KMAC took no crypto-EDN beats during the concurrent fork "
            f"(beats {kmac_before}->{kmac_after})"
        )
        self.logger.info(
            "CHK-BOTH-BEATS PASS: both crypto sinks took real post-adapter EDN beats "
            "in the contention window (AES %d->%d, KMAC %d->%d)",
            aes_before,
            aes_after,
            kmac_before,
            kmac_after,
        )

        # --- CHK-OVERLAP: positive arbiter-CONTENTION proof. CHK-BOTH-BEATS only
        # proves each client took beats SOMEWHERE in the fork; this proves AES's and
        # KMAC's crypto-EDN beat TIME-SPANS overlap -- both were being granted words by
        # u_axis_edn_crypto_s3c_scan during an overlapping window, so neither sink
        # drained fully before the other started. Interval-span containment, not
        # per-cycle interleaving. Scoping by the pre-fork beat count isolates the
        # fork's beats. Same-cycle dual req does not occur here: each masking reseed
        # is a brief req pulse separated by long AXI configuration.
        aes_ft = self.drbg_sb.sink_beat_times("aes")[aes_before:]
        kmac_ft = self.drbg_sb.sink_beat_times("kmac")[kmac_before:]
        assert aes_ft and kmac_ft, (
            f"missing fork beats (AES {len(aes_ft)}, KMAC {len(kmac_ft)}) -- "
            "cannot evaluate contention overlap"
        )
        overlap = aes_ft[0] <= kmac_ft[-1] and kmac_ft[0] <= aes_ft[-1]
        assert overlap, (
            "AES and KMAC crypto-EDN beat windows do not overlap during the fork "
            f"(AES [{aes_ft[0]:.0f},{aes_ft[-1]:.0f}]ns, KMAC [{kmac_ft[0]:.0f},"
            f"{kmac_ft[-1]:.0f}]ns): the arbiter served them sequentially, not "
            "concurrently -- the 'contention' claim would be vacuous"
        )
        ov_lo, ov_hi = max(aes_ft[0], kmac_ft[0]), min(aes_ft[-1], kmac_ft[-1])
        self.logger.info(
            "CHK-OVERLAP PASS: AES and KMAC crypto-EDN beat windows overlap over "
            "[%.0f,%.0f]ns (AES [%.0f,%.0f], KMAC [%.0f,%.0f]) -- neither sink drained "
            "before the other started (interval-span containment, not per-cycle interleaving)",
            ov_lo,
            ov_hi,
            aes_ft[0],
            aes_ft[-1],
            kmac_ft[0],
            kmac_ft[-1],
        )

        # --- EOT: engine status clean, entropy health, dual-sink CHK5 routing ------
        await self.aes.check_status_clean("EOT")
        await self.kmac.check_status_clean("EOT")
        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        # Strict report: CHK1..CHK4 bit-exact + CHK5_aes/CHK5_kmac ROUTING
        # (each post-adapter beat == the AXIS1 word granted that cycle).
        assert self.drbg_sb.report()
        ra = self.drbg_sb.results["CHK5_aes"]
        rk = self.drbg_sb.results["CHK5_kmac"]
        self.logger.info(
            "CHK-ROUTING PASS: CHK5_aes match=%d and CHK5_kmac match=%d equal the "
            "AXIS1 grant-order stream (mismatch=0)",
            ra.matches,
            rk.matches,
        )
        self.logger.info(
            "CHK-MEMBERSHIP PASS: every AES and every KMAC crypto-EDN word is a CHK4 "
            "genbits-golden word (AXIS1 chained to genbits) -- one DRBG partitions "
            "into the two contending crypto sinks; CHK1..CHK4 bit-exact; alerts zero"
        )
