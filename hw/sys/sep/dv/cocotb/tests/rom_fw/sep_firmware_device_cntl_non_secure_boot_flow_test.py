# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Device-controlled non-secure boot: the SBOOT_DIS fuse overrides PROD (PyUVM).

FEATURE UNDER TEST. ``secure_boot_enabled()`` is a three-input decision
(``manifest_load.c:223-240``)::

    sboot_dis fuse          -> always DISABLE   (device control / chicken bit)
    PROD or PROD_END        -> always ENFORCE   (regardless of the manifest flag)
    TEST_DEV or RMA         -> the manifest flag decides

This pins the highest-precedence input against the second: PROD, which on its own
forces secure boot, plus ``SBOOT_DIS = 1``. The device control must win.

That precedence is why the stimulus is PROD rather than TEST_DEV: under TEST_DEV
the manifest flag alone could explain a non-secure boot, so the run would prove
nothing about SBOOT_DIS. The image is the ordinary signed one, unmutated -- a
signed manifest declaring ``secure_boot = 1`` is the strongest form, because every
other input asks for secure boot and only the fuse asks to skip it.

The eFuse must come from a committed preload: ``write_efuse_image()`` runs inside
the cocotb coroutine, after t=0, whereas the OTP model does its ``$readmemh`` at
t=0, so setting LC_STATE from the test body has no effect on the DUT. The testlist
passes ``+sep_efuse_preload=<path>``, which ``dv_sim_prestage.stage()`` honours
before the simulator launches and ``select_efuse_image()`` honours at run time, so
the sensed fuses and the shadow-compare golden are the same file.
"""

from __future__ import annotations

import os
from pathlib import Path

import pyuvm
from rom_fw.sep_rom_ot_dma_boot_test import SECURE_FLASH_IMAGE, sep_rom_ot_dma_boot_test

# Emitted only when the ROM decides secure boot is OFF (rom_main.c:348).
_SBOOT_OFF = "SBOOT_OFF"
# rom_main.c:588-598 prints the fuse it read, in decimal. This is the evidence
# that the fuse the testcase relies on was actually sensed as 1 -- without it a
# preload that failed to stage would look identical to a working chicken bit.
_SBOOT_DIS_SET = "FUSE: SBOOT_DIS: 1"
# lifecycle.c decodes the sensed LC_STATE to one of these. Requiring PROD is what
# makes the override meaningful rather than incidental.
_LC_PROD = "LC=PROD"
# Crypto-path markers that must NOT appear: reaching any of them means the ROM
# ignored the fuse and ran the secure chain anyway.
_RSA_START = "RSA_VERIFY_START"
_SIG_VALID = "SIG_VALID"
_CRYPTO_OK = "CRYPTO_VALIDATE_OK"

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod_sboot_dis.toml"
)


@pyuvm.test()
class sep_firmware_device_cntl_non_secure_boot_flow_test(sep_rom_ot_dma_boot_test):
    """PROD + SBOOT_DIS=1: the ROM must skip secure boot and still reach BL1."""

    flash_image = SECURE_FLASH_IMAGE
    # Inherit the SPI-path markers (BOOT_SPI / MANIFEST_SRC / MANIFEST_OK) so the
    # transport is still pinned down, then add the device-control evidence.
    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _SBOOT_DIS_SET,
        _LC_PROD,
        _SBOOT_OFF,
    )
    # The negative half. SBOOT_OFF alone says the ROM *reported* the decision;
    # these say it acted on it. Without them a ROM that printed SBOOT_OFF and then
    # verified the signature anyway would pass.
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        _RSA_START,
        _SIG_VALID,
        _CRYPTO_OK,
    )

    def build_efuse_image(self):
        assert os.path.isfile(_EFUSE_PRELOAD), f"eFuse preload missing: {_EFUSE_PRELOAD}"
        image = self.select_efuse_image(default_preload=_EFUSE_PRELOAD)
        # Guard the stimulus. select_efuse_image() falls back to a seeded random
        # image when the plusarg is absent, and a random image would almost
        # certainly sense TEST_DEV with sboot_dis=0 -- i.e. a run that boots
        # non-secure for the ordinary reason and proves nothing here.
        lc = image.lc_raw()
        sboot_dis = image.field_int("SBOOT_DIS") & 0x1
        assert sboot_dis == 1, (
            f"SBOOT_DIS is {sboot_dis}, expected 1: the testlist must pass "
            f"+sep_efuse_preload={_EFUSE_PRELOAD}"
        )
        assert lc == 0x1, (
            f"LC_STATE raw is 0x{lc:x}, expected 0x1 (PROD): without PROD the "
            f"manifest flag could explain a non-secure boot and the fuse override "
            f"would be untested"
        )
        self.logger.info(
            "CHK-SBOOT-STIMULUS: OTP image LC raw=0x%x (PROD), SBOOT_DIS=%d", lc, sboot_dis
        )
        return image
