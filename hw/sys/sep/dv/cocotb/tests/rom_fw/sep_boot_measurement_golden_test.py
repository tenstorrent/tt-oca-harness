# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Test that the BL0 boot measurement digest equals a Python SHA-256 model over the same inputs.

The full digest is read from BL1's BL0S_MEAS= line at LC=PROD, secure boot on, no BL2 demotion.
"""

from __future__ import annotations

import os
from pathlib import Path

import pyuvm

from env import sep_manifest_mutate as mm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_measurement_golden as mg
from rom_fw.sep_rom_ot_secure_boot_test import sep_rom_ot_secure_boot_test

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads"
    / "efuse_configurations" / "sep_efuse_lc_prod.toml"
)

_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"

# PROD enforces secure boot from the lifecycle state, not from the manifest flag.
_LC_PROD = 0x1
# demotion_bits: bit0 deciding flag, bit1 lock_demotion, bit2 bl2_demotion_decision.
# A PROD boot with no BL2 demotion flag locks non-demoted, which is 0x2.
_DEMOTE_PROD_NO_FLAG = 0x2


@pyuvm.test()
class sep_boot_measurement_golden_test(sep_rom_ot_secure_boot_test):
    """BL0's measurement digest equals a Python golden over the same inputs."""

    efuse_preload = _EFUSE_PRELOAD
    required_markers = sep_rom_ot_secure_boot_test.required_markers + (
        "MEASUREMENT_OK", "MEAS_LC=", "MEAS_DEMOTE=", "MEAS_SBOOT=",
        "MEAS_SBOOT_DIS=", "MEASUREMENT=", "BL0S_MEAS=", "BL0S_OK",
        "MANIFEST_OK", "BL1_COPIED", "BL1_JUMP=",
    )
    forbidden_markers = sep_rom_ot_secure_boot_test.forbidden_markers + (
        _BACKUP_SRC, "MANIFEST_ERR=", "MANIFEST_ALL_FAILED",
        "MEASUREMENT_FAIL", "FAIL:BL0S", "BL0S_VERIFY_FAIL",
    )

    def build_efuse_image(self):
        assert self.efuse_preload and os.path.isfile(self.efuse_preload), (
            f"eFuse preload missing: {self.efuse_preload}"
        )
        image = self.select_efuse_image(default_preload=self.efuse_preload)
        lc = image.lc_raw()
        sboot_dis = image.field_int("SBOOT_DIS") & 0x1
        assert lc == _LC_PROD, (
            f"LC_STATE raw is 0x{lc:x}, expected 0x{_LC_PROD:x} (PROD): the "
            f"golden below is computed for that state"
        )
        assert sboot_dis == 0, (
            "SBOOT_DIS is set: secure_boot would be 0 and the golden's inputs "
            "would not match this testcase's declared scenario"
        )
        fd.assert_clean_key_fuses(image)
        self._lc_state = lc
        self._sboot_dis = sboot_dis
        return image

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        # Take the hash from the stimulus, not the log, so the golden is independent of the DUT.
        self._manifest_hash = bytes(mm.manifest_hash(buf, "primary"))
        self.logger.info(
            "CHK-STIMULUS-MEAS: primary manifest_hash=%s, LC raw=0x%x, "
            "SBOOT_DIS=%d -- the golden is built from these",
            self._manifest_hash.hex().upper(), self._lc_state, self._sboot_dis,
        )
        return buf

    def check_transport(self, console: list[str], flash) -> None:
        inputs = mg.assert_inputs(
            self.logger, console,
            lc_state=self._lc_state,
            secure_boot=1,
            sboot_dis=self._sboot_dis,
            demotion_decision=_DEMOTE_PROD_NO_FLAG,
        )
        mg.assert_digest(self.logger, console, self._manifest_hash, inputs)
