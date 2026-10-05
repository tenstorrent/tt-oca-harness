# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CPU-driven HMAC matches a software SHA-256, and AES round-trips the FIPS-197 vector via SRAM.

The test boots the VeeR EL2 core and runs the hmac_kmac firmware, which exercises three
OpenTitan crypto engines over the real CPU->fabric path on bare ``sep``:

  * HMAC (SHA-256 mode): hashes empty / "abc" / "Hello OTBN." and compares each
    HW digest against an independent software SHA-256 (fw/tests/common/sha256.c), plus
    no done-timeout and HMAC ERR_CODE == 0.
  * KMAC (KMAC128/cSHAKE): masked hash of "test" with a zero key using SOFTWARE
    entropy (no EDN, cannot hang) -- checks done, ERR_CODE == 0, and the unmasked
    digest (share0 ^ share1) is non-zero. The KMAC side is smoke-only (no
    bare-metal Keccak model); the HMAC side carries exact digests.
  * AES (128-ECB): an SRAM round trip. Firmware stages the FIPS-197 C.1
    plaintext in SRAM, reads it back into the engine, encrypts, and stores the
    ciphertext to SRAM where it is compared against the published vector; then
    it feeds that ciphertext back under DECRYPT and compares the recovered block
    against the plaintext re-read from SRAM. SRAM is on the path in both
    directions, which is what ``sep_aes_mode_keysize_rand_test`` cannot claim -- there the block
    never leaves the registers.

The AES leg needs live entropy: masking reseeds its PRNG from crypto-EDN and
STATUS.IDLE never clears until that completes, so the firmware brings the stack
up (sep_entropy.h) and this test drives the raw noise the ring oscillators
cannot produce under Verilator.

Firmware-self-checking: main() returns the error count and fw/startup/crt0.s emits the PASS
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
from sep_reg_meta import sym

_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "hmac_kmac_smoke_test")
_ITCM_HEX = os.path.join(_FW_DIR, "hmac_kmac_smoke_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "hmac_kmac_smoke_test.dtcm.hex")

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
# 3 HMAC hashes (+ SW SHA-256), one KMAC masked hash and two AES-128-ECB passes;
# the run loop early-exits on fw_done, so this is an upper bound.
_MAX_RUN_CYCLES = 2_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
_BANNER = "SEP HMAC/KMAC crypto smoke test"


@pyuvm.test()
class sep_hmac_kmac_cpu_crypto_smoke_test(sep_base_test):
    """HMAC, KMAC and AES firmware checks pass over the real CPU-to-fabric path."""

    build_env = False

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    async def run_scenario(self) -> None:
        # Override the boot scoreboard's expected banner here (after its own
        # build_phase, which resets it to the hello_world default).
        self.sb.expected_line = _BANNER

        # The firmware programs ESRC/CSRNG/EDN itself, but the ring oscillators
        # do not self-oscillate under Verilator: +esrc_noise_force routes this
        # port onto the noise input and something still has to drive it. Started
        # before the core is released so the raw bits are already moving when the
        # firmware opens the health window.
        noise = self.start_esrc_noise_driver()

        await self.boot_firmware(
            self.sb,
            _ITCM_HEX,
            _DTCM_HEX,
            rst_vec=_ICCM_BASE >> 1,
            max_run_cycles=_MAX_RUN_CYCLES,
            no_boot_cycles=_NO_BOOT_CYCLES,
            progress_every=_PROGRESS_EVERY,
        )

        # Stop driving before the simulator tears the DUT down: a forked task
        # still writing a DUT port after $finish segfaults the simulation, which
        # surfaces as a non-zero exit on an otherwise passing run.
        noise.kill()

        # The firmware error count gates the PASS magic, so a failed leg already
        # fails the scoreboard. These gates are here so the kept log cannot show
        # a green run with a checker that never ran: a firmware image built
        # without one of the named legs, or one where a leg was skipped, would
        # otherwise pass this test silently.
        # Match the firmware's [PASS] prefix, not the bare checker name: the
        # firmware's own [FAIL] line names the same checker, so a bare-substring
        # gate would be satisfied by the failure it is meant to catch and would
        # then log a PASS of its own.
        console = self.sb.console_text()
        for chk, what in (
            ("CHK-HMAC-EMPTY", "the empty-message HMAC digest"),
            ("CHK-HMAC-SHORT", "the short-message HMAC digest"),
            ("CHK-HMAC-MULTI", "the longer-message HMAC digest"),
            ("CHK-RW1C", "HMAC and KMAC done-bit write-one-to-clear"),
            ("CHK-KMAC-LIVE", "the KMAC completion and non-zero digest"),
            ("CHK-CPU-AES-ENC", "the AES encrypt leg against the FIPS-197 vector"),
            ("CHK-CPU-AES-RT", "the AES SRAM round trip"),
        ):
            assert f"[PASS] {chk}" in console, (
                f"firmware console has no '[PASS] {chk}' line, so {what} did not "
                f"run or did not pass. Console was:\n{console}"
            )
        self.logger.info(
            "CHK-HMAC-EMPTY / CHK-HMAC-SHORT / CHK-HMAC-MULTI / CHK-RW1C / "
            "CHK-KMAC-LIVE / CHK-CPU-AES-ENC / CHK-CPU-AES-RT PASS: every named "
            "checker reported passing in the firmware console"
        )
