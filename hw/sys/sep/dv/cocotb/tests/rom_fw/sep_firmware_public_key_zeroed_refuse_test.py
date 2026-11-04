# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD refuses a secure manifest whose public key bytes are all zero.

The enforced bit, signature, key select and ``public_key_size`` are left as
shipped, and only the 532-byte public-key field is zeroed; the manifest hash is
recomputed. The slot passes the structural size check and reaches
``plat_is_key_authorized()`` (``oca_platform.c``), which resolves the selected
slot (``PUBK_SEL=``) and then refuses a modulus whose digest does not match that
slot's anchor with ``PUBK_UNAUTHORIZED``. Both slots fail with
``OCA_FAIL_ROOT_KEY_UNAUTHORIZED`` and the verifier never runs.
"""

from __future__ import annotations

import pyuvm
from env import sep_manifest_mutate as mm
from env.sep_secure_boot_cases import CASES
from rom_fw.sep_firmware_cntl_secure_boot_flow_test import (
    _SBOOT_DIS_SET,
    sep_firmware_cntl_secure_boot_flow_test,
)

_CASE = CASES["public_key_zeroed"]


@pyuvm.test()
class sep_firmware_public_key_zeroed_refuse_test(sep_firmware_cntl_secure_boot_flow_test):
    """PROD + secure manifest with an all-zero public key -> both slots refused."""

    backup_defect_marker = "PUBK_UNAUTHORIZED"
    expected_error = _CASE.boot_error
    primary_expected_error = _CASE.boot_error
    extra_forbidden = (
        "PUBK_AUTHORIZED",
        "RSA_EXEC",
        "RSA_VERIFY_OK",
        "MANIFEST_OK",
        _SBOOT_DIS_SET,
    )

    def mutate_slot(self, buf: bytearray, slot: str) -> None:
        size = mm.public_key_size(buf, slot)
        _CASE.mutate(buf, slot)
        assert not any(mm.public_key_modulus(buf, slot)), f"{slot} modulus not zeroed"
        assert mm.public_key_size(buf, slot) == size, f"{slot} public_key_size changed"
        mm.verify_layout(buf, slot)
        self.logger.info(
            "CHK-MUTATION: %s public key zeroed, public_key_size kept, %s",
            slot,
            mm.describe(buf, slot),
        )
