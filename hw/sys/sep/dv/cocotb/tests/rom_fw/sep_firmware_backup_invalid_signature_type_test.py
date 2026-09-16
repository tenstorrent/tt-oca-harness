# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup manifest declares an unsupported signature TYPE -> terminal.

The primary's ``manifest_identifier`` is corrupted to force failover, then the
backup's ``signature_type`` is set to 0. ``validate_signature`` accepts only
``MANIFEST_SIG_TYPE_RSA_3072`` (1, ``manifest.h``) and refuses anything else
with ``BAD_SIG_TYPE=`` (``manifest_crypto.c``).

WHY 0, AND WHY A FIXED VALUE. The reference draws from
``random.choice([0, random.randint(3, 10)])``,
so 0 is one of its own values; it is not 2, because 2 is
``MANIFEST_SIG_TYPE_ECC_P_256`` (``manifest.h``) and the reference avoids the
one non-RSA type its packer treats specially. The ROM's check is a single ``!=``
against RSA-3072, so every value in that set exercises the identical arm, and
fixing it is what lets this testcase assert the exact ``BAD_SIG_TYPE=`` the ROM
echoed rather than accepting any value at all -- the same reason
``sep_firmware_backup_invalid_public_key_selection_test`` fixes its selection.

THE ROM DOES VALIDATE TYPE SEPARATELY FROM VALUE, AND THIS TEST PROVES IT RATHER
THAN ASSUMING IT. The type check is the FIRST arm of ``validate_signature``,
ahead even of the ``PUBK_SEL=`` echo at ``manifest_crypto.c``. So ``PUBK_SEL=``
is forbidden below: the primary died at BAD_MAGIC before any crypto ran, so if the
selector is echoed at all it can only be the backup's, which would mean the type
check did not preempt key selection. That single forbid is what turns "the ROM
rejected it" into "the ROM rejected it AT the type check".

WHY THIS IS NOT THE SAME TESTCASE AS ``sep_firmware_backup_invalid_signature_test``.
Both return ``MANIFEST_ERR_SIG_FAILED`` (0x0003000c, ``manifest.h``), which six
arms of ``validate_signature`` share, so the error code cannot tell them apart.
The status ring does not close the gap either: the only ring difference between
the two is that the ROM-key arm re-reports ``SEP_MSG_VALIDATE_CHECK``
(``manifest_crypto.c``) once the selector has been accepted, which is a
side effect of reaching a LATER arm rather than a statement of the rejection
reason -- and neither testcase asserts it. The console token is what actually
discriminates. This testcase therefore requires ``BAD_SIG_TYPE=0x00000000`` and
forbids ``RSA_VERIFY_START`` and ``RSA_VERIFY_FAIL``; its sibling requires
``RSA_VERIFY_FAIL``, which this run must never produce. Asserting the shared code
alone would make the two interchangeable.

``signature_type`` is one byte at manifest offset 165, INSIDE the TBS, so the
helper re-hashes. It cannot be a signature-region patch: the field is covered by
``manifest_hash``, so an un-rehashed write dies in the manifest loop as a hash
mismatch and never reaches the type check at all. No re-sign is needed or possible
-- the type is rejected before ``rsa_3072_verify`` (``manifest_crypto.c``), so
the now-stale signature is never examined, and ``RSA_VERIFY_START`` being
forbidden is what checks that ordering instead of assuming it.

No ``+sep_crypto_edn_force``: OTBN is never driven on either slot.
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
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod.toml"
)

# One of the reference's own values (sep_firmware_secure_boot_test.py), fixed
# so the echoed value is assertable. See the docstring for why not 2.
_BAD_SIG_TYPE = 0
# manifest_crypto.c -- simputshex32("BAD_SIG_TYPE=", signature_type).
_BAD_SIG_TYPE_ECHO = f"BAD_SIG_TYPE=0x{_BAD_SIG_TYPE:08x}"


@pyuvm.test()
class sep_firmware_backup_invalid_signature_type_test(sep_backup_manifest_fail_base):
    """Primary BAD_MAGIC -> failover -> backup declares sig type 0 -> terminal."""

    backup_defect_marker = _BAD_SIG_TYPE_ECHO
    expected_error = MANIFEST_ERR_SIG_FAILED
    efuse_preload = _EFUSE_PRELOAD
    # PUBK_SEL= is the load-bearing one: it is the very next thing
    # validate_signature prints (manifest_crypto.c), so its absence proves the
    # type check ran FIRST rather than merely eventually. RSA_VERIFY_FAIL is the
    # discriminator against the signature-VALUE sibling, which shares this error
    # code. The rest are the later arms, none of which may be reached.
    extra_forbidden = (
        "PUBK_SEL=",
        "RSA_VERIFY_START",
        "RSA_VERIFY_FAIL",
        "SIG_VALID",
        "CRYPTO_VALIDATE_OK",
        "BAD_KEY_IDX",
        "BAD_KEY_SEL",
        "ROM_KEY_EMPTY",
        "FUSE_KEY_EMPTY",
        "PUBK_HASH_MISMATCH",
        "KEY_REVOKED",
        "VERSION_ROLLBACK",
    )

    def corrupt_backup(self, buf: bytearray) -> None:
        before = mm.get_signature_type(buf, "backup")
        assert before == mm.SIG_TYPE_RSA_3072, (
            f"backup signature_type is already {before}, expected "
            f"{mm.SIG_TYPE_RSA_3072} (RSA-3072): the shipped image is not the "
            f"supported-type baseline this testcase mutates away from"
        )
        mm.set_signature_type(buf, "backup", _BAD_SIG_TYPE)
        got = mm.get_signature_type(buf, "backup")
        assert got == _BAD_SIG_TYPE, (
            f"signature_type is 0x{got:02x} after the write, expected "
            f"0x{_BAD_SIG_TYPE:02x}; the mutation did not land"
        )
        # The re-hash must have restored a valid TBS hash, or the backup is thrown
        # out in the manifest loop as a hash mismatch and the type check -- the
        # only thing this testcase is about -- never runs.
        mm.verify_layout(buf, "backup")
        self.logger.info(
            "CHK-STIMULUS-SIGTYPE: backup signature_type %d (MANIFEST_SIG_TYPE_"
            "RSA_3072) -> %d (unsupported), TBS re-hashed, signature now stale "
            "but never reached",
            before,
            got,
        )

    def check_efuse(self, image) -> None:
        # Both of these are evaluated before validate_signature is even entered
        # (manifest_crypto.c), so either being non-zero would end the
        # run with a different verdict and make this testcase vacuous.
        bl1_ver = image.field_int("BL1_VERSION")
        assert bl1_ver == 0, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: the rollback check runs "
            f"before validate_signature and would terminate the run first"
        )
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert revoke == 0, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0: a revocation "
            f"verdict would come from a different arm of the same function"
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)
        # Exactly once. The primary never reaches crypto, so a second occurrence
        # would mean a slot this testcase did not account for also declared a bad
        # type -- and the verdict would not be attributable to this stimulus.
        n = sum(1 for line in console if _BAD_SIG_TYPE_ECHO in line)
        assert n == 1, (
            f"{_BAD_SIG_TYPE_ECHO} appeared {n} times, expected exactly 1 (the "
            f"backup's). Console: {console}"
        )
        self.logger.info(
            "CHK-SIGTYPE-ECHO: ROM read %s exactly once and never echoed PUBK_SEL=",
            _BAD_SIG_TYPE_ECHO,
        )
