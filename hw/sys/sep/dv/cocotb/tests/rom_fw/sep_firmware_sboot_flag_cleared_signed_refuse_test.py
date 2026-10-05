# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD refuses a signed manifest whose secure-boot enable flag is cleared.

Only the enforced bit of ``secure_boot_control`` is cleared; the signature, public key and key
select stay in place and the manifest hash is recomputed. A manifest that declares itself
non-secure must carry no signing material, so ``oca_check_secure_boot_invariant()``
(``bootrom/prod/tools/tt-oca-manifest/validators/oca/lib/parser.c``) refuses both slots with
``OCA_FAIL_SECURE_BOOT_INVARIANT`` before secure boot is determined.

The refusal is structural and holds in any lifecycle state. It runs under PROD because the
question is whether a production image can shed its enable flag and still be considered: it
cannot, and the slot never reaches key selection or the verifier.
``sep_firmware_cntl_secure_boot_flow_test`` is the companion case, where the signing material is
removed as well.
"""

from __future__ import annotations

import pyuvm
from env import sep_manifest_mutate as mm
from rom_fw.sep_firmware_cntl_secure_boot_flow_test import (
    _SBOOT_DIS_SET,
    sep_firmware_cntl_secure_boot_flow_test,
)

MANIFEST_ERR_SECURE_BOOT_INVARIANT = mm.boot_err("OCA_FAIL_SECURE_BOOT_INVARIANT")


@pyuvm.test()
class sep_firmware_sboot_flag_cleared_signed_refuse_test(sep_firmware_cntl_secure_boot_flow_test):
    """PROD + enforced bit cleared on a signed manifest -> both slots refused."""

    # The invariant prints no token of its own, so the error code is the marker.
    backup_defect_marker = f"MANIFEST_ERR=0x{MANIFEST_ERR_SECURE_BOOT_INVARIANT:08x}"
    expected_error = MANIFEST_ERR_SECURE_BOOT_INVARIANT
    primary_expected_error = MANIFEST_ERR_SECURE_BOOT_INVARIANT
    extra_forbidden = (
        "PUBK_SEL=",
        "RSA_EXEC",
        "RSA_VERIFY_OK",
        "MANIFEST_OK",
        _SBOOT_DIS_SET,
    )

    def mutate_slot(self, buf: bytearray, slot: str) -> None:
        before = mm.secure_boot_control(buf, slot)
        assert before & mm.SECURE_BOOT_ENFORCED_BIT, (
            f"{slot} manifest already has secure_boot=0 (secure_boot_control=0x{before:02x})"
        )
        assert mm.signature_type(buf, slot) != mm.SIG_TYPE_NO_SIGNATURE, (
            f"{slot} carries no signature, so the invariant has nothing to refuse"
        )
        after = mm.set_secure_boot_enforced(buf, slot, False)
        mm.verify_layout(buf, slot)
        self.logger.info(
            "CHK-MUTATION: %s secure_boot_control 0x%02x -> 0x%02x, signing fields kept, %s",
            slot,
            before,
            after,
            mm.describe(buf, slot),
        )
