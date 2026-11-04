# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD refuses a manifest that asks for secure boot but carries no public key.

The enforced bit and the signature are left as shipped. The public-key field and
``public_key_size`` are zeroed, and the manifest hash is recomputed.
``oca_check_crypto_field_sizes()``
(``bootrom/prod/tools/tt-oca-manifest/validators/oca/lib/parser.c``) refuses a secure manifest
whose classical key size is zero, so both slots fail with ``OCA_FAIL_CRYPTO_FIELD_SIZE`` before
key selection.

``sep_firmware_public_key_zeroed_refuse_test`` keeps the size and lets the zeroed key reach key
authorization.
"""

from __future__ import annotations

import pyuvm
from env import sep_manifest_mutate as mm
from env.sep_secure_boot_cases import CASES
from rom_fw.sep_firmware_cntl_secure_boot_flow_test import (
    _SBOOT_DIS_SET,
    sep_firmware_cntl_secure_boot_flow_test,
)

_CASE = CASES["public_key_absent"]


@pyuvm.test()
class sep_firmware_public_key_absent_refuse_test(sep_firmware_cntl_secure_boot_flow_test):
    """PROD + secure manifest with public key and public_key_size zeroed -> refused."""

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
        _CASE.mutate(buf, slot)
        assert not any(mm.public_key_modulus(buf, slot)), f"{slot} modulus not zeroed"
        assert mm.public_key_size(buf, slot) == 0, f"{slot} public_key_size not zeroed"
        mm.verify_layout(buf, slot)
        self.logger.info(
            "CHK-MUTATION: %s public key and public_key_size zeroed, %s",
            slot,
            mm.describe(buf, slot),
        )
