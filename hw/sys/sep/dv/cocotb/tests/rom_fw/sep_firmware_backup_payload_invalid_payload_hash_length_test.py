# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup declares ``payload_hashed_length`` = 0; the ROM halts.

A zero hashed length would skip the payload hash, so the ROM must refuse it with
``PAYLOAD_HASHED_LEN_BAD=0x00000000``; the primary is refused as BAD_MAGIC.
"""

from __future__ import annotations

import struct

import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_backup_manifest_structural_fail_base import (
    sep_backup_manifest_structural_fail_base,
)
from rom_fw.sep_usage_constraint_base import EFUSE_PRELOAD

_MANIFEST_ERR_BAD_MAGIC = mm.boot_err("OCA_FAIL_MAGIC")
_MANIFEST_ERR_BAD_LENGTH = mm.boot_err("OCA_FAIL_MANIFEST_LENGTH")

_TOKEN = "PAYLOAD_HASHED_LEN_BAD="

_BAD_HASHED_LEN = 0


@pyuvm.test()
class sep_firmware_backup_payload_invalid_payload_hash_length_test(
    sep_backup_manifest_structural_fail_base
):
    """Backup payload_hashed_length is 0 -> both slots refused -> the ROM halts."""

    # Prefix only: the echoed value is asserted in _check().
    backup_defect_marker = _TOKEN
    expected_error = _MANIFEST_ERR_BAD_LENGTH
    primary_expected_error = _MANIFEST_ERR_BAD_MAGIC
    efuse_preload = EFUSE_PRELOAD
    extra_forbidden = (
        fd.LC_MARKER,
        fd.CHIPLET_MARKER,
        fd.PACKAGE_MARKER,
        "MANIFEST_HASH_MISMATCH",
        "MANIFEST_HASH_OK",
        "CRYPTO_FAIL=",
        "PAYLOAD_OFF_RANGE",
        "PAYLOAD_OFF_ALIGN",
        "ENC_HASHED_LEN_PARTIAL",
        "PAYLOAD_LEN_RANGE",
        "PAYLOAD_OVERLAPS_MANIFEST",
        "TOC_PLEN_MISMATCH=",
        "PAYLOAD_LOC_OVERFLOW",
        "NO_BL1_IMAGE",
    )

    def corrupt_backup(self, buf: bytearray) -> None:
        assert not pm.is_encrypted(buf, "backup"), (
            "backup payload is encrypted, so ENC_HASHED_LEN_PARTIAL could produce "
            "this run's verdict instead of the bound under test"
        )
        major, minor = mm.manifest_version(buf, "backup")
        length = mm.manifest_length(buf, "backup")
        assert (major, minor) == (mm.MANIFEST_MAJOR_VERSION, 0), (
            f"backup manifest version is {major}.{minor}: BAD_VERSION or the "
            f"exact-match length rule would pre-empt the payload_hashed_length bound"
        )
        assert length == mm.MANIFEST_SIZE, (
            f"backup manifest_length is {length}, expected {mm.MANIFEST_SIZE}: the "
            f"slot would be refused with BAD_LENGTH by the version-and-length rule "
            f"instead of by the payload_hashed_length bound"
        )
        assert (
            bytes(buf[mm.BACKUP_MANIFEST_OFFSET : mm.BACKUP_MANIFEST_OFFSET + 4])
            == mm.MANIFEST_MAGIC
        ), (
            "backup manifest_identifier is not OCAC, so BAD_MAGIC would pre-empt "
            "the payload_hashed_length bound -- and it is also the primary's "
            "verdict, which must stay distinct from the backup's"
        )

        p_len = pm.manifest_payload_length(buf, "backup")
        self._bad_hashed_len = _BAD_HASHED_LEN
        self._payload_len = p_len
        assert not 0 < self._bad_hashed_len <= p_len, (
            f"the declared hashed length {self._bad_hashed_len} satisfies "
            f"0 < value <= payload_length ({p_len}), so validate_manifest_header "
            f"would ACCEPT it and the slot would be refused later as "
            f"PLD_HASH_MISMATCH -- a different check with a different error code"
        )
        # The signature stays stale: the ROM refuses this bound before it verifies the signature.
        was = pm.set_payload_hashed_length(buf, "backup", self._bad_hashed_len)
        now = pm.payload_hashed_length(buf, "backup")
        assert now == self._bad_hashed_len, (
            f"backup payload_hashed_length is {now} after the write, expected "
            f"{self._bad_hashed_len}; the mutation did not land"
        )
        self.logger.info(
            "CHK-STIMULUS-HASHED-LEN: backup payload_hashed_length %d -> %d against "
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

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)

        echoed = fd.hex_value(console, _TOKEN)
        assert echoed is not None, (
            f"ROM printed {_TOKEN} without a readable 32-bit value, so the echoed "
            f"payload_hashed_length cannot be compared with the planted one. "
            f"Console: {console}"
        )
        assert echoed == self._bad_hashed_len, (
            f"{_TOKEN}0x{echoed:08x} ({echoed}) but this testcase planted "
            f"{self._bad_hashed_len}: the ROM refused a value nobody chose, so the "
            f"verdict is not attributable to this stimulus"
        )

        fd.assert_served_field(
            self.logger,
            self._flash,
            "backup",
            pm.OFF_PAYLOAD_HASHED_LEN,
            struct.pack("<Q", self._bad_hashed_len),
            "backup payload_hashed_length",
        )
        self.logger.info(
            "CHK-HASHED-LEN-RULE: backup declared payload_hashed_length %d against "
            "payload_length %d and was refused with %s0x%08x plus "
            "MANIFEST_ERR=0x%08x inside its own attempt; the bound names itself on "
            "the console, so this row needs no stimulus-side discriminator to be "
            "separable from the other BAD_LENGTH arms",
            self._bad_hashed_len,
            self._payload_len,
            _TOKEN,
            echoed,
            _MANIFEST_ERR_BAD_LENGTH,
        )
