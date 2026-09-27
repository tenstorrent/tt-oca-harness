# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Signed and encrypted OCA payload: RSA-3072, then AES-256-CBC.

The CLASS_KEY fuse must hold the packer's 32-byte encryption secret. Needs
+sep_crypto_edn_force for EDN client 0 (AES), or the run hangs after DECRYPT_START.
"""

from __future__ import annotations

import os
from pathlib import Path

import pyuvm
from env import sep_payload_mutate as pm
from rom_fw.sep_rom_ot_dma_boot_test import sep_rom_ot_dma_boot_test

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

_RSA_START = "RSA_VERIFY_START"
_SIG_VALID = "SIG_VALID"
_CRYPTO_OK = "CRYPTO_VALIDATE_OK"
_PLD_HASH_OK = "PLD_HASH_OK"
_DECRYPT_START = "DECRYPT_START"
_DECRYPT_OK = "DECRYPT_OK"


@pyuvm.test()
class sep_firmware_encrypted_boot_test(sep_rom_ot_dma_boot_test):
    """Encrypted payload decrypts with the fuse-derived key and boots BL1."""

    flash_image = _ENCRYPTED_IMAGE
    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _RSA_START,
        _SIG_VALID,
        _PLD_HASH_OK,
        _DECRYPT_START,
        _DECRYPT_OK,
        _CRYPTO_OK,
    )
    # A refused HMAC/SHA op leaves hmac_idle set, which a completion poll reads as success.
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        "KDF_FAIL",
        "KDF_HMAC_FAIL",
        "HMAC_ERR_CODE=",
        "HMAC_START_REJECTED",
        "HMAC_OP_REJECTED",
        "SHA_START_REJECTED",
        "SHA_OP_REJECTED",
        "AES_INIT_FAIL",
        "AES_INIT_BUSY",
        "AES_DEC_FAIL",
        "SBOOT_OFF",
        "PLD_HASH_MISMATCH",
        "MANIFEST_ERR=",
        "PAYLOAD_OFF_RANGE",
        "PAYLOAD_LEN_RANGE",
        "PAYLOAD_OFF_ALIGN",
        "PAYLOAD_HASHED_LEN_BAD",
        "ENC_HASHED_LEN_PARTIAL",
        "ENC_WITHOUT_SBOOT",
        "TOC_REGION_OOB",
        "TOC_PLEN_MISMATCH",
        "IMAGE_ORDER_BAD",
        "IMAGE_LEN_ZERO",
        "IMAGE_LEN_ALIGN",
        "IMAGE_HASH_MISMATCH",
        "IMAGE_HASH_TIMEOUT",
        "NO_BL1_IMAGE",
        "BL1_ADDR_RANGE",
        "BL1_ENTRY_RANGE",
        "ROM_KEY_EMPTY",
        "FLASH_REINIT_FAIL",
        "AES_CTRL_REJECTED",
        "AES_ALERT_AFTER_DEC",
        "AES_ALERT_STATUS=",
    )

    def build_efuse_image(self):
        assert os.path.isfile(_EFUSE_PRELOAD), f"eFuse preload missing: {_EFUSE_PRELOAD}"
        image = self.select_efuse_image(default_preload=_EFUSE_PRELOAD)
        key = image.field_int("CLASS_KEY")
        assert key == _EXPECTED_CLASS_KEY, (
            f"OTP CLASS_KEY is 0x{key:064x}, expected 0x{_EXPECTED_CLASS_KEY:064x} "
            f"(= {_CLASS_KEY_HEX} in packing order) "
            f"(configs/oca_encrypted_boot_test.yaml encryption_secret). The ROM "
            f"derives its AES-256 key from this fuse, so a mismatch decrypts the "
            f"payload to garbage and the run would fail for the wrong reason"
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
        # oca_secure_boot.bin carries the same payload in plaintext, so it is the reference.
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
        def index_of(marker: str) -> int:
            for i, line in enumerate(console):
                if marker in line:
                    return i
            return -1

        # The payload hash covers ciphertext, so it precedes decryption; the TOC comes after.
        i_hash = index_of(_PLD_HASH_OK)
        i_dec = index_of(_DECRYPT_START)
        i_ok = index_of(_DECRYPT_OK)
        i_images = index_of("IMAGES=")
        assert i_hash < i_dec, (
            f"payload hash ({i_hash}) was not verified before decryption "
            f"({i_dec}); the packer hashes ciphertext, so checking it after "
            f"decrypt would compare a plaintext digest. Console: {console}"
        )
        assert i_dec < i_ok < i_images, (
            f"expected DECRYPT_START({i_dec}) -> DECRYPT_OK({i_ok}) -> TOC read "
            f"IMAGES=({i_images}); the TOC must be parsed only after decryption"
        )
        self.logger.info(
            "CHK-DECRYPT-ORDER: PLD_HASH_OK@%d -> DECRYPT_START@%d -> DECRYPT_OK@%d -> IMAGES=@%d",
            i_hash,
            i_dec,
            i_ok,
            i_images,
        )
