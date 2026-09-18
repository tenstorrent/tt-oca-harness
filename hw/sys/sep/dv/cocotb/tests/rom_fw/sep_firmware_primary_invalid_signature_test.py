# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest with a corrupted RSA signature; the backup boots.

One bit of the PRIMARY signature's byte 0 is flipped. The single-bit flip is the
point: a manifest correct in every other respect -- right magic, length, hash, key
slot, key digest and version -- must still fail authentication. A larger corruption
would be a weaker test, because something else would also catch it.

``mm.flip_signature_byte(buf, "primary", byte_index=0, xor_mask=0x01)`` is the same
byte, the same mask and the same stage of the flow.

The expected outcome is A Completed boot.

**THIS IS THE ONE MEMBER OF THIS GROUP WHOSE PRIMARY MUST REACH THE VERIFIER**, so
it declares ``primary_expected_rsa_starts = 1``. The base then requires the
primary's own ``RSA_EXEC`` to sit between the primary read and the primary error,
and the total across the run to be exactly 2 -- the primary's failing modexp and
the backup's successful one. Every other member of the group declares 0 and the
base requires the first occurrence to follow the backup read. Asserting only that
"RSA ran at some point" would let this testcase pass on a run where the primary was
refused earlier and the backup alone verified.

**HOW THIS IS TOLD APART FROM ``sep_firmware_primary_invalid_signature_type_test``,
AND WHY THE ERROR CODE CANNOT DO IT.** Both end at
``OCA_BOOT_ERR_RESULT(OCA_FAIL_SIGNATURE)``, which several refusal arms share. The
console separates them in both directions and both halves are asserted here:

  * ``PUBK_AUTHORIZED`` is pinned to **two** occurrences -- one per manifest slot
    -- proving BOTH manifests' keys resolved and were anchored
    (``oca_platform.c``). The sibling shows **one**, because there the algorithm
    arm refuses the primary before its key is authorized. That count alone makes
    the two mutually exclusive on any single log;
  * ``PUBK_ALGO_UNSUPPORTED`` is forbidden here and expected there, and
    ``RSA_EXEC_FAIL`` is required here and forbidden there.

Platform adaptation -- MARKER. This ROM *defines* ``SEP_MSG_INVALID_SIGNATURE`` but
never EMITS it: there is no ``report_status`` call for it anywhere under
``bootrom/prod/src``, so the architected status ring carries only the generic code and
the console token ``RSA_PKCS1_FAIL`` (``rsa_verify.c:175``, reached only when the
recovered padding and digest do not match) is the per-reason evidence.

The signature field sits OUTSIDE the region the manifest hash covers
(``sep_manifest_mutate.OFF_SIGNATURE`` == ``SIGNED_REGION_END``), so this needs neither
a re-hash nor a re-sign -- and ``mm.verify_layout`` is asserted afterwards to prove
the hash is still intact, because a mutation that invalidated it would be rejected
before the verifier ever ran.

Needs ``+esrc_noise_force``: TWO full RSA-3072 modexps run on OTBN here, which
parks in UrndRefresh until EDN grants entropy. The ROM brings the real
ESRC -> CSRNG -> EDN chain up itself, so only the noise source is forced and the
RSA assertions are untouched -- ``RSA_PKCS1_FAIL`` still means the signature
genuinely failed and ``RSA_VERIFY_OK`` that the backup's genuinely verified.
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

# Both slots keep the shipped selector, ROM key slot 0
# Both slots select the same ROM key, so the marker is identical for both and
# only the COUNT distinguishes this testcase. PUBK_AUTHORIZED is the OCA
# evidence that a slot's key resolved and was anchored: there is no
# "PUBK_SEL=<value>" echo, because the selector is a 128-bit bitmap rather than
# a small index.
_KEY_AUTHORIZED = "PUBK_AUTHORIZED"


@pyuvm.test()
class sep_firmware_primary_invalid_signature_test(sep_primary_fail_backup_boot_base):
    """Primary signature fails RSA -> failover -> backup verifies and boots."""

    # rsa_verify.c:175 -- the modexp ran and the PKCS#1 padding/digest did not
    # match. That is the verdict this testcase is about, and it is a different
    # marker from RSA_EXEC_FAIL (:164), which means the OTBN execution itself
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
    # verdict would not be a signature verdict. PUBK_ALGO_UNSUPPORTED is also the
    # discriminator against the signature-TYPE sibling, which shares this error
    # code.
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
        # The hash must still verify: if this mutation had invalidated the TBS hash,
        # the primary would be rejected as HASH_MISMATCH in the manifest loop and
        # RSA would never run -- a different test wearing this test's name.
        mm.verify_layout(buf, "primary")
        # And the modulus is untouched, so the key bind still passes and the only
        # thing wrong with the primary is the signature value.
        mm.verify_public_key(buf, "primary")
        self.logger.info(
            "CHK-STIMULUS-SIG: primary signature[0:8] %s -> %s (1 bit), TBS hash "
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
