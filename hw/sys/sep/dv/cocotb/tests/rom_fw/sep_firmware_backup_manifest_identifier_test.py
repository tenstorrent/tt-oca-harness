# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup manifest carries a wrong identifier; the ROM halts.

The mirror of ``sep_firmware_primary_manifest_identifier_test``. There the primary
carries the bad ``manifest_identifier`` and the valid backup completes the boot;
here the backup carries it, and with both slots refused ``rom_manifest_boot``
runs out of retries and ``rom_err_fail`` halts the ROM
(``bootrom/prod/src/manifest_load.c``, ``bootrom/prod/src/rom_main.c``). The
reference expects the terminal shape -- ``ERROR: INVALID_MANIFEST_ID`` rather
than a warning.

THE FAILOVER TRIGGER, AND WHY IT IS NOT THE SHARED ONE.
Reaching the backup by breaking the primary's payload TOC version does not work
here: this ROM validates the TOC INSIDE the slot attempt and prints
``MANIFEST_OK`` only after the whole slot passes (``manifest_load.c``), so a
TOC-defective primary never reports itself validated; and the manifest's
secure-boot flag is ignored in PROD, which is the lifecycle this environment must
run for the crypto chain to be enforced at all (``secure_boot_enabled``).

The family's usual trigger -- corrupt the primary's ``manifest_identifier`` --
also cannot be used here, and that is the interesting constraint. It is the same
defect the backup carries, so both slots would be refused with
``MANIFEST_ERR_BAD_MAGIC``. On the console the two occurrences could still be told
apart by slot window, but the TERMINAL STATUS WORD could not: ``rom_err_fail``
encodes ``last_err`` (``rom_main.c``), and with both slots on one code nothing
would attribute that verdict to the backup rather than to the trigger. The trigger
is therefore the primary's ``manifest_length``, a BAD_LENGTH refused by the same
function on the very next check and equally free of hash or crypto work, but with
a DIFFERENT error code. The shared base refuses to run when the two codes match,
so this reasoning is enforced rather than documented.

MARKER SUBSTITUTION. As on the primary side, this ROM defines
``SEP_MSG_INVALID_MANIFEST_ID`` (``bootrom/prod/include/status_values.h``) and
emits it nowhere, and ``validate_manifest_header`` prints no token for BAD_MAGIC.
The error code in ``MANIFEST_ERR=`` and the terminal status word are the whole
evidence, so this testcase pins each slot's code to exactly one occurrence inside
its own attempt.
"""

from __future__ import annotations

import pyuvm

from env import sep_manifest_mutate as mm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_backup_manifest_structural_fail_base import (
    sep_backup_manifest_structural_fail_base,
)
from rom_fw.sep_usage_constraint_base import EFUSE_PRELOAD

# manifest.h
_MANIFEST_ERR_BAD_MAGIC = 0x0003_0002
_MANIFEST_ERR_BAD_LENGTH = 0x0003_0004

_BAD_IDENTIFIER = b"\x99\x99\x99\x99"
# Not sizeof(manifest_t), so the minor-version-0 exact-match check returns
# BAD_LENGTH; and 4-aligned, so it is that check rather than the alignment check
# that runs afterwards which produces the verdict.
_BAD_LENGTH = mm.MANIFEST_SIZE - 4


@pyuvm.test()
class sep_firmware_backup_manifest_identifier_test(
        sep_backup_manifest_structural_fail_base):
    """Backup identifier is not TBL1 -> both slots refused -> the ROM halts."""

    backup_defect_marker = f"MANIFEST_ERR=0x{_MANIFEST_ERR_BAD_MAGIC:08x}"
    expected_error = _MANIFEST_ERR_BAD_MAGIC
    primary_expected_error = _MANIFEST_ERR_BAD_LENGTH
    efuse_preload = EFUSE_PRELOAD
    # No slot reaches the usage-constraint block or the crypto chain, so none of
    # these arms may claim this run's verdict.
    extra_forbidden = (fd.LC_MARKER, fd.CHIPLET_MARKER, fd.PACKAGE_MARKER,
                       "MANIFEST_HASH_MISMATCH", "CRYPTO_FAIL=")

    def corrupt_primary(self, buf: bytearray) -> None:
        before = mm.manifest_length(buf, "primary")
        assert before == mm.MANIFEST_SIZE, (
            f"primary manifest_length is {before}, expected {mm.MANIFEST_SIZE}: "
            f"the shipped image is not the valid baseline this trigger mutates "
            f"away from"
        )
        major, minor = mm.manifest_version(buf, "primary")
        assert (major, minor) == (mm.MANIFEST_MAJOR_VERSION, 0), (
            f"primary manifest version is {major}.{minor}: BAD_LENGTH is only the "
            f"exact-match branch's verdict while minor is 0"
        )
        mm.set_manifest_length(buf, "primary", _BAD_LENGTH)
        self.logger.info(
            "CHK-STIMULUS-TRIGGER: primary manifest_length %d -> %d (4-aligned, "
            "not sizeof(manifest_t)), so the primary is refused with BAD_LENGTH -- "
            "a different code from the backup's BAD_MAGIC", before,
            mm.manifest_length(buf, "primary"),
        )

    def corrupt_backup(self, buf: bytearray) -> None:
        base = mm.BACKUP_MANIFEST_OFFSET
        before = bytes(buf[base:base + 4])
        assert before == mm.MANIFEST_MAGIC, (
            f"backup identifier is already {before!r}, expected "
            f"{mm.MANIFEST_MAGIC!r}"
        )
        mm.set_identifier(buf, "backup", _BAD_IDENTIFIER)
        after = bytes(buf[base:base + 4])
        assert after == _BAD_IDENTIFIER, (
            f"identifier is {after!r} after the write, expected {_BAD_IDENTIFIER!r}"
        )
        self.logger.info(
            "CHK-STIMULUS-IDENTIFIER: backup manifest_identifier %r -> %r, TBS "
            "re-hashed so the identifier is the slot's only defect",
            before, after,
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)
        # CHK-HASH-NOT-REACHED: the identifier check precedes
        # manifest_check_integrity, and BAD_LENGTH precedes it as well, so NEITHER
        # slot had a hash computed. A MANIFEST_HASH_OK here would mean a slot got
        # further than this stimulus accounts for.
        assert not any("MANIFEST_HASH_OK" in line for line in console), (
            f"ROM printed MANIFEST_HASH_OK: a slot passed "
            f"validate_manifest_header, so the structural rejection under test is "
            f"not what refused it. Console: {console}"
        )
        self.logger.info(
            "CHK-HASH-NOT-REACHED: neither slot reached manifest_check_integrity, "
            "so both were refused inside validate_manifest_header"
        )
