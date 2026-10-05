# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD refuses a secure manifest whose signature bytes are all zero.

The enforced bit, public key and ``signature_size`` are left as shipped and only
the 512-byte signature field is zeroed. That field sits outside the signed
region, so the manifest hash still matches, the key is authorized, and the slot
reaches RSA-3072.

``0^e mod n`` is zero, so the modexp leaves the shared ``inout`` buffer as it
found it and ``rsa_3072_verify()`` (``rsa_verify.c``) refuses with
``RSA_INOUT_UNCHANGED`` rather than reaching the PKCS#1 check. Both slots fail
with ``OCA_FAIL_SIGNATURE``.

Needs ``+esrc_noise_force``: two RSA-3072 modexps run on OTBN, which waits on EDN
for entropy.
"""

from __future__ import annotations

import pyuvm
from env import sep_manifest_mutate as mm
from rom_fw.sep_backup_manifest_fail_base import MANIFEST_ERR_SIG_FAILED
from rom_fw.sep_firmware_cntl_secure_boot_flow_test import (
    _SBOOT_DIS_SET,
    sep_firmware_cntl_secure_boot_flow_test,
)

# Each must appear once per slot: the key was authorized and the modexp ran
# before the verifier refused the signature.
_PER_SLOT_MARKERS = ("PUBK_AUTHORIZED", "RSA_EXEC")


@pyuvm.test()
class sep_firmware_signature_zeroed_refuse_test(sep_firmware_cntl_secure_boot_flow_test):
    """PROD + secure manifest with an all-zero signature -> both slots refused."""

    backup_defect_marker = "RSA_INOUT_UNCHANGED"
    expected_error = MANIFEST_ERR_SIG_FAILED
    primary_expected_error = MANIFEST_ERR_SIG_FAILED
    extra_forbidden = (
        "RSA_EXEC_FAIL",
        "RSA_PKCS1_FAIL",
        "RSA_VERIFY_OK",
        "MANIFEST_OK",
        _SBOOT_DIS_SET,
    )

    def mutate_slot(self, buf: bytearray, slot: str) -> None:
        assert mm.secure_boot_control(buf, slot) & mm.SECURE_BOOT_ENFORCED_BIT, (
            f"{slot} manifest does not request secure boot"
        )
        size = mm.signature_size(buf, slot)
        assert size == 384, f"{slot} signature_size is {size}, expected 384 (RSA-3072)"
        mm.remove_signature(buf, slot, keep_size=True)
        assert mm.signature_size(buf, slot) == size
        mm.verify_layout(buf, slot)
        self.logger.info(
            "CHK-MUTATION: %s signature zeroed, signature_size kept at %d, %s",
            slot,
            size,
            mm.describe(buf, slot),
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)
        for marker in _PER_SLOT_MARKERS:
            hits = sum(1 for line in console if line.strip() == marker)
            assert hits == 2, (
                f"{marker} appeared {hits} time(s), expected 2 (one per slot): the "
                f"zeroed signature did not reach the verifier on both slots. "
                f"Console: {console}"
            )
        self.logger.info(
            "CHK-VERIFIER-RAN: %s once per slot before %s",
            " and ".join(_PER_SLOT_MARKERS),
            self.backup_defect_marker,
        )
