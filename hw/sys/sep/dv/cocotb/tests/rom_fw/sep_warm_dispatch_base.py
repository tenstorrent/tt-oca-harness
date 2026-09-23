# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared scaffolding for the warm-reset dispatch legs of ``vector.S``.

Seeds cold_scratch[7] before release, samples the ROM status words, and checks that
a rejected warm target leaves the core spinning in place.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from sep_reg_meta import sym

import cocotb
from cocotb.triggers import RisingEdge

from sep_base_test import sep_base_test
from env.sep_efuse_image import SepEfuseImage, LC_TEST_DEV
from env.sep_rom_console import rom_console_task, log_scratch_cold

_SEP_ROOT = str(Path(__file__).resolve().parents[4])
_FW_DIR = os.path.join(_SEP_ROOT, "bootrom", "prod", "build")
_ROM_BASE = sym("SEP_BOOT_ROM_MEM_BASE_ADDR")

# WARM_HANDLER_RANGE_BASE / _END in vector.S.
RANGE_BASE = 0xC000_0000
RANGE_END = 0xC004_0000

# cold_scratch[1] status words.
STATUS_WARM_HANG = 0x0F01_0069      # ERROR + SEP_MSG_WARM_RESET_HANG
STATUS_WARM_JUMP = 0x0101_0068      # INFO  + SEP_MSG_WARM_RESET_JUMP
STATUS_GENERAL_EXCEPTION = 0x0F01_0028  # ERROR + SEP_MSG_GENERAL_EXCEPTION
STATUS_BOOTROM_START = 0x8001_0044
STATUS_PRESTART_DONE = 0x8001_0056

# cold_scratch[0] terminal FAIL verdict.
VERDICT_FAIL = 0xDEAD_BEEF

# Written by cold_boot over cold_scratch[7] as its first store.
COLD_POISON = 0xFFFF_FFFF

# The ROM hang is a two-instruction `wfi; j` spin.
QUIESCE_CYCLES = 2_000
QUIESCE_PC_SPAN_MAX = 64


class sep_warm_dispatch_base(sep_base_test):

    build_env = False
    rom_build_dir = _FW_DIR

    # +sep_cold_scratch7 value, or None to leave cold_scratch[7] at its reset value 0.
    seed: int | None = None
    max_run_cycles = 400_000
    progress_every = 50_000
    # Staging TCM puts a copy of the ROM in ICCM; disable it when ICCM contents matter.
    stage_tcm = True

    async def bring_up_to_dispatch(self) -> list[str]:
        dut = cocotb.top

        seeded = cocotb.plusargs.get("sep_cold_scratch7")
        if self.seed is None:
            assert seeded is None, (
                f"+sep_cold_scratch7={seeded} is set, but this test needs "
                f"cold_scratch[7] at its cold reset value of 0 to drive the beqz "
                f"early-out"
            )
            self.logger.info(
                "CHK-STIMULUS-HANDLER: cold_scratch[7] left unarmed (reset value 0)"
            )
        else:
            assert seeded is not None, (
                "+sep_cold_scratch7 is not set: cold_scratch[7] would read 0, the "
                "ROM would take the beqz early-out to cold_boot, and this test's "
                "leg would not be exercised at all"
            )
            assert int(str(seeded), 16) == self.seed, (
                f"+sep_cold_scratch7={seeded} does not match the address this test "
                f"checks for (0x{self.seed:08x})"
            )
            assert self.seed != COLD_POISON, (
                f"the seed must differ from cold_boot's own poison "
                f"0x{COLD_POISON:08x}, or a run that cold booted would leave the "
                f"same value and CHK-SEED could not tell the two apart"
            )
            self.logger.info(
                "CHK-STIMULUS-HANDLER: cold_scratch[7] seed = 0x%08x", self.seed,
            )

        efuse_img = SepEfuseImage()
        efuse_img.set_lc_state(LC_TEST_DEV)
        self.write_efuse_image(efuse_img)

        # Stays empty on legs that stop before the C runtime; simputs() needs C.
        console: list[str] = []
        cocotb.start_soon(rom_console_task(self.logger, sink=console))

        hook = None
        if self.stage_tcm:
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

            hook = _load_tcm
        else:
            self.logger.info(
                "TCM staging skipped: ICCM keeps its default fill, so the warm "
                "target holds no instruction"
            )

        await self.bring_up_cpu_boot(
            _ROM_BASE >> 1, pre_reset_hook=hook, run_pulse_cycles=40,
        )
        return console

    async def sample_until(self, stop_status: int | None) -> dict:
        dut = cocotb.top
        status_seq: list[int] = []
        cold7_seq: list[int] = []
        verdict_seq: list[int] = []
        last_status = None
        last_cold7 = None
        last_verdict = None
        stopped = False
        retired = 0
        last_log = 0

        for cycle in range(self.max_run_cycles):
            await RisingEdge(dut.clk_i)
            probe = self.rd(dut.scratch_cold_probe_o)
            status = (probe >> 32) & 0xFFFF_FFFF
            if status != last_status:
                last_status = status
                status_seq.append(status)
            cold7 = (probe >> 224) & 0xFFFF_FFFF
            if cold7 != last_cold7:
                last_cold7 = cold7
                cold7_seq.append(cold7)
            verdict = probe & 0xFFFF_FFFF
            if verdict != last_verdict:
                last_verdict = verdict
                verdict_seq.append(verdict)
            if self.rd(dut.cpu_trace_valid_o):
                retired += 1
            if stop_status is not None and status == stop_status:
                stopped = True
                self.logger.info("stop status 0x%08x seen at cycle %d",
                                 stop_status, cycle)
                break
            if cycle - last_log >= self.progress_every:
                last_log = cycle
                self.logger.info(
                    "warm dispatch poll cyc=%d status=0x%08x cold7=0x%08x retired=%d",
                    cycle, status, cold7, retired,
                )

        log_scratch_cold(self.logger)
        self.logger.info("cold_scratch[1] sequence: %s", [hex(v) for v in status_seq])
        self.logger.info("cold_scratch[7] sequence: %s", [hex(v) for v in cold7_seq])
        return {
            "status_seq": status_seq,
            "cold7_seq": cold7_seq,
            "verdict_seq": verdict_seq,
            "stopped": stopped,
            "retired": retired,
        }

    async def observe_quiesce(self, resting_status: int) -> dict:
        dut = cocotb.top
        # The spin keeps retiring, so PC locality, not retire count, shows the core stopped.
        post_pcs: set[int] = set()
        moved = False
        for _ in range(QUIESCE_CYCLES):
            await RisingEdge(dut.clk_i)
            if self.rd(dut.cpu_trace_valid_o):
                # cpu_trace_addr_o is already a byte PC; do not shift it.
                post_pcs.add(self.rd(dut.cpu_trace_addr_o))
            if ((self.rd(dut.scratch_cold_probe_o) >> 32) & 0xFFFF_FFFF) != resting_status:
                moved = True
        span = (max(post_pcs) - min(post_pcs)) if post_pcs else 0
        return {"pcs": post_pcs, "span": span, "moved": moved}

    def assert_hung(self, quiesce: dict, resting_status: int) -> None:
        assert not quiesce["moved"], (
            f"cold_scratch[1] moved on from 0x{resting_status:08x} within "
            f"{QUIESCE_CYCLES} cycles: the ROM reported the reject and carried on"
        )
        assert quiesce["pcs"], (
            f"core retired nothing in the {QUIESCE_CYCLES} cycles after the "
            f"terminal status; expected the `wfi; j` spin"
        )
        assert quiesce["span"] <= QUIESCE_PC_SPAN_MAX, (
            f"after the terminal status the PC covered {quiesce['span']} bytes "
            f"across {len(quiesce['pcs'])} addresses "
            f"({[hex(p) for p in sorted(quiesce['pcs'])]}); a hung ROM spins "
            f"inside {QUIESCE_PC_SPAN_MAX} bytes"
        )
        self.logger.info(
            "CHK-HANG: cold_scratch[1] held 0x%08x while the PC spun across %d "
            "byte(s) at %s for %d cycles",
            resting_status, quiesce["span"],
            [hex(p) for p in sorted(quiesce["pcs"])], QUIESCE_CYCLES,
        )
