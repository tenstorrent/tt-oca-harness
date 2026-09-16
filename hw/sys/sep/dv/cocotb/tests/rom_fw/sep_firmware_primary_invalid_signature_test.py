# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest with a corrupted RSA signature; the backup boots.

One bit of the PRIMARY signature's byte 0 is flipped. The single-bit flip is the
point: a manifest correct in every other respect -- right magic, length, hash, key
slot, key digest and version -- must still fail authentication. A larger corruption
would be a weaker test, because something else would also catch it.

THE MECHANISM IS THE REFERENCE'S OWN. The reference makes no manifest modification
at all
for this scenario (``manifest_modifications`` is empty); it packs a clean image and
then post-processes the packed ``.spi_preload`` with
``tamper_spi_preload_signature(which="primary", mode="flip")``, which is
``flip_signature_byte(..., byte_index=0, xor_mask=0x01)``.
``mm.flip_signature_byte(buf, "primary", byte_index=0, xor_mask=0x01)`` is the same
byte, the same mask and the same stage of the flow.

THE EXPECTED OUTCOME IS A COMPLETED BOOT. The reference's ``expected_patterns``
(``sep_firmware_secure_boot_test.py``) grade the primary rejection
``WARNING: INVALID_SIGNATURE`` and end in ``COPY_AND_EXEC_IMAGE / EXEC_IMAGE``.

**THIS IS THE ONE MEMBER OF THIS GROUP WHOSE PRIMARY MUST REACH THE VERIFIER**, so
it declares ``primary_expected_rsa_starts = 1``. The base then requires the
primary's own ``RSA_VERIFY_START`` to sit between the primary read and the primary
error, and the total across the run to be exactly 2 -- the primary's failing modexp
and the backup's successful one. Every other member of the group declares 0 and the
base requires the first occurrence to follow the backup read. Asserting only that
"RSA ran at some point" would let this testcase pass on a run where the primary was
refused earlier and the backup alone verified.

**HOW THIS IS TOLD APART FROM ``sep_firmware_primary_invalid_signature_type_test``,
AND WHY THE ERROR CODE CANNOT DO IT.** Both end at
``MANIFEST_ERR_SIG_FAILED = 0x0003000c`` (``manifest.h``), shared by six arms of
``validate_signature``. The console separates them in both directions and both
halves are asserted here:

  * ``PUBK_SEL=0x00000000`` is pinned to **two** occurrences -- one per manifest
    slot -- proving BOTH manifests reached key selection
    (``manifest_crypto.c``). The sibling pins the same token to **one**, because
    there the type check returns before the echo. That count alone
    makes the two mutually exclusive on any single log;
  * ``BAD_SIG_TYPE=`` is forbidden here and required there, and ``RSA_VERIFY_FAIL``
    is required here and forbidden there.

PLATFORM ADAPTATION -- MARKER. The reference expects
``WARNING: INVALID_SIGNATURE``. This ROM *defines* ``SEP_MSG_INVALID_SIGNATURE``
(``bootrom/prod/include/status_values.h:15``) but never EMITS it: there is no
``report_status`` call for it anywhere under ``bootrom/prod/src``, so the
architected status ring carries only the generic code and the console token
``RSA_VERIFY_FAIL`` (``manifest_crypto.c``, reached only when
``rsa_3072_verify`` returns non-zero) is the per-reason evidence.

The signature field is at manifest offset 744, OUTSIDE the TBS region the hash
covers (``sep_manifest_mutate.OFF_SIGNATURE`` == ``TBS_LEN``), so this needs
neither a re-hash nor a re-sign -- and ``mm.verify_layout`` is asserted afterwards
to prove the TBS hash is still intact, because a mutation that invalidated it would
be rejected in the manifest loop and RSA would never run.

Needs ``+sep_crypto_edn_force``: TWO full RSA-3072 modexps run on OTBN here, which
parks in UrndRefresh until EDN grants entropy. It grants OTBN's EDN handshakes
only; the RSA assertions are untouched, so ``RSA_VERIFY_FAIL`` still means the
signature genuinely failed and ``SIG_VALID`` that the backup's genuinely verified.
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
# (configs/secure_boot_test.yaml:43-45 primary backup), so the echo value
# is the same for both and only the COUNT distinguishes this testcase.
_SEL_ECHO = "PUBK_SEL=0x00000000"


@pyuvm.test()
class sep_firmware_primary_invalid_signature_test(sep_primary_fail_backup_boot_base):
    """Primary signature fails RSA -> failover -> backup verifies and boots."""

    # manifest_crypto.c. Requiring this specific marker rather than any failure
    # is what distinguishes "the signature was checked and rejected" from
    # "something else went wrong first".
    primary_defect_marker = "RSA_VERIFY_FAIL"
    primary_expected_error = MANIFEST_ERR_SIG_FAILED
    # The defect IS the signature value, so the primary must drive the verifier.
    primary_expected_rsa_starts = 1
    efuse_preload = _EFUSE_PRELOAD
    extra_required = (_SEL_ECHO,)
    # BAD_SIG_TYPE= is the discriminator against the signature-TYPE sibling, which
    # shares this error code. The rest are the other rejecting arms of
    # validate_signature: reaching any of them would mean a slot was refused before
    # the verifier, so the terminal verdict would not be a signature verdict.
    extra_forbidden = (
        "BAD_SIG_TYPE=",
        "BAD_KEY_IDX",
        "BAD_KEY_SEL",
        "ROM_KEY_EMPTY",
        "FUSE_KEY_EMPTY",
        "PUBK_HASH_MISMATCH",
        "KEY_REVOKED",
        "VERSION_ROLLBACK",
    )

    def corrupt_primary(self, buf: bytearray) -> None:
        # No manifest_identifier corruption: the primary must reach
        # rsa_3072_verify.
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
        # check_security_version (manifest_crypto.c) and the revocation check
        # (:369 ->) both run BEFORE rsa_3072_verify (:244), so either being
        # non-zero would terminate the primary earlier with a different error and
        # the signature would never be reached.
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
        sels = indices_of(_SEL_ECHO)

        # CHK-BOTH-REACHED-KEYSEL: this is the discriminating check of the testcase.
        # BOTH manifests must have reached the selector echo at
        # manifest_crypto.c, which is only true when the type check at
        # accepted both. One occurrence would be the signature-TYPE
        # sibling's signature; two is this one's, and the split across the backup
        # read is what attributes one echo to each slot.
        assert len(sels) == 2, (
            f"{_SEL_ECHO} appeared {len(sels)} times at {sels}, expected exactly 2 "
            f"(one per manifest slot). One occurrence would mean a slot was refused "
            f"before the selector echo, i.e. not by its signature value. "
            f"Console: {console}"
        )
        assert 0 <= i_bsrc and sels[0] < i_bsrc < sels[1], (
            f"{_SEL_ECHO} occurrences {sels} do not straddle the backup read"
            f"@{i_bsrc}: the two echoes are not one per slot. Console: {console}"
        )
        self.logger.info(
            "CHK-BOTH-REACHED-KEYSEL: %s at lines %s, one before and one after the "
            "backup read@%d -- both manifests passed the signature-type arm and "
            "reached key selection",
            _SEL_ECHO,
            sels,
            i_bsrc,
        )
