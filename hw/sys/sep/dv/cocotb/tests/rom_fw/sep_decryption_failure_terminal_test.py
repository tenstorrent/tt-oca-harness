# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A payload whose ciphertext is corrupted in both slots must end the boot.

Each slot decrypts cleanly and is refused with ``OCA_FAIL_PAYLOAD_TOC``. AES engine fault
status is not covered: producing it would need a forced RTL status bit.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw.sep_backup_payload_fail_base import (
    DECRYPT_FAILURE_MARKERS,
    err_marker,
    sep_backup_payload_fail_base,
)

_SEP_ROOT = Path(__file__).resolve().parents[4]
_ENCRYPTED_IMAGE = str(_SEP_ROOT / "bootrom" / "prod" / "build" / "oca_encrypted_boot.bin")
_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod_class_key.toml"
)

_ERR_PAYLOAD_TOC = mm.boot_err("OCA_FAIL_PAYLOAD_TOC")
_DECRYPT_OK = "DECRYPT_OK"
# Every decrypt outcome other than DECRYPT_OK.


@pyuvm.test()
class sep_decryption_failure_terminal_test(sep_backup_payload_fail_base):
    """Corrupt BOTH slots' ciphertext; each decrypts, is refused, and the boot ends."""

    flash_image = _ENCRYPTED_IMAGE
    efuse_preload = _EFUSE_PRELOAD
    primary_expected_error = _ERR_PAYLOAD_TOC
    primary_expected_rsa_starts = 1
    primary_expected_rsa_oks = 1
    primary_expected_stage = "payload"
    primary_ordered = (_DECRYPT_OK,)
    primary_absent = DECRYPT_FAILURE_MARKERS
    expected_error = _ERR_PAYLOAD_TOC
    backup_defect_marker = err_marker(_ERR_PAYLOAD_TOC)
    backup_expected_stage = "payload"
    backup_ordered = (_DECRYPT_OK,)
    backup_absent = DECRYPT_FAILURE_MARKERS
    # A signature refusal the stimulus did not plant, and BL1 copy progress past the rejection.
    extra_forbidden = ("RSA_PKCS1_FAIL", "COPY_DST=")

    # --- stimulus ------------------------------------------------------------
    def _corrupt(self, buf: bytearray, slot: str) -> None:
        base = pm.payload_base(buf, slot)
        before = bytes(buf[base : base + 16])
        at = pm.corrupt_ciphertext(buf, slot)
        after = bytes(buf[base : base + 16])
        assert before != after, f"the {slot} ciphertext flip did not change the image"
        self.logger.info(
            "CHK-STIMULUS-CIPHERTEXT: %s payload flash byte 0x%x -> 0x%02x; CBC block 0 "
            "%s -> %s; manifest re-hashed and re-signed",
            slot,
            at,
            buf[at],
            before.hex(),
            after.hex(),
        )

    def corrupt_primary(self, buf: bytearray) -> None:
        self._corrupt(buf, "primary")

    def corrupt_backup(self, buf: bytearray) -> None:
        self._corrupt(buf, "backup")
