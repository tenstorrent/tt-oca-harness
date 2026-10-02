# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""KM -> AES sideload consume-proof KAT.

Real DRBG entropy boots the real KM firmware (rom_main). The host (CPU-LSU
frontdoor AXI) provisions a KNOWN 256-bit key into a KPV handle via CMD_KEY_LOAD,
then CMD_KEY_TRANSFER sideloads it to the OpenTitan AES core. The host then runs
ECB-256 encryptions and proves the AES engine CONSUMED exactly that key:

  ct_side  = AES-ECB(sideload key, PT)   (CTRL_SHADOWED.SIDELOAD=1)
  ct_swref = AES-ECB(known key via SW KEY_SHARE, PT)
  ct_dummy = AES-ECB(unrelated dummy SW key, PT)   (negative reference)

AES KEY CSRs are write-only and AES is not programmable, so (unlike the OTBN KAT)
the delivered key cannot be dumped back; the consume-proof is the encryption
cross-check. ct_side / ct_swref are value-checked against an independent
AES-256-ECB golden (env/sep_aes_golden.py, self-tested against FIPS-197 C.3) of
the known key, so a truncated, word-swapped or share-defeated sideload fails.

Checkers:
  CHK0     boot KM on real DRBG -> RESP_KM_READY
  CHK-A    CMD_KEY_LOAD known key
  CHK-NEG  ct_dummy == AES(dummy, PT): negative reference is a real encryption
  CHK-B    CMD_KEY_TRANSFER rc=0 to AES
  CHK-ISO  key-bus isolation: only AES released; OTBN/KMAC/HMAC parked in SW reset
           so they cannot receive the key (same mechanism as the OTBN KAT)
  PUB-OBS  AES public KEY_SHARE0/1 read zero after sideload while STATUS reads
           non-zero on the same path; swaccess=wo makes the zero read alone
           unfalsifiable
  CHK-F    ct_side == AES(known_key, PT) golden: sideload delivered the exact key
  CHK-RT   DEC(ct_side) with the SIDELOAD key == original PT: the sideloaded key
           drives a full ECB-256 ENC/DEC round-trip, not just encryption
  CHK-H    ct_swref == AES(known_key, PT) golden: SW-key path is correct
  CHK1..CHK4 strict golden proof via the DRBG scoreboard; CHK5_km alive/observed
           (rom_main pull order not golden-predictable) + CHK5_aes alive/observed:
           the released AES masking PRNG reseeds from the crypto EDN leg, so a
           second real EDN consumer (besides KM) is witnessed off one DRBG.

Limitations:
  * SHARE0 mask non-degeneracy inside the AES wrapper is not observable
    frontdoor: the combined key can be correct (CHK-F) while the 2-share masking
    is degenerate.
  * Key-bus isolation is proven by SW_RESET_N read-back, not by monitoring the
    key bus; CHK-F additionally proves AES got the correct key.

Boot recipe matches the OTBN KAT (real fuse-sense, valid PROD OTP image; KM SRAM
responder powers up zero+valid-parity; rom_main built PROD_BOOT_WIPE=0).

AES stays released through entropy bring-up so its masking-PRNG reseed is served
as EDN starts; OTBN/KMAC/HMAC are parked so the KM owns the boot/seed stream and
they cannot take the key.
"""

from __future__ import annotations

import pyuvm
from env.sep_aes_golden import aes256_ecb_encrypt_words
from sep_base_test import sep_base_test
from seq_lib.sep_aes_seq import SepAes
from seq_lib.sep_km_mailbox_seq import KM_DEST_AES, SepKmMailbox
from seq_lib.sep_sw_reset_seq import SW_RESET_N_BIT

# Known 256-bit KAT key: 8 DISTINCT 32-bit words so the golden compare and the
# negative reference catch a truncated / word-swapped / share-defeated sideload.
KAT_KEY = (
    0xDEADBEEF,
    0x00112233,
    0x44556677,
    0x8899AABB,
    0xCCDDEEFF,
    0x01234567,
    0x89ABCDEF,
    0xFEDCBA98,
)

# Fixed ECB plaintext block (ECB keeps the focus on the key-source path, no IV).
AES_ECB_PT = (0x00112233, 0x44556677, 0x8899AABB, 0xCCDDEEFF)

# Dummy SW key for the negative reference (unrelated to KAT_KEY).
AES_DUMMY_SW_KEY = (
    0xDEADBEEF,
    0xCAFEF00D,
    0x12345678,
    0x9ABCDEF0,
    0x0F0E0D0C,
    0x0B0A0908,
    0x07060504,
    0x03020100,
)


@pyuvm.test()
class sep_km_aes_sideload_kat_test(sep_base_test):
    """KM->AES sideload consume-proof (frontdoor, real rom_main, known key)."""

    async def run_scenario(self) -> None:
        # --- Boot the real KM firmware on real entropy -------------------------
        # Real fuse-sense with a valid PROD-lifecycle image (the KM firmware reads
        # OTP at boot); stage it before bring-up so sense populates the shadow.
        image = self.select_efuse_image(lc_raw=0x1)  # LC_PROD
        self.write_efuse_image(image)
        await self.bring_up_no_cpu(park=("otbn", "kmac", "hmac"))

        self.km = SepKmMailbox(self)
        self.aes = SepAes(self)

        # OTBN/KMAC/HMAC parked in SW_RESET_N so they never sit ungranted
        # through fuse sense and cannot take the key. AES stays released so its
        # masking-PRNG reseed is served when EDN starts.

        # Strict entropy bring-up: CHK1..CHK4 bit-exact golden; CHK5_km observed
        # (rom_main pull order is firmware-driven); CHK5_aes observed proves the
        # crypto EDN leg delivers real beats to the released AES masking PRNG, not
        # only the KM leg. Fork the concurrent FIFO_RDATA drain so CHK2 is scored
        # without an ESRC FIFO overflow.
        await self.bring_up_entropy(strict=True, score_km="observe", score_sinks={"aes": "observe"})
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        self.start_fifo_drain()
        self.logger.info("real entropy flowing; releasing KM firmware (rom_main)")

        await self.swrst.release("km")
        await self.km.wait_km_ready()
        self.logger.info("CHK0 KM firmware boot PASS: RESP_KM_READY over the mailbox")

        # --- Frontdoor consume-proof: load known key -> transfer -> encrypt ----
        # CHK-A: provision the KNOWN key into a KPV handle over the frontdoor.
        handle = await self.km.key_load(key_words=list(KAT_KEY), dest=KM_DEST_AES)
        self.logger.info("CHK-A CMD_KEY_LOAD PASS: known key staged, handle=0x%02x", handle)

        # CHK-NEG: negative reference. Encrypt with an unrelated DUMMY SW key BEFORE
        # the transfer. A real encryption, golden-checked, so ct_side !=
        # ct_dummy later is a meaningful "a distinct key was delivered" proof.
        await self.aes.configure_ecb_enc_256(sideload=False)
        await self.aes.write_full_key(list(AES_DUMMY_SW_KEY))
        await self.aes.trigger_prng_reseed()
        ct_dummy = await self.aes.run_ecb_block(list(AES_ECB_PT))
        exp_dummy = aes256_ecb_encrypt_words(list(AES_DUMMY_SW_KEY), list(AES_ECB_PT))
        assert ct_dummy == exp_dummy, (
            "negative-ref AES(dummy) mismatch vs golden:\n"
            f"  got={[hex(w) for w in ct_dummy]} exp={[hex(w) for w in exp_dummy]}"
        )
        self.logger.info("CHK-NEG dummy-key ECB PASS: ct_dummy == AES(dummy, PT) golden")

        # CHK-B: sideload the handle's key to the AES wrapper KEY CSRs.
        rc, _ = await self.km.key_transfer(handle=handle, dest=KM_DEST_AES)
        assert rc == 0, f"CMD_KEY_TRANSFER returned rc={rc} (expected 0)"
        self.logger.info("CHK-B CMD_KEY_TRANSFER PASS: rc=0 (key sideloaded to AES)")

        # CHK-ISO: key-bus isolation, positive evidence. Only AES (of the five KM
        # sideload targets) is released; OTBN/KMAC/HMAC are held in SW reset
        # and cannot receive the key. OSS analog of the reference suite's per-engine key-bus AW count.
        rst = await self.swrst.read_back()
        parked = (
            (1 << SW_RESET_N_BIT["otbn"])
            | (1 << SW_RESET_N_BIT["kmac"])
            | (1 << SW_RESET_N_BIT["hmac"])
        )
        assert (rst & parked) == 0, (
            f"key-bus isolation: OTBN/KMAC/HMAC not parked (SW_RESET_N=0x{rst:08x})"
        )
        assert rst & (1 << SW_RESET_N_BIT["aes"]), (
            f"AES not released for the transfer (SW_RESET_N=0x{rst:08x})"
        )
        self.logger.info(
            "CHK-ISO key-bus isolation PASS: only KM+AES released, "
            "OTBN/KMAC/HMAC parked (SW_RESET_N=0x%02x)",
            rst,
        )

        # PUB-OBSERVATION: the public KEY_SHARE CSRs read zero, and the read path
        # that produced those zeros is alive. Logged, not scored. The control is
        # the only falsifiable half:
        # KEY_SHARE0/1 are write-only with read data tied to zero in the generated
        # register block, so on its own "reads zero" is unfalsifiable -- it holds
        # whether the key is protected, mirrored elsewhere, or never delivered.
        # Pairing it with a readable register in the same window at least makes
        # the check fail if the read path dies or if these become readable.
        s0_pub, s1_pub, ctl_pub = await self.aes.read_public_key_shares()
        assert ctl_pub != 0, (
            "PUB-OBSERVATION positive control failed: AES STATUS read back 0 over the same "
            "frontdoor, so the all-zero KEY_SHARE reads prove nothing about the key"
        )
        assert all(w == 0 for w in s0_pub) and all(w == 0 for w in s1_pub), (
            "AES public KEY_SHARE0/1 CSRs not all zero after sideload (key leak):\n"
            f"  s0={[hex(w) for w in s0_pub if w]}\n"
            f"  s1={[hex(w) for w in s1_pub if w]}"
        )
        self.logger.info(
            "PUB-OBSERVATION AES public KEY_SHARE0/1 frontdoor reads zero after "
            "sideload. Not scored: aes.hjson declares them swaccess=wo, so this read "
            "cannot fail. Read path alive: STATUS=%#010x",
            ctl_pub,
        )

        # CHK-F: encrypt with the SIDELOAD key and value-check against the golden.
        # This proves AES consumed the exact KM-delivered key.
        golden = aes256_ecb_encrypt_words(list(KAT_KEY), list(AES_ECB_PT))
        await self.aes.configure_ecb_enc_256(sideload=True)
        await self.aes.trigger_prng_reseed()
        ct_side = await self.aes.run_ecb_block(list(AES_ECB_PT))
        assert ct_side == golden, (
            "sideload ciphertext != AES(known_key, PT) golden -- AES did not consume "
            "the exact KM-delivered key:\n"
            f"  ct_side={[hex(w) for w in ct_side]}\n"
            f"  golden ={[hex(w) for w in golden]}"
        )
        self.logger.info("CHK-F KM->AES sideload KAT PASS: ct_side == AES(known_key, PT) golden")

        # CHK-RT: decrypt ct_side with the SIDELOAD key and prove it
        # recovers the original plaintext -- the sideloaded key drives a full
        # ENC/DEC round-trip, not just one direction. The recovered PT is checked
        # against the known AES_ECB_PT (value-specific; no decrypt golden needed
        # since the round-trip target is the known input).
        await self.aes.configure_ecb_dec_256(sideload=True)
        await self.aes.trigger_prng_reseed()
        pt_side_dec = await self.aes.run_ecb_block(list(ct_side))
        assert pt_side_dec == list(AES_ECB_PT), (
            "sideload decrypt did not recover the original plaintext:\n"
            f"  pt_side_dec={[hex(w) for w in pt_side_dec]}\n"
            f"  expected PT={[hex(w) for w in AES_ECB_PT]}"
        )
        self.logger.info("CHK-RT sideload round-trip PASS: DEC(ct_side) == original PT")

        # CHK-H: write the KNOWN key through the SW KEY_SHARE path and prove
        # the SW-key ciphertext equals AES(known_key, PT) golden.
        await self.aes.configure_ecb_enc_256(sideload=False)
        await self.aes.write_full_key(list(KAT_KEY))
        await self.aes.trigger_prng_reseed()
        ct_swref = await self.aes.run_ecb_block(list(AES_ECB_PT))
        assert ct_swref == golden, (
            "SW-key ciphertext != AES(known_key, PT) golden:\n"
            f"  ct_swref={[hex(w) for w in ct_swref]} golden={[hex(w) for w in golden]}"
        )
        self.logger.info("CHK-H consume-proof PASS: ct_swref == AES(known_key, PT) golden")

        # --- EOT: entropy health + clean shutdown ------------------------------
        await self.km.check_outbound_empty("EOT")
        await self.aes.wait_idle("EOT")
        # AES raised no recoverable (shadowed-CTRL mismatch) or fatal alert across
        # the three encryptions, alongside the CSRNG/EDN alert check below.
        await self.aes.check_status_clean("EOT")
        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        assert self.drbg_sb.report()
        self.logger.info("CHK1..CHK5 alive + entropy alerts PASS (DRBG scoreboard)")
