# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD refuses a manifest that asks for secure boot but carries no signature.

The enforced bit and the public key are left as shipped. The signature field and
``signature_size`` are zeroed, and the manifest hash is recomputed over the changed size field.
``oca_check_crypto_field_sizes()``
(``bootrom/prod/tools/tt-oca-manifest/validators/oca/lib/parser.c``) refuses a secure manifest
whose classical signature size is zero, so both slots fail with ``OCA_FAIL_CRYPTO_FIELD_SIZE``
before key selection.

``sep_firmware_signature_zeroed_refuse_test`` keeps the size and lets the zeroed signature reach
the verifier.
"""

from __future__ import annotations

import pyuvm
from env import sep_manifest_mutate as mm
from env.sep_secure_boot_cases import CASES
from rom_fw.sep_firmware_cntl_secure_boot_flow_test import (
    _SBOOT_DIS_SET,
    sep_firmware_cntl_secure_boot_flow_test,
)

_CASE = CASES["signature_absent"]


@pyuvm.test()
class sep_firmware_signature_absent_refuse_test(sep_firmware_cntl_secure_boot_flow_test):
    """PROD + secure manifest with signature and signature_size zeroed -> refused."""

    backup_defect_marker = f"MANIFEST_ERR=0x{_CASE.boot_error:08x}"
    expected_error = _CASE.boot_error
    primary_expected_error = _CASE.boot_error
    extra_forbidden = (
        "PUBK_SEL=",
        "RSA_EXEC",
        "RSA_VERIFY_OK",
        "MANIFEST_OK",
        _SBOOT_DIS_SET,
    )

    def mutate_slot(self, buf: bytearray, slot: str) -> None:
        before = mm.signature_size(buf, slot)
        _CASE.mutate(buf, slot)
        assert before and mm.signature_size(buf, slot) == 0
        mm.verify_layout(buf, slot)
        self.logger.info(
            "CHK-MUTATION: %s signature and signature_size (%d -> 0) zeroed, %s",
            slot,
            before,
            mm.describe(buf, slot),
        )
