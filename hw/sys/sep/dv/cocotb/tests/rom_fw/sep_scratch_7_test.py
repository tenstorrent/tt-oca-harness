# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP Boot ROM warm-reset dispatch: the ROM jumps to a valid cold_scratch[7] handler.

The handler is a ``j .`` poked into ICCM with ECC, since a warm-path trap has no stack.
The handler never writes the mailbox, so the checks here replace SepBootScoreboard.
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
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_SEP_ROOT = str(Path(__file__).resolve().parents[4])
_FW_DIR = os.path.join(_SEP_ROOT, "bootrom", "prod", "build")

_ROM_BASE = sym("SEP_BOOT_ROM_MEM_BASE_ADDR")

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
_ICCM_END = _ICCM_BASE + sym("SEP_ICCM_MEM_SIZE")

# Offset from the ICCM base so a jump to the range base cannot pass the check.
_HANDLER_OFFSET = 0x100
_HANDLER_ADDR = _ICCM_BASE + _HANDLER_OFFSET
# `j .` (jump to self).
_HANDLER_INSN = 0x0000_006F

# STATUS_ENCODE(STATUS_TYPE_INFO, SEP_MSG_WARM_RESET_JUMP) with SEP_STATUS_ID 1 (BL0).
_STATUS_WARM_RESET_JUMP = 0x0101_0068
# Out-of-range value only cold_boot writes to the handler slot.
_COLD_POISON = 0xFFFF_FFFF

# Covers real fuse sense, which completes before the core is released.
_MAX_RUN_CYCLES = 400_000
_PROGRESS_EVERY = 50_000


@pyuvm.test()
class sep_scratch_7_test(sep_base_test):
    """Seed the warm handler slot, boot the ROM, and prove it jumped there."""

    build_env = False
    rom_build_dir = _FW_DIR

    async def run_scenario(self) -> None:
        dut = cocotb.top

        seeded = cocotb.plusargs.get("sep_cold_scratch7")
        assert seeded is not None, (
            "+sep_cold_scratch7 is not set: the testlist must seed the warm handler "
            "slot or this test proves nothing about the warm path"
        )
        assert int(str(seeded), 16) == _HANDLER_ADDR, (
            f"+sep_cold_scratch7={seeded} does not match the address this test "
            f"expects (0x{_HANDLER_ADDR:08x}); the ICCM poke puts the "
            f"handler instruction only at that address"
        )
        assert _ICCM_BASE <= _HANDLER_ADDR < _ICCM_END, (
            f"handler address 0x{_HANDLER_ADDR:08x} is outside the ROM's "
            f"accept window [0x{_ICCM_BASE:08x}, 0x{_ICCM_END:08x}) -- this test "
            f"would then be exercising the reject arm, which is a different item"
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

        # Start sampling before reset release: the seed is visible only inside bring-up.
        obs = _WarmDispatchObserver(self)
        sampler = cocotb.start_soon(obs.run(dut))
        await self.bring_up_cpu_boot(
            _ROM_BASE >> 1,
            pre_reset_hook=_load_tcm,
            run_pulse_cycles=40,
        )
        await sampler
        log_scratch_cold(self.logger)

        obs.check(self.logger, console)


class _WarmDispatchObserver:
    def __init__(self, test: sep_base_test) -> None:
        self._test = test
        # Change-only sequences: the seed is overwritten, so an end-state read cannot see it.
        self.cold7_seq: list[int] = []
        self.status_seq: list[int] = []
        self.pcs: set[int] = set()
        self.retired = 0

    async def run(self, dut) -> None:
        rd = self._test.rd
        log = self._test.logger
        last_cold7 = None
        last_status = None
        last_log = 0
        for cycle in range(_MAX_RUN_CYCLES):
            await RisingEdge(dut.clk_i)
            cold7 = (rd(dut.scratch_cold_probe_o) >> 224) & 0xFFFF_FFFF
            if cold7 != last_cold7:
                last_cold7 = cold7
                self.cold7_seq.append(cold7)
            status = (rd(dut.scratch_cold_probe_o) >> 32) & 0xFFFF_FFFF
            if status != last_status:
                last_status = status
                self.status_seq.append(status)
            if rd(dut.cpu_trace_valid_o):
                self.retired += 1
                self.pcs.add(rd(dut.cpu_trace_addr_o) & 0xFFFF_FFFF)
            # Stop after the slot's zero write; any cold-boot write precedes the jump.
            if (
                _STATUS_WARM_RESET_JUMP in self.status_seq
                and _HANDLER_ADDR in self.pcs
                and self.cold7_seq[-1] == 0
            ):
                log.info("warm dispatch observed at cycle %d; stopping sampler", cycle)
                return
            if cycle - last_log >= _PROGRESS_EVERY:
                last_log = cycle
                log.info(
                    "warm dispatch poll cyc=%d cold7=0x%08x status=0x%08x retired=%d pcs=%d",
                    cycle,
                    cold7,
                    status,
                    self.retired,
                    len(self.pcs),
                )
        log.info(
            "sampler ran out at %d cycles: cold7_seq=%s status_seq=%s retired=%d",
            _MAX_RUN_CYCLES,
            [hex(v) for v in self.cold7_seq],
            [hex(v) for v in self.status_seq],
            self.retired,
        )

    def check(self, log, console: list[str]) -> None:
        cold7_hex = [hex(v) for v in self.cold7_seq]
        status_hex = [hex(v) for v in self.status_seq]
        log.info("cold_scratch[7] sequence: %s", cold7_hex)
        log.info("cold_scratch[1] sequence: %s", status_hex)
        log.info("retired=%d distinct PCs=%d", self.retired, len(self.pcs))

        # A zero slot also cold-boots and retires instructions, so prove the seed landed.
        assert _HANDLER_ADDR in self.cold7_seq, (
            f"cold_scratch[7] never held the seeded handler address "
            f"0x{_HANDLER_ADDR:08x}; observed {cold7_hex}. The tb deposit did "
            f"not take, so this run says nothing about the warm path"
        )
        log.info("CHK-COLD7-SEED PASS: cold_scratch[7] held 0x%08x", _HANDLER_ADDR)

        assert _STATUS_WARM_RESET_JUMP in self.status_seq, (
            f"ROM never wrote WARM_RESET_JUMP (0x{_STATUS_WARM_RESET_JUMP:08x}) to "
            f"cold_scratch[1]; observed {status_hex}"
        )
        log.info(
            "CHK-WARM-ANNOUNCE: cold_scratch[1] = 0x%08x (WARM_RESET_JUMP)",
            _STATUS_WARM_RESET_JUMP,
        )

        assert _HANDLER_ADDR in self.pcs, (
            f"no instruction retired at the handler address "
            f"0x{_HANDLER_ADDR:08x}; the ROM announced the jump but control "
            f"did not arrive there. Distinct PCs seen: "
            f"{sorted(hex(p) for p in self.pcs)[:32]}"
        )
        log.info("CHK-WARM-JUMP PASS: retired at 0x%08x", _HANDLER_ADDR)

        # The slot is one-shot, so a later reset cannot re-enter a stale handler.
        last_seed = max(i for i, v in enumerate(self.cold7_seq) if v == _HANDLER_ADDR)
        after_seed = [hex(v) for v in self.cold7_seq[last_seed + 1 :]]
        assert after_seed == ["0x0"], (
            f"cold_scratch[7] after the seed 0x{_HANDLER_ADDR:08x} went {after_seed}, "
            f"expected exactly ['0x0']: the ROM must write 0 to the slot before it jumps "
            f"to the handler. Sequence: {cold7_hex}"
        )
        log.info(
            "CHK-WARM-POISONED PASS: cold_scratch[7] went 0x%08x -> 0x0 on the accept path",
            _HANDLER_ADDR,
        )

        # Not keyed on BOOTROM_START: the boot flow emits it before the scratch-7 decision.
        assert _COLD_POISON not in self.cold7_seq, (
            f"cold_scratch[7] took cold_boot's out-of-range poison "
            f"0x{_COLD_POISON:08x}: the ROM fell through to cold_boot instead of "
            f"dispatching to the warm handler. Sequence: {cold7_hex}"
        )
        assert not console, (
            f"ROM produced console output, which only happens on the cold-boot "
            f"path (every simputs call sits downstream of cold_boot): {console}"
        )
        log.info(
            "CHK-WARM-NO-COLD: cold_boot's 0x%08x poison never appeared and "
            "no cold-path console output",
            _COLD_POISON,
        )
