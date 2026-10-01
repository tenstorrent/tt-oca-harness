# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A stalled HMAC message FIFO fails the ROM self-hash instead of hanging it (PyUVM).

FEATURE UNDER TEST. ``fifo_feed()`` (``bootrom/prod/src/hmac_sha256.c``) waits for
message-FIFO room through helpers bounded by ``HMAC_FIFO_POLL_MAX``. When the engine
stops consuming, the wait times out and ``sha256()`` takes its fail path.

``hmac_fifo_drain_stall_i`` holds the FIFO's read side idle, so the engine stops
draining and the FIFO fills. It is raised only once the ROM prints
``CRYPTO_SELFTEST_OK`` at the end of [S14]: that self-test hashes three bytes,
which never fill a 32-entry FIFO, so a stall from reset would fail that hash in
the completion wait rather than in the FIFO wait under test. rom_main() runs the
[S17] ROM self-hash next, ahead of [S15] and [S16]. It covers the whole ROM
region, so the FIFO fills almost at once and the word-aligned feed waits for
credit.

The ROM must print ``SHA_FIFO_TIMEOUT`` and ``ROM_HASH_COMPUTE_FAIL`` and halt on
``ROM_ERR_ROM_HASH_MISMATCH`` with a FAIL verdict. A ROM whose FIFO wait is
unbounded never reaches a verdict, and the run times out.

The terminal outcome is a halt before any manifest transport is chosen, so no SPI
flash is attached and ``SepBootScoreboard`` is not used, as in
``sep_firmware_sboot_dis_rsvd_terminal_test``.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from env.sep_efuse_image import LC_TEST_DEV, SepEfuseImage
from env.sep_rom_console import log_scratch_cold, rom_console_task
from env.sep_verdict import decode_verdict
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_SEP_ROOT = str(Path(__file__).resolve().parents[4])
_FW_DIR = os.path.join(_SEP_ROOT, "bootrom", "prod", "build_ot")
_ROM_BASE = sym("SEP_BOOT_ROM_MEM_BASE_ADDR")

# Printed at the end of [S14], immediately before the [S17] self-hash.
_ARM_MARKER = "CRYPTO_SELFTEST_OK"
_FIFO_TIMEOUT = "SHA_FIFO_TIMEOUT"
_HASH_FAIL = "ROM_HASH_COMPUTE_FAIL"
# ERROR + ROM_ERR_ROM_HASH_MISMATCH (0xF005); SEP_STATUS_ID is 1 for BL0.
_STATUS_TERMINAL = 0x0F01_F005
# Must NOT appear: the self-hash succeeding, and anything after it.
_DOWNSTREAM_MARKERS = ("ROM_HASH_VERIFIED", ">>C9b_ICCM_CLR", "FUSE: SBOOT_DIS:", "MANIFEST_OK")

# [S17] starts after the boot up to [S14]; the FIFO timeout adds
# HMAC_FIFO_POLL_MAX STATUS reads on top. Generous against both.
_MAX_RUN_CYCLES = 20_000_000
_PROGRESS_EVERY = 500_000
# How long to watch after the terminal verdict before believing the ROM halted.
_QUIESCE_CYCLES = 20_000


@pyuvm.test()
class sep_rom_hmac_fifo_stall_terminal_test(sep_base_test):
    """HMAC FIFO drain stalled at [S17]: the self-hash fails and the ROM halts."""

    build_env = False
    rom_build_dir = _FW_DIR

    async def run_scenario(self) -> None:
        dut = cocotb.top

        efuse_img = SepEfuseImage()
        efuse_img.set_lc_state(LC_TEST_DEV)
        self.write_efuse_image(efuse_img)

        console: list[str] = []
        cocotb.start_soon(rom_console_task(self.logger, sink=console))

        for src, dst in (
            (os.path.join(self.rom_build_dir, "boot_rom.itcm.hex"), "sep_itcm.hex"),
            (os.path.join(self.rom_build_dir, "boot_rom.dtcm.hex"), "sep_dtcm.hex"),
        ):
            if not os.path.isfile(src):
                raise FileNotFoundError(f"ROM image not found: {src}")
            shutil.copyfile(src, os.path.join(os.getcwd(), dst))

        async def _load_tcm() -> None:
            dut.tcm_load_i.value = 1
            await RisingEdge(dut.clk_i)
            await RisingEdge(dut.clk_i)
            dut.tcm_load_i.value = 0

        await self.bring_up_cpu_boot(
            _ROM_BASE >> 1,
            pre_reset_hook=_load_tcm,
            run_pulse_cycles=40,
        )

        status_seq: list[int] = []
        last_status = None
        armed_at = None
        armed_lines = 0
        fw_done = False
        fw_pass = 0
        retired = 0
        last_log = 0
        post_status_moved = False
        post_console: list[str] = []
        for cycle in range(_MAX_RUN_CYCLES):
            await RisingEdge(dut.clk_i)
            if armed_at is None and any(_ARM_MARKER in line for line in console):
                dut.hmac_fifo_drain_stall_i.value = 1
                armed_at = cycle
                armed_lines = len(console)
                self.logger.info("HMAC FIFO drain stalled at cycle %d", cycle)
            probe = self.rd(dut.scratch_cold_probe_o)
            status = (probe >> 32) & 0xFFFF_FFFF
            if status != last_status:
                last_status = status
                status_seq.append(status)
            if self.rd(dut.cpu_trace_valid_o):
                retired += 1
            verdict = decode_verdict(probe)
            if verdict is not None:
                fw_done = True
                fw_pass = verdict[1]
                self.logger.info(
                    "ROM signalled completion at cycle %d via cold_scratch[0], pass=%d",
                    cycle,
                    fw_pass,
                )
                break
            if cycle - last_log >= _PROGRESS_EVERY:
                last_log = cycle
                self.logger.info(
                    "hmac stall poll cyc=%d status=0x%08x retired=%d lines=%d armed=%s",
                    cycle,
                    status,
                    retired,
                    len(console),
                    armed_at is not None,
                )

        if fw_done:
            console_len_at_done = len(console)
            for _ in range(_QUIESCE_CYCLES):
                await RisingEdge(dut.clk_i)
                probe = self.rd(dut.scratch_cold_probe_o)
                if ((probe >> 32) & 0xFFFF_FFFF) != last_status:
                    post_status_moved = True
                    break
            post_console = console[console_len_at_done:]

        log_scratch_cold(self.logger)
        status_hex = [hex(v) for v in status_seq]
        self.logger.info("cold_scratch[1] sequence: %s", status_hex)
        self.logger.info("ROM console: %s", console)

        # Liveness and stimulus. The stall must have been raised, and raised
        # before the self-hash reported anything.
        assert retired, "core retired no instructions; the ROM never ran"
        assert armed_at is not None, (
            f"ROM never printed {_ARM_MARKER}, so the FIFO stall was never raised and "
            f"[S17] ran on a healthy engine. Console: {console}"
        )
        after_arm = console[armed_lines:]
        self.logger.info(
            "CHK-HMAC-STALL-STIMULUS PASS: drain stalled at cycle %d after %s",
            armed_at,
            _ARM_MARKER,
        )

        # CHK-HMAC-STALL-TIMEOUT: the FIFO wait expired and failed the self-hash.
        def index_of(lines: list[str], marker: str) -> int:
            return next((i for i, line in enumerate(lines) if marker in line), -1)

        i_timeout = index_of(after_arm, _FIFO_TIMEOUT)
        i_fail = index_of(after_arm, _HASH_FAIL)
        assert fw_done, (
            f"ROM never signalled completion within {_MAX_RUN_CYCLES} cycles: the FIFO "
            f"wait did not give up. cold_scratch[1] observed {status_hex}"
        )
        assert i_timeout >= 0, (
            f"ROM never printed {_FIFO_TIMEOUT} after the stall: the self-hash did not "
            f"fail in the FIFO wait. Console after the stall: {after_arm}"
        )
        assert i_fail > i_timeout, (
            f"{_HASH_FAIL} did not follow {_FIFO_TIMEOUT}. Console after the stall: {after_arm}"
        )
        self.logger.info("CHK-HMAC-STALL-TIMEOUT PASS: %s then %s", _FIFO_TIMEOUT, _HASH_FAIL)

        # CHK-HMAC-STALL-TERMINAL: the boot failed on the self-hash and stopped.
        assert not fw_pass, "ROM signalled PASS with the HMAC FIFO stalled"
        assert _STATUS_TERMINAL in status_seq, (
            f"cold_scratch[1] never held 0x{_STATUS_TERMINAL:08x} "
            f"(ERROR + ROM_ERR_ROM_HASH_MISMATCH); observed {status_hex}"
        )
        assert not post_status_moved, (
            "cold_scratch[1] moved on after the terminal verdict, so the ROM did not halt"
        )
        assert not post_console, (
            f"ROM kept printing after the terminal verdict, so it did not halt: {post_console}"
        )
        self.logger.info(
            "CHK-HMAC-STALL-TERMINAL PASS: cold_scratch[1]=0x%08x, mailbox FAIL, quiet "
            "for %d cycles",
            _STATUS_TERMINAL,
            _QUIESCE_CYCLES,
        )

        # CHK-HMAC-STALL-NO-PROGRESS: nothing past the failed self-hash ran.
        for marker in _DOWNSTREAM_MARKERS:
            assert not any(marker in line for line in console), (
                f"ROM printed {marker} with the HMAC FIFO stalled. Console: {console}"
            )
        self.logger.info(
            "CHK-HMAC-STALL-NO-PROGRESS PASS: none of %s reached", ", ".join(_DOWNSTREAM_MARKERS)
        )
