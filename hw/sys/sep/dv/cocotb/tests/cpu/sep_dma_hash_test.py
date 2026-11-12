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

An inline hash also copies its data (OpenTitan DMA ``programmers_guide.md``: the copy runs along
with the hash), across chunks and into ICCM. The host grades these from the values the firmware
prints:

* CTRL-DCCM-DST-CLEAR: the DCCM image (``BSS_END``) ends at or below the DCCM destination.
* CTRL-MULTICHUNK-SENTINEL: before the two-chunk SHA-256 GO, every destination word holds the
  sentinel. CHK-MULTICHUNK-COPY: after DONE, every one of the 56 destination bytes equals the
  message byte.
* CTRL-ICCM-FILL: before the ICCM pass, every source word is filled and every word of the SRAM
  readback buffer holds the sentinel. CTRL-ICCM-HASH-CLEAR: the code image, which the loader places
  from the ICCM base (``dma_hash_test.itcm.hex`` byte offsets), ends at or below the ICCM
  destination.
* CHK-ICCM-HASH: the SHA-256 pass from SRAM into ICCM ends with the DONE interrupt and ERROR_CODE
  0, and its hardware digest equals the software SHA-256 of the source.
* CHK-ICCM-HASH-COPY: a DMA copy of the ICCM destination back to the SRAM buffer ends with the
  DONE interrupt and ERROR_CODE 0, and every buffer word equals its source word. The CPU load/store
  unit cannot read ICCM (``hw/sys/sep/doc/rom.adoc``), so the firmware witnesses the ICCM write
  with this copy. On Verilator the host also reads the ICCM array at the destination address
  (``env/sep_mem_backdoor.py``) and requires every word to equal the source word in the SRAM array;
  VCS gives no access to the ICCM array, so there the host logs ``INFO-ICCM-ARRAY`` instead.

The host pins each count the firmware prints to the firmware's sizes: 14 sentinel words and 56
bytes for the two-chunk pass, 64 words (256 bytes) for the ICCM pass.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import cocotb
import pyuvm
from env import sep_mem_backdoor as mem
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_smc_mem import load_verilog_hex
from sep_base_test import sep_base_test
from sep_reg_meta import CHeaderRegBlock, ot_c_header, sym

_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "dma_hash_test")
_ITCM_HEX = os.path.join(_FW_DIR, "dma_hash_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "dma_hash_test.dtcm.hex")

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
# Sizes in dma_hash_test.c: the two-chunk message (FIPS_MSG_LEN) and the ICCM pass
# (TEST_DATA_SIZE).
_MC_BYTES = 56
_MC_WORDS = _MC_BYTES // 4
_ICCM_LEN = 0x100
_ICCM_WORDS = _ICCM_LEN // 4
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
_DCCM_CLEAR = re.compile(r"DCCM-DST-CLEAR bss_end=0x([0-9a-f]+) dst=0x([0-9a-f]+)")
_MC_SENTINEL = re.compile(r"MULTICHUNK-SENTINEL dst_sentinel=(\d+)/(\d+)")
_MC_COPY = re.compile(r"MULTICHUNK-COPY match=(\d+)/(\d+)")
_ICCM_FILL = re.compile(r"ICCM-FILL src_live=(\d+)/(\d+) buf_sentinel=(\d+)/(\d+)")
_ICCM_DST = re.compile(r"ICCM-HASH-DST iccm_base=0x([0-9a-f]+) dst=0x([0-9a-f]+) len=(\d+)")
_ICCM_HASH = re.compile(r"ICCM-HASH done=(\d+) error_code=0x([0-9a-f]+)")
_ICCM_HW = re.compile(r"ICCM-HASH HW = ([0-9a-f]{64})")
_ICCM_SW = re.compile(r"ICCM-HASH SW = ([0-9a-f]{64})")
_ICCM_COPY = re.compile(
    r"ICCM-HASH-COPY done=(\d+) error_code=0x([0-9a-f]+) match=(\d+)/(\d+) sentinel_left=(\d+)"
)


def _grab(rx: re.Pattern, console: str, rec: str) -> tuple[str, ...]:
    """The groups of the firmware line ``rx``; a missing line fails ``rec``."""
    m = rx.search(console)
    if not m:
        raise AssertionError(
            f"{rec} FAIL: firmware console has no line matching {rx.pattern!r}. "
            f"Console was:\n{console}"
        )
    return m.groups()


def _itcm_image_bytes(path: str) -> int:
    """Byte length of the ICCM image: the end of its last byte run, from offset 0."""
    return max((addr + len(data) for addr, data in load_verilog_hex(path)), default=0)


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
        self._grade_copy_passes(console)

    def _grade(self, rec: str, ok: bool, fields: str) -> None:
        """Log ``rec`` PASS with its values, or raise ``rec`` FAIL with them."""
        if not ok:
            raise AssertionError(f"{rec} FAIL: {fields}")
        self.logger.info("%s PASS: %s", rec, fields)

    def _grade_copy_passes(self, console: str) -> None:
        """The DCCM clearance, the two-chunk copy and the ICCM hash and copy-back records."""
        bss_end, dst = (int(v, 16) for v in _grab(_DCCM_CLEAR, console, "CTRL-DCCM-DST-CLEAR"))
        self._grade(
            "CTRL-DCCM-DST-CLEAR",
            bss_end <= dst,
            f"bss_end=0x{bss_end:08x} dccm_dst=0x{dst:08x}",
        )

        sent, n = (int(v) for v in _grab(_MC_SENTINEL, console, "CTRL-MULTICHUNK-SENTINEL"))
        self._grade(
            "CTRL-MULTICHUNK-SENTINEL", n == _MC_WORDS and sent == n, f"dst_sentinel={sent}/{n}"
        )
        match, n = (int(v) for v in _grab(_MC_COPY, console, "CHK-MULTICHUNK-COPY"))
        self._grade(
            "CHK-MULTICHUNK-COPY",
            n == _MC_BYTES and match == n,
            f"dst_bytes_equal_source={match}/{n} (two-chunk SHA-256 pass, DCCM destination)",
        )

        src_live, src_n, buf_sent, buf_n = (
            int(v) for v in _grab(_ICCM_FILL, console, "CTRL-ICCM-FILL")
        )
        self._grade(
            "CTRL-ICCM-FILL",
            src_n == _ICCM_WORDS and src_live == src_n and buf_n == src_n and buf_sent == buf_n,
            f"src_live={src_live}/{src_n} buf_sentinel={buf_sent}/{buf_n}",
        )
        base_s, dst_s, length_s = _grab(_ICCM_DST, console, "CTRL-ICCM-HASH-CLEAR")
        fw_base, iccm_dst, length = int(base_s, 16), int(dst_s, 16), int(length_s)
        image_end = _ICCM_BASE + _itcm_image_bytes(_ITCM_HEX)
        self._grade(
            "CTRL-ICCM-HASH-CLEAR",
            fw_base == _ICCM_BASE and length == _ICCM_LEN and image_end <= iccm_dst,
            f"iccm_base=0x{_ICCM_BASE:08x} fw_iccm_base=0x{fw_base:08x} "
            f"image_end=0x{image_end:08x} iccm_dst=0x{iccm_dst:08x} len={length}",
        )

        done_s, err_s = _grab(_ICCM_HASH, console, "CHK-ICCM-HASH")
        (hw,) = _grab(_ICCM_HW, console, "CHK-ICCM-HASH")
        (sw,) = _grab(_ICCM_SW, console, "CHK-ICCM-HASH")
        done, err = int(done_s), int(err_s, 16)
        self._grade(
            "CHK-ICCM-HASH",
            done == 1 and err == 0 and hw == sw,
            f"done={done} error_code=0x{err:x} hw=0x{hw} sw=0x{sw}",
        )

        done, err, match, n, left = _grab(_ICCM_COPY, console, "CHK-ICCM-HASH-COPY")
        done, err, match, n, left = int(done), int(err, 16), int(match), int(n), int(left)
        self._grade(
            "CHK-ICCM-HASH-COPY",
            done == 1 and err == 0 and n == _ICCM_WORDS and match == n,
            f"done={done} error_code=0x{err:x} words_equal_source={match}/{n} sentinel_left={left}",
        )
        self._grade_iccm_array(iccm_dst)

    def _grade_iccm_array(self, iccm_dst: int) -> None:
        """CHK-ICCM-HASH-COPY, array part: the ICCM words at the destination address equal the
        source words of the ICCM pass at the SRAM base, both read from the storage arrays. The
        arrays are reachable only on Verilator."""
        sim = str(getattr(cocotb, "SIM_NAME", "") or "")
        if "verilator" not in sim.lower():
            self.logger.info(
                "INFO-ICCM-ARRAY: array compare not run on %s (no access to the ICCM array); "
                "the DMA copy-back above is the ICCM witness on this simulator",
                sim,
            )
            return
        banks, sram = mem.iccm_banks(), mem.sram_array()
        bad = []
        for i in range(_ICCM_WORDS):
            src = (int(sram[i // 2].value) >> (32 * (i % 2))) & 0xFFFF_FFFF
            got = mem.iccm_word(banks, iccm_dst + 4 * i)
            if got != src:
                bad.append(f"@0x{iccm_dst + 4 * i:08x} iccm=0x{got:08x} source=0x{src:08x}")
        self._grade(
            "CHK-ICCM-HASH-COPY",
            not bad,
            f"iccm_array_equal_source={_ICCM_WORDS - len(bad)}/{_ICCM_WORDS} at 0x{iccm_dst:08x} "
            + "; ".join(bad[:4]),
        )
