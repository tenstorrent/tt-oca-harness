# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP ROM secure boot over the OpenTitan SPI host: RSA-3072 verified on OTBN.

The signed sibling of ``sep_rom_ot_dma_boot_test``: same ROM and SPI transport, but the
flash image carries an RSA-3072 PKCS#1 v1.5 signature (``make oca-images``, dev0 key,
digest in ROM slot 0 of ``bootrom/prod/include/key_digests.h``). ``oca_validate_manifest()``
then runs ``oca_determine_secure_boot()``, ``oca_check_root_key_authorized()``,
``oca_check_root_key_revocation()``, ``oca_check_security_version()`` and
``oca_check_signature()``; the signature check calls ``rsa_3072_verify()``
(``rsa_verify.c``) on OTBN. The payload hash, hash chain and TOC entry hashes follow,
then the BL1 jump.

PROD and PROD_END always enforce secure boot; TEST_DEV and RMA enforce it only when the
manifest's ``secure_boot_control`` asks. The ROM brings up ESRC -> CSRNG -> EDN itself
before OTBN runs. ``+esrc_noise_force`` only drives the ring-oscillator noise input.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
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
_ENTROPY_OK = "ENTROPY_OK"
_RSA_EXEC = "RSA_EXEC"
_RSA_OK = "RSA_VERIFY_OK"
# Printed when the ROM decides secure boot is OFF -- the non-secure test's normal
# output, and a silent-downgrade signature here.
_SBOOT_OFF = "SBOOT_OFF"

_OTBN_RND = 1 << 2
_OTBN_URND = 1 << 3
_OTBN_EDN_CLIENTS = _OTBN_RND | _OTBN_URND
_OTBN_EDN_NAMES = {
    _OTBN_RND: "RND",
    _OTBN_URND: "URND",
}


@pyuvm.test()
class sep_rom_ot_secure_boot_test(sep_rom_ot_dma_boot_test):
    """Boot from the signed SPI image and verify the RSA-3072 path really ran."""

    flash_image = SECURE_FLASH_IMAGE
    verify_otbn_edn = True
    # Inherit the SPI-path markers, then demand the crypto ones. RSA_EXEC proves
    # OTBN was actually driven (not just that the manifest parsed), RSA_VERIFY_OK
    # that the check reached a verdict and it was "valid", and PUBK_AUTHORIZED
    # that the key it used is one the device trusts.
    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _PUBK_AUTH,
        _ENTROPY_OK,
        _RSA_EXEC,
        _RSA_OK,
    )
    # SBOOT_OFF must NOT appear: it would mean the ROM silently downgraded to the
    # unsigned path and booted anyway, which passes every other check while
    # verifying no crypto at all.
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (_SBOOT_OFF,)

    async def _monitor_otbn_edn(self) -> None:
        dut = cocotb.top
        while True:
            await RisingEdge(dut.clk_i)
            req = dut.crypto_edn_req_o.value
            ack = dut.crypto_edn_ack_o.value
            if req.is_resolvable and ack.is_resolvable:
                req_value = int(req)
                ack_value = int(ack)
                for mask, state in self._otbn_edn_state.items():
                    requesting = bool(req_value & mask)
                    acknowledging = bool(ack_value & mask)
                    if requesting and not state["pending"]:
                        state["requests"] += 1
                        state["pending"] = True
                    if acknowledging:
                        if not requesting:
                            state["acks_without_req"] += 1
                        state["acks"] += 1
                        state["pending"] = False
                    elif not requesting and state["pending"]:
                        state["drops"] += 1
                        state["pending"] = False

    async def run_scenario(self) -> None:
        if not self.verify_otbn_edn:
            await super().run_scenario()
            return

        self._otbn_edn_state = {
            mask: {
                "requests": 0,
                "acks": 0,
                "drops": 0,
                "acks_without_req": 0,
                "pending": False,
            }
            for mask in _OTBN_EDN_NAMES
        }
        monitor = cocotb.start_soon(self._monitor_otbn_edn())
        try:
            await super().run_scenario()
        finally:
            monitor.cancel()

        requested = sum(mask for mask, state in self._otbn_edn_state.items() if state["requests"])
        assert requested & _OTBN_URND, (
            f"OTBN never requested URND during secure boot (requested=0x{requested:x})"
        )
        incomplete = {
            _OTBN_EDN_NAMES[mask]: state
            for mask, state in self._otbn_edn_state.items()
            if state["requests"] != state["acks"]
            or state["drops"]
            or state["acks_without_req"]
            or state["pending"]
        }
        assert not incomplete, (
            f"OTBN entropy handshake incomplete on the real EDN path (incomplete={incomplete})"
        )
        counts = ", ".join(
            f"{_OTBN_EDN_NAMES[mask]} requests={state['requests']} acks={state['acks']}"
            for mask, state in self._otbn_edn_state.items()
            if state["requests"]
        )
        self.logger.info(
            "CHK-OTBN-EDN PASS: every observed OTBN EDN request episode was "
            "acknowledged on the real path (%s); RSA uses URND, while the "
            "dedicated EDN grant test drives RND",
            counts,
        )
