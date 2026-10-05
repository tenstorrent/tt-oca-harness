# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The SEP EXT SRAM is cleared between the primary failure and the backup fetch.

On a failed SPI slot with a retry left, ``rom_manifest_boot()`` (``bootrom/prod/src/oca_boot.c``)
calls ``clear_sram_region(SRAM_BASE, SRAM_SIZE)`` and then ``boot_flash_reinit()``. The test
writes a distinct non-zero value to all 32768 SRAM words and reads them back (CHK-SRAM-POISON),
so a ROM that clears nothing cannot pass on zero-initialised memory. A scoreboard reads the
array through VPI (``sep_public_scope.vlt``: ``prim_ram_1p`` ``mem`` is ``public_flat_rw``).
It requires, in order: the erased primary's bytes in word 0, every word zero after the primary
verdict and before ``MANIFEST_BACKUP``, then the backup fetch writing SRAM again.

Not covered: an SMC SRAM clear. The OCA manifest has no staging-select bit, so the ROM stages
the payload in EXT SRAM only. ``rom_clear_ext_sram()`` is a separate pre-manifest scrub, gated
on ``SRAM_SCRUB_BYTES`` (``bootrom/prod/Makefile``), and is not under test here.

Stimulus and failover checks come from ``sep_spi_primary_fail_backup_test``.
"""

from __future__ import annotations

import logging

import cocotb
import pyuvm
from cocotb.handle import Immediate
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time
from env import sep_manifest_mutate as mm
from env.sep_rom_console import rom_console_task
from rom_fw.sep_spi_primary_fail_backup_test import sep_spi_primary_fail_backup_test
from sep_reg_meta import sym

# 0x1000_0000. From the RDL export, not a literal, so the test cannot drift from
# the address the ROM's SRAM_BASE macro resolves to.
_SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
# prim_ram_1p_adv Depth of u_sep_sram (hw/top/sep_ip_integration.sv): 256 KiB / 8 B.
_SRAM_WORDS = 32768
_WORD_BYTES = 8
_LAST_WORD = _SRAM_WORDS - 1

# Hierarchy from cocotb.top (= sep_uvm_top) down to the macro's storage array.
_SRAM_SCOPE = ("u_dut", "u_sep_ip_integration", "u_sep_sram")
_SRAM_GEN = "gen_ram_inst"
_SRAM_LEAF = ("u_mem", "mem")

# Scoreboard sampling period, in clocks. The two windows this has to resolve are
# ~30k cycles (primary DMA -> clear start) and >=1.4k cycles (clear end -> backup
# fetch), both measured on this testbench. 100 is well inside
# the smaller of the two and costs two VPI reads per sample.
_SAMPLE_EVERY = 100

# An erased primary slot: what the flash device returns, and therefore what the
# ROM's own DMA leaves in SRAM word 0 before it rejects the slot. Derived from the
# mutator's own erase byte so the two cannot drift apart.
_ERASED_WORD = int.from_bytes(bytes([mm.ERASED_BYTE]) * _WORD_BYTES, "little")

# Console lines used purely as TIME references for the window. Slot identity is
# already asserted by the parent on MANIFEST_SRC= and the device transactions;
# MANIFEST_BACKUP is used here only to mark "the second attempt has begun", which
# is what it means regardless of which slot the retry counter selected.
_PRIMARY_ERR = f"MANIFEST_ERR=0x{mm.boot_err('OCA_FAIL_MAGIC'):08x}"
_BACKUP_LABEL = "MANIFEST_BACKUP"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"

# Report at most this many offending words in an assertion message.
_MAX_REPORT = 8


def _poison(idx: int) -> int:
    """Non-zero, per-word-unique fill for word ``idx``.

    Both halves are distinct functions of the index, so a read that returned a
    neighbouring word, a stale word, or a constant cannot look correct. The top
    byte is 0xA5 in every word, so no poison value can ever be 0 -- which is what
    makes "this word is now 0" a real state change rather than a possible no-op.
    """
    return ((0xA5A5_0000 | (idx & 0xFFFF)) << 32) | (0x5A5A_0000 | ((~idx) & 0xFFFF))


@pyuvm.test()
class sep_failover_sram_clear_assertion_test(sep_spi_primary_fail_backup_test):
    """Primary rejected -> whole EXT SRAM zeroed -> backup fetched and booted."""

    # Scoreboard state. Declared as class-level immutable defaults and rebound per
    # instance in run_scenario(), so nothing here depends on the pyuvm component
    # constructor signature. Recording in the monitor and asserting in
    # check_transport() keeps every observation in the log even when a check fails.
    _mem = None
    _sb_err: BaseException | None = None
    _first_sample: dict | None = None
    _first_touch: dict | None = None
    _residue: dict | None = None
    _cleared: dict | None = None
    _redirtied: dict | None = None
    _poison_words = 0
    # Private console sink, so the window can be expressed against the ROM's own
    # lines. The parent keeps its sink local to run_scenario(); this is a second,
    # quiet instance of the same decoder rather than a copy of it, so the two
    # cannot disagree about what the ROM printed.
    _console: list[str] = []

    # ---------------------------------------------------------------- plumbing

    def _resolve_sram(self):
        """Return the SRAM macro's storage array handle, or fail loudly."""
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
                f'Vtop__Syms__ctor__1__Slow.cpp varInsert("mem", ...) under '
                f"sep_uvm_top.u_dut.u_sep_ip_integration.u_sep_sram.gen_ram_inst[0].u_mem "
                f"-- so a failure here means the public scope in "
                f"hw/sys/sep/dv/sep_public_scope.vlt changed, not that the test is wrong"
            ) from exc
        self.logger.info("CHK-SRAM-HANDLE: resolved %s", ".".join(walked))
        return node

    def _word(self, idx: int) -> int:
        """Read one 64-bit SRAM word directly from the macro array (not a port probe)."""
        return int(self._mem[idx].value)

    def _nonzero_words(self) -> tuple[int, list[tuple[int, int]]]:
        """Scan all 32768 words. Returns (count_nonzero, first few offenders)."""
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
        """Fill every word with its unique non-zero value, then read them all back."""
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
            _SRAM_WORDS,
            _SRAM_BASE,
            _SRAM_BASE + _SRAM_WORDS * _WORD_BYTES - 1,
            _SRAM_WORDS * _WORD_BYTES // 1024,
            self._word(0),
            _LAST_WORD,
            self._word(_LAST_WORD),
        )

    def _snapshot(self, what: str) -> dict:
        return {
            "what": what,
            "time_ns": get_sim_time("ns"),
            "word0": self._word(0),
            "last": self._word(_LAST_WORD),
            "console": list(self._console),
        }

    # -------------------------------------------------------------- scoreboard

    async def _sram_scoreboard(self) -> None:
        """Sample the SRAM until the clear has been seen, then to the backup fetch.

        Four transitions are recorded as memory events:

          first-touch word[0] stops holding its poison (first SRAM write)
          residue     word[0] settles at the erased slot's bytes (primary DMA
                      landed; clear not started)
          cleared     word[LAST] reads 0 (the ascending loop in
                      clear_sram_region() reached its last word)
          redirtied   word[0] stops reading 0 (backup fetch began)

        "residue" triggers on the settled value, not on a change: the 64-bit macro
        has a per-bit write mask (``hw/top/sep_ip_integration.sv``) and the DMA
        writes narrower beats, so a word can be half-written for a few hundred
        clocks. The value then stands for tens of thousands of clocks, against a
        100-clock sampling interval.
        """
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

    # -------------------------------------------------------------- test hooks

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
        cocotb.start_soon(rom_console_task(_quiet_logger(), sink=self._console, prefix=""))
        cocotb.start_soon(self._sram_scoreboard())
        await super().run_scenario()

    def log_transport(self, flash) -> None:
        """Dump the SRAM scoreboard before any assertion can abort the test."""
        super().log_transport(flash)
        for snap in (
            self._first_sample,
            self._first_touch,
            self._residue,
            self._cleared,
            self._redirtied,
        ):
            if snap is None:
                continue
            self.logger.info(
                "SRAM-SCOREBOARD %-11s t=%sns word[0]=0x%016x word[%d]=0x%016x console_lines=%d%s",
                snap["what"],
                snap["time_ns"],
                snap["word0"],
                _LAST_WORD,
                snap["last"],
                len(snap["console"]),
                "" if "nonzero_count" not in snap else f" nonzero_words={snap['nonzero_count']}",
            )

    def check_transport(self, console: list[str], flash) -> None:
        # The inherited failover checks first: console order, device-side address
        # order, blank primary, real manifest at the backup. The SRAM checks add
        # to that scenario; they do not replace it.
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

        # --- (i)->(ii): the rejected primary really did leave data behind -------
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
            self._first_touch["time_ns"],
            self._residue["time_ns"],
            self._residue["word0"],
            _LAST_WORD,
            self._residue["last"],
        )

        # --- the clear itself ---------------------------------------------------
        assert self._cleared is not None, (
            f"CHK-SRAM-CLEARED FAIL: word[{_LAST_WORD}] never reached 0, so the "
            f"failover clear did not run to completion between "
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
            "whole 256 KiB."
        )
        self.logger.info(
            "CHK-SRAM-CLEARED: at t=%sns all %d words (0x%08x..0x%08x, %d KiB) read 0 "
            "-- the clear pattern is zero, which answers TP080's open item",
            self._cleared["time_ns"],
            _SRAM_WORDS,
            _SRAM_BASE,
            _SRAM_BASE + _SRAM_WORDS * _WORD_BYTES - 1,
            _SRAM_WORDS * _WORD_BYTES // 1024,
        )

        # --- the window: after the primary verdict, before the backup attempt ---
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
            self._cleared["time_ns"],
            _PRIMARY_ERR,
            _BACKUP_LABEL,
        )

        # --- the window closes when the backup fetch writes SRAM again ----------
        assert self._redirtied is not None, (
            "CHK-CLEAR-BRACKET FAIL: word[0] never became non-zero again, so no backup "
            "manifest was ever fetched into the cleared SRAM"
        )
        assert self._residue["time_ns"] < self._cleared["time_ns"] < self._redirtied["time_ns"], (
            f"CHK-CLEAR-BRACKET FAIL: the three SRAM events are out of order -- "
            f"residue@{self._residue['time_ns']}ns, "
            f"cleared@{self._cleared['time_ns']}ns, "
            f"redirtied@{self._redirtied['time_ns']}ns"
        )
        self.logger.info(
            "CHK-CLEAR-BRACKET: dirty@%sns -> all-zero@%sns -> backup fetch@%sns",
            self._residue["time_ns"],
            self._cleared["time_ns"],
            self._redirtied["time_ns"],
        )

        # --- scope of this pass, stated where a reader of the log will see it ---
        self.logger.info(
            "CHK-SCOPE: only the EXT SRAM clear is asserted. The OCA manifest has no "
            "staging-select bit, so this payload was staged in EXT SRAM "
            "(COPY_SRC=0x10002000; LOAD=0xC0000000 is BL1's ICCM destination) and no "
            "SMC SRAM clear is checked."
        )


def _quiet_logger() -> logging.Logger:
    """A logger for the second console decoder instance.

    The parent already logs every ROM line through its own decoder. This instance
    exists only to give the scoreboard a sink it can read, so its level is raised
    to suppress a duplicate transcript. Sharing the parent's sink is not possible:
    it is a local in ``sep_rom_ot_dma_boot_test.run_scenario``.
    """
    log = logging.getLogger("sep_failover_sram_clear_assertion_test.console_mirror")
    log.setLevel(logging.WARNING)
    return log
