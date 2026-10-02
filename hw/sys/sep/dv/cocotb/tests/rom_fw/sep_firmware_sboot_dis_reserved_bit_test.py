# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD with only a reserved SBOOT_DIS bit set: secure boot stays on and both unsigned slots are refused.

Only bit 0 of SBOOT_DIS disables secure boot, so 0x2 leaves PROD enforcing it; each unsigned
slot fails ``OCA_FAIL_SIGNATURE_CLASS_CONTROL`` before key selection and the ROM halts.
"""

from __future__ import annotations

import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_oca_console as oc
from rom_fw.sep_backup_manifest_fail_base import (
    MANIFEST_ERR_SIG_CLASS_CONTROL,
    sep_backup_manifest_fail_base,
)
from rom_fw.sep_fuse_lock_base import EFUSE_DIR, UNSIGNED_FLASH_IMAGE

_SBOOT_DIS_VALUE = 0x2
_SBOOT_DIS_DECODED = "FUSE: SBOOT_DIS: 0"
_SBOOT_DIS_SET = "FUSE: SBOOT_DIS: 1"
_SBOOT_OFF = "SBOOT_OFF"
_LC_PROD = "LC=PROD"
_BODY = "OCA_BODY="
_ALL_FAILED = "MANIFEST_ALL_FAILED"
_ERR = "MANIFEST_ERR="
_ERR_LINE = f"{_ERR}0x{MANIFEST_ERR_SIG_CLASS_CONTROL:08x}"
_PAST_DETERMINATION = (
    "PUBK_SEL=",
    "PUBK_NO_SIGNATURE",
    "PUBK_AUTHORIZED",
    "PUBK_REVOKE=",
    "FUSE_VER=",
    "RSA_EXEC",
    "MANIFEST_OK",
)
_BOOT_PROGRESS = ("PAYLOAD_OK", "PRE_JUMP", "BL1_COPIED", "BL1_JUMP=")


@pyuvm.test()
class sep_firmware_sboot_dis_reserved_bit_test(sep_backup_manifest_fail_base):
    """PROD + SBOOT_DIS=0x2 + unsigned image -> both slots SIGNATURE_CLASS_CONTROL -> halt."""

    efuse_preload = EFUSE_DIR / "sep_efuse_lc_prod_sboot_dis_rsvd.toml"
    flash_image = UNSIGNED_FLASH_IMAGE
    backup_defect_marker = _ERR_LINE
    expected_error = MANIFEST_ERR_SIG_CLASS_CONTROL

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        oc.assert_known(
            (_SBOOT_DIS_DECODED, _SBOOT_DIS_SET, _SBOOT_OFF, _LC_PROD, _BODY, _ALL_FAILED)
            + _PAST_DETERMINATION
            + _BOOT_PROGRESS,
            type(self).__name__,
        )

    def check_efuse(self, image) -> None:
        value = image.field_int("SBOOT_DIS")
        assert value == _SBOOT_DIS_VALUE, (
            f"SBOOT_DIS is 0x{value:x}, expected 0x{_SBOOT_DIS_VALUE:x}: only a reserved "
            f"bit set, disable_secure_boot clear"
        )
        self.logger.info("CHK-STIMULUS-SBOOT-DIS: SBOOT_DIS=0x%x, disable_secure_boot=0", value)

    def _check_unsigned(self, buf, slot: str) -> None:
        control = mm.secure_boot_control(buf, slot)
        assert control == 0, (
            f"{slot} secure_boot_control is 0x{control:02x}: the image must neither request "
            f"secure boot nor name a signature class, so the device inputs alone decide"
        )

    def corrupt_primary(self, buf: bytearray) -> None:
        self._check_unsigned(buf, "primary")

    def corrupt_backup(self, buf: bytearray) -> None:
        self._check_unsigned(buf, "backup")

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

        for marker, want_n in ((_LC_PROD, 1), (_SBOOT_DIS_DECODED, 1), (_SBOOT_DIS_SET, 0)):
            n = oc.count(console, marker)
            assert n == want_n, (
                f"{marker} appeared {n} times, expected {want_n}. Console: {console}"
            )
        n_off = oc.count(console, _SBOOT_OFF)
        assert n_off == 0, (
            f"SBOOT_DIS=0x{_SBOOT_DIS_VALUE:x}: ROM printed {_SBOOT_OFF} while it latched "
            f"{_SBOOT_DIS_DECODED}; a reserved bit disabled secure boot. Console: {console}"
        )

        attempts = oc.split_attempts(console)
        srcs = [f"0x{a.src:08x}" for a in attempts]
        want = [f"0x{mm.PRIMARY_MANIFEST_OFFSET:08x}", f"0x{mm.BACKUP_MANIFEST_OFFSET:08x}"]
        assert srcs == want, (
            f"slot attempts read {srcs}, expected {want}: the primary then the backup, "
            f"once each. Console: {console}"
        )
        primary, backup = attempts

        def lines_with(token: str) -> list[int]:
            return [i for i, line in enumerate(console) if oc.count([line], token)]

        i_fuse = lines_with(_SBOOT_DIS_DECODED)[0]
        assert i_fuse < primary.first, (
            f"{_SBOOT_DIS_DECODED}@{i_fuse} is not before the primary attempt@{primary.first}"
        )
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
        assert len(i_all) == 1 and backup.last < i_all[0], (
            f"{_ALL_FAILED}@{i_all} is not once after the backup error@{backup.last}. "
            f"Console: {console}"
        )

        for att in attempts:
            oc.assert_attempt(
                att,
                error=MANIFEST_ERR_SIG_CLASS_CONTROL,
                stage="manifest",
                ordered=(_BODY, _ERR_LINE),
                absent=_PAST_DETERMINATION,
            )
        log.info(
            "CHK-BOTH-REFUSED PASS: primary@%d-%d and backup@%d-%d end %s -> %s; none of %s; %s@%d",
            primary.first,
            primary.last,
            backup.first,
            backup.last,
            _BODY,
            _ERR_LINE,
            ", ".join(_PAST_DETERMINATION),
            _ALL_FAILED,
            i_all[0],
        )

        for marker, want_n in ((_ERR, 2), ("RSA_EXEC", 0)) + tuple((m, 0) for m in _BOOT_PROGRESS):
            n = oc.count(console, marker)
            assert n == want_n, (
                f"{marker} appeared {n} times, expected exactly {want_n}. Console: {console}"
            )

        status_msg = mm.rom_status_for_result(MANIFEST_ERR_SIG_CLASS_CONTROL)
        expected_status = 0x0F01_0000 | status_msg
        assert expected_status in status_seq, (
            f"cold_scratch[1] never held 0x{expected_status:08x} "
            f"(STATUS_ENCODE(ERROR, 0x{status_msg:04x})); observed {status_hex}"
        )
        assert fw_done, (
            f"ROM never signalled completion; two refused slots must converge on a FAIL "
            f"verdict. cold_scratch[1]: {status_hex}"
        )
        assert not fw_pass, "ROM signalled PASS: it booted an unsigned image in PROD"
        log.info(
            "CHK-SBOOT-DIS-RESERVED PASS: SBOOT_DIS=0x%x latched as %s, secure boot "
            "enforced, %s x2, %s, cold_scratch[1]=0x%08x, verdict FAIL",
            _SBOOT_DIS_VALUE,
            _SBOOT_DIS_DECODED,
            _ERR_LINE,
            _ALL_FAILED,
            expected_status,
        )
