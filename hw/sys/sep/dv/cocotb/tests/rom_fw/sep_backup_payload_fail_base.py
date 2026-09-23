# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared base for testcases where the backup passes its signature check but fails its payload.

The backup's crypto chain must run exactly once, CRYPTO_FAIL= and MANIFEST_OK must not appear, and
the run must end on MANIFEST_ALL_FAILED with the backup's own error code. The ROM must then halt.
"""

from __future__ import annotations

from rom_fw.sep_backup_manifest_fail_base import sep_backup_manifest_fail_base
from rom_fw import sep_manifest_field_defect as fd

_ALL_FAILED = "MANIFEST_ALL_FAILED"
_MANIFEST_OK = "MANIFEST_OK"
_HASH_OK = "MANIFEST_HASH_OK"
_CRYPTO_FAIL = "CRYPTO_FAIL="
_SBOOT_OFF = "SBOOT_OFF"
_BOOT_PROGRESS_MARKERS = ("PRE_JUMP", "BL1_COPIED", "BL1_JUMP=")

# Printed only on the signed path, in this order.
_CRYPTO_CHAIN = ("RSA_VERIFY_START", "SIG_VALID", "PLD_HASH_OK",
                 "CRYPTO_VALIDATE_OK")


class sep_backup_payload_fail_base(sep_backup_manifest_fail_base):

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
        if not self.backup_defect_marker:
            assert type(self)._check is not sep_backup_payload_fail_base._check, (
                f"{type(self).__name__} declares no backup_defect_marker and adds "
                f"no checks of its own. The silent payload arms leave only the "
                f"error code, which several arms could produce; a member here must "
                f"override _check to forbid the codes it could be confused with "
                f"and to assert what the flash device served"
            )
            neighbours = [m for m in self.extra_forbidden
                          if m.startswith("MANIFEST_ERR=")]
            assert neighbours, (
                f"{type(self).__name__} declares no backup_defect_marker and "
                f"forbids no neighbouring MANIFEST_ERR= code, so a rejection by a "
                f"different payload arm would satisfy this run"
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

        previous = i_bsrc
        positions = []
        for marker in _CRYPTO_CHAIN:
            n = fd.count(console, marker)
            assert n == 1, (
                f"{marker} appeared {n} times, expected exactly 1 (the backup's). "
                f"A second occurrence would mean the primary also reached the "
                f"crypto chain, which this family does not plant. Console: {console}"
            )
            i = fd.first_index(console, marker)
            assert previous < i < i_all, (
                f"{marker}@{i} does not sit between the previous stage@{previous} "
                f"and {_ALL_FAILED}@{i_all}: the backup's crypto chain is out of "
                f"order or outside its own attempt. Chain so far: "
                f"{list(zip(_CRYPTO_CHAIN, positions))}. Console: {console}"
            )
            positions.append(i)
            previous = i
        i_hash_ok = fd.first_index(console, _HASH_OK, after=i_bsrc)
        assert i_bsrc < i_hash_ok < positions[0], (
            f"{_HASH_OK}@{i_hash_ok} does not sit between the backup read@{i_bsrc} "
            f"and its {_CRYPTO_CHAIN[0]}@{positions[0]}: the backup's integrity "
            f"check is not part of its own attempt. Console: {console}"
        )
        log.info("CHK-BACKUP-CRYPTO: backup read@%d -> %s@%d -> %s -- signature "
                 "verified before the payload was refused", i_bsrc, _HASH_OK,
                 i_hash_ok, ", ".join(f"{m}@{p}" for m, p in
                                      zip(_CRYPTO_CHAIN, positions)))

        after = positions[-1]
        if self.backup_defect_marker:
            after = fd.assert_slot_attributed(console, self.backup_defect_marker,
                                              after=positions[-1], before=i_all)
        fd.assert_slot_attributed(console, backup_err, after=after, before=i_all)
        log.info("CHK-BACKUP-DEFECT: %s then %s, both after CRYPTO_VALIDATE_OK@%d "
                 "and inside the backup attempt (..%d)",
                 self.backup_defect_marker or "(this arm prints no token)",
                 backup_err, positions[-1], i_all)

        assert not any(_CRYPTO_FAIL in line for line in console), (
            f"ROM printed {_CRYPTO_FAIL}: a slot was refused inside "
            f"manifest_crypto_validate, so the payload rejection under test is not "
            f"what ended this run. Console: {console}"
        )
        assert not any(_MANIFEST_OK in line for line in console), (
            f"ROM printed {_MANIFEST_OK}: a slot passed in full, so neither slot "
            f"was refused. Console: {console}"
        )
        assert not any(_SBOOT_OFF in line for line in console), (
            f"ROM printed {_SBOOT_OFF}: a slot took the secure-boot-disabled path, "
            f"so the backup's signature was never verified. Console: {console}"
        )
        log.info("CHK-NOT-A-CRYPTO-FAILURE: neither %s, %s nor %s appeared",
                 _CRYPTO_FAIL, _MANIFEST_OK, _SBOOT_OFF)

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
