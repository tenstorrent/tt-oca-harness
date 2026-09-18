# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DRBG real-sink multi-consumer: KM + AES concurrent.

One real DRBG/ESRC/EDN stream feeds TWO real entropy sinks concurrently:
the KM AXIS endpoint (real KM firmware rom_main pulls the DRBG sampler)
and the AES native crypto-EDN leg (ECB-256 reseed+encrypt). KM and AES are driven as a
TRUE cocotb fork so both contend at the EDN arbiter in the same window. The CHK5 proof
is BIT-EXACT and genbits-anchored:

  * AES (per-sink ROUTING, golden): each AES post-adapter beat == the next word on the
    AXIS1 pre-adapter golden tap (sep_crypto.entropy_muxed_req[1], tb_top axis1_*).
    The drbg_axis_edn_adapter is round-robin, so this in-order equality holds because
    AES is the ONLY active crypto sink (OTBN/KMAC parked -> never request -> AES is
    granted every word in order). This is exactly the reference suite's AXIS1 routing proof.
  * Genbits chain: every AXIS1 word AND every KM AXIS word must be
    a member of the CHK4 CTR_DRBG genbits-golden word multiset (report() tally, with
    removal) -- proving the one verified DRBG stream PARTITIONS into the two sinks.
    the reference suite treats the AXIS1 tap as its own golden; here it is anchored back to the
    bit-exact CTR_DRBG genbits.
  * KM (membership): rom_main's pull ORDER is firmware-driven (not order-predictable),
    so KM is scored bit-exact MEMBERSHIP (each KM word is a genbits-golden word) rather
    than order.

Consumption is bounded to a single CSRNG Generate (<= cfg.glen=32 genbits blocks) so
the CHK4 genbits golden (one Generate per seed) stays bit-exact -- the genbits-word
pool the membership tally draws from must cover all consumed words. 1 keygen + 2 AES
blocks + KM boot ~ 24 blocks (< 32); the per-consumer block costs are at the
constants.

Checkers:
  CHK1..CHK4  bit-exact golden (decorrelator / compressor / seed / CTR_DRBG genbits)
              -- the correctness anchor for the genbits-chain membership below.
  CHK-AESKAT  AES block-0 ciphertext == independent AES-256-ECB golden (sep_aes_golden,
              FIPS-197) -- the AES engine computes correctly, not just "consumed".
  CHK5_aes (golden)  bit-exact per-sink ROUTING: every AES post-adapter beat == the
              next AXIS1 word (scoreboard _mon_edn_sink_golden); strict report() fails
              on any mismatch or an ack with an empty AXIS1 queue.
  CHK5_axis1 / CHK5_km (membership)  every AXIS1 word and every KM word is a genbits-
              golden word (report() multiset tally, removal) -- the genbits-anchored
              partition proof; a non-member word fails the run.
  CHK-CONCUR  KM AXIS beats AND AES crypto-EDN beats BOTH advance during the concurrent
              fork (per-sink beat delta > 0) -- both sinks consumed within the fork
              window (the OSS analog of the reference suite's fork count_good/ack-advance check;
              like the reference suite it evidences overlap, not strict same-cycle arbiter contention).
  CSRNG/EDN error/recoverable-alert regs stay zero; AES STATUS no alert.

Delta vs the reference suite: per-sink bit-exact for >1 CONCURRENT crypto sink
(e.g. AES+KMAC at once) would need the reference suite's full per-endpoint arbiter-assignment trace
(the round-robin reorder); the scoreboard rejects >1 golden crypto sink. KM bit-exact
ORDER needs controlled KM firmware (rom_main is firmware-driven); KM here is bit-exact
membership. Neither is required by this test's KM+AES scope.

Boot recipe matches the KAT family (real fuse-sense, valid PROD OTP image;
rom_main built PROD_BOOT_WIPE=0). AES is left released through entropy bring-up so
its masking PRNG reseed is served as EDN starts (the real_sink_aes ordering);
OTBN/KMAC/HMAC are parked so KM + AES are the only entropy sinks.
"""

from __future__ import annotations

import cocotb
import pyuvm
from env.sep_aes_golden import aes256_ecb_encrypt_words
from sep_base_test import sep_base_test
from seq_lib.sep_aes_seq import SepAes
from seq_lib.sep_km_mailbox_seq import KM_DEST_AES, SepKmMailbox

# AES SW-key path key + plaintext for the entropy-pulling encrypt loop (values
# are arbitrary -- this test exercises the entropy datapath, not a key contract).
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
AES_PT = (0x00112233, 0x44556677, 0x8899AABB, 0xCCDDEEFF)

# Concurrent-window consumers: KM keygen DRBG pulls (KM AXIS sink) interleaved with
# AES reseed+encrypt blocks (crypto-EDN sink). Bounded so KM boot + these stay
# inside one CSRNG Generate (cfg.glen=32). Budget: each KM keygen ~6-7 genbits
# blocks, each AES reseed+block ~2, KM boot ~13. KM_CMDS=1 and AES_BLOCKS=2
# stay under glen (~24 blocks). Raising glen is not a substitute: a longer
# Generate can drift the seed boundary on a longer firmware run.
KM_CMDS = 1
AES_BLOCKS = 2


@pyuvm.test()
class sep_drbg_real_sink_multi_km_aes_test(sep_base_test):
    """KM + AES concurrent entropy sinks off one real DRBG; bit-exact per-sink routing."""

    def _km_beats(self) -> int:
        """Live count of KM AXIS beats (membership stash grows per beat)."""
        return self.drbg_sb.km_beats()

    def _aes_beats(self) -> int:
        """Live count of AES crypto-EDN beats (CHK5_aes golden compare, per beat)."""
        return self.drbg_sb.results["CHK5_aes"].dut_items

    async def run_scenario(self) -> None:
        # --- Boot the real KM firmware on real entropy -------------------------
        image = self.select_efuse_image(lc_raw=0x1)  # LC_PROD (KM reads OTP at boot)
        self.write_efuse_image(image)
        await self.bring_up_no_cpu(park=("otbn", "kmac", "hmac"))

        self.km = SepKmMailbox(self)
        self.aes = SepAes(self)

        # OTBN/KMAC/HMAC JTAG-held across rst_ni release, then parked in SW_RESET_N. AES stays released so its
        # masking-PRNG reseed is served as EDN starts, making AES a live
        # crypto-EDN consumer.

        # Strict entropy bring-up. CHK1..CHK4 bit-exact golden anchors the one DRBG.
        # KM = "membership" (each KM AXIS word is a genbits-golden word; rom_main pull
        # order is firmware-driven so not order-scored) and AES = "golden" (bit-exact
        # per-sink ROUTING: each AES post-adapter beat == the next AXIS1 pre-adapter
        # word -- the single-active-crypto-sink in-order case). Both are chained to the
        # CHK4 genbits golden in report() (the reference suite treats the AXIS1 tap as
        # its own golden; here AXIS1 is anchored to genbits).
        await self.bring_up_entropy(
            strict=True, score_km="membership", score_sinks={"aes": "golden"}
        )
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        self.start_fifo_drain()
        self.logger.info("real entropy flowing; releasing KM firmware (rom_main)")

        await self.swrst.release("km")
        await self.km.wait_km_ready()
        self.logger.info("KM firmware booted (RESP_KM_READY)")

        # --- Drive KM + AES as CONCURRENT entropy consumers off the SAME DRBG ---
        await self.aes.configure_ecb_enc_256(sideload=False)
        await self.aes.write_full_key(list(AES_KEY))
        golden = aes256_ecb_encrypt_words(list(AES_KEY), list(AES_PT))

        # Snapshot per-sink beats; the concurrent fork below must advance BOTH.
        km_before = self._km_beats()
        aes_before = self._aes_beats()

        async def km_arm():
            """KM AXIS DRBG pulls: each CMD_KEY_GENERATE makes the KM firmware read
            the DRBG sampler."""
            for i in range(KM_CMDS):
                h = await self.km.key_generate(dest=KM_DEST_AES, req_size=7)
                assert h != 0, f"KM CMD_KEY_GENERATE returned zero handle (iter {i})"

        async def aes_arm():
            """AES crypto-EDN pulls: reseed the masking PRNG (fresh EDN word) then run
            an ECB block; block-0 ciphertext is value-checked against the golden."""
            for i in range(AES_BLOCKS):
                await self.aes.trigger_prng_reseed()
                ct = await self.aes.run_ecb_block(list(AES_PT))
                if i == 0:
                    assert ct == golden, (
                        "AES block-0 ciphertext != AES-256-ECB golden:\n"
                        f"  ct    ={[hex(w) for w in ct]}\n"
                        f"  golden={[hex(w) for w in golden]}"
                    )
                else:
                    assert any(w != 0 for w in ct), f"AES all-zero ciphertext (block {i})"

        # TRUE FORK (cocotb analog of SV fork...join): both arms run as concurrent
        # cocotb tasks, so the KM keygen DRBG pulls and the AES crypto-EDN pulls overlap
        # and contend at the EDN arbiter in the same window (not interleaved by one
        # coroutine). Bounded to one CSRNG Generate so the CHK4 golden stays bit-exact.
        km_task = cocotb.start_soon(km_arm())
        aes_task = cocotb.start_soon(aes_arm())
        await km_task  # join (aes runs concurrently meanwhile)
        await aes_task  # join + re-raise any AES-arm assertion
        self.logger.info("CHK-AESKAT PASS: block-0 ciphertext == AES-256-ECB golden")

        # Both sinks consumed entropy DURING the concurrent fork (not just one) --
        # evidences overlap (the OSS analog of the reference suite's fork count_good/ack-advance
        # check); like the reference suite it shows both advanced in-window, not strict same-cycle
        # arbiter contention.
        km_after = self._km_beats()
        aes_after = self._aes_beats()
        assert km_after > km_before, (
            f"KM AXIS did not consume entropy during the concurrent fork "
            f"(beats {km_before}->{km_after})"
        )
        assert aes_after > aes_before, (
            f"AES crypto-EDN did not consume entropy during the concurrent fork "
            f"(beats {aes_before}->{aes_after})"
        )
        self.logger.info(
            "CHK-CONCUR PASS: KM+AES both advanced during the concurrent fork: KM %d->%d, AES %d->%d",
            km_before,
            km_after,
            aes_before,
            aes_after,
        )

        # --- EOT: both sinks scored, entropy health ----------------------------
        await self.aes.check_status_clean("EOT")
        await self.km.check_outbound_empty("EOT")
        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        # Strict report runs the genbits-chain membership tally + per-sink checks and
        # raises on: CHK1..CHK4 mismatch, CHK5_aes routing mismatch / AXIS1 underrun,
        # any AXIS1 or KM word not in the genbits golden, or a starved sink.
        assert self.drbg_sb.report()
        self.logger.info(
            "CHK1..CHK4 bit-exact + CHK5_aes per-sink ROUTING (AES==AXIS1) + CHK5_km/"
            "CHK5_axis1 genbits-membership + entropy alerts zero (bit-exact, > reference suite)"
        )
