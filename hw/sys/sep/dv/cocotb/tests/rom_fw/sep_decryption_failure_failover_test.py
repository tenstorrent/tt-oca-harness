# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary's decrypted payload is not a TOC; the backup boots.

A CBC block-0 flip leaves the pad intact, so decryption succeeds, ``read_toc_span()``
refuses the TOC with ``OCA_FAIL_PAYLOAD_TOC``, and the ROM fails over to the backup.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw.sep_primary_fail_backup_boot_base import sep_primary_fail_backup_boot_base

_SEP_ROOT = Path(__file__).resolve().parents[4]
_ENCRYPTED_IMAGE = str(_SEP_ROOT / "bootrom" / "prod" / "build" / "oca_encrypted_boot.bin")
_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod_class_key.toml"
)

_DECRYPT_OK = "DECRYPT_OK"

# Stops before the plaintext exists; AES_PAD_BAD indicates a wrong class key.
_PREMATURE = (
    "AES_PAD_BAD",
    "AES_DEC_FAIL",
    "AES_RST_FAIL",
    "AES_INIT_BUSY",
    "KDF_HMAC_FAIL",
    "KDF_FAIL",
    "DECRYPT_NO_SECRET",
    "DECRYPT_CLASS_KEY_EMPTY",
    "SHA_START_REJECTED",
    "SHA_OP_REJECTED",
)


@pyuvm.test()
class sep_decryption_failure_failover_test(sep_primary_fail_backup_boot_base):
    """Primary decrypts to a non-TOC -> refused -> backup boots."""

    flash_image = _ENCRYPTED_IMAGE
    efuse_preload = _EFUSE_PRELOAD
    primary_expected_error = mm.boot_err("OCA_FAIL_PAYLOAD_TOC")
    # The TOC checks print no marker of their own, so the defect is named by its error line.
    primary_defect_marker = f"MANIFEST_ERR=0x{primary_expected_error:08x}"
    # Refused downstream of a verified signature, so each slot prints RSA_VERIFY_OK once.
    primary_expected_rsa_starts = 1
    primary_expected_rsa_oks = 1
    primary_expected_stage = "payload"
    # Decryption must have RUN and completed, or the refusal is not the one aimed at.
    primary_ordered = (_DECRYPT_OK,)
    extra_forbidden = _PREMATURE

    # --- stimulus ------------------------------------------------------------
    def corrupt_primary(self, buf: bytearray) -> None:
        base = pm.payload_base(buf, "primary")
        before = bytes(buf[base : base + 16])
        at = pm.corrupt_ciphertext(buf, "primary")
        after = bytes(buf[base : base + 16])
        assert before != after, "the ciphertext flip did not change the image"
        self.logger.info(
            "CHK-STIMULUS-CIPHERTEXT: primary payload flash byte 0x%x -> 0x%02x; "
            "CBC block 0 %s -> %s (C0 also flips the TOC image_count in plaintext "
            "block 1); manifest re-hashed and re-signed",
            at,
            buf[at],
            before.hex(),
            after.hex(),
        )

    def check_efuse(self, image) -> None:
        key = image.field_int("CLASS_KEY")
        want = int.from_bytes(bytes(range(32)), "little")
        assert key == want, (
            f"CLASS_KEY is 0x{key:064x}, expected 0x{want:064x} -- the 32 bytes "
            f"00 01 .. 1f that configs/oca_encrypted_boot_test.yaml encrypts with. "
            f"A different value derives a different AES key and the payload "
            f"decrypts to garbage, which surfaces as AES_PAD_BAD rather than as "
            f"anything mentioning keys"
        )
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert revoke == 0, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0: both slots select "
            f"ROM key slot 0 and must be able to use it, or the backup could not boot"
        )
        self.logger.info(
            "CHK-STIMULUS-EFUSE PASS: CLASS_KEY is the packer's secret and "
            "CHIPLET_PUBK_REVOKE=0, so decryption and key authorization can only "
            "succeed or fail on the stimulus"
        )
