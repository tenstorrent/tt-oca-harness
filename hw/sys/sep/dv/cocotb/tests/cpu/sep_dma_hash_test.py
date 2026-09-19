# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP Secure-DMA inline SHA-256 firmware-boot test (PyUVM).

OSS port of the reference suite ``sep_dma_hash_test``. Boots the VeeR EL2 core and runs the
dma_hash firmware, which programs the Secure DMA to copy a buffer with the
inline SHA-256 engine, waits for the DMA-done interrupt through the VeeR PIC
(WFI + ISR), and self-checks the hardware digest against a software SHA-256, the
copied data, and the DMA error code. Proves DMA plus inline SHA-256, and
DMA-done IRQ through the PIC to a CPU ISR.

Like the reference test this is firmware-self-checking: the firmware returns its
error count and start.S emits the PASS (0xCAFEBABE) / FAIL (0xDEADBEEF) magic on
the 0x8000_0000 mailbox, which the boot scoreboard gates on (so a digest/data
mismatch inside the firmware surfaces as fw_pass=False). The scoreboard also
checks the firmware banner and that the core actually executed out of ICCM.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pyuvm
from env.sep_boot_scoreboard import SepBootScoreboard
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "dma_hash_test")
_ITCM_HEX = os.path.join(_FW_DIR, "dma_hash_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "dma_hash_test.dtcm.hex")

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
# DMA copy + inline SHA-256 + a software SHA-256 over 256 bytes; the run loop
# early-exits on fw_done, so this is just an upper bound.
_MAX_RUN_CYCLES = 3_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
# Must match the banner dma_hash_test.c actually prints.
_BANNER = "Secure DMA SHA-256 Hash Test"


@pyuvm.test()
class sep_dma_hash_test(sep_base_test):
    """Boot VeeR EL2 and run the Secure-DMA inline SHA-256 firmware."""

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

        # The banner alone cannot tell a current image from a stale SHA-256-only
        # one: both print it. The firmware scores SHA-384, the multi-chunk pass
        # and the DIGEST_SWAP=0 comparison into its own error count, so gate on
        # each leg's PASS line -- an image built before those legs existed
        # reaches the PASS magic with three contracts never exercised.
        console = self.sb.console_text()
        for needle, what in (
            ("PASS: SHA-384 digest matches", "the SHA-384 FIPS 180-4 vector"),
            ("PASS: multi-chunk SHA-256 digest matches", "the multi-chunk SHA-256 pass"),
            ("under DIGEST_SWAP=0 are the byte-reverse", "the DIGEST_SWAP=0 comparison"),
        ):
            assert needle in console, (
                f"firmware console has no {needle!r} line, so {what} did not run "
                f"or did not pass. Console was:\n{console}"
            )
        self.logger.info(
            "CHK-SHA384 / CHK-MULTICHUNK / CHK-DIGEST-SWAP PASS: all three hash "
            "legs reported passing in the firmware console"
        )

        # The SHA-256 pass legs are scored the same way: each prints the line the
        # card's checker names, so a leg that did not run loses its line here
        # instead of hiding behind the PASS magic.
        for needle, chk, what in (
            (
                "CFG_REGWEN = 0x6 (expected 0x6 for unlocked)",
                "CHK-CFG",
                "CFG_REGWEN readable and unlocked before configuration",
            ),
            ("DMA transfer completed!", "CHK-COMPLETE", "the DMA reporting completion"),
            (
                "PASS: SRAM and DCCM data matches",
                "CHK-COPY",
                "the copied bytes matching the source",
            ),
            (
                "PASS: SHA-384 pass also copied the message to DCCM intact",
                "CHK-SHA384-COPY",
                "the SHA-384 pass copying its message intact",
            ),
        ):
            assert any(
                needle in ln and not ln.lstrip().startswith(("FAIL", "ERROR"))
                for ln in console.splitlines()
            ), (
                f"firmware console has no passing line carrying {needle!r}, so "
                f"{what} was not checked. Console was:\n{console}"
            )
            self.logger.info("%s PASS: firmware reported %s", chk, what)

        # CHK-DIGEST: the firmware prints the hardware digest and its own software
        # recomputation. Compare them here as well, so the record rests on the two
        # values rather than on the firmware's error count alone.
        hw = re.search(r"Expected \(HW\) = 0x([0-9a-f]{64})", console)
        sw = re.search(r"Computed \(SW\) = 0x([0-9a-f]{64})", console)
        assert hw and sw, (
            f"firmware console does not carry both SHA-256 digests, so CHK-DIGEST has "
            f"nothing to compare. Console was:\n{console}"
        )
        assert hw.group(1) == sw.group(1), (
            f"hardware digest 0x{hw.group(1)} != software digest 0x{sw.group(1)}"
        )
        self.logger.info(
            "CHK-DIGEST PASS: hardware SHA-256 digest == the software recomputation "
            "over the same SRAM bytes"
        )
