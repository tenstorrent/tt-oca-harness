# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The SEP verifies an ML-DSA-87 signature on Adams Bridge through the boot ROM's driver.

The abr_mldsa87_verify_test firmware verifies a 5903-byte blob signed at build time
with the test-only ML-DSA-87 key, then the rejected variants: tampered blob, z and
c~, a wrong key, a context, a pre-hash, a genuine c~ over an out-of-range z or a
malformed hint, an all-zero c~, and a zeroize part-way through a stream. Each case
prints one line with the driver's status and diagnostics; the same image runs on the
virtual platform, so the two runs' case lines can be compared. The firmware returns
0 only when every selected case met its expectation, which crt0.s reports as PASS,
and this test also requires a PASS line for every selected case, so a mask that ran
fewer cases than it selected cannot pass.

``+abr_case_mask=<hex>`` selects cases by bit (bit n runs case n) by patching the
firmware's case-parameter block in the staged DCCM image, so a subset runs from the
same image. No fuse data is read, so the testlist entry uses ``+skip_fuse_sense``.
"""

from __future__ import annotations

import os
from pathlib import Path

import cocotb
import pyuvm
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_dtcm_param_patch import patch_param_block
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_NAME = "abr_mldsa87_verify_test"
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", _FW_NAME)
_ITCM_HEX = os.path.join(_FW_DIR, f"{_FW_NAME}.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, f"{_FW_NAME}.dtcm.hex")

# abr_case_params in the firmware: the magic, then the case mask.
_CASE_PARAM_MAGIC = 0xAB2D5A87
_ALL_CASES = 0x3FFF

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
# Fourteen verifies, each loading 7 KiB of key and signature and streaming up to
# 5903 bytes through MSG; the run loop early-exits on fw_done.
_MAX_RUN_CYCLES = 60_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 500_000
_PASS_LINE = f"{_FW_NAME}: PASS"


@pyuvm.test()
class sep_abr_mldsa87_verify_test(sep_base_test):
    """Every selected ML-DSA-87 verify case meets its expectation on the RTL."""

    build_env = False
    # The firmware grades every case and reports the result as its completion
    # verdict, so that verdict is this leaf's own evidence.
    required_evidence = ("CHK-FW-CONSOLE",)

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    async def run_scenario(self) -> None:
        dtcm_hex = _DTCM_HEX
        mask = _ALL_CASES
        plusarg = cocotb.plusargs.get("abr_case_mask")
        if plusarg is not None:
            mask = int(str(plusarg), 16)
            assert mask != 0 and mask & ~_ALL_CASES == 0, (
                f"+abr_case_mask=0x{mask:x} selects no case or an unknown one"
            )
            dtcm_hex = os.path.join(os.getcwd(), f"{_FW_NAME}.masked.dtcm.hex")
            patch_param_block(_DTCM_HEX, dtcm_hex, _CASE_PARAM_MAGIC, [_CASE_PARAM_MAGIC, mask])
            self.logger.info("abr_case_mask=0x%x patched into %s", mask, dtcm_hex)

        self.sb.expected_line = _PASS_LINE
        await self.boot_firmware(
            self.sb,
            _ITCM_HEX,
            dtcm_hex,
            rst_vec=_ICCM_BASE >> 1,
            max_run_cycles=_MAX_RUN_CYCLES,
            no_boot_cycles=_NO_BOOT_CYCLES,
            progress_every=_PROGRESS_EVERY,
        )
        console = self.sb.console_text().splitlines()
        for n in range(_ALL_CASES.bit_length()):
            if (mask >> n) & 1:
                lines = [line for line in console if line.startswith(f"case {n} ")]
                assert lines and all(": PASS " in line for line in lines), (
                    f"CHK-FW-CONSOLE FAIL: case {n} selected but its lines are {lines!r}"
                )
        self.logger.info("CHK-FW-CONSOLE PASS: every case in mask 0x%x printed PASS", mask)
