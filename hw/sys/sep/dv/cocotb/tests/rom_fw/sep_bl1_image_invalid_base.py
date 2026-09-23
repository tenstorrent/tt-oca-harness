# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared base for testcases that plant the same BL1 size or entry-point defect in both slots.

Both slots must pass the crypto chain and then fail the payload check, so the run must end on
MANIFEST_ALL_FAILED and the ROM must halt before any BL1 copy or jump.
"""

from __future__ import annotations

from pathlib import Path

from rom_fw.sep_backup_manifest_fail_base import sep_backup_manifest_fail_base

_EFUSE_DIR = (Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads"
              / "efuse_configurations")
_EFUSE_LC_PROD = _EFUSE_DIR / "sep_efuse_lc_prod.toml"

_PRIMARY_SRC = "MANIFEST_SRC=0x00001000"
_BACKUP_SRC = "MANIFEST_SRC=0x00041000"

_CRYPTO_OK = "CRYPTO_VALIDATE_OK"
_ALL_FAILED = "MANIFEST_ALL_FAILED"
_SBOOT_OFF = "SBOOT_OFF"

# "LOAD=" is not a marker: it is a substring of the ordinary "PAYLOAD=" line.
_BL1_PROGRESS = ("BL1_TYPE=", "COPY_SRC=", "COPY_DST=", "COPY_LEN=", "BL1_COPIED",
                 "PRE_JUMP", "BL1_JUMP=")

_OTHER_REJECTIONS = (
    "PLD_HASH_MISMATCH", "PLD_HASH_TIMEOUT", "RSA_VERIFY_FAIL", "RSA_PKCS1_FAIL",
    "SIG_VALID_FAIL", "TOC_PLEN_MISMATCH", "TOC_REGION_OOB", "IMAGE_ORDER_BAD",
    "IMAGE_HASH_MISMATCH", "IMAGE_HASH_TIMEOUT", "NO_BL1_IMAGE",
    "LC_USAGE_CONSTRAINT_FAIL", "ENC_WITHOUT_SBOOT", "FLASH_REINIT_FAIL",
)


class sep_bl1_image_invalid_base(sep_backup_manifest_fail_base):

    efuse_preload = _EFUSE_LC_PROD

    sibling_markers: tuple[str, ...] = ()

    def mutate_bl1(self, buf: bytearray, slot: str) -> None:
        raise NotImplementedError

    def corrupt_primary(self, buf: bytearray) -> None:
        self.mutate_bl1(buf, "primary")

    def corrupt_backup(self, buf: bytearray) -> None:
        self.mutate_bl1(buf, "backup")

    def check_defect_attribution(self, console, i_backup: int) -> None:
        # The primary has the same defect, so require one marker on each side of the backup read.
        hits = [i for i, line in enumerate(console) if self.backup_defect_marker in line]
        assert len(hits) >= 2, (
            f"{self.backup_defect_marker} appeared {len(hits)} time(s) at {hits}; both "
            f"slots carry this defect, so it must be printed once for each. "
            f"Console: {console}"
        )
        assert hits[0] < i_backup, (
            f"first {self.backup_defect_marker} at line {hits[0]} did not precede the "
            f"backup read at line {i_backup}: the primary's own defect was not "
            f"reported, so the primary may have been rejected for another reason"
        )
        assert any(i > i_backup for i in hits), (
            f"{self.backup_defect_marker} never appeared after the backup read at line "
            f"{i_backup} (occurrences {hits}): the backup slot's BL1 entry was "
            f"never evaluated"
        )
        self.logger.info(
            "CHK-BL1-DEFECT: %s reported for both slots (lines %s, backup read at %d)",
            self.backup_defect_marker, hits, i_backup,
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

        def count_of(marker: str) -> int:
            return sum(1 for line in console if marker in line)

        assert retired, "core retired no instructions; the ROM never ran"
        assert console, (
            "ROM console is empty, so no marker check below means anything (the "
            "virt console is DEBUG-build only -- check the ROM build)"
        )

        err_marker = f"MANIFEST_ERR=0x{self.expected_error:08x}"
        i_primary = index_of(_PRIMARY_SRC)
        i_backup = index_of(_BACKUP_SRC)

        # Check order, not only presence: a ROM that read the backup first also prints both markers.
        assert i_primary >= 0, (
            f"ROM never read the primary slot ({_PRIMARY_SRC}). Console: {console}"
        )
        assert i_backup >= 0, (
            f"ROM never fell over to the backup slot ({_BACKUP_SRC}); the procedure "
            f"requires the backup to be attempted and to fail too. Console: {console}"
        )
        assert i_primary < i_backup, (
            f"backup slot was read at line {i_backup}, before the primary at line "
            f"{i_primary}: this is not a primary-then-backup retry"
        )
        log.info("CHK-FAILOVER: primary at %s (line %d), then backup at %s (line %d)",
                 _PRIMARY_SRC, i_primary, _BACKUP_SRC, i_backup)

        # Both slots must clear crypto first, or the defect was not caught by the payload check.
        assert not any(_SBOOT_OFF in line for line in console), (
            f"ROM printed {_SBOOT_OFF}: secure boot was skipped, so this run "
            f"reached the BL1 check by a path production does not take. "
            f"Console: {console}"
        )
        n_crypto = count_of(_CRYPTO_OK)
        assert n_crypto >= 2, (
            f"{_CRYPTO_OK} appeared {n_crypto} time(s); both slots must clear the "
            f"whole crypto chain (security version, RSA signature, payload hash) "
            f"before their payload is validated, so a count below two means a slot "
            f"was rejected earlier and the BL1 verdict below is not what stopped "
            f"it. Console: {console}"
        )
        log.info("CHK-CRYPTO-RAN: %s seen %d times; signature and payload hash "
                 "verified on both slots", _CRYPTO_OK, n_crypto)

        self.check_defect_attribution(console, i_backup)

        n_err = count_of(err_marker)
        assert n_err >= 2, (
            f"{err_marker} appeared {n_err} time(s); each slot must be rejected "
            f"with the error this defect produces. Console: {console}"
        )
        assert any(_ALL_FAILED in line for line in console), (
            f"ROM never printed {_ALL_FAILED}; the retry loop did not exhaust both "
            f"slots. Console: {console}"
        )
        expected_status = 0x0F01_0000 | (self.expected_error & 0xFFFF)
        assert expected_status in status_seq, (
            f"cold_scratch[1] never held 0x{expected_status:08x} "
            f"(STATUS_ENCODE(ERROR, 0x{self.expected_error & 0xFFFF:04x})); "
            f"observed {status_hex}"
        )
        log.info("CHK-REJECT-REASON: %s on both slots, %s, cold_scratch[1]=0x%08x",
                 err_marker, _ALL_FAILED, expected_status)

        for marker in _OTHER_REJECTIONS + tuple(self.sibling_markers):
            assert not any(marker in line for line in console), (
                f"ROM printed {marker}: the image is wrong in a way this testcase "
                f"did not plant, so the verdict cannot be attributed to the defect "
                f"under test. Console: {console}"
            )
        log.info("CHK-ONLY-REASON: no other rejection reason appeared")

        assert fw_done, (
            f"ROM never signalled completion; a manifest that fails every slot must "
            f"converge on a mailbox FAIL. cold_scratch[1]: {status_hex}"
        )
        assert not fw_pass, (
            "ROM signalled PASS: it booted an image it was supposed to reject"
        )
        log.info("CHK-TERMINAL: mailbox FAIL (fw_pass=0)")

        for marker in _BL1_PROGRESS:
            assert not any(marker in line for line in console), (
                f"ROM printed {marker}, which rom_handoff.c emits while loading or "
                f"entering BL1: the image was rejected too late, after BL0 had "
                f"already begun the handoff. Console: {console}"
            )
        log.info("CHK-NO-HANDOFF: none of %s reached, so BL1 was never copied or "
                 "entered", ", ".join(_BL1_PROGRESS))
