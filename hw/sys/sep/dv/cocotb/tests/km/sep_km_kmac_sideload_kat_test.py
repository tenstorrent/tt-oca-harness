# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""KMAC computes with exactly the key the KM sideloads, matching the SW-key digest and the golden.

Real DRBG entropy boots the real KM firmware (rom_main). The host (CPU-LSU
frontdoor AXI) provisions a KNOWN 256-bit key into a KPV handle via CMD_KEY_LOAD,
then CMD_KEY_TRANSFERs it to the OpenTitan KMAC engine. KMAC computes a keyed
KMAC-256 (cSHAKE, PREFIX="KMAC") over a fixed message; the test proves KMAC
consumed exactly the sideloaded key.

KMAC has a CFG.sideload bit, so (like AES, unlike HMAC) the consume-proof is a
sideload-vs-SW cross-check with a KNOWN distinct-word key, plus a dummy-key
negative reference that proves the key drives the output. The SW-key digest is
also compared against the bit-exact KMAC golden (env/sep_kmac_golden.py).

Checkers:
  CHK0      boot KM on real DRBG -> RESP_KM_READY
  CHK-A     CMD_KEY_LOAD known key (frontdoor; wrapper shares are write-only)
  CHK-NEG   negative ref: keyed MAC with a DUMMY SW key -> c_dummy (a real op)
  CHK-ISO   key-bus isolation by SW_RESET_N read-back: only KMAC of the four
            non-ABR sideload engines released; AES/HMAC/OTBN parked
  CHK-B     CMD_KEY_TRANSFER rc=0 to KMAC
  PUB-OBSERVATION  public KMAC KEY_SHARE0/1 read back zero after sideload. NOT a
            checker: kmac.hjson declares them swaccess=wo, so the read cannot fail
  CHK-SIDE  sideload digest != dummy digest (the sideloaded key drives the output)
  CHK-MAC   sideload digest == SW-key(KNOWN key) digest (consume-proof: KMAC used
            exactly the KM-delivered known key)
  CHK-MAC-GOLDEN  SW-key(KNOWN key) digest == KMAC256(K, X, 256, S="") from
            env/sep_kmac_golden.py (NIST SP 800-185), so the keyed PREFIX and
            the right_encode(L) tail the sequence drives are the spec encoding
  CHK-ENT   KMAC consumed real DRBG/EDN masking entropy during the keyed ops --
            proven by the CHK5_kmac sink (>=1 post-adapter crypto-EDN beat to KMAC),
            measured frontdoor rather than by counting EDN acks internally
  CHK-ERR   KMAC ERR_CODE == 0
  CHK1..CHK4 strict DRBG golden + CHK5_km observed (KM boot/load consumer)

Scope:
  * The consume-proof is the sideload-vs-SW cross-check. The SW-key digest is
    also compared against the bit-exact KMAC golden (CHK-MAC-GOLDEN). The key is
    KNOWN and distinct-word, so no backdoor and no key/mask non-degeneracy guard
    is needed. The wrapper-internal SHARE0 mask
    non-degeneracy is out of frontdoor scope; km/sep_km_otbn_sideload_kat_test
    covers it, as for the AES and HMAC sideload KATs.
  * Key-bus isolation is graded by SW_RESET_N read-back; CHK-MAC also proves KMAC
    got the correct key.

Boot recipe matches the OTBN, AES and HMAC sideload KATs (real fuse-sense, valid
PROD OTP image).
KMAC IS an EDN consumer (masking entropy), so it is parked through KM boot/load for
clean isolation + entropy dedication, then released before the transfer,
after which its keyed ops pull real EDN masking entropy (scored via CHK5_kmac).
"""

from __future__ import annotations

import pyuvm
from env.sep_kmac_golden import kmac_family_words
from sep_base_test import sep_base_test
from seq_lib.sep_km_mailbox_seq import KM_DEST_KMAC, SepKmMailbox
from seq_lib.sep_kmac_seq import SepKmac
from seq_lib.sep_sw_reset_seq import SW_RESET_N_BIT

# Known 256-bit KAT key: 8 DISTINCT 32-bit words (non-degenerate by construction).
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

# Fixed message: bytes 0x00..0x1f as 8 words.
KMAC_MSG = (
    0x00010203,
    0x04050607,
    0x08090A0B,
    0x0C0D0E0F,
    0x10111213,
    0x14151617,
    0x18191A1B,
    0x1C1D1E1F,
)

# Unrelated dummy key for the negative reference.
KMAC_DUMMY_KEY = (
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
class sep_km_kmac_sideload_kat_test(sep_base_test):
    """The sideload digest equals the SW-key digest of the known key and differs from the dummy."""

    async def run_scenario(self) -> None:
        # --- Boot the real KM firmware on real entropy -------------------------
        image = self.select_efuse_image(lc_raw=0x1)  # LC_PROD (KM reads OTP at boot)
        self.write_efuse_image(image)
        await self.bring_up_no_cpu(park=("otbn", "aes", "hmac", "kmac"))

        self.km = SepKmMailbox(self)
        self.kmac = SepKmac(self)

        # The four non-ABR sideload engines (OTBN, AES, HMAC, KMAC) are JTAG-held
        # across rst_ni release, then parked in SW_RESET_N. KMAC is released only
        # before the transfer so its keyed ops pull EDN masking entropy.

        # Strict bring-up: CHK1..CHK4 golden; CHK5_km observed. CHK5_kmac (CHK-ENT)
        # proves KMAC pulls real crypto-EDN masking beats during its keyed ops. The
        # drain keeps the ESRC FIFO from overflowing during the long entropy phase.
        await self.bring_up_entropy(
            strict=True, score_km="observe", score_sinks={"kmac": "observe"}
        )
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        self.start_fifo_drain()
        self.logger.info("real entropy flowing; releasing KM firmware (rom_main)")

        await self.swrst.release("km")
        await self.km.wait_km_ready()
        self.logger.info("CHK0 KM firmware boot PASS: RESP_KM_READY over the mailbox")

        # --- Frontdoor consume-proof: load known key -> transfer -> keyed MAC ---
        # CHK-A: provision the KNOWN key into a KPV handle over the frontdoor.
        handle = await self.km.key_load(key_words=list(KAT_KEY), dest=KM_DEST_KMAC)
        self.logger.info("CHK-A CMD_KEY_LOAD PASS: known key staged, handle=0x%02x", handle)

        # Release KMAC before the transfer: the KM writes the KMAC wrapper key CSRs
        # (kmac sw-reset domain). Released here so it can also run the negative-ref MAC.
        await self.swrst.release("kmac")

        # CHK-NEG: negative reference -- keyed MAC with an unrelated DUMMY SW key.
        c_dummy = await self.kmac.keyed_mac(
            list(KMAC_MSG), sideload=False, sw_key=list(KMAC_DUMMY_KEY)
        )
        # CHK-SIDE compares against c_dummy; require it nonzero so an all-zero
        # failed operation cannot satisfy the inequality.
        assert any(w != 0 for w in c_dummy), (
            "dummy-key KMAC returned an all-zero digest -- the negative reference is "
            f"not a real observation, so CHK-SIDE below would be vacuous: {[hex(w) for w in c_dummy]}"
        )
        self.logger.info(
            "CHK-NEG dummy-key KMAC PASS: non-zero digest observed (alive, not "
            "value-compared): c_dummy=%s",
            [hex(w) for w in c_dummy],
        )

        # CHK-ISO: only KMAC (of the four non-ABR sideload engines) is released; others parked.
        rst = await self.swrst.read_back()
        parked = (
            (1 << SW_RESET_N_BIT["aes"])
            | (1 << SW_RESET_N_BIT["hmac"])
            | (1 << SW_RESET_N_BIT["otbn"])
        )
        assert (rst & parked) == 0, (
            f"key-bus isolation: AES/HMAC/OTBN not parked (SW_RESET_N=0x{rst:08x})"
        )
        assert rst & (1 << SW_RESET_N_BIT["kmac"]), (
            f"KMAC not released for the transfer (SW_RESET_N=0x{rst:08x})"
        )
        self.logger.info(
            "CHK-ISO key-bus isolation PASS: only KM+KMAC released, "
            "AES/HMAC/OTBN parked (SW_RESET_N=0x%02x)",
            rst,
        )

        # CHK-B: sideload the handle's key to the KMAC wrapper KEY CSRs.
        rc, _ = await self.km.key_transfer(handle=handle, dest=KM_DEST_KMAC)
        assert rc == 0, f"CMD_KEY_TRANSFER returned rc={rc} (expected 0)"
        self.logger.info("CHK-B CMD_KEY_TRANSFER PASS: rc=0 (key sideloaded to KMAC)")

        # PUB-OBSERVATION: the public KEY_SHARE CSRs read zero. Asserted, but
        # kmac.hjson declares them swaccess=wo, so "reads zero" holds on any RTL
        # that follows it.
        s0_pub, s1_pub, ctl_pub = await self.kmac.read_public_key_shares()
        assert all(w == 0 for w in s0_pub + s1_pub), (
            "KMAC public KEY_SHARE0/1 not all zero after sideload (key leak): "
            f"s0={[hex(w) for w in s0_pub if w]} s1={[hex(w) for w in s1_pub if w]}"
        )
        assert ctl_pub != 0, (
            "PUB-OBSERVATION positive control failed: KMAC STATUS read back 0 over the same "
            "frontdoor, so the all-zero KEY_SHARE reads prove nothing about the key"
        )
        self.logger.info(
            "PUB-OBSERVATION KMAC public KEY_SHARE0/1 frontdoor reads zero after "
            "sideload. Asserted, but kmac.hjson declares them swaccess=wo, so this read "
            "alone cannot fail. Read path alive: STATUS=%#010x",
            ctl_pub,
        )

        # CHK-SIDE/CHK-MAC: sideload MAC, then SW-key MAC with the KNOWN key.
        a_side = await self.kmac.keyed_mac(list(KMAC_MSG), sideload=True)
        assert a_side != c_dummy, (
            "KMAC sideload digest equals the dummy-key digest (key not consumed)"
        )
        self.logger.info("CHK-SIDE PASS: sideload digest != dummy-key digest")

        b_swref = await self.kmac.keyed_mac(list(KMAC_MSG), sideload=False, sw_key=list(KAT_KEY))
        assert a_side == b_swref, (
            "KMAC sideload vs SW-key(known) digest mismatch -- KMAC did not consume "
            "the exact KM-delivered key:\n"
            f"  a_side ={[hex(w) for w in a_side]}\n"
            f"  b_swref={[hex(w) for w in b_swref]}"
        )
        # Both digests come from this engine, so this is a cross-check against
        # the known key, not a comparison with a known answer.
        self.logger.info(
            "CHK-MAC KM->KMAC sideload PASS: sideload digest == SW-key(known) digest "
            "(engine cross-check, not a golden)"
        )
        # CHK-MAC-GOLDEN: the SW-key digest against the SP 800-185 KMAC256 golden.
        # A wrong PREFIX or message tail in the stimulus changes the digest, so it
        # fails here and not only in a comparison of the engine with itself.
        golden = kmac_family_words(
            "kmac", 256, list(KMAC_MSG), len(b_swref) * 4, key_words=list(KAT_KEY)
        )
        assert b_swref == golden, (
            "KMAC SW-key(known) digest != KMAC256 golden:\n"
            f"  b_swref={[hex(w) for w in b_swref]}\n"
            f"  golden ={[hex(w) for w in golden]}"
        )
        self.logger.info(
            'CHK-MAC-GOLDEN PASS: SW-key(known) digest == KMAC256(K, X, L=256, S="") '
            "golden (env/sep_kmac_golden.py)"
        )

        # CHK-ERR: KMAC raised no error across the keyed ops.
        await self.kmac.check_status_clean("EOT")

        # --- EOT: entropy health + clean shutdown ------------------------------
        # CHK-ENT (KMAC masking entropy) + CHK1..CHK5 are finalized by the strict
        # scoreboard report: CHK5_kmac requires >=1 real crypto-EDN beat to KMAC.
        await self.km.check_outbound_empty("EOT")
        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        assert self.drbg_sb.report()
        self.logger.info("CHK-ENT + CHK1..CHK5 alive + entropy alerts PASS (DRBG scoreboard)")
