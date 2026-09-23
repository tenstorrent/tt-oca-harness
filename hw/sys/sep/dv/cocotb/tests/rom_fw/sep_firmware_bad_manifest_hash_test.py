# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest's stored hash disagrees with its TBS; the backup boots.

Only the stored ``manifest_hash`` (outside the TBS) is changed, so it is the sole defect.
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
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads"
    / "efuse_configurations" / "sep_efuse_lc_prod.toml"
)

_MANIFEST_ERR_HASH_MISMATCH = 0x0003_000B

_HASH_MISMATCH = "MANIFEST_HASH_MISMATCH"
_HASH_OK = "MANIFEST_HASH_OK"


@pyuvm.test()
class sep_firmware_bad_manifest_hash_test(sep_primary_fail_backup_boot_base):
    """Primary's manifest_hash does not match its TBS -> the backup boots."""

    # This arm prints no CRYPTO_FAIL=, so the base's defect-marker check does not apply.
    primary_defect_marker = ""
    primary_expected_error = _MANIFEST_ERR_HASH_MISMATCH
    primary_expected_rsa_starts = 0
    efuse_preload = _EFUSE_PRELOAD
    extra_required = (_HASH_MISMATCH, "PLD_HASH_OK", "BL1_COPIED", "BL1_JUMP=")
    # The primary is refused before the usage-constraint and crypto checks; the backup is valid.
    extra_forbidden = ("MANIFEST_HASH_TIMEOUT", "CRYPTO_FAIL=", "RSA_VERIFY_FAIL",
                       "PLD_HASH_MISMATCH", fd.LC_MARKER, fd.CHIPLET_MARKER,
                       fd.PACKAGE_MARKER)

    def corrupt_primary(self, buf: bytearray) -> None:
        before = mm.manifest_hash(buf, "primary")
        computed = mm.tbs_hash(buf, mm.PRIMARY_MANIFEST_OFFSET)
        assert before == computed, (
            f"primary manifest_hash {before.hex()} already disagrees with "
            f"sha256(TBS) {computed.hex()}: the shipped image is not the valid "
            f"baseline this testcase mutates away from"
        )
        mm.corrupt_manifest_hash(buf, "primary")
        after = mm.manifest_hash(buf, "primary")
        assert after != before, "the manifest_hash write did not land"
        assert mm.tbs_hash(buf, mm.PRIMARY_MANIFEST_OFFSET) == computed, (
            "the TBS digest changed, so the mutation reached inside the signed "
            "region: the rejection would no longer be attributable to the stored "
            "hash alone"
        )
        self.logger.info(
            "CHK-STIMULUS-HASH: primary manifest_hash %s -> %s while sha256(TBS) "
            "stays %s, so the stored copy is the only defect",
            before.hex(), after.hex(), computed.hex(),
        )

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        slot_err = f"MANIFEST_ERR=0x{self.primary_expected_error:08x}"
        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)

        i_bad = fd.assert_slot_attributed(console, _HASH_MISMATCH, after=i_psrc,
                                          before=i_bsrc)
        fd.assert_slot_attributed(console, slot_err, after=i_bad - 1, before=i_bsrc)

        # A second OK would mean the primary also verified, i.e. the mutation never landed.
        n_ok = fd.count(console, _HASH_OK)
        assert n_ok == 1, (
            f"{_HASH_OK} appeared {n_ok} times, expected exactly 1 (the backup's). "
            f"Console: {console}"
        )
        i_ok = fd.first_index(console, _HASH_OK)
        assert i_bsrc < i_ok, (
            f"{_HASH_OK}@{i_ok} did not follow the backup read@{i_bsrc}: the one "
            f"hash that verified is not the backup's. Console: {console}"
        )
        self.logger.info(
            "CHK-MANIFEST-HASH: %s@%d and %s inside the primary attempt (read@%d, "
            "backup read@%d), and %s appears exactly once at %d -- the backup's",
            _HASH_MISMATCH, i_bad, slot_err, i_psrc, i_bsrc, _HASH_OK, i_ok,
        )
