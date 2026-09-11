# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Both slots refused inside the manifest loop; the run is terminal.

Sibling of :mod:`sep_backup_manifest_fail_base`, and a subclass of it so the whole
run harness -- OTP preload, flash BFM, console decoder, verdict poll and the
post-verdict quiescence window -- is shared rather than copied. Only the checker
differs, and it differs for a structural reason.

WHY A SEPARATE CHECKER. The parent grades a backup that passed the manifest loop
and then failed the crypto chain, so it requires ``CRYPTO_FAIL=``. The defects
here -- a bad ``manifest_identifier``, and the three usage-constraint arms -- are
refused EARLIER, by ``validate_manifest_header`` or by the ``selector_bits``
block, so ``manifest_crypto_validate`` is never entered on either slot and
``CRYPTO_FAIL=`` can never appear. Requiring it would fail every member of this
family, and relaxing the parent's requirement would weaken the testcases that
legitimately depend on it.

Such a run converges on ``MANIFEST_ALL_FAILED`` with the backup's error code, and
prints no ``MANIFEST_OK`` either -- that token is emitted only after a slot passes
in full (``bootrom/prod/src/manifest_load.c``), so it is forbidden here as
positive evidence that no slot got that far.

WHAT ATTRIBUTES A VERDICT TO A SLOT. There is no per-reason status code for any
of these rejections -- see :mod:`sep_manifest_field_defect` -- so each member pins
its verdict with three things instead, all asserted below:

  * the ORDER ``primary read -> primary error -> backup read -> backup error ->
    MANIFEST_ALL_FAILED``, which a run that never reached the backup cannot
    produce;
  * the backup's own error code, DISTINCT from the primary's, so the two slots'
    rejections are individually countable. Every member therefore has to declare
    ``primary_expected_error != expected_error``, and this base refuses to run
    otherwise;
  * the terminal status word ``STATUS_ENCODE(ERROR, expected_error)``, which is
    the ROM's own convergence rather than the console's account of it.
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
    """Primary refused, backup refused for the planted reason, ROM halts."""

    # Set by the subclass to the arm's own console token, or left as the backup's
    # ``MANIFEST_ERR=`` line when the defect produces no token of its own.
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

        # Guard the guards: a dark console makes every marker check trivially satisfied.
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

        # CHK-FAILOVER: both slots were read, in order, and the loop then gave up.
        # Without the ordering this would also be satisfied by a backup-first run,
        # which is not the scenario.
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

        # CHK-PRIMARY: the failover trigger fired, and it is the primary's.
        fd.assert_slot_attributed(console, primary_err, after=i_psrc,
                                  before=i_bsrc)
        log.info("CHK-FAILOVER-PRIMARY: primary@%d rejected with %s before the "
                 "backup read@%d", i_psrc, primary_err, i_bsrc)

        # CHK-DEFECT: the backup was refused for the planted reason, inside its own
        # attempt. The error code carries the attribution for a structural defect;
        # a member whose arm prints a token of its own names it as well.
        fd.assert_slot_attributed(console, backup_err, after=i_bsrc, before=i_all)
        if self.backup_defect_marker and self.backup_defect_marker != backup_err:
            fd.assert_slot_attributed(console, self.backup_defect_marker,
                                      after=i_bsrc, before=i_all)
        log.info("CHK-BACKUP-DEFECT: %s and %s both inside the backup attempt "
                 "(lines %d..%d)", backup_err, self.backup_defect_marker or backup_err,
                 i_bsrc, i_all)

        # CHK-NO-CRYPTO: neither slot reached manifest_crypto_validate. These
        # defects are refused upstream of it, so a run that verified a signature
        # took a different path and its verdict is not this testcase's.
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

        # CHK-TERMINAL: the ROM converged on the BACKUP's code. The status word is
        # the independent half -- the console says which check complained, the
        # encoded status says what rom_err_fail() was handed
        # (bootrom/prod/src/rom_main.c).
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

        # CHK-NO-BOOT: nothing downstream of the rejection ran.
        for marker in _BOOT_PROGRESS_MARKERS + tuple(self.extra_forbidden):
            assert not any(marker in line for line in console), (
                f"ROM printed {marker}, which sits past the rejection: it "
                f"continued booting a manifest it had already failed. "
                f"Console: {console}"
            )
        log.info("CHK-NO-BOOT: none of %s reached",
                 ", ".join(_BOOT_PROGRESS_MARKERS + tuple(self.extra_forbidden)))
