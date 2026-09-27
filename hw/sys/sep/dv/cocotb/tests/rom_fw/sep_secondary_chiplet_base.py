# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared scenario for the secondary-chiplet boot arm, reached with ``STRAPS_LO[25]`` clear.

The ROM makes one manifest attempt from SMC SRAM at the offset the SMC publishes in scratch[8].
Members set ``manifest_offset``, ``expect_boot``, ``expected_error`` and ``check_outcome``.
"""

from __future__ import annotations

import os

import cocotb
from cocotb.triggers import RisingEdge
from env import sep_manifest_mutate as mm
from env.sep_efuse_image import LC_TEST_DEV, SepEfuseImage
from env.sep_rom_console import log_scratch_cold, rom_console_task
from env.sep_verdict import decode_verdict
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_ROM_BASE = sym("SEP_BOOT_ROM_MEM_BASE_ADDR")
SMC_SRAM_BASE = 0x4006_0000
# The testbench default, and where the packed SMC image carries "legacy manifest".
DEFAULT_MANIFEST_OFFSET = 0x1000
MANIFEST_MAGIC = b"OCAC"
ERR_BAD_MAGIC = mm.boot_err("OCA_FAIL_MAGIC")

SECONDARY_MARKER = "BOOT_SECONDARY"
SPI_MARKER = "BOOT_SPI"
RECOVERY_MARKER = "BOOT_RECOVERY"
STRAP_PRIMARY_CLEAR = "STRAP primary=0"
STRAP_RECOVERY_CLEAR = " recovery=0"
STRAPS_LO_ECHO = "STRAPS_LO=0x00000000"
SMC_COORD_NOT_READY = "SMC_COORD_NOT_READY"
SMC_MANIFEST_OFF_INVALID = "SMC_MANIFEST_OFF_INVALID"
# In emission order on the SMC path.
WAIT_SMC = "WAIT_SMC_MANIFEST"
MANIFEST_PRIMARY = "MANIFEST_PRIMARY"
MANIFEST_BACKUP = "MANIFEST_BACKUP"
MANIFEST_OK = "MANIFEST_OK"
ALL_FAILED = "MANIFEST_ALL_FAILED"
# Would mean the ROM brought up the SPI controller despite the secondary strap.
SPI_INIT_MARKERS = (">>SPI_INIT", "SPI_INIT_OK")

_MAX_RUN_CYCLES = 8_000_000
_PROGRESS_EVERY = 200_000
# Must exceed the ~559k-cycle silent DCCM scrub, or a healthy run reads as a stall.
_STALL_CYCLES = 2_000_000
# rom_err_fail() writes the verdict before it halts, so watch that nothing moves after it.
_QUIESCE_CYCLES = 20_000


class sep_secondary_chiplet_base(sep_base_test):
    build_env = False
    # Gate on the cold_scratch[0] verdict word, not the outbound mailbox.
    verdict_source = "scratch0"

    # --- subclass contract -------------------------------------------------
    # Must match +sep_smc_scratch8; the default offset needs no plusarg.
    manifest_offset: int = DEFAULT_MANIFEST_OFFSET
    expect_boot: bool = True
    expected_error: int = 0
    extra_required: tuple[str, ...] = ()
    extra_forbidden: tuple[str, ...] = ()

    # --- shared marker sets ------------------------------------------------
    @property
    def _required(self) -> tuple[str, ...]:
        return (
            STRAPS_LO_ECHO,
            STRAP_PRIMARY_CLEAR,
            STRAP_RECOVERY_CLEAR,
            SECONDARY_MARKER,
            self.published_off_echo,
            self.published_addr_echo,
            WAIT_SMC,
            MANIFEST_PRIMARY,
            self.src_echo,
        ) + tuple(self.extra_required)

    @property
    def _forbidden(self) -> tuple[str, ...]:
        return (
            (
                SPI_MARKER,
                RECOVERY_MARKER,
                "STRAP primary=1",
                MANIFEST_BACKUP,
                SMC_COORD_NOT_READY,
                SMC_MANIFEST_OFF_INVALID,
            )
            + SPI_INIT_MARKERS
            + tuple(self.extra_forbidden)
        )

    @property
    def published_off_echo(self) -> str:
        return f"MANIFEST_OFF=0x{self.manifest_offset:08x}"

    @property
    def published_addr_echo(self) -> str:
        return f"SMC_MANIFEST_ADDR=0x{SMC_SRAM_BASE + self.manifest_offset:08x}"

    @property
    def src_echo(self) -> str:
        return f"MANIFEST_SRC=0x{SMC_SRAM_BASE + self.manifest_offset:08x}"

    # --- image-side evidence ------------------------------------------------
    def check_smc_image(self) -> None:
        path = cocotb.plusargs.get("sep_smc_mem_hex")
        assert isinstance(path, str) and os.path.isfile(path), (
            f"+sep_smc_mem_hex must name the packed SMC image; got {path!r}. "
            f"Without it nothing supplies the published offset's bytes and the "
            f"manifest identifier the ROM compares is not attributable to any "
            f"image this testcase can inspect"
        )
        with open(path) as handle:
            lines = [ln for ln in handle.read().split("\n") if ln.strip()]
        assert lines[0].strip() == f"@{SMC_SRAM_BASE:08x}", (
            f"{path} starts at {lines[0].strip()!r}, expected @{SMC_SRAM_BASE:08x}: "
            f"the offset arithmetic below assumes the image is based at the SMC "
            f"SRAM window"
        )
        # One $readmemh address header, then 8 bytes per line.
        per_line = 8
        data = lines[1:]
        span = len(data) * per_line

        def word_at(off: int) -> bytes:
            assert 0 <= off and off + 4 <= span, (
                f"offset 0x{off:x} is outside the {span} bytes {path} covers, so "
                f"this file supplies nothing there and the bytes the ROM compares "
                f"would not come from the image under test"
            )
            i, k = divmod(off, per_line)
            assert k + 4 <= per_line, (
                f"offset 0x{off:x} starts at byte {k} of an {per_line}-byte line, "
                f"so its word straddles two lines and this reader would return "
                f"fewer than 4 bytes"
            )
            row = bytes(int(b, 16) for b in data[i].split())
            assert len(row) == per_line, (
                f"{path} data line {i} holds {len(row)} bytes, expected {per_line}"
            )
            return row[k : k + 4]

        default = word_at(DEFAULT_MANIFEST_OFFSET)
        assert default == MANIFEST_MAGIC, (
            f"the packed SMC image carries {default!r} at 0x{DEFAULT_MANIFEST_OFFSET:x}, "
            f"not {MANIFEST_MAGIC!r}: this pair is about WHICH offset the SMC "
            f"publishes, so the image must hold a real manifest somewhere"
        )
        published = word_at(self.manifest_offset)
        if self.expect_boot:
            assert published == MANIFEST_MAGIC, (
                f"published offset 0x{self.manifest_offset:x} holds {published!r}, "
                f"not {MANIFEST_MAGIC!r}: this member expects a bootable manifest "
                f"there"
            )
        else:
            assert published != MANIFEST_MAGIC, (
                f"published offset 0x{self.manifest_offset:x} holds "
                f"{MANIFEST_MAGIC!r}: the invalid member would be handed a valid "
                f"manifest and would boot"
            )
        self.logger.info(
            "CHK-SMC-IMAGE: %s covers %d bytes from 0x%08x; 0x%x holds %r and the "
            "published offset 0x%x holds %r",
            path,
            span,
            SMC_SRAM_BASE,
            DEFAULT_MANIFEST_OFFSET,
            default,
            self.manifest_offset,
            published,
        )

    def check_plusarg_agreement(self) -> None:
        arg = cocotb.plusargs.get("sep_smc_scratch8")
        if self.manifest_offset == DEFAULT_MANIFEST_OFFSET:
            assert arg is None, (
                f"+sep_smc_scratch8={arg!r} is present but this member grades the "
                f"testbench default 0x{DEFAULT_MANIFEST_OFFSET:x}"
            )
        else:
            assert arg is not None and int(str(arg), 16) == self.manifest_offset, (
                f"+sep_smc_scratch8={arg!r} does not publish "
                f"0x{self.manifest_offset:x}, which is the offset this member "
                f"grades"
            )
        self.logger.info(
            "CHK-STIMULUS-OFFSET: SMC scratch[8] publishes 0x%x "
            "(+sep_smc_scratch8=%s), so the ROM loads from 0x%08x",
            self.manifest_offset,
            arg,
            SMC_SRAM_BASE + self.manifest_offset,
        )

    def build_efuse_image(self):
        # The SMC image is unsigned, so a secure-boot lifecycle would reject it.
        image = SepEfuseImage()
        image.set_lc_state(LC_TEST_DEV)
        return image

    # --- scenario -----------------------------------------------------------
    async def run_scenario(self) -> None:
        dut = cocotb.top

        self.check_plusarg_agreement()
        self.check_smc_image()

        image = self.build_efuse_image()
        self.write_efuse_image(image)

        console: list[str] = []
        cocotb.start_soon(rom_console_task(self.logger, sink=console))

        status_seq: list[int] = []
        last_status = None
        fw_done = False
        fw_pass = 0
        retired = 0
        last_log = 0
        post_status_moved = False
        post_console: list[str] = []
        try:
            await self.bring_up_cpu_boot(_ROM_BASE >> 1, run_pulse_cycles=40)
            last_move = 0
            last_lines = 0
            for cycle in range(_MAX_RUN_CYCLES):
                await RisingEdge(dut.clk_i)
                probe = self.rd(dut.scratch_cold_probe_o)
                status = (probe >> 32) & 0xFFFF_FFFF
                if status != last_status:
                    last_status = status
                    status_seq.append(status)
                    last_move = cycle
                if len(console) != last_lines:
                    last_lines = len(console)
                    last_move = cycle
                if self.rd(dut.cpu_trace_valid_o):
                    retired += 1
                if cycle - last_move >= _STALL_CYCLES:
                    self.logger.error(
                        "secondary poll stalled: no status or console movement for "
                        "%d cycles (cyc=%d, status=0x%08x, lines=%d)",
                        _STALL_CYCLES,
                        cycle,
                        status,
                        len(console),
                    )
                    break
                verdict = decode_verdict(probe)
                if verdict is not None:
                    fw_done = True
                    fw_pass = verdict[1]
                    self.logger.info(
                        "CHK-VERDICT: firmware signalled completion at cycle %d via "
                        "cold_scratch[0], pass=%d",
                        cycle,
                        fw_pass,
                    )
                    break
                if cycle - last_log >= _PROGRESS_EVERY:
                    last_log = cycle
                    self.logger.info(
                        "secondary poll cyc=%d status=0x%08x retired=%d lines=%d",
                        cycle,
                        status,
                        retired,
                        len(console),
                    )

            if fw_done and not self.expect_boot:
                console_len_at_done = len(console)
                for _ in range(_QUIESCE_CYCLES):
                    await RisingEdge(dut.clk_i)
                    probe = self.rd(dut.scratch_cold_probe_o)
                    if ((probe >> 32) & 0xFFFF_FFFF) != last_status:
                        post_status_moved = True
                        break
                post_console = console[console_len_at_done:]
        finally:
            log_scratch_cold(self.logger)

        self._check(console, status_seq, fw_done, fw_pass, retired)
        if fw_done and not self.expect_boot:
            self._check_quiesced(post_status_moved, post_console, last_status)

    # --- checks -------------------------------------------------------------
    def _check_quiesced(self, post_status_moved, post_console, terminal_status) -> None:
        assert not post_status_moved, (
            f"cold_scratch[1] moved on from 0x{terminal_status:08x} within "
            f"{_QUIESCE_CYCLES} cycles of the terminal verdict: the ROM reported "
            f"the terminal error and then kept running"
        )
        assert not post_console, (
            f"ROM printed {post_console} after the terminal verdict; a terminal "
            f"error path ends in `for(;;) wfi` and produces no further output"
        )
        self.logger.info(
            "CHK-HANG: cold_scratch[1] held 0x%08x and the console stayed silent "
            "for %d cycles after the terminal verdict",
            terminal_status,
            _QUIESCE_CYCLES,
        )

    @staticmethod
    def _index_of(console: list[str], marker: str) -> int:
        for i, line in enumerate(console):
            if marker in line:
                return i
        return -1

    @staticmethod
    def _count(console: list[str], marker: str) -> int:
        return sum(1 for line in console if marker in line)

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        log = self.logger
        status_hex = [hex(v) for v in status_seq]
        log.info("cold_scratch[1] sequence: %s", status_hex)
        log.info("ROM console: %s", console)

        assert retired, "core retired no instructions; the ROM never ran"
        assert console, (
            "ROM console is empty, so no marker check below means anything (the "
            "virt console is DEBUG-build only -- check the ROM build)"
        )
        assert self.expect_boot or self.expected_error, (
            "a member that expects no boot must declare expected_error, so its "
            "halt is graded on the encoded cold_scratch[1] word as well as on the "
            "console"
        )

        required = self._required
        forbidden = self._forbidden
        assert required, "required marker set is empty -- the checks below would be vacuous"
        for marker in required:
            assert any(marker in line for line in console), (
                f"ROM never printed {marker}. Console: {console}"
            )
        log.info("CHK-SECONDARY-MARKERS: all of %s observed", ", ".join(required))
        for marker in forbidden:
            assert not any(marker in line for line in console), (
                f"ROM printed {marker}, which this member forbids. Console: {console}"
            )
        log.info("CHK-SECONDARY-FORBIDDEN: none of %s appeared", ", ".join(forbidden))

        src = self.src_echo
        i_straps = self._index_of(console, STRAPS_LO_ECHO)
        i_branch = self._index_of(console, SECONDARY_MARKER)
        i_off = self._index_of(console, self.published_off_echo)
        i_addr = self._index_of(console, self.published_addr_echo)
        i_wait = self._index_of(console, WAIT_SMC)
        i_first = self._index_of(console, MANIFEST_PRIMARY)
        i_src = self._index_of(console, src)
        assert i_straps < i_branch < i_off < i_addr < i_wait < i_first < i_src, (
            f"secondary sequence is out of order: {STRAPS_LO_ECHO}@{i_straps} -> "
            f"{SECONDARY_MARKER}@{i_branch} -> {self.published_off_echo}@{i_off} -> "
            f"{self.published_addr_echo}@{i_addr} -> {WAIT_SMC}@{i_wait} -> "
            f"{MANIFEST_PRIMARY}@{i_first} -> {src}@{i_src}. Console: {console}"
        )
        log.info(
            "CHK-SECONDARY-ORDER: STRAPS_LO@%d -> BOOT_SECONDARY@%d -> %s@%d -> "
            "%s@%d -> WAIT_SMC_MANIFEST@%d -> MANIFEST_PRIMARY@%d -> %s@%d",
            i_straps,
            i_branch,
            self.published_off_echo,
            i_off,
            self.published_addr_echo,
            i_addr,
            i_wait,
            i_first,
            src,
            i_src,
        )

        # A repeated read of the same offset prints no MANIFEST_BACKUP, so count the attempts.
        n_attempts = self._count(console, MANIFEST_PRIMARY)
        n_src = self._count(console, src)
        assert n_attempts == 1 and n_src == 1, (
            f"{MANIFEST_PRIMARY} appeared {n_attempts} times and {src} {n_src} "
            f"times, expected exactly 1 each: rom_manifest_boot gives the SMC path "
            f"num_retries = 0, so there is one attempt and no second slot. "
            f"Console: {console}"
        )
        log.info(
            "CHK-SINGLE-ATTEMPT: one %s and one %s, no %s", MANIFEST_PRIMARY, src, MANIFEST_BACKUP
        )

        self.check_outcome(console, status_seq, fw_done, fw_pass)

    def check_outcome(self, console, status_seq, fw_done, fw_pass) -> None:
        raise NotImplementedError
