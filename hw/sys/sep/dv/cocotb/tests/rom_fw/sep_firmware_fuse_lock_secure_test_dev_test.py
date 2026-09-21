# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Fuse lock in TEST_DEV with the chicken bit clear: the manifest asks, and gets, secure boot.

THE CELL. LC_STATE raw 0x0 (TEST_DEV), SBOOT_DIS 0. This is the only one of the
four in which ``secure_boot_enabled()`` (``manifest_load.c``) defers to the
MANIFEST: the fuse does not veto, and TEST_DEV is not a lifecycle that enforces,
so the verdict is the signed manifest's ``secure_boot`` flag. The base asserts
that flag is set on the loaded image, so the authenticated boot this row observes
is attributable to it.

Distinction from ``sep_rom_ot_secure_boot_test``, which boots the same image on
the same zero OTP. That test grades the RSA path and forbids ``SBOOT_OFF``; it
says nothing about the lifecycle it ran in, the fuse it read, or the fuse lock,
and would pass unchanged in PROD. This row pins ``LC=TEST_DEV`` and
``FUSE: SBOOT_DIS: 0``, forbids every other decode and the opposite fuse value,
and adds the lock evidence -- the console marker, the ordering against the
handoff, and the DUT-side read of the shadow LOCKS register.

THE OTP IS NAMED EXPLICITLY, AND WHAT THAT DOES NOT BUY. An unprogrammed OTP
senses exactly this cell, so the preload is about provenance, not about the DUT:
it gives ``check_efuse()`` a committed file to assert against and keeps all four
cells staging their OTP the same way. It does NOT let the run witness that the
file reached the DUT. ``sep_efuse_lc_test_dev.toml`` sets LC_STATE and nothing
else, and ``SepEfuseImage.shadow_word()`` regenerates LC_STATE's shadow from the
raw nibble, so the image this preload produces senses bit-identically to a blank
array -- ``LC_STATE=0x00000000`` is the blank value too. This cell's identity
rests on the other axis instead: ``FUSE: SBOOT_DIS: 0``, with
``FUSE: SBOOT_DIS: 1`` forbidden, which is what separates it from the TEST_DEV
sibling that blows the chicken bit.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_fuse_lock_base import EFUSE_DIR, LC_RAW_TEST_DEV, sep_fuse_lock_base


@pyuvm.test()
class sep_firmware_fuse_lock_secure_test_dev_test(sep_fuse_lock_base):
    """TEST_DEV + SBOOT_DIS=0 -> manifest-selected secure boot -> secrets locked."""

    efuse_preload = EFUSE_DIR / "sep_efuse_lc_test_dev.toml"
    expected_lc_raw = LC_RAW_TEST_DEV
    expected_sboot_dis = 0
