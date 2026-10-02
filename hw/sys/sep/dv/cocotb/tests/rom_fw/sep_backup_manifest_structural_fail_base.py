# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared base: both slots are refused in the manifest stage before key selection; the ROM halts.

Each ``MANIFEST_SRC=`` attempt is checked on its own; the run then prints
``MANIFEST_ALL_FAILED`` once and halts on a FAIL verdict.
"""

from __future__ import annotations

from env import sep_manifest_mutate as mm
from env import sep_oca_console as oc
from rom_fw.sep_backup_manifest_fail_base import (
    MANIFEST_ERR_BAD_MAGIC,
    sep_backup_manifest_fail_base,
)

_ALL_FAILED = "MANIFEST_ALL_FAILED"
_ERR = "MANIFEST_ERR="
_SBOOT_OFF = "SBOOT_OFF"
_BOOT_PROGRESS_MARKERS = ("PRE_JUMP", "BL1_COPIED", "BL1_JUMP=")
# Printed from key selection onwards; a refusal before it prints none of them.
_PAST_STRUCTURE = ("PUBK_SEL=", "PUBK_AUTHORIZED", "PUBK_REVOKE=", "FUSE_VER=", "RSA_EXEC")
_MANIFEST_OK = "MANIFEST_OK"
_RETIRED_FIELDS = ("requires_defect_marker", "backup_sealed_check_toc")


def err_marker(code: int) -> str:
    return f"{_ERR}0x{code:08x}"


class sep_backup_manifest_structural_fail_base(sep_backup_manifest_fail_base):
    # --- subclass contract -------------------------------------------------
    # Printed once, on or just before the backup's error line; a silent arm uses err_marker().
    backup_defect_marker: str = ""
    # ROM error code the backup, and so the run, must end with.
    expected_error: int = 0
    # Markers the backup prints before its defect marker, in ROM order.
    backup_ordered: tuple[str, ...] = ()
    # Markers that must not appear inside the backup attempt.
    backup_absent: tuple[str, ...] = ()
    # The primary's refusal; the default is corrupt_primary()'s broken magic word.
    primary_expected_error: int = MANIFEST_ERR_BAD_MAGIC
    # Markers the primary prints before its error line, in ROM order.
    primary_ordered: tuple[str, ...] = ()
    # A broken magic is refused by the peek, before the ROM sizes the body.
    primary_absent: tuple[str, ...] = ("OCA_BODY=",)

    # --- contract checks -----------------------------------------------------
    @staticmethod
    def _check_contract(obj) -> None:
        # obj is a class at import time and the instance at run time.
        concrete = not isinstance(obj, type)
        name = type(obj).__name__ if concrete else obj.__name__
        oc.assert_known(
            tuple(obj.extra_forbidden)
            + tuple(obj.backup_ordered)
            + tuple(obj.backup_absent)
            + tuple(obj.primary_ordered)
            + tuple(obj.primary_absent)
            + ((obj.backup_defect_marker,) if obj.backup_defect_marker else ()),
            name,
        )
        stale = [f for f in _RETIRED_FIELDS if hasattr(obj, f)]
        assert not stale, f"{name}: {stale} are not read by this base; remove them"
        marker = obj.backup_defect_marker
        if marker.startswith(_ERR) and obj.expected_error:
            assert marker == err_marker(obj.expected_error), (
                f"{name}: backup_defect_marker {marker} is an error line other than the "
                f"expected {err_marker(obj.expected_error)}"
            )
        if concrete:
            assert obj.expected_error and obj.primary_expected_error, (
                f"{name}: set expected_error and primary_expected_error"
            )
            assert obj.expected_error != obj.primary_expected_error, (
                f"{name}: both slots refused with 0x{obj.expected_error:08x}; the "
                f"terminal code would not identify the backup"
            )
            assert marker, (
                f"{name}: set backup_defect_marker to the arm's own marker, or to "
                f"err_marker(expected_error) when the arm prints none"
            )

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        cls._check_contract(cls)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._check_contract(self)

    # --- checks ------------------------------------------------------------
    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        log = self.logger
        status_hex = [hex(v) for v in status_seq]
        log.info("cold_scratch[1] sequence: %s", status_hex)
        log.info("ROM console: %s", console)

        assert retired, "core retired no instructions; the ROM never ran"
        assert console, (
            "ROM console is empty, so no marker check below means anything (the "
            "virt console is DEBUG-build only -- check the ROM build)"
        )

        attempts = oc.split_attempts(console)
        srcs = [f"0x{a.src:08x}" for a in attempts]
        want = [f"0x{mm.PRIMARY_MANIFEST_OFFSET:08x}", f"0x{mm.BACKUP_MANIFEST_OFFSET:08x}"]
        assert srcs == want, (
            f"slot attempts read {srcs}, expected {want}: the primary then the backup, "
            f"once each. Console: {console}"
        )
        primary, backup = attempts

        # The slot headers precede MANIFEST_SRC=, so they sit outside both attempts.
        def lines_with(token: str) -> list[int]:
            return [i for i, line in enumerate(console) if oc.count([line], token)]

        i_ph, i_bh, i_all = (
            lines_with("MANIFEST_PRIMARY"),
            lines_with("MANIFEST_BACKUP"),
            lines_with(_ALL_FAILED),
        )
        assert len(i_ph) == 1 and i_ph[0] < primary.first, (
            f"MANIFEST_PRIMARY@{i_ph} is not once before the primary attempt@{primary.first}"
        )
        assert len(i_bh) == 1 and primary.last < i_bh[0] < backup.first, (
            f"MANIFEST_BACKUP@{i_bh} is not once between the primary error@{primary.last} "
            f"and the backup attempt@{backup.first}"
        )
        # The outcome leads the message: the runner keeps only its first 400 characters.
        assert len(i_all) == 1 and backup.last < i_all[0], (
            f"{_ALL_FAILED}@{i_all} is not once after the backup error@{backup.last}: "
            f"the ROM did not give up after evaluating the backup (backup attempt "
            f"{backup.stage}). Console: {console}"
        )

        p_ordered = tuple(self.primary_ordered) + (err_marker(self.primary_expected_error),)
        p_absent = tuple(self.primary_absent) + _PAST_STRUCTURE
        oc.assert_attempt(
            primary,
            error=self.primary_expected_error,
            stage="manifest",
            ordered=p_ordered,
            absent=p_absent,
        )
        log.info(
            "CHK-FAILOVER-PRIMARY PASS: primary@%d-%d refused 0x%08x after %s; none of %s",
            primary.first,
            primary.last,
            self.primary_expected_error,
            " -> ".join(p_ordered),
            ", ".join(p_absent),
        )

        b_ordered = tuple(self.backup_ordered) + (self.backup_defect_marker,)
        b_absent = tuple(self.backup_absent) + _PAST_STRUCTURE
        oc.assert_attempt(
            backup,
            error=self.expected_error,
            stage="manifest",
            ordered=b_ordered,
            absent=b_absent,
        )
        tail = [line for _, line in backup.markers][-2:]
        assert oc.count(tail, self.backup_defect_marker) == 1, (
            f"{self.backup_defect_marker} is not the backup's error line or the line just "
            f"before it (attempt ends {tail}): a later check also refused the slot"
        )

        for marker, want_n in ((_ERR, 2), (_MANIFEST_OK, 0), ("RSA_EXEC", 0)) + tuple(
            (m, 1) for m in b_ordered if m not in p_ordered
        ):
            n = oc.count(console, marker)
            assert n == want_n, (
                f"{marker} appeared {n} times, expected exactly {want_n}. Console: {console}"
            )
        log.info(
            "CHK-BACKUP-DEFECT PASS: backup@%d-%d refused 0x%08x after %s; none of %s; %s@%d",
            backup.first,
            backup.last,
            self.expected_error,
            " -> ".join(b_ordered),
            ", ".join(b_absent),
            _ALL_FAILED,
            i_all[0],
        )

        status_msg = mm.rom_status_for_result(self.expected_error)
        expected_status = 0x0F01_0000 | status_msg
        assert expected_status in status_seq, (
            f"cold_scratch[1] never held 0x{expected_status:08x} "
            f"(STATUS_ENCODE(ERROR, 0x{status_msg:04x})); "
            f"observed {status_hex}"
        )
        assert fw_done, (
            f"ROM never signalled completion; two rejected slots must converge on "
            f"a FAIL verdict. cold_scratch[1]: {status_hex}"
        )
        assert not fw_pass, "ROM signalled PASS: it booted an image it was supposed to reject"
        log.info(
            "CHK-TERMINAL PASS: %s, %s, cold_scratch[1]=0x%08x, verdict FAIL",
            err_marker(self.expected_error),
            _ALL_FAILED,
            expected_status,
        )

        never = (_SBOOT_OFF,) + _BOOT_PROGRESS_MARKERS + tuple(self.extra_forbidden)
        for marker in never:
            assert oc.count(console, marker) == 0, (
                f"ROM printed {marker}: secure boot was skipped, or the ROM continued "
                f"past a rejection it had already made. Console: {console}"
            )
        log.info("CHK-NO-BOOT: none of %s reached", ", ".join(never))
