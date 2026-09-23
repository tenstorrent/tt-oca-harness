# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Terminal decryption failure: corrupted ciphertext in both slots must end the boot.

Each slot is re-sealed, so it decrypts to garbage and fails only its TOC identifier.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm

from env import sep_payload_mutate as pm
from rom_fw.sep_backup_manifest_fail_base import sep_backup_manifest_fail_base

_SEP_ROOT = Path(__file__).resolve().parents[4]
_ENCRYPTED_IMAGE = str(_SEP_ROOT / "bootrom" / "prod" / "build" / "encrypted_boot.bin")
_EFUSE_PRELOAD = (Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads"
                  / "efuse_configurations" / "sep_efuse_lc_prod_class_key.toml")

_PRIMARY_SRC = "MANIFEST_SRC=0x00001000"
_BACKUP_SRC = "MANIFEST_SRC=0x00041000"
_PLD_HASH_OK = "PLD_HASH_OK"
_DECRYPT_START = "DECRYPT_START"
_DECRYPT_OK = "DECRYPT_OK"
_SBOOT_OFF = "SBOOT_OFF"
_ALL_FAILED = "MANIFEST_ALL_FAILED"

# Anything past the rejection.
_BL1_PROGRESS = ("BL1_TYPE=", "COPY_DST=", "BL1_COPIED", "PRE_JUMP", "BL1_JUMP=")

# Failures before or inside the engine; PLD_HASH_MISMATCH means the re-seal is broken.
_PREMATURE = (
    "KDF_FAIL", "KDF_HMAC_FAIL", "AES_INIT_FAIL", "AES_INIT_BUSY", "AES_RST_FAIL",
    "AES_CTRL_REJECTED", "AES_ALERT_AFTER_DEC", "AES_ALERT_STATUS=", "AES_DEC_FAIL",
    "PLD_HASH_MISMATCH", "PLD_HASH_TIMEOUT", "RSA_VERIFY_FAIL", "RSA_PKCS1_FAIL",
    "ENC_WITHOUT_SBOOT", "LC_USAGE_CONSTRAINT_FAIL",
)


@pyuvm.test()
class sep_decryption_failure_terminal_test(sep_backup_manifest_fail_base):
    """Corrupt both slots' ciphertext; decryption must run and the boot must end."""

    flash_image = _ENCRYPTED_IMAGE
    efuse_preload = _EFUSE_PRELOAD
    backup_defect_marker = _DECRYPT_OK
    # Reached only after decryption produces a plaintext that is not a TOC.
    expected_error = pm.MANIFEST_ERR_BAD_TOC_ID

    def corrupt_primary(self, buf: bytearray) -> None:
        base = pm.payload_base(buf, "primary")
        before = bytes(buf[base:base + 16])
        at, new = pm.corrupt_ciphertext(buf, "primary")
        after = bytes(buf[base:base + 16])
        assert before != after, "the ciphertext flip did not change the image"
        self.logger.info(
            "CHK-STIMULUS-CIPHERTEXT: primary payload flash byte 0x%x -> 0x%02x; "
            "CBC block 0 %s -> %s (block 0 decrypts to the bytes carrying the TOC "
            "identifier); manifest re-hashed and re-signed with dev0",
            at, new, before.hex(), after.hex(),
        )

    def corrupt_backup(self, buf: bytearray) -> None:
        # A healthy backup would boot, so both slots must fail for the boot to end.
        base = pm.payload_base(buf, "backup")
        before = bytes(buf[base:base + 16])
        at, new = pm.corrupt_ciphertext(buf, "backup")
        after = bytes(buf[base:base + 16])
        assert before != after, "the backup ciphertext flip did not change the image"
        self.logger.info(
            "CHK-STIMULUS-BACKUP: backup payload flash byte 0x%x -> 0x%02x; "
            "CBC block 0 %s -> %s; manifest re-hashed and re-signed with dev0, so "
            "the only defect in either slot is the ciphertext itself",
            at, new, before.hex(), after.hex(),
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        log = self.logger
        status_hex = [hex(v) for v in status_seq]
        log.info("cold_scratch[1] sequence: %s", status_hex)
        log.info("ROM console: %s", console)

        def index_of(marker: str) -> int:
            for i, line in enumerate(console):
                if marker in line:
                    return i
            return -1

        assert retired, "core retired no instructions; the ROM never ran"
        assert console, (
            "ROM console is empty, so no marker check below means anything (the "
            "virt console is DEBUG-build only -- check the ROM build)"
        )

        i_primary = index_of(_PRIMARY_SRC)
        assert i_primary >= 0, (
            f"ROM never read the primary slot ({_PRIMARY_SRC}). Console: {console}"
        )

        # CHK-SECURE-RAN: without the crypto chain, decryption is never attempted.
        assert not any(_SBOOT_OFF in line for line in console), (
            f"ROM printed {_SBOOT_OFF}: secure boot was skipped, so the payload was "
            f"never decrypted. Console: {console}"
        )

        # CHK-NO-PREMATURE: nothing stopped the run before or inside the engine.
        for marker in _PREMATURE:
            assert not any(marker in line for line in console), (
                f"ROM printed {marker}: the run stopped for a reason this testcase "
                f"did not plant, so the verdict below is not attributable to the "
                f"corrupted ciphertext. Console: {console}"
            )

        # CHK-DECRYPT-RAN: without this order, a run that never decrypted also passes.
        i_hash = index_of(_PLD_HASH_OK)
        i_start = index_of(_DECRYPT_START)
        i_ok = index_of(_DECRYPT_OK)
        assert i_hash >= 0, (
            f"ROM never printed {_PLD_HASH_OK}: the ciphertext was not verified, so "
            f"the re-sealed image is wrong. Console: {console}"
        )
        assert i_start >= 0, (
            f"ROM never printed {_DECRYPT_START}: decrypt_payload() was not called, "
            f"so nothing about decryption is being tested. Console: {console}"
        )
        assert i_ok >= 0, (
            f"ROM never printed {_DECRYPT_OK}: the AES engine did not complete. A "
            f"corrupted ciphertext must still decrypt without error -- CBC is a "
            f"permutation -- so this means the engine failed for another reason. "
            f"Console: {console}"
        )
        assert i_hash < i_start < i_ok, (
            f"expected {_PLD_HASH_OK}({i_hash}) -> {_DECRYPT_START}({i_start}) -> "
            f"{_DECRYPT_OK}({i_ok}); the payload hash covers ciphertext and must be "
            f"checked before decryption. Console: {console}"
        )
        log.info("CHK-DECRYPT-RAN: %s@%d -> %s@%d -> %s@%d",
                 _PLD_HASH_OK, i_hash, _DECRYPT_START, i_start, _DECRYPT_OK, i_ok)

        # CHK-DECRYPT-FAILED: the rejection, and that it came AFTER the engine ran.
        err_marker = f"MANIFEST_ERR=0x{self.expected_error:08x}"
        i_err = index_of(err_marker)
        assert i_err >= 0, (
            f"primary was not rejected with {err_marker}; a payload whose plaintext "
            f"is not a TOC must fail the identifier check. Console: {console}"
        )
        assert i_ok < i_err, (
            f"{err_marker} appeared at line {i_err}, before {_DECRYPT_OK} at line "
            f"{i_ok}: the boot failed BEFORE decryption ran, so this run does not "
            f"show a decryption failure at all"
        )
        expected_status = 0x0F01_0000 | (self.expected_error & 0xFFFF)
        assert expected_status in status_seq, (
            f"cold_scratch[1] never held 0x{expected_status:08x}; observed {status_hex}"
        )
        log.info("CHK-DECRYPT-FAILED: %s at line %d, after %s; cold_scratch[1]=0x%08x",
                 err_marker, i_err, _DECRYPT_OK, expected_status)

        # CHK-BACKUP-RETRIED: the backup read must follow the primary's rejection.
        i_backup = index_of(_BACKUP_SRC)
        assert i_backup > i_err, (
            f"expected the backup slot ({_BACKUP_SRC}) to be read AFTER the "
            f"primary's rejection ({err_marker} at line {i_err}), got backup at "
            f"line {i_backup}. An invalid TOC identifier is a Warning followed by "
            f"the backup-retry connector, and upstream "
            f"boot.c does `continue` for the same failure. A missing retry "
            f"would mean the ROM stopped short of the backup it is required to try. "
            f"Console: {console}"
        )
        log.info("CHK-BACKUP-RETRIED: %s read at line %d, after %s at line %d",
                 _BACKUP_SRC, i_backup, err_marker, i_err)

        # CHK-TERMINAL: it stopped, and it stopped as a failure.
        assert any(_ALL_FAILED in line for line in console), (
            f"ROM never printed {_ALL_FAILED}. Console: {console}"
        )
        assert fw_done, (
            f"ROM never signalled completion; cold_scratch[1]: {status_hex}"
        )
        assert not fw_pass, (
            "ROM signalled PASS: it booted an image whose payload it could not decrypt"
        )
        log.info("CHK-TERMINAL: %s, mailbox FAIL (fw_pass=0)", _ALL_FAILED)

        # CHK-NO-BOOT: nothing downstream of the rejection ran.
        for marker in _BL1_PROGRESS:
            assert not any(marker in line for line in console), (
                f"ROM printed {marker}, which sits past the rejection. "
                f"Console: {console}"
            )
        log.info("CHK-NO-BOOT: none of %s reached", ", ".join(_BL1_PROGRESS))
