# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary declares ``payload_hashed_length`` = 0; the backup boots.

A zero hashed length would skip the payload digest, so the ROM must refuse it with
``PAYLOAD_HASHED_LEN_BAD=`` and ``MANIFEST_ERR_BAD_LENGTH``, then fail over.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
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

_MANIFEST_ERR_BAD_MAGIC = mm.boot_err("OCA_FAIL_MAGIC")
_MANIFEST_ERR_BAD_VERSION = mm.boot_err("OCA_FAIL_FORMAT_VERSION_MISMATCH")
_MANIFEST_ERR_BAD_LENGTH = mm.boot_err("OCA_FAIL_MANIFEST_LENGTH")

_BAD_HASHED_LEN = 0


@pyuvm.test()
class sep_firmware_primary_payload_invalid_payload_hash_length_test(
    sep_primary_fail_backup_boot_base
):
    """Primary payload_hashed_length is 0 -> refused -> the backup boots."""

    # Left empty: a declared marker also makes the base require CRYPTO_FAIL=.
    primary_defect_marker = ""
    primary_expected_error = _MANIFEST_ERR_BAD_LENGTH
    primary_expected_rsa_starts = 0
    primary_expected_sig_valids = 0
    efuse_preload = _EFUSE_PRELOAD
    extra_required = ("MANIFEST_HASH_OK", "PLD_HASH_OK", "BL1_COPIED", "BL1_JUMP=")
    extra_forbidden = (
        f"MANIFEST_ERR=0x{_MANIFEST_ERR_BAD_MAGIC:08x}",
        f"MANIFEST_ERR=0x{_MANIFEST_ERR_BAD_VERSION:08x}",
        "MANIFEST_HASH_MISMATCH",
        "CRYPTO_FAIL=",
        "RSA_VERIFY_FAIL",
        "PLD_HASH_MISMATCH",
        "MANIFEST_ALL_FAILED",
        "IMAGE_HASH_MISMATCH",
        "NO_BL1_IMAGE",
        "PAYLOAD_OFF_ALIGN",
        "PAYLOAD_OFF_RANGE",
        "PAYLOAD_LEN_RANGE",
        "PAYLOAD_OVERLAPS_MANIFEST",
        "TOC_PLEN_MISMATCH=",
        "PAYLOAD_LOC_OVERFLOW",
        "ENC_HASHED_LEN_PARTIAL",
        fd.LC_MARKER,
        fd.CHIPLET_MARKER,
        fd.PACKAGE_MARKER,
    )

    def corrupt_primary(self, buf: bytearray) -> None:
        assert not pm.is_encrypted(buf, "primary"), (
            "primary payload is encrypted, so ENC_HASHED_LEN_PARTIAL could produce "
            "this run's verdict instead of the bound under test"
        )
        # An earlier header check would otherwise refuse the slot before this bound.
        major, minor = mm.manifest_version(buf, "primary")
        length = mm.manifest_length(buf, "primary")
        assert (major, minor) == (mm.MANIFEST_MAJOR_VERSION, 0), (
            f"primary manifest version is {major}.{minor}: BAD_VERSION or the "
            f"exact-match length rule would pre-empt the payload_hashed_length bound"
        )
        assert length == mm.MANIFEST_SIZE, (
            f"primary manifest_length is {length}, expected {mm.MANIFEST_SIZE}: the "
            f"slot would be refused with BAD_LENGTH by the version-and-length rule "
            f"instead of by the payload_hashed_length bound"
        )
        assert (
            bytes(buf[mm.PRIMARY_MANIFEST_OFFSET : mm.PRIMARY_MANIFEST_OFFSET + 4])
            == mm.MANIFEST_MAGIC
        ), (
            "primary manifest_identifier is not OCAC, so BAD_MAGIC would pre-empt "
            "the payload_hashed_length bound"
        )

        p_len = pm.manifest_payload_length(buf, "primary")
        self._bad_hashed_len = _BAD_HASHED_LEN
        self._payload_len = p_len
        assert not 0 < self._bad_hashed_len <= p_len, (
            f"the declared hashed length {self._bad_hashed_len} satisfies "
            f"0 < value <= payload_length ({p_len}), so validate_manifest_header "
            f"would ACCEPT it and the slot would be refused later as "
            f"PLD_HASH_MISMATCH -- a different check with a different error code"
        )
        was = pm.set_payload_hashed_length(buf, "primary", self._bad_hashed_len)
        now = pm.payload_hashed_length(buf, "primary")
        assert now == self._bad_hashed_len, (
            f"primary payload_hashed_length is {now} after the write, expected "
            f"{self._bad_hashed_len}; the mutation did not land"
        )
        self.logger.info(
            "CHK-STIMULUS-HASHED-LEN: primary payload_hashed_length %d -> %d against "
            "payload_length %d -- zero, so the ROM would compute no payload digest "
            "at all. manifest_identifier OCAC, version %d.%d and manifest_length "
            "%d are all left VALID, so the payload_hashed_length bound is the only "
            "rule validate_manifest_header can refuse this slot on. The payload is "
            "not encrypted, so ENC_HASHED_LEN_PARTIAL is unreachable",
            was,
            now,
            p_len,
            major,
            minor,
            length,
        )

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        slot_err = f"MANIFEST_ERR=0x{self.primary_expected_error:08x}"
        token = "PAYLOAD_HASHED_LEN_BAD="
        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)

        i_err = fd.assert_slot_attributed(console, slot_err, after=i_psrc, before=i_bsrc)

        i_tok = fd.assert_slot_attributed(console, token, after=i_psrc, before=i_bsrc)

        echoed = fd.hex_value(console, token)
        assert echoed is not None, (
            f"ROM printed {token} without a readable 32-bit value, so the echoed "
            f"payload_hashed_length cannot be compared with the planted one. "
            f"Console: {console}"
        )
        assert echoed == self._bad_hashed_len, (
            f"{token}0x{echoed:08x} ({echoed}) but this testcase planted "
            f"{self._bad_hashed_len}: the ROM refused a value nobody chose, so the "
            f"verdict is not attributable to this stimulus"
        )

        n_ok = fd.count(console, "MANIFEST_HASH_OK")
        assert n_ok == 1, (
            f"MANIFEST_HASH_OK appeared {n_ok} times, expected exactly 1 (the "
            f"backup's). A second occurrence would mean the primary passed "
            f"validate_manifest_header, so its payload_hashed_length was accepted. "
            f"Console: {console}"
        )
        i_hash = fd.first_index(console, "MANIFEST_HASH_OK")
        assert i_bsrc < i_hash, (
            f"MANIFEST_HASH_OK@{i_hash} did not follow the backup read@{i_bsrc}: "
            f"the one hash that verified is not the backup's. Console: {console}"
        )

        fd.assert_served_field(
            self.logger,
            flash,
            "primary",
            pm.OFF_PAYLOAD_HASHED_LEN,
            struct.pack("<Q", self._bad_hashed_len),
            "primary payload_hashed_length",
        )
        self.logger.info(
            "CHK-HASHED-LEN-RULE: primary@%d declared payload_hashed_length %d "
            "against payload_length %d and was refused %s0x%08x@%d then %s@%d, both "
            "inside its own attempt and before its hash was computed; the untouched "
            "backup was accepted with the only MANIFEST_HASH_OK@%d and booted",
            i_psrc,
            self._bad_hashed_len,
            self._payload_len,
            token,
            echoed,
            i_tok,
            slot_err,
            i_err,
            i_hash,
        )
