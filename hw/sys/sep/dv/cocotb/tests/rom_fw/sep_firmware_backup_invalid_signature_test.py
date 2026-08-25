# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup manifest with a corrupted RSA signature (PyUVM).

The primary's ``manifest_identifier`` is corrupted to force failover, then a single
bit of the backup signature's byte 0 is flipped. The single-bit flip is the point:
a manifest correct in every other respect -- right magic, length, hash, key slot
and version -- must still fail authentication. A larger corruption would be a
weaker test, because something else would also catch it.

The signature field is at manifest offset 744, outside the TBS region the hash
covers, so this needs neither a re-hash nor a re-sign. The ROM's verdict is
``RSA_VERIFY_FAIL`` -> ``MANIFEST_ERR_SIG_FAILED``.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm

from env import sep_manifest_mutate as mm
from rom_fw.sep_backup_manifest_fail_base import (
    MANIFEST_ERR_SIG_FAILED,
    sep_backup_manifest_fail_base,
)

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads" / "sep_efuse_lc_prod.hex"
)


@pyuvm.test()
class sep_firmware_backup_invalid_signature_test(sep_backup_manifest_fail_base):
    """Primary BAD_MAGIC -> failover -> backup signature fails RSA -> terminal."""

    # rsa_verify.c / manifest_crypto.c:213-216. Requiring this specific marker
    # rather than any failure is what distinguishes "the signature was checked and
    # rejected" from "something else went wrong first".
    backup_defect_marker = "RSA_VERIFY_FAIL"
    expected_error = MANIFEST_ERR_SIG_FAILED
    efuse_preload = _EFUSE_PRELOAD
    # RSA must actually have been driven, and must not have succeeded.
    extra_forbidden = ("SIG_VALID", "CRYPTO_VALIDATE_OK")

    def corrupt_backup(self, buf: bytearray) -> None:
        before = bytes(buf[mm.BACKUP_MANIFEST_OFFSET + mm.OFF_SIGNATURE:][:8])
        mm.flip_signature_byte(buf, "backup", byte_index=0, xor_mask=0x01)
        after = bytes(buf[mm.BACKUP_MANIFEST_OFFSET + mm.OFF_SIGNATURE:][:8])
        assert before != after, "signature flip was a no-op"
        # The hash must still verify: if this mutation had invalidated the TBS
        # hash, the backup would be rejected as HASH_MISMATCH in the manifest loop
        # and RSA would never run -- a different test wearing this test's name.
        mm.verify_layout(buf, "backup")
        self.logger.info(
            "CHK-STIMULUS-SIG: backup signature[0:8] %s -> %s (1 bit), TBS hash intact",
            before.hex(), after.hex(),
        )

    def check_efuse(self, image) -> None:
        bl1_ver = image.field_int("BL1_VERSION")
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        # check_security_version and the revocation check both run BEFORE the
        # signature is verified (manifest_crypto.c:325-358), so either of these
        # being non-zero would terminate the run earlier with a different error and
        # the signature would never be reached.
        assert bl1_ver == 0, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: a rollback rejection "
            f"precedes the signature check and would mask this defect"
        )
        assert revoke == 0, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0: a revocation "
            f"rejection precedes the signature check"
        )
