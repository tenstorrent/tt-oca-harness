# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared base for testcases where both manifest slots fail a structural or usage-constraint check.

Neither slot reaches the crypto chain, so the run must end on MANIFEST_ALL_FAILED with the
backup's own error code, which must differ from the primary's. The ROM must then halt.
"""

from __future__ import annotations

from rom_fw.sep_backup_manifest_fail_base import sep_backup_manifest_fail_base
from rom_fw import sep_manifest_field_defect as fd

_ALL_FAILED = "MANIFEST_ALL_FAILED"
_MANIFEST_OK = "MANIFEST_OK"
_CRYPTO_ENTERED = "RSA_VERIFY_START"
_SBOOT_OFF = "SBOOT_OFF"
_BOOT_PROGRESS_MARKERS = ("PRE_JUMP", "BL1_COPIED", "BL1_JUMP=")


class sep_backup_manifest_structural_fail_base(sep_backup_manifest_fail_base):

    backup_defect_marker: str = ""
    expected_error: int = 0
    primary_expected_error: int = 0

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        log = self.logger
        status_hex = [hex(v) for v in status_seq]
        log.info("cold_scratch[1] sequence: %s", status_hex)
        log.info("ROM console: %s", console)

        assert self.expected_error and self.primary_expected_error, (
            "subclass must declare both primary_expected_error and expected_error"
        )
        assert self.expected_error != self.primary_expected_error, (
            f"primary_expected_error and expected_error are both "
            f"0x{self.expected_error:08x}: the two slots' rejections would be "
            f"indistinguishable on the console, so nothing would attribute the "
            f"terminal verdict to the backup"
        )

        assert retired, "core retired no instructions; the ROM never ran"
        assert console, (
            "ROM console is empty, so no marker check below means anything (the "
            "virt console is DEBUG-build only -- check the ROM build)"
        )

        primary_err = f"MANIFEST_ERR=0x{self.primary_expected_error:08x}"
        backup_err = f"MANIFEST_ERR=0x{self.expected_error:08x}"
        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)
        i_all = fd.first_index(console, _ALL_FAILED)

        # Check order, not only presence: a backup-first run would also print both markers.
        assert i_psrc >= 0, (
            f"ROM never read the primary slot ({fd.PRIMARY_SRC}). Console: {console}"
        )
        assert i_psrc < i_bsrc, (
            f"backup slot ({fd.BACKUP_SRC}@{i_bsrc}) was not read after the "
            f"primary@{i_psrc}: this is not a failover. Console: {console}"
        )
        assert i_bsrc < i_all, (
            f"{_ALL_FAILED}@{i_all} did not follow the backup read@{i_bsrc}: the "
            f"ROM gave up before evaluating the backup. Console: {console}"
        )

        fd.assert_slot_attributed(console, primary_err, after=i_psrc,
                                  before=i_bsrc)
        log.info("CHK-FAILOVER-PRIMARY: primary@%d rejected with %s before the "
                 "backup read@%d", i_psrc, primary_err, i_bsrc)

        fd.assert_slot_attributed(console, backup_err, after=i_bsrc, before=i_all)
        if self.backup_defect_marker and self.backup_defect_marker != backup_err:
            fd.assert_slot_attributed(console, self.backup_defect_marker,
                                      after=i_bsrc, before=i_all)
        log.info("CHK-BACKUP-DEFECT: %s and %s both inside the backup attempt "
                 "(lines %d..%d)", backup_err, self.backup_defect_marker or backup_err,
                 i_bsrc, i_all)

        for marker in (_MANIFEST_OK, _CRYPTO_ENTERED):
            assert not any(marker in line for line in console), (
                f"ROM printed {marker}: a slot passed the structural checks and "
                f"entered the crypto chain, so the rejection under test is not "
                f"what ended this run. Console: {console}"
            )
        assert not any(_SBOOT_OFF in line for line in console), (
            f"ROM printed {_SBOOT_OFF}: a slot took the secure-boot-disabled path. "
            f"Console: {console}"
        )
        log.info("CHK-NO-CRYPTO: neither slot printed %s, %s or %s",
                 _MANIFEST_OK, _CRYPTO_ENTERED, _SBOOT_OFF)

        expected_status = 0x0F01_0000 | (self.expected_error & 0xFFFF)
        assert expected_status in status_seq, (
            f"cold_scratch[1] never held 0x{expected_status:08x} "
            f"(STATUS_ENCODE(ERROR, 0x{self.expected_error & 0xFFFF:04x})); "
            f"observed {status_hex}"
        )
        assert fw_done, (
            f"ROM never signalled completion; two rejected slots must converge on "
            f"a FAIL verdict. cold_scratch[1]: {status_hex}"
        )
        assert not fw_pass, (
            "ROM signalled PASS: it booted an image it was supposed to reject"
        )
        log.info("CHK-TERMINAL: %s, %s, cold_scratch[1]=0x%08x, verdict FAIL",
                 backup_err, _ALL_FAILED, expected_status)

        for marker in _BOOT_PROGRESS_MARKERS + tuple(self.extra_forbidden):
            assert not any(marker in line for line in console), (
                f"ROM printed {marker}, which sits past the rejection: it "
                f"continued booting a manifest it had already failed. "
                f"Console: {console}"
            )
        log.info("CHK-NO-BOOT: none of %s reached",
                 ", ".join(_BOOT_PROGRESS_MARKERS + tuple(self.extra_forbidden)))
