# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP HMAC + KMAC CPU crypto smoke test (PyUVM).

OSS port combining the reference suite ``hmac_test`` and ``kmac_test`` (crypto
engine datapath). Boots the VeeR EL2 core and runs the hmac_kmac firmware, which
exercises the two OpenTitan crypto engines over the real CPU->fabric path on bare
``sep``:

  * HMAC (SHA-256 mode): hashes empty / "abc" / "Hello OTBN." and compares each
    HW digest against an independent software SHA-256 (fw/tests/common/sha256.c), plus
    no done-timeout and HMAC ERR_CODE == 0.
  * KMAC (KMAC128/cSHAKE): masked hash of "test" with a zero key using SOFTWARE
    entropy (no EDN, cannot hang) -- checks done, ERR_CODE == 0, and the unmasked
    digest (share0 ^ share1) is non-zero. The exact KMAC reference is a documented
    smoke-only delta (no bare-metal Keccak model); the HMAC side carries exact
    digests.

Firmware-self-checking: main() returns the error count and start.S emits the PASS
(0xCAFEBABE) / FAIL (0xDEADBEEF) magic on the 0x8000_0000 mailbox, which the boot
scoreboard gates on, alongside the banner + ICCM-execution checks.

No fuse data is read, so the testlist entry uses ``+skip_fuse_sense``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pyuvm
from env.sep_boot_scoreboard import SepBootScoreboard
from sep_base_test import sep_base_test

_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "hmac_kmac_smoke_test")
_ITCM_HEX = os.path.join(_FW_DIR, "hmac_kmac_smoke_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "hmac_kmac_smoke_test.dtcm.hex")

_ICCM_BASE = 0xC000_0000
# 3 HMAC hashes (+ SW SHA-256) and one KMAC masked hash; the run loop early-exits
# on fw_done, so this is an upper bound.
_MAX_RUN_CYCLES = 2_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
_BANNER = "SEP HMAC/KMAC crypto smoke test"


@pyuvm.test()
class sep_hmac_kmac_cpu_crypto_smoke_test(sep_base_test):
    """Boot VeeR EL2 and run the HMAC + KMAC crypto smoke firmware."""

    build_env = False

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    async def run_scenario(self) -> None:
        # Override the boot scoreboard's expected banner here (after its own
        # build_phase, which resets it to the hello_world default).
        self.sb.expected_line = _BANNER
        await self.boot_firmware(
            self.sb,
            _ITCM_HEX,
            _DTCM_HEX,
            rst_vec=_ICCM_BASE >> 1,
            max_run_cycles=_MAX_RUN_CYCLES,
            no_boot_cycles=_NO_BOOT_CYCLES,
            progress_every=_PROGRESS_EVERY,
        )
