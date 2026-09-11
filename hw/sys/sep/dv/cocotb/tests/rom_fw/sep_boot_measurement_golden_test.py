# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The boot measurement digest matches an independent Python model.

BL0 records ``SHA256`` over a 48-byte block -- the manifest hash
plus masked lc_state, demotion bits, secure_boot and sboot_dis
(``bootrom/prod/include/measurement.h``) -- and stores it in
``bl0_state.measurement``. This testcase recomputes that digest in Python and
requires binary equality.

THE DIGEST IS READ FROM BL1. BL0 emits only the digest's first word; the full 32
bytes reach the log through BL1's ``BL0S_MEAS=`` line, because BL1 already reads
``bl0_state`` for its handoff check. That is deliberate: it also covers something
a ROM-side dump would not, namely that the digest survived the handoff. The production ROM is
unchanged by this testcase.

WHAT A PASS ACTUALLY PROVES. Two independent claims, both asserted:

  * ``CHK-MEAS-INPUTS`` -- the four values BL0 hashed are the ones this scenario
    established (LC=PROD from the OTP preload, secure_boot enforced, sboot_dis
    clear, demotion bits 0x2 for a PROD boot whose manifest sets no BL2 demotion
    flag). Without this, a digest match would only prove the ROM agrees with a
    golden built from whatever it happened to hash.
  * ``CHK-MEAS-GOLDEN`` -- the 32 bytes BL1 read equal ``hashlib.sha256`` over
    the same layout, and BL0's own first-word report agrees with them, so the two
    observation points describe one run.

The manifest hash is taken from the served flash image rather than from the log,
so the golden's first 32 bytes come from the stimulus and not from the DUT.

COVERAGE LIMIT. This is one point of the LC x demotion x sboot_dis cross that
the procedure asks for. The remaining combinations need their own OTP preloads and
manifest demotion flags; the checker in ``sep_measurement_golden`` is written to
be reused for them and takes the expected inputs as arguments.
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

# LC_STATE raw 0x1 is PROD, which enforces secure boot from the lifecycle rather
# than from the manifest flag (secure_boot_enabled, manifest_load.c).
_LC_PROD = 0x1
# demotion_bits packing is measurement.h: bit0 the deciding flag, bit1
# lock_demotion, bit2 bl2_demotion_decision. A PROD boot whose manifest sets no
# BL2 demotion flag locks non-demoted, which is 0x2 -- the value
# sep_firmware_demotion_decision_no_flag_prod_test establishes for outcome O5.
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
        # A failed measurement or a broken handoff must not be reported as a pass.
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
        # From the stimulus, not the log: the golden's first 32 bytes must come
        # from the image the ROM was given.
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
