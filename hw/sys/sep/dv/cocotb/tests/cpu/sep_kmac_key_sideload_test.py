# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP KMAC key-sideload test (PyUVM).

Boots the VeeR EL2 core and runs the ``kmac_key_sideload_test`` firmware, which
drives the OpenTitan KMAC engine over the real CPU->fabric path:

  * CFG_SHADOWED.sideload register control (default, write/readback both ways).
  * KMAC-128 (cSHAKE, PREFIX="KMAC") with a software key and software entropy,
    against a fixed digest vector, then repeated for determinism.
  * ``sideload=1`` START without a keymgr allow-path, which fails closed with
    ErrKeyNotValid; the firmware recovers through CMD.err_processed and repeats
    the software-key operation, whose digest must still match.

The recovery phase is the reason this runs on the CPU path rather than direct
AXI: it needs the register sequence a driver would issue, including the ordering
constraints CFG_REGWEN imposes after an error.

Firmware-self-checking: main() returns the error count and start.S emits the PASS
(0xCAFEBABE) / FAIL (0xDEADBEEF) magic on the 0x8000_0000 mailbox, which the boot
scoreboard gates on, alongside the banner + ICCM-execution checks.

No fuse data is read, so the testlist entry uses ``+skip_fuse_sense``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pyuvm

from sep_base_test import sep_base_test
from env.sep_boot_scoreboard import SepBootScoreboard

_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "kmac_key_sideload_test")
_ITCM_HEX = os.path.join(_FW_DIR, "kmac_key_sideload_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "kmac_key_sideload_test.dtcm.hex")

_ICCM_BASE = 0xC000_0000
# Three keyed KMAC-128 hashes plus one failed sideload START and its recovery;
# the run loop early-exits on fw_done, so this is an upper bound.
_MAX_RUN_CYCLES = 3_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
_BANNER = "KMAC Key Sideload Test"


@pyuvm.test()
class sep_kmac_key_sideload_test(sep_base_test):
    """Boot VeeR EL2 and run the KMAC key-sideload firmware."""

    build_env = False

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    async def run_scenario(self) -> None:
        # Override the boot scoreboard's expected banner here (after its own
        # build_phase, which resets it to the hello_world default).
        self.sb.expected_line = _BANNER
        await self.boot_firmware(
            self.sb, _ITCM_HEX, _DTCM_HEX,
            rst_vec=_ICCM_BASE >> 1,
            max_run_cycles=_MAX_RUN_CYCLES,
            no_boot_cycles=_NO_BOOT_CYCLES,
            progress_every=_PROGRESS_EVERY,
        )
