# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The Secure-DMA inline hash produces the correct SHA-256 and SHA-384 digests while it copies.

The dma_hash firmware programs the Secure DMA to copy a buffer through the inline SHA-256 engine,
waits for the DMA-done interrupt through the VeeR PIC (WFI + ISR), and checks the hardware digest
against a software SHA-256, the copied data and the DMA error code. It returns its error count and
fw/startup/crt0.s emits PASS (0xCAFEBABE) / FAIL (0xDEADBEEF) on the 0x8000_0000 mailbox, which the
boot scoreboard gates on with the banner and ICCM-execution checks.

Before GO the firmware fills the destination with a sentinel that no source word can hold and
prints the readback counts of both regions; the host requires every source word filled and every
destination word at the sentinel (CTRL-SRC-FILL), so a copy that does not run cannot match the
source. The host also gates on CHK-SHA384, CHK-MULTICHUNK, CHK-DIGEST-SWAP, CHK-CFG, CHK-COMPLETE
(the SHA-256 pass line, which no other pass prints), CHK-COPY and CHK-SHA384-COPY, and compares the
printed hardware and software digests itself (CHK-DIGEST).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pyuvm
from env.sep_boot_scoreboard import SepBootScoreboard
from sep_base_test import sep_base_test
from sep_reg_meta import CHeaderRegBlock, ot_c_header, sym

_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "dma_hash_test")
_ITCM_HEX = os.path.join(_FW_DIR, "dma_hash_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "dma_hash_test.dtcm.hex")

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
# CFG_REGWEN reads its RDL reset (MUBI4 TRUE, unlocked) before any DMA
# configuration; the value comes from the generated secure_dma C header.
_CFG_REGWEN_RESET = CHeaderRegBlock("SECURE_DMA", ot_c_header("secure_dma")).reset("CFG_REGWEN")
# DMA copy + inline SHA-256 + a software SHA-256 over 256 bytes; the run loop
# early-exits on fw_done, so this is just an upper bound.
_MAX_RUN_CYCLES = 3_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
# Must match the banner dma_hash_test.c actually prints.
_BANNER = "Secure DMA SHA-256 Hash Test"
_SRC_FILL = re.compile(r"SRC-FILL src_live=(\d+)/(\d+) dst_sentinel=(\d+)/(\d+)")


@pyuvm.test()
class sep_dma_hash_test(sep_base_test):
    """Inline SHA digests, copied data and the DMA status match their goldens."""

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
        # each leg's PASS line -- an image without those legs reaches the PASS
        # magic with three contracts never exercised.
        console = self.sb.console_text()

        # CTRL-SRC-FILL: before GO every source word is filled and every
        # destination word holds the sentinel.
        fill = _SRC_FILL.search(console)
        src_live, src_n, dst_sent, dst_n = (int(v) for v in fill.groups()) if fill else (0, 0, 0, 0)
        fill_ok = src_n > 0 and src_live == src_n and dst_n == src_n and dst_sent == dst_n
        fields = f"src_live={src_live}/{src_n} dst_sentinel={dst_sent}/{dst_n}"
        assert fill_ok, (
            f"CTRL-MISSING SRC-FILL: {fields} (line present={int(bool(fill))}). "
            f"Console was:\n{console}"
        )
        self.logger.info("CTRL-SRC-FILL seen: %s", fields)

        for needle, chk, what in (
            ("PASS: SHA-384 digest matches", "CHK-SHA384", "the SHA-384 FIPS 180-4 vector"),
            (
                "PASS: multi-chunk SHA-256 digest matches",
                "CHK-MULTICHUNK",
                "the multi-chunk SHA-256 pass",
            ),
            (
                "under DIGEST_SWAP=0 are the byte-reverse",
                "CHK-DIGEST-SWAP",
                "the DIGEST_SWAP=0 comparison",
            ),
        ):
            assert needle in console, (
                f"{chk} FAIL: firmware console has no {needle!r} line, so {what} did "
                f"not run or did not pass. Console was:\n{console}"
            )
        self.logger.info(
            "CHK-SHA384 / CHK-MULTICHUNK / CHK-DIGEST-SWAP PASS: all three hash "
            "legs reported passing in the firmware console"
        )

        # The SHA-256 pass legs are scored the same way: each prints the line the
        # VPLAN checker names, so a leg that did not run loses its line here
        # instead of hiding behind the PASS magic.
        for needle, chk, what in (
            (
                f"CFG_REGWEN = 0x{_CFG_REGWEN_RESET:x} (expected 0x{_CFG_REGWEN_RESET:x} for unlocked)",
                "CHK-CFG",
                "CFG_REGWEN readable and unlocked before configuration",
            ),
            (
                "SHA-256 pass DMA_DONE seen, ERROR_CODE = 0x0",
                "CHK-COMPLETE",
                "the SHA-256 pass DMA_DONE interrupt with ERROR_CODE = 0",
            ),
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
