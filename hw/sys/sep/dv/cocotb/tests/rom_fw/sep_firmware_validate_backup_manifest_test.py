# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest refused on its major version; the backup validates end to end.

The backup's full validation chain is asserted in order after the backup read,
so a run that boots the primary cannot pass.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_primary_fail_backup_boot_base import (
    sep_primary_fail_backup_boot_base,
)

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod.toml"
)

_MANIFEST_ERR_BAD_VERSION = mm.boot_err("OCA_FAIL_FORMAT_VERSION_MISMATCH")

_BAD_MAJOR_VERSION = 99

# The backup's validation stages, in the order the ROM emits them.
_BACKUP_CHAIN = (
    "MANIFEST_HASH_OK",
    "RSA_VERIFY_START",
    "SIG_VALID",
    "PLD_HASH_OK",
    "CRYPTO_VALIDATE_OK",
    "MANIFEST_OK",
    "BL1_COPIED",
    "BL1_JUMP=",
)


@pyuvm.test()
class sep_firmware_validate_backup_manifest_test(sep_primary_fail_backup_boot_base):
    """Primary refused on its major version; the backup validates end to end."""

    primary_defect_marker = ""
    primary_expected_error = _MANIFEST_ERR_BAD_VERSION
    primary_expected_rsa_starts = 0
    efuse_preload = _EFUSE_PRELOAD
    extra_required = _BACKUP_CHAIN
    # The backup must pass every check and the primary must stop at the header check.
    extra_forbidden = (
        "MANIFEST_HASH_MISMATCH",
        "PLD_HASH_MISMATCH",
        "CRYPTO_FAIL=",
        "RSA_VERIFY_FAIL",
        "MANIFEST_ALL_FAILED",
        "IMAGE_HASH_MISMATCH",
        fd.LC_MARKER,
        fd.CHIPLET_MARKER,
        fd.PACKAGE_MARKER,
    )

    def corrupt_primary(self, buf: bytearray) -> None:
        before = mm.manifest_version(buf, "primary")
        assert before == (mm.MANIFEST_MAJOR_VERSION, 0), (
            f"primary manifest version is {before[0]}.{before[1]}, expected "
            f"{mm.MANIFEST_MAJOR_VERSION}.0: the shipped image is not the valid "
            f"baseline this testcase mutates away from"
        )
        mm.set_manifest_version(buf, "primary", major=_BAD_MAJOR_VERSION)
        after = mm.manifest_version(buf, "primary")
        assert after == (_BAD_MAJOR_VERSION, 0), (
            f"primary manifest version is {after[0]}.{after[1]} after the write, "
            f"expected {_BAD_MAJOR_VERSION}.0; the mutation did not land"
        )
        assert mm.manifest_length(buf, "primary") == mm.MANIFEST_SIZE, (
            "manifest_length moved: the primary would be refused with BAD_LENGTH "
            "instead of BAD_VERSION and the asserted code would be wrong"
        )
        self.logger.info(
            "CHK-STIMULUS-VERSION: primary manifest_version_major %d -> %d "
            "(minor stays 0, length stays %d), signed region re-hashed so the version is "
            "the slot's only defect",
            before[0],
            after[0],
            mm.MANIFEST_SIZE,
        )

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        slot_err = f"MANIFEST_ERR=0x{self.primary_expected_error:08x}"
        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)

        fd.assert_slot_attributed(console, slot_err, after=i_psrc, before=i_bsrc)

        # Order matters: presence alone could be met by stages from different slots.
        previous = i_bsrc
        positions = []
        for marker in _BACKUP_CHAIN:
            i = fd.first_index(console, marker)
            assert i > previous, (
                f"{marker}@{i} does not follow the previous stage of the backup's "
                f"validation chain@{previous}: the chain is out of order or a stage "
                f"belongs to another slot. Chain so far: "
                f"{list(zip(_BACKUP_CHAIN, positions))}. Console: {console}"
            )
            positions.append(i)
            previous = i
        self.logger.info(
            "CHK-BACKUP-VALIDATED: backup read@%d then %s -- the backup manifest "
            "went through structure, hash, signature, payload hash, TOC, BL1 copy "
            "and handoff",
            i_bsrc,
            ", ".join(f"{m}@{p}" for m, p in zip(_BACKUP_CHAIN, positions)),
        )
