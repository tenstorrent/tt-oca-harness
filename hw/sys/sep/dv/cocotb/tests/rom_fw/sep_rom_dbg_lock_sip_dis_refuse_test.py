# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A debug-locked TEST_DEV part must refuse an unsigned image.

In TEST_DEV, secure boot is enforced when chiplet-scope debug is disabled: ``CHIPLET_DBG``
set in ``SIP_DIS`` or ``SYS_DIS``, or either vector read-locked (SEP-ROM-SB-025).
``rom_chiplet_dbg_policy()`` (``lifecycle.c``) latches that at [S18], and
``plat_is_secure_boot_active()`` adds it to the enforcement view. This run sets
``SIP_DIS.CHIPLET_DBG``, leaves ``SBOOT_DIS`` clear, and clears ``secure_boot_control`` on
both slots. The image is legally unsigned, so with secure boot in force the validator
refuses both slots with ``OCA_FAIL_SIGNATURE_CLASS_CONTROL``. ``SBOOT_DBG_LOCK`` is
required: [S18] prints it only when the lock makes the part enforce.

Stimulus and checks come from ``sep_firmware_cntl_secure_boot_flow_test`` (the PROD form).
The same image boots in TEST_DEV with debug open (``sep_rom_non_secure_boot_test``).
"""

from __future__ import annotations

from pathlib import Path

import pyuvm
from env.sep_efuse_image import SBOOT_DIS_MASK
from rom_fw.sep_firmware_cntl_secure_boot_flow_test import (
    sep_firmware_cntl_secure_boot_flow_test,
)
from sep_reg_meta import RegBlock

_EFUSE_DIR = Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads" / "efuse_configurations"

_CHIPLET_DBG_BIT = RegBlock("SEP_EFUSE_MAP").field_mask("LC_DISABLE", "chiplet_dbg")
_SIP_DIS_READ_LOCK_BIT = RegBlock("SEP_EFUSE_MAP").field_mask("LOCKS", "sip_dis_read_lock")
_SYS_DIS_READ_LOCK_BIT = RegBlock("SEP_EFUSE_MAP").field_mask("LOCKS", "sys_dis_read_lock")

# [S18]'s value print, and the marker it emits when the lock is what makes this
# TEST_DEV part enforce.
DBG_LOCK_VALUE = "FUSE: CHIPLET_DBG_DIS: 1"
DBG_LOCK_MARKER = "SBOOT_DBG_LOCK"


@pyuvm.test()
class sep_rom_dbg_lock_sip_dis_refuse_test(sep_firmware_cntl_secure_boot_flow_test):
    """TEST_DEV + SIP_DIS.CHIPLET_DBG + manifest secure_boot=0 -> both slots refused."""

    efuse_preload = _EFUSE_DIR / "sep_efuse_lc_test_dev_chiplet_dbg_sip.toml"
    expected_lc_raw = 0x0
    lc_marker = "LC=TEST_DEV"

    def check_disable_vectors(self, sip_dis: int, sys_dis: int, locks: int) -> None:
        """The debug-lock condition this member presents. Overridden per member."""
        assert sip_dis & _CHIPLET_DBG_BIT, (
            f"SIP_DIS is 0x{sip_dis:x}: CHIPLET_DBG (bit 1) is clear, so debug is open "
            f"and TEST_DEV would honour the cleared manifest flag"
        )
        assert not sys_dis & _CHIPLET_DBG_BIT, (
            f"SYS_DIS is 0x{sys_dis:x}: CHIPLET_DBG is set there too, so this run "
            f"would not isolate SIP_DIS"
        )
        assert not locks & (_SIP_DIS_READ_LOCK_BIT | _SYS_DIS_READ_LOCK_BIT), (
            f"LOCKS is 0x{locks:x}: a disable vector is read-locked, which enforces "
            f"on its own and would hide whether CHIPLET_DBG was read"
        )

    def check_efuse(self, image) -> None:
        lc = image.lc_raw()
        sboot_dis = image.field_int("SBOOT_DIS") & SBOOT_DIS_MASK
        bl1_ver = image.field_int("BL1_VERSION")
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        sip_dis = image.field_int("SIP_DIS")
        sys_dis = image.field_int("SYS_DIS")
        locks = image.field_int("LOCKS")
        assert lc == self.expected_lc_raw, (
            f"LC_STATE raw is 0x{lc:x}, expected 0x{self.expected_lc_raw:x} "
            f"({self.lc_marker}). In PROD the lifecycle enforces regardless and the "
            f"debug lock would be untested"
        )
        self.check_disable_vectors(sip_dis, sys_dis, locks)
        assert sboot_dis == 0, (
            f"SBOOT_DIS is {sboot_dis}: the chicken bit overrides the debug lock, so "
            f"secure boot would be off for a different reason"
        )
        assert bl1_ver == 0, f"BL1_VERSION is 0x{bl1_ver:x}, expected 0 (rollback would mask this)"
        assert revoke == 0, f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0"
        self.logger.info(
            "CHK-DBG-LOCK-STIMULUS: OTP LC raw=0x%x (%s), SIP_DIS=0x%x, "
            "SYS_DIS=0x%x, LOCKS=0x%x, SBOOT_DIS=%d",
            lc,
            self.lc_marker,
            sip_dis,
            sys_dis,
            locks,
            sboot_dis,
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)
        for marker in (DBG_LOCK_VALUE, DBG_LOCK_MARKER):
            assert any(marker in line for line in console), (
                f"ROM never printed {marker}: [S18] did not see chiplet debug as "
                f"disabled, so the refusal has some other cause. Console: {console}"
            )
        self.logger.info(
            "CHK-DBG-LOCK-ENFORCES: %s and %s, and both slots refused -- the debug "
            "lock put secure boot in force under %s",
            DBG_LOCK_VALUE,
            DBG_LOCK_MARKER,
            self.lc_marker,
        )
