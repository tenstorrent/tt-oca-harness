# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Enforced secure boot under the PROD lifecycle (PyUVM).

A signed image authenticating and booting under PROD: full RSA-3072 chain, then
handoff to BL1.

WHAT THIS DOES NOT ESTABLISH -- read before extending. It does not exercise a
distinct "enforce arm". In ``secure_boot_enabled()``
(``manifest_load.c:233-239``) the lifecycle is consulted only inside
``if (!mfst_flag && ...)``; with the manifest's secure_boot flag SET that branch is
never taken and the function returns true on every lifecycle. The instruction path
is therefore the same one ``sep_rom_ot_secure_boot_test`` takes under TEST_DEV, so
no lifecycle-precedence claim may be made from a pass. The sibling
``sep_firmware_cntl_secure_boot_flow_test`` clears the flag and isolates that.

What it does add: the PROD path through ``rom_lifecycle_policy`` (LC decode,
validation, and the production feature-control masking it applies) and the PROD bit
of the manifest's ``life_cycle_states`` constraint (``manifest_load.c:371-381``).
The lifecycle assertion in :meth:`build_efuse_image` keeps that honest -- without
it the OTP could silently be TEST_DEV again.

The image already permits PROD: ``life_cycle_states = 0x7`` with the selector bit
set, and ``security_version = 0`` against a zero BL1_VERSION fuse, so no
usage-constraint or rollback rejection is expected. Read from
``build/secure_boot.bin``, not assumed.
"""

from __future__ import annotations

import os
from pathlib import Path

import pyuvm
from rom_fw.sep_rom_ot_dma_boot_test import SECURE_FLASH_IMAGE, sep_rom_ot_dma_boot_test

_LC_PROD = "LC=PROD"
_RSA_START = "RSA_VERIFY_START"
_SIG_VALID = "SIG_VALID"
_CRYPTO_OK = "CRYPTO_VALIDATE_OK"
# Must not appear: it would mean the ROM decided secure boot was off in PROD.
_SBOOT_OFF = "SBOOT_OFF"
# Must not appear: the fuse chicken bit is 0 in this image, so a ROM reporting 1
# has sensed the wrong OTP and the run would prove nothing about enforcement.
_SBOOT_DIS_SET = "FUSE: SBOOT_DIS: 1"

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod.toml"
)


@pyuvm.test()
class sep_firmware_enforced_secure_boot_flow_test(sep_rom_ot_dma_boot_test):
    """PROD + signed image: the full RSA-3072 chain runs and BL1 is entered."""

    flash_image = SECURE_FLASH_IMAGE
    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _LC_PROD,
        _RSA_START,
        _SIG_VALID,
        _CRYPTO_OK,
    )
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        _SBOOT_OFF,
        _SBOOT_DIS_SET,
    )

    def build_efuse_image(self):
        assert os.path.isfile(_EFUSE_PRELOAD), f"eFuse preload missing: {_EFUSE_PRELOAD}"
        image = self.select_efuse_image(default_preload=_EFUSE_PRELOAD)
        lc = image.lc_raw()
        sboot_dis = image.field_int("SBOOT_DIS") & 0x1
        bl1_ver = image.field_int("BL1_VERSION")
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert lc == 0x1, (
            f"LC_STATE raw is 0x{lc:x}, expected 0x1 (PROD). Under TEST_DEV the "
            f"manifest flag would explain the crypto chain running, so the "
            f"enforcement arm would be untested and this test would duplicate "
            f"sep_rom_ot_secure_boot_test"
        )
        assert sboot_dis == 0, (
            f"SBOOT_DIS is {sboot_dis}: the chicken bit would disable secure boot "
            f"and the enforcement arm would never be reached"
        )
        # These two would make the run fail for an unrelated reason, which on a
        # negative-looking marker set is easy to misread as "enforcement broken".
        assert bl1_ver == 0, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: a non-zero thermometer "
            f"count makes the manifest's security_version=0 a rollback rejection"
        )
        assert revoke == 0, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0: the image signs "
            f"with ROM key slot 0, which a revocation bit would reject"
        )
        self.logger.info(
            "CHK-SBOOT-STIMULUS: OTP LC raw=0x%x (PROD), SBOOT_DIS=%d, "
            "BL1_VERSION=0x%x, PUBK_REVOKE=0x%x",
            lc,
            sboot_dis,
            bl1_ver,
            revoke,
        )
        return image
