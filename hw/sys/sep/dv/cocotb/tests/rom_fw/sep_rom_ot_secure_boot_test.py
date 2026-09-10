# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP ROM SECURE boot over the OpenTitan SPI host (PyUVM) -- RSA-3072 on OTBN.

The signed sibling of ``sep_rom_ot_dma_boot_test``. Identical ROM, identical SPI
transport (OpenTitan spi_host, SECURE_DMA drain, OcahSpiFlash BFM); the only
change is the flash image, which carries an RSA-3072 PKCS#1 v1.5 signature over
the manifest (``make oca-images``, dev0 key from the tt-oca-manifest
submodule, digest pinned in key_digests.c slot 0).

That one swap turns on a whole code path the non-secure test never reaches:

    oca_boot.c        staged flow, OCA validator library
      -> determine_secure_boot            -- manifest bit, sboot_dis, lifecycle
        -> check_root_key_authorized      -- oca_platform.c: ROM digest / OTP hash
        -> check_root_key_revocation      -- CHIPLET_PUBK_REVOKE
        -> the anti-rollback check         -- anti-rollback
        -> check_signature -> rsa_verify.c
          -> OTBN rsa_3072_app            -- signature^e mod n (Montgomery)
        -> PKCS#1 v1.5 unpad, digest compare
      -> payload hash + hash chain + TOC entry hashes -> BL1 jump

The determination gates on the manifest's secure_boot_control bit, `sboot_dis` (eFuse)
and the lifecycle state: PROD/PROD_END always enforce, TEST_DEV/RMA enforce only when
the manifest asks.

NOTE ON ENTROPY: this run DOES exercise the entropy chain. The ROM brings
entropy_source -> CSRNG -> EDN up itself before the signature-verification
callback drives OTBN. The testlist opts into +esrc_noise_force only because ring
oscillators do not self-oscillate under Verilator; the health tests, CSRNG, EDN
and the command handshakes above that noise source all run for real. The RSA
assertions below are untouched, so a pass still means the signature genuinely
verified.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_rom_ot_dma_boot_test import (
    SECURE_FLASH_IMAGE,
    sep_rom_ot_dma_boot_test,
)

# Emitted only on the signed path.
#
# PUBK_AUTHORIZED is the one worth having beyond the RSA pair: it says the key was
# matched against a trust anchor -- a ROM digest or an OTP hash bank -- rather
# than merely carried by the manifest. A boot that verified a signature made by a
# key nothing vouched for would print RSA_VERIFY_OK and not this.
_PUBK_AUTH = "PUBK_AUTHORIZED"
_RSA_EXEC = "RSA_EXEC"
_RSA_OK = "RSA_VERIFY_OK"
# Printed when the ROM decides secure boot is OFF -- the non-secure test's normal
# output, and a silent-downgrade signature here.
_SBOOT_OFF = "SBOOT_OFF"


@pyuvm.test()
class sep_rom_ot_secure_boot_test(sep_rom_ot_dma_boot_test):
    """Boot from the signed SPI image and verify the RSA-3072 path really ran."""

    flash_image = SECURE_FLASH_IMAGE
    # Inherit the SPI-path markers, then demand the crypto ones. RSA_EXEC proves
    # OTBN was actually driven (not just that the manifest parsed), RSA_VERIFY_OK
    # that the check reached a verdict and it was "valid", and PUBK_AUTHORIZED
    # that the key it used is one the device trusts.
    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _PUBK_AUTH,
        _RSA_EXEC,
        _RSA_OK,
    )
    # SBOOT_OFF must NOT appear: it would mean the ROM silently downgraded to the
    # unsigned path and booted anyway, which passes every other check while
    # verifying no crypto at all.
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (_SBOOT_OFF,)
