# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD refuses a manifest that asks for secure boot but carries no signature (PyUVM).

The enforced bit and the public key are left as shipped. The signature field and
``signature_size`` are zeroed, and the manifest hash is recomputed over the
changed size field. ``oca_check_crypto_field_sizes()`` (``parser.c``) refuses a
secure manifest whose classical signature size is zero, so both slots fail with
``OCA_FAIL_CRYPTO_FIELD_SIZE`` before key selection.

``sep_firmware_signature_zeroed_refuse_test`` keeps the size and lets the zeroed
signature reach the verifier.
"""

from __future__ import annotations

import pyuvm
from env import sep_manifest_mutate as mm
from rom_fw.sep_backup_manifest_fail_base import MANIFEST_ERR_SIG_TYPE_INVALID
from rom_fw.sep_firmware_cntl_secure_boot_flow_test import (
    _SBOOT_DIS_SET,
    sep_firmware_cntl_secure_boot_flow_test,
)


@pyuvm.test()
class sep_firmware_signature_absent_refuse_test(sep_firmware_cntl_secure_boot_flow_test):
    """PROD + secure manifest with signature and signature_size zeroed -> refused."""

    backup_defect_marker = f"MANIFEST_ERR=0x{MANIFEST_ERR_SIG_TYPE_INVALID:08x}"
    expected_error = MANIFEST_ERR_SIG_TYPE_INVALID
    primary_expected_error = MANIFEST_ERR_SIG_TYPE_INVALID
    extra_forbidden = (
        "PUBK_SEL=",
        "RSA_EXEC",
        "RSA_VERIFY_OK",
        "MANIFEST_OK",
        _SBOOT_DIS_SET,
    )

    def mutate_slot(self, buf: bytearray, slot: str) -> None:
        assert mm.secure_boot_control(buf, slot) & mm.SECURE_BOOT_ENFORCED_BIT, (
            f"{slot} manifest does not request secure boot"
        )
        before = mm.signature_size(buf, slot)
        assert before, f"{slot} signature_size is already zero"
        mm.remove_signature(buf, slot, keep_size=False)
        assert mm.signature_size(buf, slot) == 0
        mm.verify_layout(buf, slot)
        self.logger.info(
            "CHK-MUTATION: %s signature and signature_size (%d -> 0) zeroed, %s",
            slot,
            before,
            mm.describe(buf, slot),
        )
