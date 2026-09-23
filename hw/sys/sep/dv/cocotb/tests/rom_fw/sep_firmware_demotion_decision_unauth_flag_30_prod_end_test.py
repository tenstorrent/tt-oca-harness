# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD_END with ``skip_SHA256`` requested -> not demoted, both registers locked.

The ROM honours ``skip_SHA256`` only in TEST_DEV, so the payload hash still runs here.
Needs ``+sep_crypto_edn_force``: PROD_END enforces secure boot.
"""

from __future__ import annotations

import pyuvm

from env import sep_manifest_mutate as mm
from rom_fw.sep_demotion_prod_end_base import sep_demotion_prod_end_base

_EXPECTED_FLAG_ARGS = (1 << mm.FLAG_ARGS_BIT_SECURE_BOOT) | (1 << mm.FLAG_ARGS_BIT_SKIP_SHA256)

_MEAS_LOCK_ONLY = "MEAS_DEMOTE=0x00000002"


@pyuvm.test()
class sep_firmware_demotion_decision_unauth_flag_30_prod_end_test(
        sep_demotion_prod_end_base):
    """PROD_END with skip_SHA256 set: not demoted, both registers locked."""

    required_markers = sep_demotion_prod_end_base.required_markers + (
        _MEAS_LOCK_ONLY, "PLD_HASH_OK", "MANIFEST_HASH_OK",
    )
    forbidden_markers = sep_demotion_prod_end_base.forbidden_markers + (
        "PLD_HASH_FAIL=", "MANIFEST_HASH_MISMATCH",
    )

    _SEL = 0
    _AUTH = 0
    _BL2 = 0

    def mutate_manifest(self, buf: bytearray) -> None:
        # flag_args is outside the TBS, so writing it after the base's re-seal is safe.
        super().mutate_manifest(buf)
        before = mm.get_flag_args(buf, "primary")
        mm.set_flag_args_bit(buf, "primary", mm.FLAG_ARGS_BIT_SKIP_SHA256, True)
        after = mm.get_flag_args(buf, "primary")
        assert after == before | (1 << mm.FLAG_ARGS_BIT_SKIP_SHA256), (
            f"primary flag_args is 0x{after:08x} after the write, expected "
            f"0x{before | (1 << mm.FLAG_ARGS_BIT_SKIP_SHA256):08x}; the mutation did "
            f"not land"
        )
        self.logger.info(
            "CHK-STIMULUS-SKIP-SHA256: primary flag_args 0x%08x -> 0x%08x (bit %d "
            "set). No ROM code reads this bit, so the only "
            "channels that can see it are the packed image and the bytes the flash "
            "device serves", before, after, mm.FLAG_ARGS_BIT_SKIP_SHA256,
        )

    def check_manifest_stimulus(self, buf: bytearray) -> None:
        super().check_manifest_stimulus(buf)
        fa = mm.get_flag_args(buf, "primary")
        assert fa == _EXPECTED_FLAG_ARGS, (
            f"primary flag_args is 0x{fa:08x}, expected 0x{_EXPECTED_FLAG_ARGS:08x} "
            f"(secure_boot bit {mm.FLAG_ARGS_BIT_SECURE_BOOT} plus skip_SHA256 bit "
            f"{mm.FLAG_ARGS_BIT_SKIP_SHA256}). This word is the ONLY thing that "
            f"distinguishes this run from sep_firmware_demotion_decision_no_flag_"
            f"prod_end_test, because no ROM code reads bit "
            f"{mm.FLAG_ARGS_BIT_SKIP_SHA256}"
        )
