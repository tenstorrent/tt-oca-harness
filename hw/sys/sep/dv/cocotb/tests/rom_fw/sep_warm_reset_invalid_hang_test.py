# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""An out-of-range warm-reset handler address must hang, not be jumped to.

Seeds cold_scratch[7] with WARM_HANDLER_RANGE_END, the smallest address the bgeu rejects,
and checks the hang status, no jump, no cold-boot fallthrough, and a PC spin in place.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from sep_reg_meta import sym

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge

from sep_base_test import sep_base_test
from env.sep_efuse_image import SepEfuseImage, LC_TEST_DEV
from env.sep_rom_console import rom_console_task, log_scratch_cold

_SEP_ROOT = str(Path(__file__).resolve().parents[4])
_FW_DIR = os.path.join(_SEP_ROOT, "bootrom", "prod", "build")
_ROM_BASE = sym("SEP_BOOT_ROM_MEM_BASE_ADDR")

# Must match WARM_HANDLER_RANGE_BASE / _END in vector.S, or the seed probes the wrong edge.
_RANGE_BASE = 0xC000_0000  # SEP ICCM base
_RANGE_END = 0xC004_0000  # ICCM base + size
# Smallest address the upper bound rejects; must match +sep_cold_scratch7 in the testlist.
_INVALID_HANDLER = _RANGE_END

# cold_scratch[1] status words from vector.S.
_STATUS_WARM_HANG = 0x0F01_0069   # ERROR + SEP_MSG_WARM_RESET_HANG, warm_reset_hang
_STATUS_WARM_JUMP = 0x0101_0068   # INFO  + SEP_MSG_WARM_RESET_JUMP, accept arm
_STATUS_BOOTROM_START = 0x8001_0044
_STATUS_PRESTART_DONE = 0x8001_0056
# cold_boot's first store over cold_scratch[7]; seeing it means the dispatch fell through.
_COLD_POISON = 0xFFFF_FFFF

_MAX_RUN_CYCLES = 400_000
_PROGRESS_EVERY = 50_000
# The ROM hang is a two-instruction `wfi; j` spin.
_QUIESCE_CYCLES = 2_000
_QUIESCE_PC_SPAN_MAX = 64


@pyuvm.test()
class sep_warm_reset_invalid_hang_test(sep_base_test):
    """Seed an out-of-range warm handler; the ROM must hang instead of jumping."""

    build_env = False
    rom_build_dir = _FW_DIR

    async def run_scenario(self) -> None:
        dut = cocotb.top

        seeded = cocotb.plusargs.get("sep_cold_scratch7")
        assert seeded is not None, (
            "+sep_cold_scratch7 is not set: cold_scratch[7] would read 0, the ROM "
            "would take the beqz early-out to cold_boot, and no warm dispatch "
            "decision would be exercised at all"
        )
        assert int(str(seeded), 16) == _INVALID_HANDLER, (
            f"+sep_cold_scratch7={seeded} does not match the address this test "
            f"checks for (0x{_INVALID_HANDLER:08x})"
        )
        assert _INVALID_HANDLER != 0, (
            "a zero handler is the beqz early-out to cold_boot, not the reject arm"
        )
        assert not (_RANGE_BASE <= _INVALID_HANDLER < _RANGE_END), (
            f"0x{_INVALID_HANDLER:08x} is INSIDE "
            f"[0x{_RANGE_BASE:08x}, 0x{_RANGE_END:08x}) -- that is the accept arm"
        )
        assert _INVALID_HANDLER == _RANGE_END, (
            f"0x{_INVALID_HANDLER:08x} is not the boundary value; only "
            f"0x{_RANGE_END:08x} exactly distinguishes the ROM's `bgeu` from a "
            f"mistaken `bgtu`, which would accept the first out-of-range address"
        )
        assert _INVALID_HANDLER != _COLD_POISON, (
            f"the seed must differ from cold_boot's own poison "
            f"0x{_COLD_POISON:08x}, or a run that cold booted would leave the same "
            f"value in the register and CHK-SEED could not tell them apart"
        )
        self.logger.info(
            "CHK-STIMULUS-HANDLER: cold_scratch[7] seed = 0x%08x, the smallest "
            "address rejected by `bgeu handler, 0x%08x`",
            _INVALID_HANDLER, _RANGE_END,
        )

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
            _ROM_BASE >> 1, pre_reset_hook=_load_tcm, run_pulse_cycles=40,
        )

        status_seq: list[int] = []
        cold7_seq: list[int] = []
        last_status = None
        last_cold7 = None
        halted = False
        retired = 0
        last_log = 0
        for cycle in range(_MAX_RUN_CYCLES):
            await RisingEdge(dut.clk_i)
            status = (self.rd(dut.scratch_cold_probe_o) >> 32) & 0xFFFF_FFFF
            if status != last_status:
                last_status = status
                status_seq.append(status)
            cold7 = (self.rd(dut.scratch_cold_probe_o) >> 224) & 0xFFFF_FFFF
            if cold7 != last_cold7:
                last_cold7 = cold7
                cold7_seq.append(cold7)
            if self.rd(dut.cpu_trace_valid_o):
                retired += 1
            # No verdict is written on this path; the hang status is the only completion signal.
            if status == _STATUS_WARM_HANG:
                halted = True
                self.logger.info("ROM hung on the warm reject arm at cycle %d", cycle)
                break
            if cycle - last_log >= _PROGRESS_EVERY:
                last_log = cycle
                self.logger.info(
                    "warm dispatch poll cyc=%d status=0x%08x cold7=0x%08x retired=%d",
                    cycle, status, cold7, retired,
                )

        # The spin keeps retiring, so PC locality, not retire count, shows the core stopped.
        post_pcs: set[int] = set()
        post_status_moved = False
        if halted:
            for _ in range(_QUIESCE_CYCLES):
                await RisingEdge(dut.clk_i)
                if self.rd(dut.cpu_trace_valid_o):
                    # cpu_trace_addr_o is already a byte PC; do not shift it.
                    post_pcs.add(self.rd(dut.cpu_trace_addr_o))
                if ((self.rd(dut.scratch_cold_probe_o) >> 32) & 0xFFFF_FFFF) != \
                        _STATUS_WARM_HANG:
                    post_status_moved = True
        post_span = (max(post_pcs) - min(post_pcs)) if post_pcs else 0

        log_scratch_cold(self.logger)
        status_hex = [hex(v) for v in status_seq]
        cold7_hex = [hex(v) for v in cold7_seq]
        self.logger.info("cold_scratch[1] sequence: %s", status_hex)
        self.logger.info("cold_scratch[7] sequence: %s", cold7_hex)
        self.logger.info("ROM console: %s", console)

        # The console is empty on this path, so retirement is the only liveness evidence.
        assert retired, "core retired no instructions; the ROM never ran"

        assert _INVALID_HANDLER in cold7_seq, (
            f"cold_scratch[7] never held the seeded handler address "
            f"0x{_INVALID_HANDLER:08x}; observed {cold7_hex}. The tb deposit did "
            f"not take, so this run says nothing about the warm dispatch"
        )
        self.logger.info("CHK-SEED: cold_scratch[7] held 0x%08x", _INVALID_HANDLER)

        assert _STATUS_WARM_HANG in status_seq, (
            f"cold_scratch[1] never held 0x{_STATUS_WARM_HANG:08x} "
            f"(STATUS_ENCODE(ERROR, SEP_MSG_WARM_RESET_HANG)); observed "
            f"{status_hex}"
        )
        assert halted, (
            f"cold_scratch[1] never reached 0x{_STATUS_WARM_HANG:08x} within "
            f"{_MAX_RUN_CYCLES} cycles; observed {status_hex}"
        )
        self.logger.info("CHK-WARM-REJECT: cold_scratch[1] = 0x%08x",
                         _STATUS_WARM_HANG)

        # The ROM writes WARM_RESET_JUMP before it jumps, so its absence rules out a jump.
        assert _STATUS_WARM_JUMP not in status_seq, (
            f"cold_scratch[1] held 0x{_STATUS_WARM_JUMP:08x} "
            f"(SEP_MSG_WARM_RESET_JUMP): the ROM accepted an out-of-range handler "
            f"and jumped to it. Observed {status_hex}"
        )
        self.logger.info(
            "CHK-NO-JUMP: 0x%08x absent from cold_scratch[1]", _STATUS_WARM_JUMP,
        )

        for word, name in ((_STATUS_BOOTROM_START, "BOOTROM_START"),
                           (_STATUS_PRESTART_DONE, "BOOTROM_PRESTART_DONE")):
            assert word not in status_seq, (
                f"cold_scratch[1] held 0x{word:08x} ({name}), which cold_boot "
                f"writes: the ROM fell through the dispatch into a normal boot "
                f"instead of hanging. Observed {status_hex}"
            )
        assert _COLD_POISON not in cold7_seq, (
            f"cold_scratch[7] held cold_boot's poison 0x{_COLD_POISON:08x} "
            f"({cold7_hex}): execution reached cold_boot"
        )
        self.logger.info("CHK-NO-COLD-FALLTHROUGH: no cold_boot status word and no "
                         "0x%08x poison", _COLD_POISON)

        assert not console, (
            f"ROM printed {console}; the warm dispatch runs before the C runtime, "
            f"so any console output means execution continued into cold_boot"
        )
        self.logger.info("CHK-PRE-C: console silent, so the hang preceded C")

        assert not post_status_moved, (
            f"cold_scratch[1] moved on from 0x{_STATUS_WARM_HANG:08x} within "
            f"{_QUIESCE_CYCLES} cycles: the ROM reported the reject and carried on"
        )
        assert post_pcs, (
            f"core retired nothing in the {_QUIESCE_CYCLES} cycles after the "
            f"terminal status; expected the `wfi; j` spin, so either the trace "
            f"probe is dead or the core stopped in a way the ROM does not do"
        )
        assert post_span <= _QUIESCE_PC_SPAN_MAX, (
            f"after the terminal status the PC covered {post_span} bytes across "
            f"{len(post_pcs)} addresses ({[hex(p) for p in sorted(post_pcs)]}); a "
            f"hung ROM spins inside {_QUIESCE_PC_SPAN_MAX} bytes, so this one "
            f"reported the reject and then carried on executing"
        )
        self.logger.info(
            "CHK-HANG: cold_scratch[1] held 0x%08x while the PC spun across %d "
            "byte(s) at %s for %d cycles",
            _STATUS_WARM_HANG, post_span, [hex(p) for p in sorted(post_pcs)],
            _QUIESCE_CYCLES,
        )
