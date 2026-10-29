# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD refuses an unsigned manifest that still names a signature class.

``sep_firmware_cntl_secure_boot_flow_test`` clears ``secure_boot_control`` to
``0x00``, so the lifecycle's enforcement finds no class to verify with and the
determination refuses both slots with ``OCA_FAIL_SIGNATURE_CLASS_CONTROL``. This
member keeps the classical class bit and clears only the enforced bit
(``secure_boot_control = 0x02``), with the signature, public key, key select and
type/encoding bytes zeroed as the invariant requires.

So the determination settles, PROD puts secure boot in force, and the slot reaches
key authorization carrying no key. ``plat_is_key_authorized()``
(``oca_platform.c``) refuses a key whose signature type is none with
``PUBK_NO_SIGNATURE``, ahead of key selection, and the slot fails with
``OCA_FAIL_ROOT_KEY_UNAUTHORIZED``. That marker is the ROM's own refusal, which
the validator unit tests cannot reach because they do not link the ROM's
platform callbacks.
"""

from __future__ import annotations

import pyuvm
from env import sep_manifest_mutate as mm
from env.sep_secure_boot_cases import CASES
from rom_fw.sep_firmware_cntl_secure_boot_flow_test import (
    _SBOOT_DIS_SET,
    sep_firmware_cntl_secure_boot_flow_test,
)

_CASE = CASES["class_only"]


@pyuvm.test()
class sep_firmware_sboot_class_only_refuse_test(sep_firmware_cntl_secure_boot_flow_test):
    """PROD + secure_boot_control=0x02 + no key or signature -> both slots refused."""

    backup_defect_marker = "PUBK_NO_SIGNATURE"
    expected_error = _CASE.boot_error
    primary_expected_error = _CASE.boot_error
    # PUBK_SEL= would mean a key slot was resolved, i.e. the refusal came from
    # somewhere past the no-signature check.
    extra_forbidden = (
        "PUBK_SEL=",
        "PUBK_AUTHORIZED",
        "RSA_EXEC",
        "RSA_VERIFY_OK",
        "MANIFEST_OK",
        _SBOOT_DIS_SET,
    )

    def mutate_slot(self, buf: bytearray, slot: str) -> None:
        before = mm.secure_boot_control(buf, slot)
        _CASE.mutate(buf, slot)
        after = mm.secure_boot_control(buf, slot)
        assert after == mm.SECURE_BOOT_CLASSIC_BIT, f"{slot} secure_boot_control is 0x{after:02x}"
        assert mm.signature_type(buf, slot) == mm.SIG_TYPE_NO_SIGNATURE, (
            f"{slot} signature_type is {mm.signature_type(buf, slot)}: the invariant "
            f"would refuse the slot before key authorization"
        )
        mm.verify_layout(buf, slot)
        self.logger.info(
            "CHK-MUTATION: %s secure_boot_control 0x%02x -> 0x%02x, crypto fields zeroed, %s",
            slot,
            before,
            after,
            mm.describe(buf, slot),
        )
