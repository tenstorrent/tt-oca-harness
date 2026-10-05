# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest with a corrupted RSA signature; the backup boots.

``mm.flip_signature_byte(buf, "primary", byte_index=0, xor_mask=0x01)`` flips one bit of signature
byte 0. The manifest is correct in every other respect (magic, length, hash, key slot, key digest,
version), so only authentication can refuse it. The backup boots.

This is the one member of the group whose primary must reach the verifier, so
``primary_expected_rsa_starts = 1``: the primary's ``RSA_EXEC`` sits between the primary read and
the primary error, and the run total is exactly 2. The verdict is the console token
``RSA_PKCS1_FAIL`` (``rsa_verify.c``, padding or digest mismatch after the modexp).

``sep_firmware_primary_invalid_signature_type_test`` ends at a different code. The console also
separates them: ``PUBK_AUTHORIZED`` appears twice here and once (the backup's) there, and
``RSA_PKCS1_FAIL`` is required here and forbidden there.

The signature is outside the hashed region (``OFF_SIGNATURE == SIGNED_REGION_END``), so no re-hash
or re-sign is needed; ``mm.verify_layout`` checks the hash is intact. Needs ``+esrc_noise_force``:
two RSA-3072 modexps run on OTBN, which stalls until EDN grants entropy.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from rom_fw.sep_primary_fail_backup_boot_base import (
    MANIFEST_ERR_SIG_FAILED,
    sep_primary_fail_backup_boot_base,
)

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod.toml"
)

# Both slots keep the shipped selector, ROM key slot 0, so the marker is the same
# for both and only the COUNT distinguishes this test. PUBK_AUTHORIZED is the OCA
# evidence that a slot's key resolved and was anchored.
_KEY_AUTHORIZED = "PUBK_AUTHORIZED"


@pyuvm.test()
class sep_firmware_primary_invalid_signature_test(sep_primary_fail_backup_boot_base):
    """Primary signature fails RSA -> failover -> backup verifies and boots."""

    # rsa_verify.c -- the modexp ran and the PKCS#1 padding/digest did not
    # match. That is the verdict this test is about, and it is a different
    # marker from RSA_EXEC_FAIL, which means the OTBN execution itself
    # failed: an engine fault, not a signature verdict. RSA_EXEC_FAIL is
    # forbidden below for exactly that reason.
    primary_defect_marker = "RSA_PKCS1_FAIL"
    primary_expected_error = MANIFEST_ERR_SIG_FAILED
    # The defect IS the signature value, so the primary must drive the verifier.
    primary_expected_rsa_starts = 1
    efuse_preload = _EFUSE_PRELOAD
    extra_required = (_KEY_AUTHORIZED,)
    # Every refusal plat_is_key_authorized() can report (oca_platform.c). Reaching
    # any of them would mean a slot was refused before the verifier ran, so the
    # verdict would not be a signature verdict.
    #
    # Key revocation and anti-rollback need no marker here: they report through
    # MANIFEST_ERR=<code>, and the base already requires this member's exact code,
    # so a different rejection reason cannot satisfy it.
    extra_forbidden = (
        # An engine fault would end the primary's attempt without the signature
        # ever being judged, so the run would not be a signature verdict.
        "RSA_EXEC_FAIL",
        "PUBK_ALGO_UNSUPPORTED",
        "PUBK_ENCODING_UNSUPPORTED",
        "PUBK_FIELD_TOO_SMALL",
        "PUBK_NO_SIGNATURE",
        "PUBK_SEL_AMBIGUOUS",
        "PUBK_SEL_EMPTY",
        "PUBK_SLOT_RESERVED",
        "PUBK_SLOT_PQC_UNSUPPORTED",
        "PUBK_SLOT_UNPROVISIONED",
        "PUBK_OTP_EMPTY",
        "PUBK_UNAUTHORIZED",
        "PUBK_HASH_TIMEOUT",
    )

    def corrupt_primary(self, buf: bytearray) -> None:
        # No magic corruption: the primary must reach the verifier.
        base = mm.slot_base("primary") + mm.OFF_SIGNATURE
        before = bytes(buf[base : base + 8])
        mm.flip_signature_byte(buf, "primary", byte_index=0, xor_mask=0x01)
        after = bytes(buf[base : base + 8])
        assert before != after, "signature flip was a no-op"
        # A mutation that broke the manifest hash would be refused before RSA runs.
        mm.verify_layout(buf, "primary")
        # And the modulus is untouched, so the key bind still passes and the only
        # thing wrong with the primary is the signature value.
        mm.verify_public_key(buf, "primary")
        self.logger.info(
            "CHK-STIMULUS-SIG: primary signature[0:8] %s -> %s (1 bit), signed region hash "
            "intact and modulus still binds the ROM slot-0 digest",
            before.hex(),
            after.hex(),
        )

    def check_efuse(self, image) -> None:
        bl1_ver = image.field_int("BL1_VERSION")
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        # The anti-rollback and revocation checks both run BEFORE signature
        # verification, so either input being non-zero would terminate the primary
        # earlier with a different error and the signature would never be
        # reached.
        assert bl1_ver == 0, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: a rollback rejection "
            f"precedes the signature check and would mask this defect"
        )
        assert revoke == 0, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0: a revocation "
            f"rejection precedes the signature check on both slots"
        )

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        def indices_of(marker: str) -> list[int]:
            return [i for i, line in enumerate(console) if marker in line]

        i_bsrc = next(iter(indices_of(f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}")), -1)
        sels = indices_of(_KEY_AUTHORIZED)

        # CHK-BOTH-REACHED-KEYSEL: this is the discriminating check of the
        # testcase. PUBK_AUTHORIZED is printed once per slot whose key resolved
        # and was anchored (oca_platform.c), so BOTH manifests must show it: one
        # occurrence would be the signature-TYPE sibling's signature, where the
        # primary is refused before its key is even authorized. Two, split across
        # the backup read, attributes one to each slot -- and places the primary's
        # rejection after key selection, at the verifier.
        assert len(sels) == 2, (
            f"{_KEY_AUTHORIZED} appeared {len(sels)} times at {sels}, expected exactly 2 "
            f"(one per manifest slot). One occurrence would mean a slot was refused "
            f"before the selector echo, i.e. not by its signature value. "
            f"Console: {console}"
        )
        assert 0 <= i_bsrc and sels[0] < i_bsrc < sels[1], (
            f"{_KEY_AUTHORIZED} occurrences {sels} do not straddle the backup read"
            f"@{i_bsrc}: the two echoes are not one per slot. Console: {console}"
        )
        self.logger.info(
            "CHK-BOTH-REACHED-KEYSEL: %s at lines %s, one before and one after the "
            "backup read@%d -- both manifests' keys were authorized, so neither "
            "was refused before the verifier",
            _KEY_AUTHORIZED,
            sels,
            i_bsrc,
        )
