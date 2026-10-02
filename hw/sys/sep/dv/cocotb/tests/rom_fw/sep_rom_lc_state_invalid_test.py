# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""An invalid LC_STATE halts the ROM with the SMC cores held in reset (PyUVM).

FEATURE UNDER TEST. [S11] validates the sensed lifecycle state against the set the
lifecycle controller decodes (SEP-ROM-FUSE-020). On anything else it holds every
SMC core in reset and fails fatally: an invalid state may mean a fuse attack or a
hardware fault, and the SMU must not run in it.

This run presents raw ``0x9``, outside every encoding the LCC decodes. The
preload stores it differentially with a complementary pair, so the LCC's
signal-integrity check passes and the value reaches the decode rather than a
fault. [S11] must print ``LC_STATE_INVALID=``, report ``SEP_MSG_LIFECYCLE_INVALID``
and halt on ``ROM_ERR_LIFECYCLE_INVALID``.

THE SMC HOLD. ``CPU_CTRL.RESET_CTRL`` bits [3:0] are the per-core resets, active
low. The SMC responder is a flat memory, so it cannot hold anything in reset
itself; what it can show is what the ROM wrote and where. The test seeds the
register with its released value plus a pattern in the bits above, and requires
the ROM to have cleared exactly bits [3:0] at the register's real address. The
testbench's SMC address-decode counter must stay at zero, which is what fails if
the write goes anywhere else.

``lc_raw`` and ``efuse_preload`` are class data so other invalid encodings can
reuse the scenario.

The terminal outcome is a halt before any manifest transport is chosen, so no
SPI flash is attached and ``SepBootScoreboard`` is not used, as in
``sep_firmware_sboot_dis_rsvd_terminal_test``.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from env.sep_rom_console import log_scratch_cold, rom_console_task
from env.sep_verdict import decode_verdict
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_SEP_ROOT = str(Path(__file__).resolve().parents[4])
_FW_DIR = os.path.join(_SEP_ROOT, "bootrom", "prod", "build")
_ROM_BASE = sym("SEP_BOOT_ROM_MEM_BASE_ADDR")
EFUSE_DIR = Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads" / "efuse_configurations"

# cold_scratch[1] words, in the order [S11] emits them. SEP_STATUS_ID is 1 for BL0:
#   ERROR + SEP_MSG_LIFECYCLE_INVALID (0x01)    -> 0x0f << 24 | 0x01 << 16 | 0x01
#   ERROR + ROM_ERR_LIFECYCLE_INVALID (0xA002)  -> 0x0f << 24 | 0x01 << 16 | 0xA002
_STATUS_INVALID_DETECTED = 0x0F01_0001
_STATUS_TERMINAL = 0x0F01_A002

# SEP view of SMC CPU_CTRL.RESET_CTRL (SMC-local 0xC0039020), and what it is
# seeded with: the four per-core resets released (their reset value) plus a
# pattern in bits the ROM must leave alone.
_SMC_RESET_CTRL_ADDR = 0x4003_9020
_SMC_CORE_RESET_N_MASK = 0xF
_SMC_RESET_CTRL_SEED = 0x0000_00AF

_INVALID_MARKER = "LC_STATE_INVALID="
_SMC_RESET_MARKER = "SMC_RESET_ON_INVALID_LC"
_SMC_NOT_HELD_MARKER = "SMC_RESET_NOT_HELD="
# Must NOT appear: a decoded state name (rom_lifecycle_policy prints one only for
# a valid state), and anything past the lifecycle stage.
_LC_NAME = "LC="
_DOWNSTREAM_MARKERS = ("FUSE: SBOOT_DIS:", "MANIFEST_OK", "BL1_COPIED", "PRE_JUMP", "BL1_JUMP=")

# [S11] runs before the ROM self-hash, so the verdict comes early.
_MAX_RUN_CYCLES = 6_000_000
_PROGRESS_EVERY = 500_000
# How long to watch after the terminal verdict before believing the ROM halted.
_QUIESCE_CYCLES = 20_000


@pyuvm.test()
class sep_rom_lc_state_invalid_test(sep_base_test):
    """Invalid LC_STATE: the ROM holds the SMC cores in reset and halts."""

    build_env = False
    rom_build_dir = _FW_DIR
    lc_raw = 0x9
    efuse_preload = EFUSE_DIR / "sep_efuse_lc_invalid_0x9.toml"

    async def run_scenario(self) -> None:
        dut = cocotb.top

        assert os.path.isfile(self.efuse_preload), f"eFuse preload missing: {self.efuse_preload}"
        image = self.select_efuse_image(default_preload=self.efuse_preload)
        # Guard the stimulus: a random fallback image would sense a valid state.
        lc = image.lc_raw()
        assert lc == self.lc_raw, (
            f"LC_STATE raw is 0x{lc:x}, expected 0x{self.lc_raw:x}: the testlist must "
            f"pass +sep_efuse_preload={self.efuse_preload}"
        )
        self.write_efuse_image(image)
        self.logger.info("CHK-LC-INVALID-STIMULUS PASS: OTP LC raw=0x%x", lc)

        smc_mem = self.cfg.smc_mem
        assert smc_mem is not None, "no SMC responder: this test needs the rom_boot target"
        smc_mem.write32(_SMC_RESET_CTRL_ADDR, _SMC_RESET_CTRL_SEED)

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
                    "lc invalid poll cyc=%d status=0x%08x retired=%d lines=%d",
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
        assert console, "ROM console is empty, so no marker check below means anything"

        # CHK-LC-INVALID-DETECT: [S11] rejected the encoding, and the marker carries
        # the raw value, which shows the ROM read the preload rather than a blank
        # shadow.
        expected_marker = f"{_INVALID_MARKER}0x{self.lc_raw:08x}"
        assert any(expected_marker in line for line in console), (
            f"ROM never printed {expected_marker}: [S11] accepted LC_STATE 0x{self.lc_raw:x}. "
            f"Console: {console}"
        )
        assert _STATUS_INVALID_DETECTED in status_seq, (
            f"cold_scratch[1] never held 0x{_STATUS_INVALID_DETECTED:08x} "
            f"(ERROR + SEP_MSG_LIFECYCLE_INVALID); observed {status_hex}"
        )
        decoded = [line for line in console if line.startswith(_LC_NAME)]
        assert not decoded, (
            f"ROM printed {decoded}: it decoded 0x{self.lc_raw:x} as a state the "
            f"lifecycle controller treats as INVALID. Console: {console}"
        )
        self.logger.info(
            "CHK-LC-INVALID-DETECT PASS: %s, cold_scratch[1]=0x%08x, no state decoded",
            expected_marker,
            _STATUS_INVALID_DETECTED,
        )

        # CHK-LC-INVALID-SMC-HOLD: the core resets were cleared, at the register's
        # real address, and nothing else in the register moved.
        reset_ctrl = smc_mem.read32(_SMC_RESET_CTRL_ADDR)
        expected = _SMC_RESET_CTRL_SEED & ~_SMC_CORE_RESET_N_MASK
        violations = self.rd(dut.smc_addr_violations_o)
        assert any(_SMC_RESET_MARKER in line for line in console), (
            f"ROM never printed {_SMC_RESET_MARKER}. Console: {console}"
        )
        assert reset_ctrl == expected, (
            f"SMC CPU_CTRL.RESET_CTRL is 0x{reset_ctrl:08x}, expected 0x{expected:08x}: "
            f"seeded 0x{_SMC_RESET_CTRL_SEED:08x}, and the ROM must clear the active-low "
            f"core resets [3:0] and leave the other bits as they were"
        )
        assert not any(_SMC_NOT_HELD_MARKER in line for line in console), (
            f"ROM printed {_SMC_NOT_HELD_MARKER}: its read-back found a core not held. "
            f"Console: {console}"
        )
        assert violations == 0, (
            f"smc_addr_violations_o is {violations}: the ROM accessed an SMC address "
            f"outside every register window"
        )
        self.logger.info(
            "CHK-LC-INVALID-SMC-HOLD PASS: RESET_CTRL 0x%08x -> 0x%08x, no SMC address violations",
            _SMC_RESET_CTRL_SEED,
            reset_ctrl,
        )

        # CHK-LC-INVALID-TERMINAL: the error code, and a halt rather than a boot.
        assert fw_done, (
            f"ROM never signalled completion within {_MAX_RUN_CYCLES} cycles; "
            f"cold_scratch[1] observed {status_hex}"
        )
        assert not fw_pass, "ROM signalled PASS: it booted on an invalid lifecycle state"
        assert _STATUS_TERMINAL in status_seq, (
            f"cold_scratch[1] never held 0x{_STATUS_TERMINAL:08x} "
            f"(ERROR + ROM_ERR_LIFECYCLE_INVALID); observed {status_hex}"
        )
        assert status_seq.index(_STATUS_INVALID_DETECTED) < status_seq.index(_STATUS_TERMINAL), (
            f"the terminal code preceded the detection code in {status_hex}"
        )
        assert not post_status_moved, (
            "cold_scratch[1] moved on after the terminal code, so the ROM reported "
            "the fault and then continued instead of halting"
        )
        assert not post_console, (
            f"ROM kept printing after the terminal code, so it did not halt: {post_console}"
        )
        self.logger.info(
            "CHK-LC-INVALID-TERMINAL PASS: cold_scratch[1]=0x%08x, mailbox FAIL, "
            "quiet for %d cycles",
            _STATUS_TERMINAL,
            _QUIESCE_CYCLES,
        )

        # CHK-LC-INVALID-NO-PROGRESS: nothing downstream of [S11] ran.
        for marker in _DOWNSTREAM_MARKERS:
            assert not any(marker in line for line in console), (
                f"ROM printed {marker}, which sits downstream of [S11]. Console: {console}"
            )
        self.logger.info(
            "CHK-LC-INVALID-NO-PROGRESS PASS: none of %s reached",
            ", ".join(_DOWNSTREAM_MARKERS),
        )
