# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP Boot ROM MEM_REPAIR / MBIST boot gate, failure arm (PyUVM).

FEATURE UNDER TEST. Before the ROM boots anything it asks the SMC whether memory
repair succeeded, and refuses to continue if it did not. The gate lives in
``bootrom/prod/src/vector.S``, immediately before the DCCM scrub::

    lw   t1, (SMC_DFX_CTRL_STATUS_SMU)      # smc_base + 0xF800
    andi t2, t1, DFT_MEM_REPAIR_SUCCESS     # bit 1 set -> continue
    sw   t1, (SMC_SCRATCH_MBIST_FAIL)       # publish raw value, scratch 10
    sw   0x08010219, (SEP_COLD_SCRATCH_1)   # WARN + SEP_MSG_MBIST_FAIL
    lw   t3, (SEP_EFUSE_STATUS_RPT)         # bypass fuse
    andi t4, t3, (1 << 2)                   # blown -> continue
    sw   0x0f01d001, (SEP_COLD_SCRATCH_1)   # ERROR + ROM_ERR_DFT_GATE_BLOCKED
    <mailbox MAGIC / FAIL / 0xd001>, then spin

This covers the fail + no-bypass arm only. The bypass and pass arms are separate
items and are NOT exercised here.

WHY THE GATE IS IN ASSEMBLY, AND WHAT THAT MEANS FOR THIS TEST. It used to run in
C, after straps, PLL, lifecycle and chip-ID. A repair failure therefore let the
ROM compute and store the lifecycle -- the input deciding whether secure boot is
enforced -- in DCCM whose integrity had not been established, and
``LC_STATE_TEST_DEV`` is 0x0 so a corrupted value biases toward the permissive
answer. Moving the gate ahead of the DCCM scrub fixes that, and it also means
**there is no virtual console on this path**: ``simputs()`` needs the C runtime.
The old ``MEM_REPAIR_FAIL`` / ``MEM_REPAIR_BYPASS`` / ``DFT_STATUS=`` markers are
gone by construction, so this test now reads the register evidence instead --
which is strictly more than it could check before, because an empty console is
itself proof the gate ran ahead of C.

The status word and mailbox triple are unchanged from the C version on purpose
(``0x0f01d001`` / ``0xd001``), so those assertions still pin the same contract.

The injected value is 0xFFFFFFFD -- every bit set except mem_repair_success.
Injecting 0 would also pass against a ROM that gated on any-bit-clear, on a zero
word, or on the wrong bit entirely, so it would not test what it claims.
All-ones-but-one can only pass if the ROM reads bit 1 specifically.

BYPASS. Now the eFuse ``STATUS_RPT`` bit 2, left unblown, rather than the old
``STRAPS_LO[13]`` strap -- a strap is a pin, so anyone able to hold it could
switch this gate off on a production part. Bit 2 is still inside
``reserved[31:2]`` in ``sep_efuse_map.rdl``; declaring it is tracked as A32.

The terminal outcome is a mailbox FAIL, so ``SepBootScoreboard`` is not used: it
treats fw_pass=0 as an error, whereas here it is the expected result.
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
# Same ROM build as the OT boot tests: the DFT gate runs well before any manifest
# transport is selected, so the SPI variant is irrelevant and this adds no new
# firmware build profile.
_FW_DIR = os.path.join(_SEP_ROOT, "bootrom", "prod", "build_ot")
_ROM_BASE = sym("SEP_BOOT_ROM_MEM_BASE_ADDR")

# The injected DFX_CTRL_STATUS word. Must match +sep_dft_status in the testlist.
_DFT_STATUS_FAIL = 0xFFFF_FFFD
# bootrom/prod/include/sep_smc_interface.h: DFT_STATUS_MEM_REPAIR_SUCCESS_BIT 1.
_MEM_REPAIR_SUCCESS_BIT = 1

# The gate is pre-C, so the console is silent on this path. Any of these appearing
# would mean the ROM reached the C runtime, i.e. the gate did NOT stop it early.
# This replaces the old presence-checks on MEM_REPAIR_FAIL / DFT_STATUS= /
# MEM_REPAIR_BYPASS, which were simputs() text that no longer exists.
_PRE_C_MARKERS = ("SMC_MEM_CHK", "LC=", "DFT_STATUS=", "CHIP_ID=")
# Must NOT appear either: anything downstream of the gate.
_DOWNSTREAM_MARKERS = ("MANIFEST_OK", "BL1_COPIED", "PRE_JUMP")

# cold_scratch[1] on the two arms. The assembly reproduces exactly what
# report_status()/rom_err_fail() used to emit, so these words are unchanged:
#   WARN  + SEP_MSG_MBIST_FAIL (0x219)      -> 0x08 << 24 | 0x01 << 16 | 0x219
#   ERROR + ROM_ERR_DFT_GATE_BLOCKED (0xD001) -> 0x0f << 24 | 0x01 << 16 | 0xD001
# SEP_STATUS_ID is 1 for BL0.
_SEP_MSG_MBIST_FAIL = 0x219
_STATUS_MBIST_WARN = 0x0801_0000 | _SEP_MSG_MBIST_FAIL
_ROM_ERR_DFT_GATE_BLOCKED = 0xD001
_STATUS_DFT_GATE_BLOCKED = 0x0F01_0000 | _ROM_ERR_DFT_GATE_BLOCKED

# The gate is early in rom_main (DFT_STATUS prints around 50k cycles, with real
# fuse sense in front of it), so this budget is generous. The run ends on
# fw_done, not on the budget.
_MAX_RUN_CYCLES = 400_000
_PROGRESS_EVERY = 50_000


@pyuvm.test()
class sep_firmware_mbist_fail_test(sep_base_test):
    """Inject a MEM_REPAIR failure and prove the ROM refuses to boot."""

    build_env = False
    rom_build_dir = _FW_DIR

    async def run_scenario(self) -> None:
        dut = cocotb.top

        # Guard the stimulus. The injection arrives as a plusarg; if it is missing
        # or wrong the ROM sails through the gate and every check below would be
        # reporting on an ordinary boot.
        injected = cocotb.plusargs.get("sep_dft_status")
        assert injected is not None, (
            "+sep_dft_status is not set: without the injection the DFT gate passes "
            "and this test proves nothing about the failure arm"
        )
        assert int(str(injected), 16) == _DFT_STATUS_FAIL, (
            f"+sep_dft_status={injected} does not match the word this test checks "
            f"for (0x{_DFT_STATUS_FAIL:08x})"
        )
        # Self-check the stimulus shape, so a future edit cannot quietly turn this
        # into a pass-arm injection (which would still boot, and still be green).
        assert not (_DFT_STATUS_FAIL >> _MEM_REPAIR_SUCCESS_BIT) & 1, (
            f"injected DFT status 0x{_DFT_STATUS_FAIL:08x} has mem_repair_success "
            f"(bit {_MEM_REPAIR_SUCCESS_BIT}) SET -- that is the pass arm"
        )
        assert _DFT_STATUS_FAIL & ~(1 << _MEM_REPAIR_SUCCESS_BIT) & 0xFFFF_FFFF == (
            0xFFFF_FFFF & ~(1 << _MEM_REPAIR_SUCCESS_BIT)
        ), (
            "injected DFT status must have every bit except mem_repair_success set, "
            "otherwise it cannot distinguish a bit-1 check from a zero-word check"
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
        scratch10_seq: list[int] = []
        last_status = None
        last_s10 = None
        fw_done = False
        fw_pass = 0
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
            if self.rd(dut.fw_done_o):
                fw_done = True
                fw_pass = self.rd(dut.fw_pass_o)
                self.logger.info("ROM signalled completion at cycle %d", cycle)
                break
            if cycle - last_log >= _PROGRESS_EVERY:
                last_log = cycle
                self.logger.info(
                    "mbist gate poll cyc=%d status=0x%08x scratch10=0x%08x retired=%d",
                    cycle, status, s10, retired,
                )
        log_scratch_cold(self.logger)

        status_hex = [hex(v) for v in status_seq]
        s10_hex = [hex(v) for v in scratch10_seq]
        self.logger.info("cold_scratch[1] sequence: %s", status_hex)
        self.logger.info("SMC scratch[10] sequence: %s", s10_hex)
        self.logger.info("ROM console: %s", console)

        # Guard the guard: the ROM must have executed at all, or every absence
        # check below is vacuously true. The console is NOT used for this any more
        # -- on this path it is legitimately empty -- so instruction retirement is
        # the only liveness evidence available.
        assert retired, "core retired no instructions; the ROM never ran"

        # CHK-DFT-READ: the ROM read the injected word. scratch[10] carries it, so
        # this ties the rest of the run to our stimulus rather than to the tb's
        # default 0x03. It replaces the old console echo, and is better evidence:
        # scratch[10] is readable over JTAG on a part that is hung.
        assert _DFT_STATUS_FAIL in scratch10_seq, (
            f"SMC scratch[10] never held the injected DFT status "
            f"0x{_DFT_STATUS_FAIL:08x}; the ROM did not read our DFX_CTRL_STATUS. "
            f"Observed {s10_hex}"
        )
        self.logger.info("CHK-DFT-READ: ROM read DFT_STATUS=0x%08x", _DFT_STATUS_FAIL)

        # CHK-DFT-DETECT: the gate classified it as a failure and said so before
        # consulting the bypass fuse. Without this, a ROM that skipped straight to
        # the terminal status would be indistinguishable from one that evaluated
        # the failure arm properly.
        assert _STATUS_MBIST_WARN in status_seq, (
            f"cold_scratch[1] never held the WARN word 0x{_STATUS_MBIST_WARN:08x} "
            f"(SEP_MSG_MBIST_FAIL): the gate did not take the failure arm. "
            f"Observed {status_hex}"
        )
        self.logger.info(
            "CHK-DFT-DETECT: cold_scratch[1] = 0x%08x (WARN)", _STATUS_MBIST_WARN
        )

        # CHK-DFT-PRE-C: the gate stopped the ROM before the C runtime, which is
        # the whole point of it living in vector.S. A silent console proves it: the
        # virtual console is simputs(), and simputs() needs C. If any of these
        # appear, the gate ran too late even if it eventually blocked the boot.
        for marker in _PRE_C_MARKERS:
            assert not any(marker in line for line in console), (
                f"ROM printed {marker}, which only the C runtime emits: the gate "
                f"did not stop the boot before C. Console: {console}"
            )
        self.logger.info(
            "CHK-DFT-PRE-C: console silent (%d lines), so the gate preceded C",
            len(console),
        )

        # CHK-DFT-PUBLISH: the raw value reached SMC scratch[10]. The procedure
        # calls this out specifically -- it is the JTAG-readable evidence that the
        # ROM stopped *because* of MEM_REPAIR, available on a part that is hung.
        assert _DFT_STATUS_FAIL in scratch10_seq, (
            f"SMC scratch[10] never held the failing DFT status "
            f"0x{_DFT_STATUS_FAIL:08x}; observed {s10_hex}"
        )
        self.logger.info(
            "CHK-DFT-PUBLISH: SMC scratch[10] = 0x%08x", _DFT_STATUS_FAIL
        )

        # CHK-DFT-NO-BYPASS: the bypass fuse (STATUS_RPT bit 2) is unblown in this
        # eFuse image, so the ROM must not have taken the bypass path. Evidence is
        # the terminal status below plus fw_pass=0; the bypass arm would instead
        # have continued into C and produced console output, which CHK-DFT-PRE-C
        # already established did not happen.
        bypass_bit = (efuse_img.field_int("STATUS_RPT") >> 2) & 1
        assert bypass_bit == 0, (
            f"STATUS_RPT bit 2 (mem_repair bypass) is set in the eFuse image, so "
            f"the ROM was entitled to continue and this test proves nothing about "
            f"the enforced arm"
        )
        self.logger.info("CHK-DFT-NO-BYPASS: STATUS_RPT bit 2 unblown in the OTP")

        # CHK-DFT-TERMINAL: the error code, and a FAIL rather than a boot. Both
        # halves matter: the status word says *why* it stopped, fw_pass=0 says it
        # really did stop instead of reporting an error and carrying on.
        assert _STATUS_DFT_GATE_BLOCKED in status_seq, (
            f"cold_scratch[1] never held ROM_ERR_DFT_GATE_BLOCKED "
            f"(0x{_STATUS_DFT_GATE_BLOCKED:08x}); observed {status_hex}"
        )
        assert fw_done, (
            f"ROM never signalled completion within {_MAX_RUN_CYCLES} cycles; the "
            f"gate should end in a mailbox FAIL. cold_scratch[1]: {status_hex}"
        )
        assert not fw_pass, (
            "ROM signalled PASS: it booted despite the MEM_REPAIR failure"
        )
        self.logger.info(
            "CHK-DFT-TERMINAL: cold_scratch[1] = 0x%08x, mailbox FAIL (fw_pass=0)",
            _STATUS_DFT_GATE_BLOCKED,
        )

        # CHK-DFT-NO-PROGRESS: nothing downstream of the gate ran.
        for marker in _DOWNSTREAM_MARKERS:
            assert not any(marker in line for line in console), (
                f"ROM printed {marker}, which sits downstream of the DFT gate: it "
                f"continued booting past a failure it was supposed to block. "
                f"Console: {console}"
            )
        self.logger.info(
            "CHK-DFT-NO-PROGRESS: none of %s reached", ", ".join(_DOWNSTREAM_MARKERS)
        )
