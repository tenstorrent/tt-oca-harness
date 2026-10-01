# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""OCA boot-manifest happy paths on sep-vp: unsigned, signed, and encrypted.

These are the counterpart to test_bootcode_oca_negative.py. Each asserts a full
boot to BL1 plus the checks that had to have run to get there, because reaching
SEP_MSG_STARTING_BL1 alone does not distinguish "verified and booted" from
"skipped verification and booted".
"""

import pytest
import shared
from sepvp.config import SimConfig

pytestmark = pytest.mark.bootcode

TIMEOUT = 180


def _cfg(name, elf, image, **kw):
    return SimConfig(
        name=name, elf=str(elf), flash_image=str(image), boot="primary", boot_timeout=TIMEOUT, **kw
    )


def test_unsigned_boots_to_bl1(vp, bootcode_elf, oca_images):
    """An unsigned OCA manifest boots: framing, manifest hash, TOC and payload hashes.

    Nothing is verified cryptographically here beyond the hashes -- the manifest
    does not assert secure boot and the device does not enforce it -- so this is
    the case that proves the non-secure path is still a path.
    """
    t = vp(_cfg("oca_unsigned", bootcode_elf, oca_images["unsigned"]))
    t.spawn()
    shared.expect_common_early(t, timeout=TIMEOUT)
    t.expect_status("SEP_MSG_MANIFEST_VALIDATED", type="INFO", timeout=TIMEOUT)
    t.expect_status("SEP_MSG_PAYLOAD_VALIDATED", type="INFO", timeout=TIMEOUT)
    t.expect_status("SEP_MSG_STARTING_BL1", type="INFO", timeout=TIMEOUT)
    t.close()


def test_signed_boots_to_bl1(vp, bootcode_elf, oca_images):
    """A signed manifest boots, and the authorization and RSA steps both ran.

    The two virt-console markers are the load-bearing part. PUBK_AUTHORIZED says
    the key was matched against the ROM digest table rather than merely carried by
    the manifest, and RSA_VERIFY_OK says the signature was actually checked. A
    boot that reached BL1 without both would be a boot that verified nothing --
    which is precisely what happened for months while otbn.algorithm_type
    defaulted to the loop model.

    Expected in that ORDER, and the order is the assertion: expect() consumes the
    stream, so this passes only if authorization precedes verification. Swap the
    two checks in oca_validate_manifest() and this test fails rather than quietly
    verifying against a key nothing had vouched for.
    """
    t = vp(_cfg("oca_signed", bootcode_elf, oca_images["signed"]))
    t.spawn()
    shared.expect_common_early(t, timeout=TIMEOUT)
    t.expect("PUBK_AUTHORIZED", timeout=TIMEOUT)
    t.expect("RSA_VERIFY_OK", timeout=TIMEOUT)
    t.expect_status("SEP_MSG_MANIFEST_VALIDATED", type="INFO", timeout=TIMEOUT)
    t.expect_status("SEP_MSG_STARTING_BL1", type="INFO", timeout=TIMEOUT)
    t.close()


def test_encrypted_payload_boots_to_bl1(vp, bootcode_elf, oca_images):
    """An AES-256-CBC encrypted payload is decrypted and booted.

    Exercises the whole crypto stack in one run: the OCA KDF over the CLASS_KEY
    fuse bank, AES-256-CBC, and PKCS#7 stripping. SEP_MSG_PAYLOAD_VALIDATED after
    the decrypt is the real assertion -- the library verifies payload_hash over
    the ciphertext before decrypting and the hash chain plus every TOC entry hash
    over the plaintext afterwards, so a wrong derived key cannot reach it.

    Needs the fuse map: the secret comes from CLASS_KEY, and an unprovisioned
    bank is refused as NO_PROVISIONED_SECRET rather than deriving from zeros.
    """
    t = vp(
        _cfg(
            "oca_encrypted",
            bootcode_elf,
            oca_images["encrypted"],
            otp="tests/fuse_maps/oca_encrypted.yaml",
        )
    )
    t.spawn()
    shared.expect_common_early(t, timeout=TIMEOUT)
    t.expect_status("SEP_MSG_DECRYPTION_START", type="INFO", timeout=TIMEOUT)
    t.expect_status("SEP_MSG_DECRYPTION_END", type="INFO", timeout=TIMEOUT)
    t.expect_status("SEP_MSG_PAYLOAD_VALIDATED", type="INFO", timeout=TIMEOUT)
    t.expect_status("SEP_MSG_STARTING_BL1", type="INFO", timeout=TIMEOUT)
    t.close()


def test_encrypted_without_class_key_is_refused(vp, bootcode_elf, oca_images):
    """The same image on a part with no CLASS_KEY provisioned must not boot.

    An all-zero bank is a distinct failure from a decrypt error: the image may be
    perfectly good and simply built for another device. Deriving from zeros would
    "succeed" and then fail the plaintext hash chain, blaming the image for a
    provisioning gap, so the ROM refuses up front.
    """
    t = vp(_cfg("oca_enc_no_key", bootcode_elf, oca_images["encrypted"]))
    t.spawn()
    match = t.expect_status("SEP_MSG_INVALID_KEY_CONTENTS", type="ERROR", timeout=TIMEOUT)
    assert "ERROR" in match.group(0)
    t.close()


def test_rotate_update_strap_selects_backup_first(vp, bootcode_elf, oca_images):
    """rotate_update swaps the slot order, and the backup slot boots.

    Both slots carry the same bundle, so this cannot assert WHICH one booted from
    the status stream alone -- MANIFEST_BACKUP on the virt console is what
    distinguishes them.
    """
    t = vp(_cfg("oca_rotate", bootcode_elf, oca_images["signed"], rotate_update=True))
    t.spawn()
    t.expect("MANIFEST_BACKUP", timeout=TIMEOUT)
    t.expect_status("SEP_MSG_STARTING_BL1", type="INFO", timeout=TIMEOUT)
    t.close()


# --- OTP-anchored key authorization ----------------------------------------
#
# The images above are signed with a key whose digest is embedded in ROM
# (key_digests.c). These four use an image selecting an OTP anchor instead --
# public_key_select_classic bit 16, which is CHIPLET_PUBK_HASH0 -- so the ROM
# reads its trust anchor from a fuse bank. Same signing key throughout; only
# where the anchor lives changes, which keeps the anchor lookup as the single
# variable.


def test_otp_anchored_key_boots(vp, bootcode_elf, oca_images):
    """A key anchored in OTP rather than ROM authorizes and boots.

    Proves the OTP branch of plat_is_key_authorized() resolves the right bank and
    that the digest is taken over the 384-byte modulus, not the 388-byte RAW blob
    -- a blob-wide digest would simply never match.
    """
    t = vp(
        _cfg(
            "oca_otp_key",
            bootcode_elf,
            oca_images["otp_key"],
            otp="tests/fuse_maps/oca_otp_key.yaml",
        )
    )
    t.spawn()
    t.expect("PUBK_AUTHORIZED", timeout=TIMEOUT)
    t.expect("RSA_VERIFY_OK", timeout=TIMEOUT)
    t.expect_status("SEP_MSG_STARTING_BL1", type="INFO", timeout=TIMEOUT)
    t.close()


def test_otp_anchored_key_wrong_digest_refused(vp, bootcode_elf, oca_images):
    """A provisioned-but-different OTP digest refuses the key.

    The map is byte-identical to the passing one except for one flipped bit in
    word 0, so this isolates the comparison itself rather than the plumbing.
    """
    t = vp(
        _cfg(
            "oca_otp_key_wrong",
            bootcode_elf,
            oca_images["otp_key"],
            otp="tests/fuse_maps/oca_otp_key_wrong.yaml",
        )
    )
    t.spawn()
    match = t.expect_status("SEP_MSG_INVALID_KEY_HASH", type="ERROR", timeout=TIMEOUT)
    assert "ERROR" in match.group(0)
    t.close()


def test_otp_anchored_key_unprovisioned_refused(vp, bootcode_elf, oca_images):
    """An erased OTP bank authorizes nothing.

    No fuse map, so CHIPLET_PUBK_HASH0 reads all zeroes. That must be refused
    rather than treated as "no anchor configured, allow anything" -- an unburned
    part is the state every part starts in, and it is the one an attacker would
    most like to be permissive.
    """
    t = vp(_cfg("oca_otp_key_empty", bootcode_elf, oca_images["otp_key"]))
    t.spawn()
    match = t.expect_status("SEP_MSG_INVALID_KEY_HASH", type="ERROR", timeout=TIMEOUT)
    assert "ERROR" in match.group(0)
    t.close()


def test_otp_anchored_key_revocation_uses_the_same_slot_numbering(vp, bootcode_elf, oca_images):
    """Provisioned AND revoked: the same bit index must mean the same key.

    public_key_select_classic and CHIPLET_PUBK_REVOKE index the same key entries,
    so bit 16 in the manifest and bit 16 in the fuse have to name one key. The
    fuse map provisions the anchor (so authorization passes) and revokes slot 16,
    which must then refuse.

    This is the case that catches a numbering disagreement: if select and revoke
    were offset from each other, authorization would pass, revocation would test
    an unrelated bit, and the image would boot on a device that had revoked its
    key. Reported as REVOKED_KEY rather than INVALID_KEY_HASH, which also
    confirms authorization ran first and passed.
    """
    t = vp(
        _cfg(
            "oca_otp_key_revoked",
            bootcode_elf,
            oca_images["otp_key"],
            otp="tests/fuse_maps/oca_otp_key_revoked.yaml",
        )
    )
    t.spawn()
    t.expect("PUBK_AUTHORIZED", timeout=TIMEOUT)
    match = t.expect_status("SEP_MSG_REVOKED_KEY", type="ERROR", timeout=TIMEOUT)
    assert "ERROR" in match.group(0)
    t.close()


# --- SMC-SRAM load path ----------------------------------------------------
#
# The second in-scope load path. On silicon the SMC fetches the bundle (over I3C)
# and stages it in its SRAM; the VP models no SMC, so smc_sram_image presents the
# same contract. A BARE BUNDLE, not a combined SPI image: this path resolves the
# payload from the manifest's own payload_offset, which for a bundle is body_size.


def test_smc_sram_secondary_chiplet_boots(vp, bootcode_elf, oca_images):
    """Secondary chiplet: wait for the SMC handshake, then boot its manifest.

    primary_chiplet=false means boot_from_spi() is false, so the ROM polls
    STATUS_TO_SEP for MANIFEST_READY and reads the offset the SMC published
    rather than touching SPI flash at all.
    """
    t = vp(
        SimConfig(
            name="oca_smc_secondary",
            elf=str(bootcode_elf),
            smc_sram_image=str(oca_images["smc_bundle"]),
            boot="secondary",
            boot_timeout=TIMEOUT,
        )
    )
    t.spawn()
    t.expect("WAIT_SMC_MANIFEST", timeout=TIMEOUT)
    t.expect("PUBK_AUTHORIZED", timeout=TIMEOUT)
    t.expect_status("SEP_MSG_STARTING_BL1", type="INFO", timeout=TIMEOUT)
    t.close()


def test_smc_sram_recovery_strap_boots(vp, bootcode_elf, oca_images):
    """Recovery: a PRIMARY chiplet told to take its manifest from the SMC anyway.

    Distinct from the secondary case -- the part is primary, so it could have
    booted from SPI, and the recovery strap is what redirects it. Proves the strap
    reaches the load-path decision rather than only being reported.
    """
    t = vp(
        SimConfig(
            name="oca_smc_recovery",
            elf=str(bootcode_elf),
            smc_sram_image=str(oca_images["smc_bundle"]),
            boot="primary",
            recovery=True,
            boot_timeout=TIMEOUT,
        )
    )
    t.spawn()
    t.expect("WAIT_SMC_MANIFEST", timeout=TIMEOUT)
    t.expect_status("SEP_MSG_STARTING_BL1", type="INFO", timeout=TIMEOUT)
    t.close()


# --- identity usage constraints --------------------------------------------
#
# The library calls get_identity_bytes() only when the manifest's selector bits
# constrain that field, so an unconstrained manifest never reaches this at all.
# These two are the accept and reject directions for the same image.


def test_identity_constraint_matching_chiplet_boots(vp, bootcode_elf, oca_images):
    """A manifest bound to this chiplet's identity boots."""
    t = vp(
        _cfg(
            "oca_id_match",
            bootcode_elf,
            oca_images["identity"],
            otp="tests/fuse_maps/oca_identity_match.yaml",
        )
    )
    t.spawn()
    t.expect_status("SEP_MSG_STARTING_BL1", type="INFO", timeout=TIMEOUT)
    t.close()


def test_identity_constraint_other_chiplet_refused(vp, bootcode_elf, oca_images):
    """The same manifest on a different chiplet is refused.

    One byte of SEP_CHIPLET_ID differs from the passing map, so this isolates the
    identity comparison. Worth having both directions: a reject-only test would
    also pass on a device that reported no identity at all, which is exactly what
    the VP did before the eFuse model gained this register.
    """
    t = vp(
        _cfg(
            "oca_id_mismatch",
            bootcode_elf,
            oca_images["identity"],
            otp="tests/fuse_maps/oca_identity_mismatch.yaml",
        )
    )
    t.spawn()
    match = t.expect_status("SEP_MSG_INVALID_CHIPLET_ID", type="ERROR", timeout=TIMEOUT)
    assert "ERROR" in match.group(0)
    t.close()


# --- variant, algorithm and encoding coverage ------------------------------


def test_pqc_variant_with_classical_signature_boots(vp, bootcode_elf, oca_images):
    """An OCAP body signed with a classical RSA-3072 key boots.

    This is the "parse all variants, verify RSA-3072 only" scope in one test: the
    36864-byte PQC geometry is understood and staged, and the classical signature
    over it verifies. A natively PQC-signed manifest is a different case the
    library refuses as unsupported -- nothing here can verify one.
    """
    t = vp(_cfg("oca_pqc", bootcode_elf, oca_images["pqc"]))
    t.spawn()
    t.expect("PUBK_AUTHORIZED", timeout=TIMEOUT)
    t.expect_status("SEP_MSG_STARTING_BL1", type="INFO", timeout=TIMEOUT)
    t.close()


def test_ecdsa_signature_type_refused(vp, bootcode_elf, oca_images):
    """ECDSA P-256 is a legal OCA primitive this ROM cannot verify, so it refuses.

    Refused at AUTHORIZATION, before any crypto: the anchor is a digest of an
    RSA modulus, so an EC key cannot be matched against it whatever its signature
    would have done. The console marker is what distinguishes this from a genuine
    digest mismatch -- both report INVALID_KEY_HASH, since the library gives the
    callback one failure code.
    """
    t = vp(_cfg("oca_ecdsa", bootcode_elf, oca_images["ecdsa"]))
    t.spawn()
    t.expect("PUBK_ALGO_UNSUPPORTED", timeout=TIMEOUT)
    match = t.expect_status("SEP_MSG_INVALID_KEY_HASH", type="ERROR", timeout=TIMEOUT)
    assert "ERROR" in match.group(0)
    t.close()


def test_der_public_key_encoding_refused(vp, bootcode_elf, oca_images):
    """A DER-encoded public key is refused; the ROM parses RAW only.

    Same key and algorithm as the passing signed image -- only the encoding
    differs -- so this isolates the encoding check from everything else.
    """
    t = vp(_cfg("oca_der", bootcode_elf, oca_images["der"]))
    t.spawn()
    t.expect("PUBK_ENCODING_UNSUPPORTED", timeout=TIMEOUT)
    match = t.expect_status("SEP_MSG_INVALID_KEY_HASH", type="ERROR", timeout=TIMEOUT)
    assert "ERROR" in match.group(0)
    t.close()


def test_aes128_encrypted_payload_boots(vp, bootcode_elf, oca_images):
    """The AES-128 half of the cipher support.

    Same secret and KDF as the AES-256 image; only out_bits in the derivation
    block and the engine's one-hot KEY_LEN change. Together the two cover both
    widths aes_cbc_decrypt() accepts -- and an unknown width is rejected rather
    than defaulted, which is why both need exercising.
    """
    t = vp(
        _cfg(
            "oca_aes128",
            bootcode_elf,
            oca_images["aes128"],
            otp="tests/fuse_maps/oca_encrypted.yaml",
        )
    )
    t.spawn()
    t.expect_status("SEP_MSG_DECRYPTION_END", type="INFO", timeout=TIMEOUT)
    t.expect_status("SEP_MSG_STARTING_BL1", type="INFO", timeout=TIMEOUT)
    t.close()


def test_sip_owner_otp_key_anchor_boots(vp, bootcode_elf, oca_images):
    """Key slot 24, SIP_PUBK_HASH1 -- the SiP owner's second root key bank.

    A different OTP anchor family from CHIPLET_PUBK_HASH0, so this checks the
    slot map resolves more than one bank correctly rather than happening to work
    for the one case already covered.
    """
    t = vp(
        _cfg(
            "oca_sip_key",
            bootcode_elf,
            oca_images["sip_key"],
            otp="tests/fuse_maps/oca_sip_key.yaml",
        )
    )
    t.spawn()
    t.expect("PUBK_AUTHORIZED", timeout=TIMEOUT)
    t.expect_status("SEP_MSG_STARTING_BL1", type="INFO", timeout=TIMEOUT)
    t.close()


def test_multi_image_payload_finds_bl1_last(vp, bootcode_elf, oca_images):
    """BL1 is the third TOC entry, so the handoff has to search by image type.

    Taking index 0 would boot the memory map. The payload carries three images
    and only the last is BLSTAGE1.
    """
    t = vp(_cfg("oca_multi", bootcode_elf, oca_images["multi"]))
    t.spawn()
    t.expect_status("SEP_MSG_STARTING_BL1", type="INFO", timeout=TIMEOUT)
    t.close()


def test_payload_without_bl1_is_refused(vp, bootcode_elf, oca_images):
    """A fully valid manifest carrying no bootable stage is a clean refusal.

    Everything verifies -- signature, payload hash, TOC -- and there is simply
    nothing to jump to. Booting whatever image happened to be present instead
    would be the dangerous outcome.
    """
    t = vp(_cfg("oca_no_bl1", bootcode_elf, oca_images["no_bl1"]))
    t.spawn()
    match = t.expect_status("SEP_MSG_SEP_BL1_MISSING", type="ERROR", timeout=TIMEOUT)
    assert "ERROR" in match.group(0)
    t.close()


def test_unsigned_image_refused_on_a_secure_lifecycle(vp, bootcode_elf, oca_images):
    """A PROD part refuses an unsigned manifest, on the DEVICE's insistence.

    The manifest never asserts secure boot; the lifecycle state does, through
    is_secure_boot_active(). This is the case that proves device-side enforcement
    works -- every other signed test has the manifest asking for verification, so
    none of them would notice if the device's opinion were ignored.

    The refusal is the library's, not ours. It used to be ours: the ROM's
    is_key_authorized callback saw an unsigned manifest and emitted
    PUBK_NO_SIGNATURE. The validator now rejects earlier, at the signature-class
    control -- secure boot in force while neither secure_boot_classic nor
    secure_boot_pqc names a family to verify by -- so the callback is never
    reached. Earlier and in the library is the better place for it; assert the
    outcome rather than the old route to it.
    """
    t = vp(
        _cfg(
            "oca_unsigned_prod",
            bootcode_elf,
            oca_images["unsigned"],
            otp="tests/fuse_maps/prod_secure.yaml",
        )
    )
    t.spawn()
    # 0x0003_0024 == OCA_FAIL_SIGNATURE_CLASS_CONTROL. Pinning the code keeps
    # this honest: refusing for some unrelated reason would also produce an
    # ERROR, and would pass a test that only looked for one. Match the per-slot
    # verdict, which precedes the ERROR -- the final MANIFEST_BOOT_FAIL carries
    # the same code but lands after it, and expect()'s default error pattern
    # would trip on the ERROR first.
    t.expect(r"MANIFEST_ERR=0x00030024", timeout=TIMEOUT)
    match = t.expect_status("SEP_MSG_MANIFEST_SECURE_BOOT", type="ERROR", timeout=TIMEOUT)
    assert "ERROR" in match.group(0)
    t.close()
