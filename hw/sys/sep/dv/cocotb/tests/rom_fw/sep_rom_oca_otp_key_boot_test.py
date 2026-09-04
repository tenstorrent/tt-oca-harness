# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP ROM secure boot anchored on an OTP public-key hash, not a ROM digest (PyUVM).

``sep_rom_ot_secure_boot_test`` verifies a signature against a key whose digest is
compiled into the ROM (``key_digests.c`` slot 0). This test verifies against a key
the ROM has never seen, vouched for by a digest fused into OTP instead. Same RSA
path, different trust anchor -- and the anchor is the part that decides whether a
signature means anything.

The two branches live in ``plat_is_key_authorized()`` (oca_platform.c), selected by
the manifest's ``public_key_select_classic``. That selector shares its bit map with
``CHIPLET_PUBK_REVOKE`` (see sep_efuse_map.rdl:727): bits [7:0] are ROM classical
keys, [16]/[17] are CHIPLET_PUBK_HASH0/1, [20] SIP_PUBK_HASH0, [22] SYS_PUBK_HASH,
[24] SIP_PUBK_HASH1. ``configs/oca_otp_key_boot_test.yaml`` selects bit 16, so the
ROM reads CHIPLET_PUBK_HASH0 and compares SHA-256 of the manifest's modulus against
it. Anything not matching is ``OCA_FAIL_ROOT_KEY_UNAUTHORIZED``.

Worth having in simulation and not only on the VP because the two branches read
different hardware: the ROM-digest path is a memcmp against .rodata, this one is a
real eFuse bank read through the sense path, subject to the same shadow/lock
behaviour as any other OTP field.

The digest below is SHA-256 over ROM key 0's RSA-3072 modulus -- the 384-byte MODULUS
only, not the 388-byte RAW blob that carries the exponent. Word order matches
``fuse_read_bytes()``: word[0] holds bits[31:0], so each word is four consecutive
digest bytes read little-endian. Same table as
``virtual_platform/tests/fuse_maps/oca_otp_key.yaml``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pyuvm
from env.sep_efuse_image import SepEfuseImage
from rom_fw.sep_rom_ot_secure_boot_test import sep_rom_ot_secure_boot_test

_SEP_ROOT = str(Path(__file__).resolve().parents[4])
OTP_KEY_FLASH_IMAGE = os.path.join(_SEP_ROOT, "bootrom", "prod", "build", "oca_otp_key_boot.bin")

_CHIPLET_PUBK_HASH0_WORDS = [
    0x63CA71A7,
    0xC2F5A837,
    0x94C96E1A,
    0xA03A7E64,
    0xD2A7FD9C,
    0xBB617D03,
    0x2B03DFEC,
    0xF6508284,
]

# plat_is_key_authorized() refuses an all-zero OTP bank rather than treating it
# as a digest to match. Forbidding the marker here proves the bank was actually
# provisioned and read, which a bare pass would not: an erased bank plus a
# broken comparison could otherwise look like success.
_PUBK_OTP_EMPTY = "PUBK_OTP_EMPTY"
# The digest-mismatch refusal. Cannot coexist with the inherited PUBK_AUTHORIZED
# in a single-slot boot, but the ROM tries both manifest slots -- so forbidding
# it also rules out a pass that only came good on the retry.
_PUBK_UNAUTHORIZED = "PUBK_UNAUTHORIZED"


@pyuvm.test()
class sep_rom_oca_otp_key_boot_test(sep_rom_ot_secure_boot_test):
    """Verify an RSA-3072 signature against an OTP-fused root-key digest."""

    flash_image = OTP_KEY_FLASH_IMAGE
    # PUBK_AUTHORIZED is inherited and means something different here than in the
    # parent: same marker, but reached through the OTP branch rather than the ROM
    # digest table.
    forbidden_markers = sep_rom_ot_secure_boot_test.forbidden_markers + (
        _PUBK_OTP_EMPTY,
        _PUBK_UNAUTHORIZED,
    )

    def build_efuse_image(self) -> SepEfuseImage:
        img = super().build_efuse_image()
        img.set_words("CHIPLET_PUBK_HASH0", _CHIPLET_PUBK_HASH0_WORDS)
        return img
