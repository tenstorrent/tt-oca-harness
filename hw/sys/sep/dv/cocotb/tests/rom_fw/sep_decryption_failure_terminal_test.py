# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""TP049: a payload that cannot be decrypted correctly must end the boot.

Procedure variant (b): "corrupt the encrypted payload so the decrypted plaintext
does not match the TOC magic". One ciphertext bit of the PRIMARY slot is flipped
in AES-CBC block 0, and the manifest is re-hashed and re-signed with the dev0 key
so that the only thing wrong with the image is the ciphertext itself
(``env/sep_payload_mutate.py``).

THE FALSE-PASS THIS TESTCASE IS BUILT TO AVOID. AES-CBC decryption is a
permutation: it never reports an error for the wrong input, and the ROM's own
``aes128cbc_decrypt`` only fails on a bad length or a hardware alert
(``aes_driver.c:175-176,193-234``). So a corrupted ciphertext -- and equally a
wrong class key -- decrypts "successfully" to garbage, and the boot then dies at
the TOC identifier check with ``MANIFEST_ERR_BAD_TOC_ID``
(``manifest_load.c:295-297``). That is the same terminal code an image whose TOC
was simply never encrypted would produce, and the same code a run that stopped
BEFORE decryption would reach. Keying a verdict on the final error alone would
therefore pass while decryption never ran.

``CHK-DECRYPT-RAN`` is the defence: the run must show ``PLD_HASH_OK`` (the
ciphertext was authenticated) then ``DECRYPT_START`` then ``DECRYPT_OK``, in that
order, and the rejection must come AFTER ``DECRYPT_OK``. Only a run that actually
drove the AES engine and then failed downstream can satisfy that sequence.

WHY THE PAYLOAD HASH HAD TO BE RECOMPUTED, AND WHY THAT IS NOT A WEAKENING.
``payload_hash`` covers the CIPHERTEXT and is verified before decryption
(``manifest_crypto.c:372-378``). Left stale, the ROM would stop at
``PLD_HASH_MISMATCH`` and never call ``decrypt_payload`` -- the run would look
like a clean negative result while testing the payload hash rather than
decryption. Re-sealing keeps every ROM check enabled and passing up to the point
under test, which is what makes the decryption failure attributable.

VARIANT (a) IS NOT COVERED HERE. The procedure's other source is "inject AES
engine status fail via the AES model". There is no AES model on RTL -- the AES is
real RTL -- so the engine's ``ALERT_FATAL_FAULT`` / ``ALERT_RECOV_CTRL_UPDATE_ERR``
status (``aes_driver.c:57``) could only be produced by forcing a status bit, which
is a forbidden sim-only shortcut. A pass here therefore covers the post-decrypt
detection arm and not the engine-status arm.

THE NO-BACKUP-RETRY EXPECTATION. Procedure step 5 requires that a decryption
failure is terminal and NOT backup-eligible, and its Expected Results say "no
backup address read". Only the PRIMARY slot is corrupted here, exactly as the
procedure's steps read, and ``CHK-NO-BACKUP-RETRY`` asserts that requirement at
full strength. Note that ``rom_manifest_boot`` (``manifest_load.c:770-788``)
treats EVERY slot error as retryable, with no per-error class -- so if that check
fails, it has found a real disagreement between the procedure and the ROM, and it
must be reported rather than relaxed.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm
from env import sep_payload_mutate as pm
from rom_fw.sep_backup_manifest_fail_base import sep_backup_manifest_fail_base

_SEP_ROOT = Path(__file__).resolve().parents[4]
_ENCRYPTED_IMAGE = str(_SEP_ROOT / "bootrom" / "prod" / "build" / "encrypted_boot.bin")
_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod_class_key.toml"
)

_PRIMARY_SRC = "MANIFEST_SRC=0x00001000"
_BACKUP_SRC = "MANIFEST_SRC=0x00041000"
_PLD_HASH_OK = "PLD_HASH_OK"
_DECRYPT_START = "DECRYPT_START"
_DECRYPT_OK = "DECRYPT_OK"
_SBOOT_OFF = "SBOOT_OFF"
_ALL_FAILED = "MANIFEST_ALL_FAILED"

# Anything past the rejection.
_BL1_PROGRESS = ("BL1_TYPE=", "COPY_DST=", "BL1_COPIED", "PRE_JUMP", "BL1_JUMP=")

# Failures that would mean decryption was never reached, or was reached for a
# reason this testcase did not plant. KDF and AES-init failures would stop the
# ROM before the engine ran; PLD_HASH_MISMATCH would mean the re-seal is broken.
_PREMATURE = (
    "KDF_FAIL",
    "KDF_HMAC_FAIL",
    "AES_INIT_FAIL",
    "AES_INIT_BUSY",
    "AES_RST_FAIL",
    "AES_CTRL_REJECTED",
    "AES_ALERT_AFTER_DEC",
    "AES_ALERT_STATUS=",
    "AES_DEC_FAIL",
    "PLD_HASH_MISMATCH",
    "PLD_HASH_TIMEOUT",
    "RSA_VERIFY_FAIL",
    "RSA_PKCS1_FAIL",
    "ENC_WITHOUT_SBOOT",
    "LC_USAGE_CONSTRAINT_FAIL",
)


@pyuvm.test()
class sep_decryption_failure_terminal_test(sep_backup_manifest_fail_base):
    """Corrupt the primary's ciphertext; decryption must run and the boot must end."""

    flash_image = _ENCRYPTED_IMAGE
    efuse_preload = _EFUSE_PRELOAD
    backup_defect_marker = _DECRYPT_OK
    # manifest.h:300 -- the sub-code variant (b) converges on, reached only after
    # the plaintext has been produced and found not to be a TOC.
    expected_error = pm.MANIFEST_ERR_BAD_TOC_ID

    # --- stimulus ------------------------------------------------------------
    def corrupt_primary(self, buf: bytearray) -> None:
        base = pm.payload_base(buf, "primary")
        before = bytes(buf[base : base + 16])
        at, new = pm.corrupt_ciphertext(buf, "primary")
        after = bytes(buf[base : base + 16])
        assert before != after, "the ciphertext flip did not change the image"
        self.logger.info(
            "CHK-STIMULUS-CIPHERTEXT: primary payload flash byte 0x%x -> 0x%02x; "
            "CBC block 0 %s -> %s (block 0 decrypts to the bytes carrying the TOC "
            "identifier); manifest re-hashed and re-signed with dev0",
            at,
            new,
            before.hex(),
            after.hex(),
        )

    def corrupt_backup(self, buf: bytearray) -> None:
        """A no-op: the procedure corrupts the PRIMARY only.

        Step 5 requires that a decryption failure is terminal and not
        backup-eligible, so leaving the backup healthy is what makes
        CHK-NO-BACKUP-RETRY a real question rather than a foregone conclusion.
        """
        pm.verify_sealed(buf, "backup", check_toc=False)
        self.logger.info(
            "CHK-STIMULUS-BACKUP: backup slot left valid and sealed; the procedure "
            "requires the boot to end without ever reading it"
        )

    # --- checks --------------------------------------------------------------
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

        # CHK-SECURE-RAN: PROD enforces the crypto chain; if it were skipped the
        # ROM would reject the encrypted image outright as ENC_WITHOUT_SBOOT and
        # decryption would never be attempted.
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

        # CHK-DECRYPT-RAN: the whole point. The ciphertext was authenticated, the
        # AES engine ran to completion, and only THEN did the boot fail. Without
        # the ordering, the terminal error alone is satisfied by a run in which
        # decryption never happened.
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
        log.info(
            "CHK-DECRYPT-RAN: %s@%d -> %s@%d -> %s@%d",
            _PLD_HASH_OK,
            i_hash,
            _DECRYPT_START,
            i_start,
            _DECRYPT_OK,
            i_ok,
        )

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
        log.info(
            "CHK-DECRYPT-FAILED: %s at line %d, after %s; cold_scratch[1]=0x%08x",
            err_marker,
            i_err,
            _DECRYPT_OK,
            expected_status,
        )

        # CHK-NO-BACKUP-RETRY: procedure step 5 and its "no backup address read"
        # expected result. Left at full strength -- see the module
        # docstring. rom_manifest_boot() has no per-error retry class, so a failure
        # here is a real procedure-versus-ROM disagreement, not a test defect.
        i_backup = index_of(_BACKUP_SRC)
        assert i_backup < 0, (
            f"ROM read the backup slot ({_BACKUP_SRC}) at line {i_backup} after the "
            f"primary's decryption failure. TP049 step 5 requires that a decryption "
            f"failure is terminal and NOT backup-eligible, and its expected results "
            f"say no backup address is read. Console: {console}"
        )
        log.info("CHK-NO-BACKUP-RETRY: %s never read", _BACKUP_SRC)

        # CHK-TERMINAL: it stopped, and it stopped as a failure.
        assert any(_ALL_FAILED in line for line in console), (
            f"ROM never printed {_ALL_FAILED}. Console: {console}"
        )
        assert fw_done, f"ROM never signalled completion; cold_scratch[1]: {status_hex}"
        assert not fw_pass, (
            "ROM signalled PASS: it booted an image whose payload it could not decrypt"
        )
        log.info("CHK-TERMINAL PASS: %s, mailbox FAIL (fw_pass=0)", _ALL_FAILED)

        # CHK-NO-BOOT: nothing downstream of the rejection ran.
        for marker in _BL1_PROGRESS:
            assert not any(marker in line for line in console), (
                f"ROM printed {marker}, which sits past the rejection. Console: {console}"
            )
        log.info("CHK-NO-BOOT: none of %s reached", ", ".join(_BL1_PROGRESS))
