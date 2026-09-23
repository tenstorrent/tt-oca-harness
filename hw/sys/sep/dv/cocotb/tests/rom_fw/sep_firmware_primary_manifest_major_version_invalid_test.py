# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest declares an unsupported major version; the backup boots.

Only the primary's major version is wrong (2), so the ROM refuses it with BAD_VERSION.
Needs ``+sep_crypto_edn_force``: the recovering backup runs a full RSA-3072 modexp on OTBN.
"""

from __future__ import annotations

import struct
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

# Must match MANIFEST_ERR_* in manifest.h.
_MANIFEST_ERR_BAD_MAGIC = 0x0003_0002
_MANIFEST_ERR_BAD_VERSION = 0x0003_0003
_MANIFEST_ERR_BAD_LENGTH = 0x0003_0004

_BAD_MAJOR_VERSION = 2

_VERSION_LENGTH_OFF = mm.OFF_VERSION_MAJOR


@pyuvm.test()
class sep_firmware_primary_manifest_major_version_invalid_test(
        sep_primary_fail_backup_boot_base):
    """Primary major version is not 1 -> refused -> the backup boots."""

    # BAD_VERSION prints no per-reason token; check_transport() attributes it instead.
    primary_defect_marker = ""
    primary_expected_error = _MANIFEST_ERR_BAD_VERSION
    primary_expected_rsa_starts = 0
    primary_expected_sig_valids = 0
    efuse_preload = _EFUSE_PRELOAD
    extra_required = ("MANIFEST_HASH_OK", "PLD_HASH_OK", "BL1_COPIED", "BL1_JUMP=")
    extra_forbidden = (f"MANIFEST_ERR=0x{_MANIFEST_ERR_BAD_MAGIC:08x}",
                       f"MANIFEST_ERR=0x{_MANIFEST_ERR_BAD_LENGTH:08x}",
                       "MANIFEST_HASH_MISMATCH", "CRYPTO_FAIL=", "RSA_VERIFY_FAIL",
                       "PLD_HASH_MISMATCH", "MANIFEST_ALL_FAILED",
                       "IMAGE_HASH_MISMATCH", "NO_BL1_IMAGE",
                       "PAYLOAD_OFF_ALIGN", "PAYLOAD_OFF_RANGE",
                       "PAYLOAD_HASHED_LEN_BAD=", "PAYLOAD_LEN_RANGE",
                       "PAYLOAD_OVERLAPS_MANIFEST", "TOC_PLEN_MISMATCH=",
                       "ENC_HASHED_LEN_PARTIAL",
                       fd.LC_MARKER, fd.CHIPLET_MARKER, fd.PACKAGE_MARKER)

    def corrupt_primary(self, buf: bytearray) -> None:
        before = mm.manifest_version(buf, "primary")
        assert before == (mm.MANIFEST_MAJOR_VERSION, 0), (
            f"primary manifest version is {before[0]}.{before[1]}, expected "
            f"{mm.MANIFEST_MAJOR_VERSION}.0: the shipped image is not the valid "
            f"baseline this testcase mutates away from"
        )
        assert bytes(buf[mm.PRIMARY_MANIFEST_OFFSET:
                         mm.PRIMARY_MANIFEST_OFFSET + 4]) == mm.MANIFEST_MAGIC, (
            "primary manifest_identifier is not TBL1, so BAD_MAGIC would pre-empt "
            "the version check and the asserted code would be wrong"
        )
        mm.set_manifest_version(buf, "primary", major=_BAD_MAJOR_VERSION)
        after = mm.manifest_version(buf, "primary")
        assert after == (_BAD_MAJOR_VERSION, 0), (
            f"primary manifest version is {after[0]}.{after[1]} after the write, "
            f"expected {_BAD_MAJOR_VERSION}.0; the mutation did not land"
        )
        length = mm.manifest_length(buf, "primary")
        assert length == mm.MANIFEST_SIZE, (
            f"primary manifest_length is {length}, expected {mm.MANIFEST_SIZE}: the "
            f"slot would be refused with BAD_LENGTH instead of BAD_VERSION"
        )
        self.logger.info(
            "CHK-STIMULUS-VERSION: primary manifest_version_major %d -> %d, with "
            "minor 0, length %d (== sizeof(manifest_t)) and identifier TBL1 all "
            "left VALID, so the major version is the only field "
            "validate_manifest_header can refuse this slot on",
            before[0], after[0], length,
        )

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        slot_err = f"MANIFEST_ERR=0x{self.primary_expected_error:08x}"
        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)

        i_err = fd.assert_slot_attributed(console, slot_err, after=i_psrc,
                                          before=i_bsrc)

        n_ok = fd.count(console, "MANIFEST_HASH_OK")
        assert n_ok == 1, (
            f"MANIFEST_HASH_OK appeared {n_ok} times, expected exactly 1 (the "
            f"backup's). A second occurrence would mean the primary passed "
            f"validate_manifest_header, so its major version was accepted. "
            f"Console: {console}"
        )
        i_hash = fd.first_index(console, "MANIFEST_HASH_OK")
        assert i_bsrc < i_hash, (
            f"MANIFEST_HASH_OK@{i_hash} did not follow the backup read@{i_bsrc}: "
            f"the one hash that verified is not the backup's. Console: {console}"
        )

        fd.assert_served_field(
            self.logger, flash, "primary", _VERSION_LENGTH_OFF,
            struct.pack("<HHI", _BAD_MAJOR_VERSION, 0, mm.MANIFEST_SIZE),
            "primary manifest_version_major/minor + manifest_length",
        )
        self.logger.info(
            "CHK-VERSION-RULE: primary@%d declared v%d.0 with manifest_length %d and "
            "was refused %s@%d before its hash was computed; the backup declared "
            "v%d.0 with the same length, was accepted with the only "
            "MANIFEST_HASH_OK@%d, and booted. One field differs between the two "
            "slots, so the major-version rule is demonstrated in both directions",
            i_psrc, _BAD_MAJOR_VERSION, mm.MANIFEST_SIZE, slot_err, i_err,
            mm.MANIFEST_MAJOR_VERSION, i_hash,
        )
