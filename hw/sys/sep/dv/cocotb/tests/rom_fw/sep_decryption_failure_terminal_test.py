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
the TOC identifier check with ``MANIFEST_ERR_BAD_TOC_ID``. That is the same terminal code an image whose TOC
was simply never encrypted would produce, and the same code a run that stopped
BEFORE decryption would reach. Keying a verdict on the final error alone would
therefore pass while decryption never ran.

``CHK-DECRYPT-RAN`` is the defence: the run must show ``PAYLOAD_OK`` (the
ciphertext was authenticated) then ``DECRYPT_START`` then ``DECRYPT_OK``, in that
order, and the rejection must come AFTER ``DECRYPT_OK``. Only a run that actually
drove the AES engine and then failed downstream can satisfy that sequence.

WHY THE PAYLOAD HASH HAD TO BE RECOMPUTED, AND WHY THAT IS NOT A WEAKENING.
``payload_hash`` covers the CIPHERTEXT and is verified before decryption. Left stale, the ROM would stop at
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

WHY BOTH SLOTS ARE CORRUPTED, AND WHY THIS TESTCASE USED TO CORRUPT ONLY ONE.
An earlier version read procedure step 5 as "a decryption failure is terminal and
NOT backup-eligible", corrupted the PRIMARY only, left the backup healthy, and
asserted the backup was never read. It also recorded, correctly, that
``oca_boot.c``'s retry loop treats EVERY slot error as retryable with no
per-error class, and that a failure of that assertion would be a real
procedure-versus-ROM disagreement rather than a test defect.

That disagreement was surfaced on 2026-09-14 and resolved in the ROM's favour.
The slot BUNDLE -- manifest and payload together, decryption and plaintext
validation included -- is the unit of verification. Until a bundle is fully
confirmed and the device begins locking for ROM exit, switching to the other slot
is legitimate. The retry loop says so in as many words: each slot's verdict is
reported as a WARN while retries remain, and only slot exhaustion is re-reported
as an ERROR with ``MANIFEST_ALL_FAILED``.

So a payload defect in ONE slot is a failover, not a terminal event, and
``sep_decryption_failure_failover_test`` is the testcase for that shape. This one
keeps the TERMINAL shape its name, its base class and its ``expected_error`` all
describe, which under bundle-level failover requires the defect in BOTH slots.

Historical note worth keeping: before 2026-09-14 this testcase appeared to reach a
terminal verdict with only the primary corrupted. That was an artifact of a stale
CLASS_KEY in the eFuse preload -- a 16-byte AES-128-era value against an AES-256
config -- which derived the wrong key and broke BOTH slots' decryption. The
terminal outcome was real; its cause was the fixture, not the stimulus.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw.sep_backup_manifest_fail_base import sep_backup_manifest_fail_base

_SEP_ROOT = Path(__file__).resolve().parents[4]
_ENCRYPTED_IMAGE = str(_SEP_ROOT / "bootrom" / "prod" / "build" / "oca_encrypted_boot.bin")
_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod_class_key.toml"
)

_PRIMARY_SRC = "MANIFEST_SRC=0x00001000"
_BACKUP_SRC = "MANIFEST_SRC=0x00041000"
# The one console token that proves decryption ran: printed only after the
# ciphertext hash verified, the AES engine drained and the PKCS#7 pad stripped.
# PAYLOAD_OK and DECRYPTION_START are deliberately NOT used -- see check_console.
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
    "PLD_HASH_TIMEOUT",
    "RSA_PKCS1_FAIL",
    "RSA_PKCS1_FAIL",
)


@pyuvm.test()
class sep_decryption_failure_terminal_test(sep_backup_manifest_fail_base):
    """Corrupt BOTH slots' ciphertext; decryption must run and the boot must end."""

    flash_image = _ENCRYPTED_IMAGE
    efuse_preload = _EFUSE_PRELOAD
    backup_defect_marker = _DECRYPT_OK
    #  -- the sub-code variant (b) converges on, reached only after
    # the plaintext has been produced and found not to be a TOC.
    expected_error = pm.MANIFEST_ERR_BAD_TOC_ID

    # --- stimulus ------------------------------------------------------------
    def corrupt_primary(self, buf: bytearray) -> None:
        base = pm.payload_base(buf, "primary")
        before = bytes(buf[base : base + 16])
        at = pm.corrupt_ciphertext(buf, "primary")
        new = buf[at]
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
        """The same defect in the backup, which is what makes the boot terminal.

        Under bundle-level failover a single corrupted slot is recovered from, so
        a testcase that wants the TERMINAL arm has to exhaust both. See the module
        docstring; ``sep_decryption_failure_failover_test`` covers the one-slot
        shape.
        """
        base = pm.payload_base(buf, "backup")
        before = bytes(buf[base : base + 16])
        at = pm.corrupt_ciphertext(buf, "backup")
        after = bytes(buf[base : base + 16])
        assert before != after, "the backup ciphertext flip did not change the image"
        self.logger.info(
            "CHK-STIMULUS-CIPHERTEXT-BACKUP: backup payload flash byte 0x%x -> 0x%02x; "
            "CBC block 0 %s -> %s; manifest re-hashed and re-signed",
            at,
            buf[at],
            before.hex(),
            after.hex(),
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
        # it, the terminal error alone is satisfied by a run in which decryption
        # never happened.
        #
        # DECRYPT_OK is the ONLY console token that carries this, and it carries
        # all of it: plat_decrypt_payload() reaches that simputs only after the
        # library has verified payload_hash over the CIPHERTEXT -- it calls this
        # callback only once that passes -- and after aes_cbc_decrypt() and
        # aes_pkcs7_strip() have both returned 0 (oca_platform.c).
        #
        # The two markers this once looked for cannot appear. DECRYPTION_START is
        # a status-ring entry (SEP_MSG_DECRYPTION_START), never a simputs, so it
        # is not on the console at all. PAYLOAD_OK is printed only after the
        # ENTIRE payload validates (oca_boot.c), which by construction cannot
        # happen here -- the plaintext is deliberately not a TOC. Requiring it
        # made the testcase unsatisfiable by its own stimulus.
        i_ok = index_of(_DECRYPT_OK)
        assert i_ok >= 0, (
            f"ROM never printed {_DECRYPT_OK}: decryption did not run to "
            f"completion, so nothing about the post-decrypt verdict is being "
            f"tested. A corrupted block 0 must still decrypt and strip padding "
            f"cleanly -- CBC is a permutation and the pad lives in the LAST block "
            f"-- so this means the engine or the class key is wrong rather than "
            f"the plaintext. Console: {console}"
        )
        log.info("CHK-DECRYPT-RAN PASS: %s@%d, before the terminal verdict", _DECRYPT_OK, i_ok)

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
        # STATUS_ENCODE(type, SEP_MSG_*), translated through the ROM's own
        # status_for_result(); the console code's low half is the result number,
        # not a status value.
        expected_status = 0x0F01_0000 | mm.rom_status_for_result(self.expected_error)
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

        # CHK-BOTH-SLOTS-REFUSED: the backup IS read -- bundle-level failover makes
        # that correct -- and is then refused for the same reason, which is what
        # exhausts the retry loop and makes the outcome terminal. Asserting the
        # order rather than mere presence is what separates this from a run that
        # never failed over at all.
        i_backup = index_of(_BACKUP_SRC)
        assert 0 <= i_err < i_backup, (
            f"expected the primary's {err_marker}({i_err}) BEFORE the backup read "
            f"{_BACKUP_SRC}({i_backup}): the ROM must fail over to the backup and "
            f"refuse it too, not stop at the primary. Console: {console}"
        )
        n_err = sum(1 for line in console if err_marker in line)
        assert n_err == 2, (
            f"{err_marker} appeared {n_err} times, expected exactly 2 -- one per "
            f"slot, because both carry the same ciphertext defect. Console: {console}"
        )
        log.info(
            "CHK-BOTH-SLOTS-REFUSED PASS: %s twice, straddling the backup read@%d",
            err_marker,
            i_backup,
        )

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
