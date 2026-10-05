# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A wedged secure DMA must fail the boot instead of hanging it.

``dma_transfer()`` (``bootrom/prod/src/sep_dma.c``) bounds its completion poll with a
budget scaled to the transfer length and aborts an engine that reports neither DONE nor
ERROR. ``+sep_dma_host_stall`` holds the DMA host port's response channel idle, so the
engine stays busy. The boot takes the SMC-SRAM manifest path, which makes a single
attempt, and its first DMA transfer is the manifest read.

The ROM must report ``SEP_MSG_DMA_TIMEOUT``, print ``DMA_TIMEOUT_STS=``, fail the slot
with ``OCA_BOOT_ERR_DMA``, report ``SEP_MSG_MANIFEST_LOAD_FAILED`` and halt with a
cold_scratch[0] FAIL verdict. The timeout status separates a stalled engine from one that
reported an error. ``SepBootScoreboard`` is not used: the outcome is a halt.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from env import sep_manifest_mutate as mm
from env.sep_efuse_image import LC_TEST_DEV, SepEfuseImage
from env.sep_rom_console import log_scratch_cold, rom_console_task
from env.sep_verdict import decode_verdict
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_ROM_BASE = sym("SEP_BOOT_ROM_MEM_BASE_ADDR")

_SMC_PATH_MARKER = "WAIT_SMC_MANIFEST"
_TIMEOUT_MARKER = "DMA_TIMEOUT_STS="
_MANIFEST_ERR_DMA = f"MANIFEST_ERR=0x{mm.rom_boot_err('OCA_BOOT_ERR_DMA'):08x}"
_ALL_FAILED = "MANIFEST_ALL_FAILED"
# ERROR + SEP_MSG_MANIFEST_LOAD_FAILED; SEP_STATUS_ID is 1 for BL0.
SEP_MSG_MANIFEST_LOAD_FAILED = 0x213
_STATUS_LOAD_FAILED = 0x0F01_0000 | SEP_MSG_MANIFEST_LOAD_FAILED
# WARN + SEP_MSG_DMA_TIMEOUT.
SEP_MSG_DMA_TIMEOUT = 0x229
_STATUS_DMA_TIMEOUT = 0x0801_0000 | SEP_MSG_DMA_TIMEOUT
_BOOT_PROGRESS_MARKERS = ("MANIFEST_OK", "PAYLOAD_OK", "BL1_COPIED", "PRE_JUMP", "BL1_JUMP=")

# The manifest peek is 20 bytes, so its poll budget is close to DMA_POLLS_SETUP
# reads. Generous against that plus the boot up to [S23].
_MAX_RUN_CYCLES = 20_000_000
_PROGRESS_EVERY = 500_000
# How long to watch after the terminal verdict before believing the ROM halted.
_QUIESCE_CYCLES = 20_000


@pyuvm.test()
class sep_rom_dma_stall_terminal_test(sep_base_test):
    """Secure DMA held busy: the manifest read times out and the ROM halts with FAIL."""

    build_env = False

    async def run_scenario(self) -> None:
        dut = cocotb.top
        assert "sep_dma_host_stall" in cocotb.plusargs, (
            "+sep_dma_host_stall is not set, so the DMA is not wedged and this run "
            "would be an ordinary boot"
        )

        efuse_img = SepEfuseImage()
        efuse_img.set_lc_state(LC_TEST_DEV)
        self.write_efuse_image(efuse_img)

        console: list[str] = []
        cocotb.start_soon(rom_console_task(self.logger, sink=console))

        await self.bring_up_cpu_boot(_ROM_BASE >> 1, run_pulse_cycles=40)

        status_seq: list[int] = []
        last_status = None
        fw_done = False
        fw_pass = 0
        retired = 0
        last_log = 0
        post_status_moved = False
        post_console: list[str] = []
        for cycle in range(_MAX_RUN_CYCLES):
            await RisingEdge(dut.clk_i)
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
                    "dma stall poll cyc=%d status=0x%08x retired=%d lines=%d",
                    cycle,
                    status,
                    retired,
                    len(console),
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

        # Liveness. Without it every absence check below is vacuously true.
        assert retired, "core retired no instructions; the ROM never ran"
        assert any(_SMC_PATH_MARKER in line for line in console), (
            f"ROM never printed {_SMC_PATH_MARKER}: it did not take the SMC-SRAM "
            f"manifest path this scenario depends on. Console: {console}"
        )

        # CHK-DMA-STALL-TIMEOUT: the bounded poll expired, and the manifest read
        # failed with the DMA error because of it.
        def index_of(marker: str) -> int:
            return next((i for i, line in enumerate(console) if marker in line), -1)

        i_timeout = index_of(_TIMEOUT_MARKER)
        i_err = index_of(_MANIFEST_ERR_DMA)
        assert fw_done, (
            f"ROM never signalled completion within {_MAX_RUN_CYCLES} cycles: the DMA "
            f"completion poll did not give up. cold_scratch[1] observed {status_hex}"
        )
        assert i_timeout >= 0, (
            f"ROM never printed {_TIMEOUT_MARKER}: the DMA wait did not time out. "
            f"Console: {console}"
        )
        assert i_err > i_timeout, (
            f"{_MANIFEST_ERR_DMA} (line {i_err}) did not follow {_TIMEOUT_MARKER} "
            f"(line {i_timeout}): the manifest read did not fail on the timeout. "
            f"Console: {console}"
        )
        self.logger.info(
            "CHK-DMA-STALL-TIMEOUT PASS: %s then %s", _TIMEOUT_MARKER, _MANIFEST_ERR_DMA
        )

        # CHK-DMA-STALL-STATUS: the timeout is on the status channel, ahead of the
        # terminal status, where a release build can see it.
        assert _STATUS_DMA_TIMEOUT in status_seq, (
            f"cold_scratch[1] never held 0x{_STATUS_DMA_TIMEOUT:08x} "
            f"(WARN + SEP_MSG_DMA_TIMEOUT); observed {status_hex}"
        )
        assert _STATUS_LOAD_FAILED not in status_seq or status_seq.index(
            _STATUS_DMA_TIMEOUT
        ) < status_seq.index(_STATUS_LOAD_FAILED), (
            f"SEP_MSG_DMA_TIMEOUT did not precede SEP_MSG_MANIFEST_LOAD_FAILED in {status_hex}"
        )
        self.logger.info(
            "CHK-DMA-STALL-STATUS PASS: cold_scratch[1]=0x%08x before the terminal status",
            _STATUS_DMA_TIMEOUT,
        )

        # CHK-DMA-STALL-TERMINAL: the boot failed and stopped.
        assert not fw_pass, "ROM signalled PASS with the secure DMA wedged"
        assert any(_ALL_FAILED in line for line in console), (
            f"ROM never printed {_ALL_FAILED}. Console: {console}"
        )
        assert _STATUS_LOAD_FAILED in status_seq, (
            f"cold_scratch[1] never held 0x{_STATUS_LOAD_FAILED:08x} "
            f"(ERROR + SEP_MSG_MANIFEST_LOAD_FAILED); observed {status_hex}"
        )
        assert not post_status_moved, (
            "cold_scratch[1] moved on after the terminal verdict, so the ROM did not halt"
        )
        assert not post_console, (
            f"ROM kept printing after the terminal verdict, so it did not halt: {post_console}"
        )
        self.logger.info(
            "CHK-DMA-STALL-TERMINAL PASS: %s, cold_scratch[1]=0x%08x, mailbox FAIL, "
            "quiet for %d cycles",
            _ALL_FAILED,
            _STATUS_LOAD_FAILED,
            _QUIESCE_CYCLES,
        )

        # CHK-DMA-STALL-NO-BOOT: nothing past the failed manifest read ran.
        for marker in _BOOT_PROGRESS_MARKERS:
            assert not any(marker in line for line in console), (
                f"ROM printed {marker} with the secure DMA wedged. Console: {console}"
            )
        self.logger.info(
            "CHK-DMA-STALL-NO-BOOT PASS: none of %s reached", ", ".join(_BOOT_PROGRESS_MARKERS)
        )
