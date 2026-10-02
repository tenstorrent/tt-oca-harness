# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Signed and encrypted OCA payload: RSA-3072, then AES-256-CBC.

Boots from the ``sep_efuse_class_key.toml`` preload and checks that it holds the packer's
32-byte encryption secret, so a drifted preload fails before the run.
Needs ``+esrc_noise_force``: the ROM runs the real entropy chain before RSA and decryption.
"""

from __future__ import annotations

import os
from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_oca_console as oc
from env import sep_payload_mutate as pm
from rom_fw.sep_rom_ot_secure_boot_test import sep_rom_ot_secure_boot_test

_SEP_ROOT = Path(__file__).resolve().parents[4]
_ENCRYPTED_IMAGE = str(_SEP_ROOT / "bootrom" / "prod" / "build" / "oca_encrypted_boot.bin")
_PLAINTEXT_IMAGE = str(_SEP_ROOT / "bootrom" / "prod" / "build" / "oca_secure_boot.bin")
_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_class_key.toml"
)

# Fuse words are assembled little-endian, so keep the config's byte order.
_CLASS_KEY_HEX = "".join(f"{value:02x}" for value in range(32))
_EXPECTED_CLASS_KEY = int.from_bytes(bytes.fromhex(_CLASS_KEY_HEX), "little")

_DECRYPT_OK = "DECRYPT_OK"
# The ciphertext hash precedes decryption; PAYLOAD_OK follows the plaintext TOC checks.
_ORDERED = (
    "PUBK_AUTHORIZED",
    "RSA_EXEC",
    "RSA_VERIFY_OK",
    "MANIFEST_OK",
    _DECRYPT_OK,
    "PAYLOAD_OK",
)


@pyuvm.test()
class sep_firmware_encrypted_boot_test(sep_rom_ot_secure_boot_test):
    """Encrypted payload decrypts with the fuse-derived key and boots BL1."""

    flash_image = _ENCRYPTED_IMAGE
    required_markers = sep_rom_ot_secure_boot_test.required_markers + (_DECRYPT_OK,)
    # A refused HMAC/SHA op leaves hmac_idle set, which a completion poll reads as success.
    forbidden_markers = sep_rom_ot_secure_boot_test.forbidden_markers + (
        "KDF_FAIL",
        "KDF_HMAC_FAIL",
        "HMAC_ERR_CODE=",
        "HMAC_START_REJECTED",
        "HMAC_OP_REJECTED",
        "SHA_START_REJECTED",
        "SHA_OP_REJECTED",
        "AES_RST_FAIL",
        "AES_INIT_BUSY",
        "AES_IDLE_TIMEOUT=",
        "AES_DEC_FAIL",
        "AES_PAD_BAD",
        "AES_CTRL_REJECTED",
        "AES_ALERT_AFTER_DEC",
        "AES_ALERT_STATUS=",
        "DECRYPT_NO_SECRET",
        "DECRYPT_CLASS_KEY_EMPTY",
        "MANIFEST_ERR=",
        "PAYLOAD_LOC_FAIL",
        "PAYLOAD_TOO_LARGE",
        "NO_BL1_IMAGE",
        "BL1_ADDR_RANGE",
        "BL1_ENTRY_RANGE",
    )

    def build_efuse_image(self):
        assert os.path.isfile(_EFUSE_PRELOAD), f"eFuse preload missing: {_EFUSE_PRELOAD}"
        image = self.select_efuse_image(default_preload=_EFUSE_PRELOAD)
        key = image.field_int("CLASS_KEY")
        assert key == _EXPECTED_CLASS_KEY, (
            f"OTP CLASS_KEY is 0x{key:064x}, expected 0x{_EXPECTED_CLASS_KEY:064x} "
            f"(= {_CLASS_KEY_HEX} in packing order). Make the preload's CLASS_KEY match "
            f"encryption_secret in configs/oca_encrypted_boot_test.yaml"
        )
        self.logger.info("CHK-CLASS-KEY: OTP CLASS_KEY matches the packing key")
        return image

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        payload = pm.payload_base(buf, "primary")
        toc = bytes(buf[payload : payload + len(pm.TOC_MAGIC)])
        assert toc != b"PTOC", (
            "primary payload starts with the plaintext TOC magic: the image is "
            "not encrypted, so this run would prove nothing about decryption"
        )
        assert pm.is_encrypted(buf, "primary"), (
            "primary OCA payload_encryption_control does not select encryption; "
            "the ROM would not call the AES-256 decrypt callback"
        )
        self.logger.info(
            "CHK-STIMULUS-ENC: primary OCA payload_encryption_control selects "
            "encryption; payload starts %s (not PTOC)",
            toc.hex(),
        )
        return buf

    def log_transport(self, flash) -> None:
        import cocotb

        word0 = int(self.rd(cocotb.top.sram_word0_probe_o))
        magic = (word0 & 0xFFFF_FFFF).to_bytes(4, "little")
        self.logger.info("CHK-PROBE: SRAM word0 = 0x%016x, low half = %r", word0, magic)
        if magic != b"OCAC":
            self.logger.error(
                "CHK-PROBE: SRAM word 0 is not the manifest magic -- this probe is "
                "NOT reading the manifest/payload region, so the block comparison "
                "below proves nothing about the ROM"
            )
            return

        got = int(self.rd(cocotb.top.sram_payload_probe_o)).to_bytes(48, "little")
        # Assumes oca_secure_boot.bin carries this payload in plaintext.
        with open(_PLAINTEXT_IMAGE, "rb") as fh:
            plain = bytearray(fh.read())
        ref_start = pm.payload_base(plain, "backup")
        ref = plain[ref_start : ref_start + 48]

        verdict = []
        for b in range(3):
            g, r = got[b * 16 : (b + 1) * 16], ref[b * 16 : (b + 1) * 16]
            ok = g == r
            verdict.append(ok)
            self.logger.info(
                "CHK-BLOCK%d: got=%s  expected=%s  %s", b, g.hex(), r.hex(), "OK" if ok else "WRONG"
            )

        if all(verdict):
            self.logger.info("CHK-DECRYPT-VERDICT: all three blocks correct")
        elif not verdict[0] and all(verdict[1:]):
            self.logger.error(
                "CHK-DECRYPT-VERDICT: block 0 WRONG, blocks 1-2 CORRECT. That is the "
                "signature of the IV never reaching the engine: CBC chains later "
                "blocks on the previous ciphertext, which does not depend on the IV. "
                "Suspect the IV write in aes_driver.c, not the key."
            )
        elif not any(verdict):
            self.logger.error(
                "CHK-DECRYPT-VERDICT: ALL blocks wrong -- that is a wrong KEY (or a "
                "wrong mode), not a lost IV; a lost IV would corrupt block 0 only. "
                "Suspect the AES-256 key derived from CLASS_KEY and the 64-byte OCA "
                "KDF context, rather than the IV path."
            )
        else:
            self.logger.error(
                "CHK-DECRYPT-VERDICT: mixed pattern %s -- matches "
                "neither a lost IV nor a wrong key",
                verdict,
            )

    def check_transport(self, console: list[str], flash) -> None:
        attempts = oc.split_attempts(console)
        assert [a.src for a in attempts] == [mm.PRIMARY_MANIFEST_OFFSET], (
            f"slot attempts read {[hex(a.src) for a in attempts]}, expected the "
            f"encrypted primary only. Console: {console}"
        )
        oc.assert_attempt(attempts[0], error=None, stage="accepted", ordered=_ORDERED)
        assert oc.count(console, _DECRYPT_OK) == 1, f"DECRYPT_OK not printed once: {console}"
        self.logger.info(
            "CHK-DECRYPT-ORDER PASS: primary@%d-%d accepted after %s; the payload hash over "
            "ciphertext passed before decryption and the TOC was graded after it",
            attempts[0].first,
            attempts[0].last,
            " -> ".join(_ORDERED),
        )


oc.assert_known(
    sep_firmware_encrypted_boot_test.required_markers
    + sep_firmware_encrypted_boot_test.forbidden_markers
    + _ORDERED,
    sep_firmware_encrypted_boot_test.__name__,
)
