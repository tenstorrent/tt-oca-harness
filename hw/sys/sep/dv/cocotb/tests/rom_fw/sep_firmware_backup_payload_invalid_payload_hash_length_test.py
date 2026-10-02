# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup declares ``payload_hashed_length`` = 0; the ROM halts.

The field is signed, so the slot is re-signed and passes the manifest stage; the payload stage
then refuses it with ``OCA_FAIL_PAYLOAD_TOC``. The primary fails with ``OCA_FAIL_MAGIC``.
"""

from __future__ import annotations

import struct

import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_toc_defect as td
from rom_fw.sep_backup_payload_fail_base import (
    err_marker,
    sep_backup_payload_fail_base,
)

_MANIFEST_ERR_PAYLOAD_TOC = mm.boot_err("OCA_FAIL_PAYLOAD_TOC")

_BAD_HASHED_LEN = 0


@pyuvm.test()
class sep_firmware_backup_payload_invalid_payload_hash_length_test(sep_backup_payload_fail_base):
    """Backup payload_hashed_length is 0 -> both slots refused -> the ROM halts."""

    backup_defect_marker = err_marker(_MANIFEST_ERR_PAYLOAD_TOC)
    expected_error = _MANIFEST_ERR_PAYLOAD_TOC
    backup_expected_stage = "payload"
    backup_absent = ("DECRYPT_OK",)
    efuse_preload = td.PLAINTEXT_EFUSE

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def corrupt_backup(self, buf: bytearray) -> None:
        assert not pm.is_encrypted(buf, "backup"), (
            "backup payload is encrypted: payload_hashed_length is then the "
            "ciphertext length and a zero value takes a different arm"
        )
        golden = bytes(buf)
        p_len = pm.manifest_payload_length(buf, "backup")
        was = pm.set_payload_hashed_length(buf, "backup", _BAD_HASHED_LEN)
        now = pm.payload_hashed_length(buf, "backup")
        assert now == _BAD_HASHED_LEN, (
            f"backup payload_hashed_length is {now} after the write, expected "
            f"{_BAD_HASHED_LEN}; the mutation did not land"
        )
        rules = pm.spec_rule_violations(buf, "backup")
        assert rules == ["hashed_length"], (
            f"backup breaks {rules}, expected only ['hashed_length']: the zero hashed "
            f"length is not the slot's only payload defect"
        )
        changed = pm.plaintext_diff(golden, bytes(buf), "backup")
        assert changed == [], f"backup cleartext payload changed at {changed}"
        mm.verify_layout(buf, "backup")
        pm.verify_signing_key(buf, "backup")
        mm.verify_public_key(buf, "backup")
        self.logger.info(
            "CHK-STIMULUS-HASHED-LEN: backup payload_hashed_length %d -> %d against "
            "payload_length %d, slot re-signed; spec rules broken: %s",
            was,
            now,
            p_len,
            rules,
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)
        fd.assert_served_field(
            self.logger,
            self._flash,
            "backup",
            pm.OFF_PAYLOAD_HASHED_LENGTH,
            struct.pack("<Q", _BAD_HASHED_LEN),
            "backup payload_hashed_length",
        )
