# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The SEP EXT SRAM is cleared between the primary failure and the backup fetch.

Every SRAM word is poisoned before boot, then sampled through VPI until the backup fetch.
"""

from __future__ import annotations

import logging

import cocotb
import pyuvm
from cocotb.handle import Immediate
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time

from sep_reg_meta import sym

from env import sep_manifest_mutate as mm
from env.sep_rom_console import rom_console_task
from rom_fw.sep_spi_primary_fail_backup_test import sep_spi_primary_fail_backup_test

_SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
# Must equal the u_sep_sram Depth parameter (256 KiB of 64-bit words).
_SRAM_WORDS = 32768
_WORD_BYTES = 8
_LAST_WORD = _SRAM_WORDS - 1

_SRAM_SCOPE = ("u_dut", "u_sep_ip_integration", "u_sep_sram")
_SRAM_GEN = "gen_ram_inst"
_SRAM_LEAF = ("u_mem", "mem")

# Must stay well below the ~1.4k-cycle gap between the clear end and the backup fetch.
_SAMPLE_EVERY = 100

_ERASED_WORD = int.from_bytes(bytes([mm.ERASED_BYTE]) * _WORD_BYTES, "little")

# Time references only; the parent asserts slot identity.
_PRIMARY_ERR = f"MANIFEST_ERR=0x{0x0003_0002:08x}"
_BACKUP_LABEL = "MANIFEST_BACKUP"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"

_MAX_REPORT = 8


def _poison(idx: int) -> int:
    # The 0xA5A5 top half keeps every value non-zero, and both halves are unique per word.
    return ((0xA5A5_0000 | (idx & 0xFFFF)) << 32) | (0x5A5A_0000 | ((~idx) & 0xFFFF))


@pyuvm.test()
class sep_failover_sram_clear_assertion_test(sep_spi_primary_fail_backup_test):
    """Primary rejected -> whole EXT SRAM zeroed -> backup fetched and booted."""

    _mem = None
    _sb_err: BaseException | None = None
    _first_sample: dict | None = None
    _first_touch: dict | None = None
    _residue: dict | None = None
    _cleared: dict | None = None
    _redirtied: dict | None = None
    _poison_words = 0
    # A second, quiet decoder instance, because the parent keeps its console sink local.
    _console: list[str] = []

    def _resolve_sram(self):
        node = cocotb.top
        walked = ["sep_uvm_top"]
        try:
            for part in _SRAM_SCOPE:
                node = getattr(node, part)
                walked.append(part)
            node = getattr(node, _SRAM_GEN)[0]
            walked.append(f"{_SRAM_GEN}[0]")
            for part in _SRAM_LEAF:
                node = getattr(node, part)
                walked.append(part)
        except Exception as exc:  # noqa: BLE001 - report where the walk stopped
            raise AssertionError(
                f"cannot reach the SEP SRAM array from cocotb.top; the walk reached "
                f"{'.'.join(walked)} and then failed with {type(exc).__name__}: {exc}. "
                f"The built model does register this scope -- see "
                f"Vtop__Syms__ctor__1__Slow.cpp varInsert(\"mem\", ...) under "
                f"sep_uvm_top.u_dut.u_sep_ip_integration.u_sep_sram.gen_ram_inst[0].u_mem "
                f"-- so a failure here means the public scope in "
                f"hw/sys/sep/dv/sep_public_scope.vlt changed, not that the test is wrong"
            ) from exc
        self.logger.info("CHK-SRAM-HANDLE: resolved %s", ".".join(walked))
        return node

    def _word(self, idx: int) -> int:
        # Not sep_base_test.rd(): it returns 0 on error, which would fake a cleared word.
        return int(self._mem[idx].value)

    def _nonzero_words(self) -> tuple[int, list[tuple[int, int]]]:
        count = 0
        sample: list[tuple[int, int]] = []
        for i in range(_SRAM_WORDS):
            val = int(self._mem[i].value)
            if val:
                count += 1
                if len(sample) < _MAX_REPORT:
                    sample.append((i, val))
        return count, sample

    def _poison_sram(self) -> None:
        for i in range(_SRAM_WORDS):
            self._mem[i].value = Immediate(_poison(i))
        bad: list[tuple[int, int, int]] = []
        for i in range(_SRAM_WORDS):
            got = int(self._mem[i].value)
            if got != _poison(i):
                if len(bad) < _MAX_REPORT:
                    bad.append((i, _poison(i), got))
        assert not bad, (
            f"CHK-SRAM-POISON FAIL: the pre-boot fill did not take. "
            f"{len(bad)}+ words differ, first: "
            + "; ".join(f"word[{i}] want 0x{w:016x} got 0x{g:016x}" for i, w, g in bad)
            + ". Without a non-zero starting state every 'SRAM is now zero' check "
              "below would pass on a ROM that cleared nothing."
        )
        self._poison_words = _SRAM_WORDS
        self.logger.info(
            "CHK-SRAM-POISON: all %d words (0x%08x..0x%08x, %d KiB) hold a distinct "
            "non-zero value before the boot; word[0]=0x%016x word[%d]=0x%016x",
            _SRAM_WORDS, _SRAM_BASE, _SRAM_BASE + _SRAM_WORDS * _WORD_BYTES - 1,
            _SRAM_WORDS * _WORD_BYTES // 1024,
            self._word(0), _LAST_WORD, self._word(_LAST_WORD),
        )

    def _snapshot(self, what: str) -> dict:
        return {
            "what": what,
            "time_ns": get_sim_time("ns"),
            "word0": self._word(0),
            "last": self._word(_LAST_WORD),
            "console": list(self._console),
        }

    async def _sram_scoreboard(self) -> None:
        # Trigger on settled values: DMA beats half-write a 64-bit word; the clear ends last.
        clk = cocotb.top.clk_i
        try:
            self._first_sample = self._snapshot("first-sample")
            while self._redirtied is None:
                await ClockCycles(clk, _SAMPLE_EVERY)
                w0 = self._word(0)
                wl = self._word(_LAST_WORD)
                if self._residue is None:
                    if self._first_touch is None and w0 != _poison(0):
                        self._first_touch = self._snapshot("first-touch")
                    if w0 == _ERASED_WORD:
                        self._residue = self._snapshot("residue")
                    continue
                if self._cleared is None:
                    if wl == 0:
                        snap = self._snapshot("cleared")
                        nz, sample = self._nonzero_words()
                        snap["nonzero_count"] = nz
                        snap["nonzero_sample"] = sample
                        self._cleared = snap
                    continue
                if w0 != 0:
                    self._redirtied = self._snapshot("redirtied")
        except Exception as exc:  # noqa: BLE001 - surfaced by check_transport
            self._sb_err = exc

    async def run_scenario(self) -> None:
        self._sb_err = None
        self._first_sample = None
        self._first_touch = None
        self._residue = None
        self._cleared = None
        self._redirtied = None
        self._poison_words = 0
        self._console = []
        self._mem = self._resolve_sram()
        self._poison_sram()
        cocotb.start_soon(
            rom_console_task(_quiet_logger(), sink=self._console, prefix="")
        )
        cocotb.start_soon(self._sram_scoreboard())
        await super().run_scenario()

    def log_transport(self, flash) -> None:
        # Log the scoreboard here so it is recorded before any assertion can abort the test.
        super().log_transport(flash)
        for snap in (self._first_sample, self._first_touch, self._residue,
                     self._cleared, self._redirtied):
            if snap is None:
                continue
            self.logger.info(
                "SRAM-SCOREBOARD %-11s t=%sns word[0]=0x%016x word[%d]=0x%016x "
                "console_lines=%d%s",
                snap["what"], snap["time_ns"], snap["word0"], _LAST_WORD, snap["last"],
                len(snap["console"]),
                "" if "nonzero_count" not in snap
                else f" nonzero_words={snap['nonzero_count']}",
            )

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        assert self._sb_err is None, (
            f"the SRAM scoreboard raised {type(self._sb_err).__name__}: {self._sb_err}"
        )
        assert self._poison_words == _SRAM_WORDS, (
            "the pre-boot poison never ran, so nothing below distinguishes a cleared "
            "SRAM from one that was zero all along"
        )
        assert self._first_sample is not None, "the SRAM scoreboard never sampled"
        assert self._first_sample["last"] == _poison(_LAST_WORD), (
            f"CHK-SRAM-ARMED FAIL: word[{_LAST_WORD}] already read "
            f"0x{self._first_sample['last']:016x} at the first sample "
            f"(t={self._first_sample['time_ns']}ns), expected the poison "
            f"0x{_poison(_LAST_WORD):016x}. The clear-completion trigger would fire "
            f"on a memory that was never dirty."
        )

        assert self._first_touch is not None, (
            f"CHK-SRAM-RESIDUE FAIL: word[0] never stopped holding its poison, so the "
            f"primary manifest was never fetched into SRAM and there was no failover "
            f"to observe. Console: {console}"
        )
        assert self._first_touch["last"] == _poison(_LAST_WORD), (
            f"CHK-SRAM-RESIDUE FAIL: word[{_LAST_WORD}] already read "
            f"0x{self._first_touch['last']:016x} the first time anything touched "
            f"word[0]; the clear had already started, so 'dirty before the failure' "
            f"is unproven."
        )
        assert self._residue is not None, (
            f"CHK-SRAM-RESIDUE FAIL: word[0] never settled at 0x{_ERASED_WORD:016x} -- "
            f"the erased primary slot's own bytes, DMA'd there by the ROM. It was "
            f"first disturbed at t={self._first_touch['time_ns']}ns "
            f"(0x{self._first_touch['word0']:016x}), so something reached SRAM, but "
            f"not the rejected image. The residue under test is not what this test "
            f"claims it is. Console: {console}"
        )
        assert self._residue["last"] == _poison(_LAST_WORD), (
            f"CHK-SRAM-RESIDUE FAIL: word[{_LAST_WORD}] already read "
            f"0x{self._residue['last']:016x} when the primary manifest landed; the "
            f"clear had already started, so 'dirty before the failure' is unproven."
        )
        self.logger.info(
            "CHK-SRAM-RESIDUE: SRAM first disturbed at t=%sns; by t=%sns word[0] holds "
            "the rejected primary's own bytes (0x%016x) and the far end is still dirty "
            "(word[%d]=0x%016x), so the clear had not begun",
            self._first_touch["time_ns"], self._residue["time_ns"],
            self._residue["word0"], _LAST_WORD, self._residue["last"],
        )

        assert self._cleared is not None, (
            f"CHK-SRAM-CLEARED FAIL: word[{_LAST_WORD}] never reached 0, so the "
            f"failover clear at manifest_load.c:776 did not run to completion between "
            f"the primary rejection and the end of the boot. Console: {console}"
        )
        assert self._cleared["nonzero_count"] == 0, (
            f"CHK-SRAM-CLEARED FAIL: {self._cleared['nonzero_count']} of {_SRAM_WORDS} "
            f"words were still non-zero at t={self._cleared['time_ns']}ns; first: "
            + "; ".join(
                f"word[{i}] (0x{_SRAM_BASE + i * _WORD_BYTES:08x}) = 0x{v:016x}"
                for i, v in self._cleared["nonzero_sample"]
            )
            + ". clear_sram_region(SRAM_BASE, SRAM_SIZE) is specified to zero the "
              "whole 256 KiB (manifest_load.c:693-699,776)."
        )
        self.logger.info(
            "CHK-SRAM-CLEARED: at t=%sns all %d words (0x%08x..0x%08x, %d KiB) read 0 "
            "-- the clear pattern is zero, which answers TP080's open item",
            self._cleared["time_ns"], _SRAM_WORDS, _SRAM_BASE,
            _SRAM_BASE + _SRAM_WORDS * _WORD_BYTES - 1,
            _SRAM_WORDS * _WORD_BYTES // 1024,
        )

        seen = self._cleared["console"]

        def _has(marker: str, lines: list[str]) -> bool:
            return any(marker in line for line in lines)

        assert _has(_PRIMARY_ERR, seen), (
            f"CHK-CLEAR-WINDOW FAIL: the SRAM was already fully zero before the ROM "
            f"published the primary verdict {_PRIMARY_ERR}. A clear that precedes the "
            f"failure is not a failover clear. Lines seen at that point: {seen}"
        )
        for marker in (_BACKUP_LABEL, _BACKUP_SRC):
            assert not _has(marker, seen), (
                f"CHK-CLEAR-WINDOW FAIL: {marker!r} had already been printed when the "
                f"SRAM finished clearing, so the clear did not complete before the "
                f"backup attempt began. Lines seen at that point: {seen}"
            )
        self.logger.info(
            "CHK-CLEAR-WINDOW: the clear completed at t=%sns, after %r and before %r "
            "-- i.e. inside the primary-fail -> backup-retry window. boot_flash_reinit() "
            "is the instruction immediately after the store loop "
            "(boot_rom.dis 10042750 -> 10042754), so it had not yet been called",
            self._cleared["time_ns"], _PRIMARY_ERR, _BACKUP_LABEL,
        )

        assert self._redirtied is not None, (
            "CHK-CLEAR-BRACKET FAIL: word[0] never became non-zero again, so no backup "
            "manifest was ever fetched into the cleared SRAM"
        )
        assert (
            self._residue["time_ns"]
            < self._cleared["time_ns"]
            < self._redirtied["time_ns"]
        ), (
            f"CHK-CLEAR-BRACKET FAIL: the three SRAM events are out of order -- "
            f"residue@{self._residue['time_ns']}ns, "
            f"cleared@{self._cleared['time_ns']}ns, "
            f"redirtied@{self._redirtied['time_ns']}ns"
        )
        self.logger.info(
            "CHK-CLEAR-BRACKET: dirty@%sns -> all-zero@%sns -> backup fetch@%sns",
            self._residue["time_ns"], self._cleared["time_ns"],
            self._redirtied["time_ns"],
        )

        self.logger.warning(
            "CHK-SCOPE: TP080 asks for EXT SRAM *and* SMC SRAM to be cleared in this "
            "window. Only the EXT SRAM half is asserted above. The boot flow "
            "conditions the SMC SRAM clear on 'if SMC SRAM used', and "
            "decides from the manifest USE_EXT bit. The stimulus side of that exists: "
            "the packer emits the bit (pack_images.py:91) and every image booted here "
            "is built with it CLEAR (bootrom/prod/configs/*_test.yaml use_ext_sram: 0), "
            "which this run observes as flag_args=0x00000000 on the manifest it booted. "
            "What is missing is the ROM's consuming branch: FLAG_ARGS_BIT_USE_EXT_SRAM "
            "(manifest.h:88) is referenced nowhere under bootrom/prod/src, and "
            "manifest_load.c:647-657 staged this payload in EXT SRAM regardless "
            "(COPY_SRC=0x10002000; LOAD=0xC0000000 is BL1's ICCM destination). So the "
            "SMC clear has nothing to "
            "assert against. Consistently, boot_rom.dis has no store loop over "
            "sep_get_smc_sram_base() (0x40060000) -- which is also where this ROM's "
            "own status ring lives. See FINDINGS F19 and F21. A green run here does "
            "NOT cover the SMC SRAM half of F038."
        )


def _quiet_logger() -> logging.Logger:
    # WARNING level: the parent already logs every ROM line, so this mirror stays quiet.
    log = logging.getLogger("sep_failover_sram_clear_assertion_test.console_mirror")
    log.setLevel(logging.WARNING)
    return log
