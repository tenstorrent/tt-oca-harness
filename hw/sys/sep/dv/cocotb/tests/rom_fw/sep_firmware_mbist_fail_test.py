# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP Boot ROM MEM_REPAIR / MBIST boot gate, failure arm (PyUVM).

With mem_repair_success clear and the STATUS_RPT bypass fuse unblown, the pre-C gate
must halt on ROM_ERR_DFT_GATE_BLOCKED with no console output and no fw_done.
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

# The injected DFX_CTRL_STATUS word. Must match +sep_dft_status in the testlist.
_DFT_STATUS_FAIL = 0xFFFF_FFFD
_MEM_REPAIR_SUCCESS_BIT = 1

# Only the C runtime prints these, so any of them means the gate ran too late.
_PRE_C_MARKERS = ("COLD", "LC=", "DFT_STATUS=", "CHIP_ID=")
_DOWNSTREAM_MARKERS = ("MANIFEST_OK", "BL1_COPIED", "PRE_JUMP")

# These words must stay in step with report_status() and rom_err_fail().
_SEP_MSG_MBIST_FAIL = 0x219
_STATUS_MBIST_WARN = 0x0801_0000 | _SEP_MSG_MBIST_FAIL
_ROM_ERR_DFT_GATE_BLOCKED = 0xD001
_STATUS_DFT_GATE_BLOCKED = 0x0F01_0000 | _ROM_ERR_DFT_GATE_BLOCKED

_MAX_RUN_CYCLES = 400_000
_PROGRESS_EVERY = 50_000

# The halt spin keeps retiring, so PC span, not retirement count, shows a halt.
_QUIESCE_CYCLES = 2_000
_QUIESCE_PC_SPAN_MAX = 64


@pyuvm.test()
class sep_firmware_mbist_fail_test(sep_base_test):
    """Inject a MEM_REPAIR failure and prove the ROM refuses to boot."""

    build_env = False
    rom_build_dir = _FW_DIR

    dft_status_injected = _DFT_STATUS_FAIL

    def check_stimulus_shape(self) -> None:
        word = self.dft_status_injected
        assert not (word >> _MEM_REPAIR_SUCCESS_BIT) & 1, (
            f"injected DFT status 0x{word:08x} has mem_repair_success "
            f"(bit {_MEM_REPAIR_SUCCESS_BIT}) SET -- that is the pass arm"
        )
        assert word & ~(1 << _MEM_REPAIR_SUCCESS_BIT) & 0xFFFF_FFFF == (
            0xFFFF_FFFF & ~(1 << _MEM_REPAIR_SUCCESS_BIT)
        ), (
            "injected DFT status must have every bit except mem_repair_success set, "
            "otherwise it cannot distinguish a bit-1 check from a zero-word check"
        )

    async def run_scenario(self) -> None:
        dut = cocotb.top

        injected = cocotb.plusargs.get("sep_dft_status")
        assert injected is not None, (
            "+sep_dft_status is not set: without the injection the DFT gate passes "
            "and this test proves nothing about the failure arm"
        )
        assert int(str(injected), 16) == self.dft_status_injected, (
            f"+sep_dft_status={injected} does not match the word this test checks "
            f"for (0x{self.dft_status_injected:08x})"
        )
        self.check_stimulus_shape()

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
        scratch10_seq: list[int] = []
        last_status = None
        last_s10 = None
        halted = False
        retired = 0
        last_log = 0
        for cycle in range(_MAX_RUN_CYCLES):
            await RisingEdge(dut.clk_i)
            status = (self.rd(dut.scratch_cold_probe_o) >> 32) & 0xFFFF_FFFF
            if status != last_status:
                last_status = status
                status_seq.append(status)
            s10 = self.rd(dut.smc_scratch10_probe_o) & 0xFFFF_FFFF
            if s10 != last_s10:
                last_s10 = s10
                scratch10_seq.append(s10)
            if self.rd(dut.cpu_trace_valid_o):
                retired += 1
            # No fw_done on this path: the terminal status word is the only end signal.
            if status == _STATUS_DFT_GATE_BLOCKED:
                halted = True
                self.logger.info("ROM halted on the gate at cycle %d", cycle)
                break
            if cycle - last_log >= _PROGRESS_EVERY:
                last_log = cycle
                self.logger.info(
                    "mbist gate poll cyc=%d status=0x%08x scratch10=0x%08x retired=%d",
                    cycle, status, s10, retired,
                )
        post_pcs: set[int] = set()
        post_status_moved = False
        if halted:
            for _ in range(_QUIESCE_CYCLES):
                await RisingEdge(dut.clk_i)
                if self.rd(dut.cpu_trace_valid_o):
                    # cpu_trace_addr_o is already a byte address; do not shift it.
                    post_pcs.add(self.rd(dut.cpu_trace_addr_o))
                if ((self.rd(dut.scratch_cold_probe_o) >> 32) & 0xFFFF_FFFF) != \
                        _STATUS_DFT_GATE_BLOCKED:
                    post_status_moved = True
        post_span = (max(post_pcs) - min(post_pcs)) if post_pcs else 0

        log_scratch_cold(self.logger)

        status_hex = [hex(v) for v in status_seq]
        s10_hex = [hex(v) for v in scratch10_seq]
        self.logger.info("cold_scratch[1] sequence: %s", status_hex)
        self.logger.info("SMC scratch[10] sequence: %s", s10_hex)
        self.logger.info("ROM console: %s", console)

        # The console is empty on this path, so retirement is the only liveness proof.
        assert retired, "core retired no instructions; the ROM never ran"

        assert self.dft_status_injected in scratch10_seq, (
            f"SMC scratch[10] never held the injected DFT status "
            f"0x{self.dft_status_injected:08x}; the ROM did not read our DFX_CTRL_STATUS. "
            f"Observed {s10_hex}"
        )
        self.logger.info("CHK-DFT-READ: ROM read DFT_STATUS=0x%08x", self.dft_status_injected)

        assert _STATUS_MBIST_WARN in status_seq, (
            f"cold_scratch[1] never held the WARN word 0x{_STATUS_MBIST_WARN:08x} "
            f"(SEP_MSG_MBIST_FAIL): the gate did not take the failure arm. "
            f"Observed {status_hex}"
        )
        self.logger.info(
            "CHK-DFT-DETECT: cold_scratch[1] = 0x%08x (WARN)", _STATUS_MBIST_WARN
        )

        for marker in _PRE_C_MARKERS:
            assert not any(marker in line for line in console), (
                f"ROM printed {marker}, which only the C runtime emits: the gate "
                f"did not stop the boot before C. Console: {console}"
            )
        self.logger.info(
            "CHK-DFT-PRE-C: console silent (%d lines), so the gate preceded C",
            len(console),
        )

        assert self.dft_status_injected in scratch10_seq, (
            f"SMC scratch[10] never held the failing DFT status "
            f"0x{self.dft_status_injected:08x}; observed {s10_hex}"
        )
        self.logger.info(
            "CHK-DFT-PUBLISH: SMC scratch[10] = 0x%08x", self.dft_status_injected
        )

        bypass_bit = (efuse_img.field_int("STATUS_RPT") >> 2) & 1
        assert bypass_bit == 0, (
            f"STATUS_RPT bit 2 (mem_repair bypass) is set in the eFuse image, so "
            f"the ROM was entitled to continue and this test proves nothing about "
            f"the enforced arm"
        )
        self.logger.info("CHK-DFT-NO-BYPASS: STATUS_RPT bit 2 unblown in the OTP")

        assert _STATUS_DFT_GATE_BLOCKED in status_seq, (
            f"cold_scratch[1] never held ROM_ERR_DFT_GATE_BLOCKED "
            f"(0x{_STATUS_DFT_GATE_BLOCKED:08x}); observed {status_hex}"
        )
        assert halted, (
            f"cold_scratch[1] never reached ROM_ERR_DFT_GATE_BLOCKED within "
            f"{_MAX_RUN_CYCLES} cycles; observed {status_hex}"
        )
        assert not post_status_moved, (
            f"cold_scratch[1] moved on after ROM_ERR_DFT_GATE_BLOCKED, so the gate "
            f"reported the failure and then continued instead of halting"
        )
        assert post_pcs, (
            f"core retired nothing in the {_QUIESCE_CYCLES} cycles after the "
            f"terminal status; expected the `wfi; j` spin, so either the trace "
            f"probe is dead or the core stopped in a way the ROM does not do"
        )
        assert post_span <= _QUIESCE_PC_SPAN_MAX, (
            f"after the terminal status the PC covered {post_span} bytes across "
            f"{len(post_pcs)} addresses ({[hex(p) for p in sorted(post_pcs)]}); a "
            f"halted ROM spins inside {_QUIESCE_PC_SPAN_MAX} bytes, so this one "
            f"reported the failure and then carried on executing"
        )
        self.logger.info(
            "CHK-DFT-TERMINAL: cold_scratch[1] = 0x%08x, then spinning across "
            "%d byte(s) at %s for %d cycles",
            _STATUS_DFT_GATE_BLOCKED, post_span,
            [hex(p) for p in sorted(post_pcs)], _QUIESCE_CYCLES,
        )

        for marker in _DOWNSTREAM_MARKERS:
            assert not any(marker in line for line in console), (
                f"ROM printed {marker}, which sits downstream of the DFT gate: it "
                f"continued booting past a failure it was supposed to block. "
                f"Console: {console}"
            )
        self.logger.info(
            "CHK-DFT-NO-PROGRESS: none of %s reached", ", ".join(_DOWNSTREAM_MARKERS)
        )
