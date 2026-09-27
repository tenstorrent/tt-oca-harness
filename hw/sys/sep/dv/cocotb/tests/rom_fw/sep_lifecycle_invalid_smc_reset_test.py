# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Invalid LC_STATE: the ROM halts, and its SMC-reset mitigation really lands.

Checks that the reset-control write hits an implemented SMC window with core reset_n
bits clear.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from env.sep_rom_console import log_scratch_cold, rom_console_task
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_SEP_ROOT = str(Path(__file__).resolve().parents[4])
# The LC check runs before transport selection, so the default ROM build suffices.
_FW_DIR = os.path.join(_SEP_ROOT, "bootrom", "prod", "build")
_ROM_BASE = sym("SEP_BOOT_ROM_MEM_BASE_ADDR")

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_invalid.toml"
)

# lc_state_is_valid() accepts raw 0x0..0x8; 0x9 is the first code outside it.
_LC_INVALID_RAW = 0x9

# STATUS_ENCODE(ERROR, ROM_ERR_LIFECYCLE_INVALID): the last store before the wfi spin.
_STATUS_LC_TERMINAL = 0x0F01_A002
# ERROR + SEP_MSG_LIFECYCLE_INVALID, reported before the SMC write.
_STATUS_LC_INVALID = 0x0F01_0001

_CORE_RESET_N_MASK = 0xF

# DCCM scrub and ICCM clear alone cost about 400k cycles before the LC check runs.
_MAX_RUN_CYCLES = 24_000_000
_PROGRESS_EVERY = 200_000
# The halt is a two-instruction `wfi; j` spin.
_QUIESCE_CYCLES = 2_000
_QUIESCE_PC_SPAN_MAX = 64


@pyuvm.test()
class sep_lifecycle_invalid_smc_reset_test(sep_base_test):
    """An invalid LC_STATE halts the boot and asserts SMC core reset correctly."""

    build_env = False
    rom_build_dir = _FW_DIR

    async def run_scenario(self) -> None:
        dut = cocotb.top

        assert os.path.isfile(_EFUSE_PRELOAD), f"eFuse preload missing: {_EFUSE_PRELOAD}"
        image = self.select_efuse_image(default_preload=_EFUSE_PRELOAD)
        lc = image.lc_raw()
        assert lc == _LC_INVALID_RAW, (
            f"LC_STATE raw is 0x{lc:x}, expected 0x{_LC_INVALID_RAW:x}. This "
            f"testcase needs a state lc_state_is_valid() rejects; a valid one "
            f"would boot on and never reach the arm under test"
        )
        self.write_efuse_image(image)
        self.logger.info(
            "CHK-STIMULUS-LC: preloaded LC_STATE raw=0x%x, which lifecycle.c "
            "rejects (valid set is 0x0..0x8)",
            lc,
        )

        for src_name, dst in (("boot_rom.vmem", "boot_rom.vmem"),):
            src = os.path.join(_FW_DIR, src_name)
            if not os.path.isfile(src):
                raise FileNotFoundError(f"ROM image not found: {src}")
            shutil.copyfile(src, os.path.join(os.getcwd(), dst))

        console: list[str] = []
        cocotb.start_soon(rom_console_task(self.logger, sink=console))

        # No TCM staging: the ROM runs from Boot ROM and vector.S scrubs DCCM ECC.
        await self.bring_up_cpu_boot(_ROM_BASE >> 1, run_pulse_cycles=40)

        status_seq: list[int] = []
        last_status = None
        halted = False
        saw_invalid_report = False
        last_log = 0
        for cycle in range(_MAX_RUN_CYCLES):
            await RisingEdge(dut.clk_i)
            status = (self.rd(dut.scratch_cold_probe_o) >> 32) & 0xFFFF_FFFF
            if status != last_status:
                last_status = status
                status_seq.append(status)
                if status == _STATUS_LC_INVALID:
                    saw_invalid_report = True
            if status == _STATUS_LC_TERMINAL:
                halted = True
                self.logger.info("ROM reached the LC terminal at cycle %d", cycle)
                break
            if cycle - last_log >= _PROGRESS_EVERY:
                last_log = cycle
                self.logger.info(
                    "lc invalid poll cyc=%d status=0x%08x",
                    cycle,
                    status,
                )

        # The spin keeps retiring instructions, so PC locality, not volume, shows the halt.
        post_pcs: set[int] = set()
        if halted:
            for _ in range(_QUIESCE_CYCLES):
                await RisingEdge(dut.clk_i)
                if self.rd(dut.cpu_trace_valid_o):
                    post_pcs.add(self.rd(dut.cpu_trace_addr_o))
        post_span = (max(post_pcs) - min(post_pcs)) if post_pcs else 0

        log_scratch_cold(self.logger)
        self.logger.info(
            "cold_scratch[1] sequence: %s",
            [hex(v) for v in status_seq],
        )

        assert saw_invalid_report, (
            f"ROM never reported STATUS 0x{_STATUS_LC_INVALID:08x} "
            f"(ERROR + SEP_MSG_LIFECYCLE_INVALID). It did not classify raw "
            f"0x{_LC_INVALID_RAW:x} as invalid, so the arm under test never ran. "
            f"Status sequence: {[hex(v) for v in status_seq]}"
        )
        self.logger.info(
            "CHK-LC-INVALID: ROM reported ERROR+LIFECYCLE_INVALID for raw 0x%x",
            lc,
        )

        violations = self.rd(dut.smc_addr_violations_o)
        assert violations == 0, (
            f"{violations} SEP->SMC access(es) fell outside every register "
            f"window in smc_addr.h. The SMC-reset mitigation must target "
            f"SMC_CPU_CTRL_RESET_CTRL at SEP-view 0x40039020 (inside the "
            f"0x4003_9000 + 0x2C0 window); a bare 0x0020 offset lands on "
            f"0x40000020, below the lowest window. See the $error lines in the "
            f"simulation log for the offending addresses."
        )
        self.logger.info(
            "CHK-SMC-RST-ADDR: smc_addr_violations_o == 0 -- every SEP->SMC "
            "access, the reset-control write included, hit an implemented window",
        )

        rst = _read_logged_reset_value(console)
        assert (rst & _CORE_RESET_N_MASK) == 0, (
            f"ROM wrote 0x{rst:08x} to SMC_CPU_CTRL_RESET_CTRL, which leaves "
            f"core reset_n bits [3:0] set. cpu_ctrl.rdl declares "
            f"core[0..3]_reset_n_n0_scan active low with reset value 1, so the "
            f"bits must be CLEARED to hold the cores in reset; setting them "
            f"releases reset, the opposite of the mitigation's intent"
        )
        self.logger.info(
            "CHK-SMC-RST-POL: ROM wrote 0x%08x, core reset_n bits [3:0] clear "
            "-- active-low reset asserted",
            rst,
        )

        assert halted, (
            f"ROM never wrote the terminal verdict 0x{_STATUS_LC_TERMINAL:08x} "
            f"(ERROR + ROM_ERR_LIFECYCLE_INVALID) within {_MAX_RUN_CYCLES} "
            f"cycles. An invalid LC_STATE must be terminal. Status sequence: "
            f"{[hex(v) for v in status_seq]}"
        )
        assert post_pcs, (
            "no instructions retired after the terminal verdict, so the halt "
            "cannot be distinguished from a stalled clock"
        )
        assert post_span <= _QUIESCE_PC_SPAN_MAX, (
            f"after the terminal verdict the PC walked 0x{post_span:x} bytes "
            f"across {len(post_pcs)} addresses, more than the wfi/j spin's "
            f"0x{_QUIESCE_PC_SPAN_MAX:x}. The ROM continued executing instead of "
            f"halting. PCs: {sorted(hex(p) for p in post_pcs)}"
        )
        self.logger.info(
            "CHK-LC-TERMINAL: terminal verdict reached and the PC stayed within "
            "0x%x bytes over %d addresses -- the boot stopped",
            post_span,
            len(post_pcs),
        )


def _read_logged_reset_value(console: list[str]) -> int:
    # The SMC memory model cannot tell the right register from the wrong one, so read the echo.
    token = "SMC_RESET_ON_INVALID_LC="
    for line in console:
        idx = line.find(token)
        if idx >= 0:
            return int(line[idx + len(token) :].split()[0], 16)
    raise AssertionError(
        f"ROM never printed {token}. It is emitted immediately after the SMC "
        f"reset-control write, so its absence means the mitigation did not run. "
        f"Console: {console}"
    )
