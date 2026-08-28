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
    wfi, then spin

This covers the fail + no-bypass arm only. The bypass and pass arms are separate
items and are NOT exercised here.

THE GATE RUNS BEFORE C, AND THAT SHAPES THIS TEST. It precedes the DCCM scrub, so
the lifecycle -- the input deciding whether secure boot is enforced -- is never
computed into memory whose integrity is unestablished; ``LC_STATE_TEST_DEV`` is
0x0, so a corrupted value would bias toward the permissive answer. It also means
**there is no virtual console on this path**: ``simputs()`` needs the C runtime.
This test therefore reads register evidence, and an empty console is itself proof
the gate ran ahead of C.

The status word matches what the C path emits (``0x0f01d001``) and must stay in
step with it, so that assertion pins the same contract on both.

NO MAILBOX ON THIS PATH, SO NO ``fw_done``. The halt writes cold_scratch and
nothing else. The mailbox sits at 0x80000000, inside the external SMU aperture,
and whether an SoC maps anything there is an integration property -- on a part
that does not, the store would take a bus error, the bus error would raise NMI,
and a clean halt would become an NMI loop. A halt path must not reach outside
SEP. This test therefore ends on the terminal status word appearing in
cold_scratch[1], not on ``fw_done``.

The injected value is 0xFFFFFFFD -- every bit set except mem_repair_success.
Injecting 0 would also pass against a ROM that gated on any-bit-clear, on a zero
word, or on the wrong bit entirely, so it would not test what it claims.
All-ones-but-one can only pass if the ROM reads bit 1 specifically.

BYPASS. Now the eFuse ``STATUS_RPT`` bit 2, left unblown, rather than the old
``STRAPS_LO[13]`` strap -- a strap is a pin, so anyone able to hold it could
switch this gate off on a production part. Bit 2 is still inside
``reserved[31:2]`` in ``sep_efuse_map.rdl``, so its use there is undeclared.

The terminal outcome is a silent halt, so ``SepBootScoreboard`` is not used: it
expects a firmware completion signal that this path deliberately never sends.
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
_PRE_C_MARKERS = ("SMC_MEM_CHK", "LC=", "DFT_STATUS=", "CHIP_ID=")
# Must NOT appear either: anything downstream of the gate.
_DOWNSTREAM_MARKERS = ("MANIFEST_OK", "BL1_COPIED", "PRE_JUMP")

# cold_scratch[1] on the two arms. These words match what
# report_status()/rom_err_fail() emits, and must stay in step with it:
#   WARN  + SEP_MSG_MBIST_FAIL (0x219)      -> 0x08 << 24 | 0x01 << 16 | 0x219
#   ERROR + ROM_ERR_DFT_GATE_BLOCKED (0xD001) -> 0x0f << 24 | 0x01 << 16 | 0xD001
# SEP_STATUS_ID is 1 for BL0.
_SEP_MSG_MBIST_FAIL = 0x219
_STATUS_MBIST_WARN = 0x0801_0000 | _SEP_MSG_MBIST_FAIL
_ROM_ERR_DFT_GATE_BLOCKED = 0xD001
_STATUS_DFT_GATE_BLOCKED = 0x0F01_0000 | _ROM_ERR_DFT_GATE_BLOCKED

# The gate is early in rom_main (DFT_STATUS prints around 50k cycles, with real
# fuse sense in front of it), so this budget is generous. The run ends when the
# terminal status word reaches cold_scratch[1]; there is no fw_done on this path.
_MAX_RUN_CYCLES = 400_000
_PROGRESS_EVERY = 50_000

# How long to watch after the terminal status before believing the ROM halted,
# and how far the PC may roam while it does. The halt is `wfi; j back` -- two
# instructions, 8 bytes -- so the span is tiny; 64 bytes leaves room for the
# spin to be restructured without rewriting this test, while still being three
# orders of magnitude below the range forward execution would cover.
#
# Retirement COUNT is deliberately not used: the spin retires roughly one
# instruction every five cycles, so volume looks identical to slow forward
# progress. Location is what separates them.
_QUIESCE_CYCLES = 2_000
_QUIESCE_PC_SPAN_MAX = 64


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
            # The halt is silent by design -- no mailbox, so no fw_done. The
            # terminal status word is the only completion signal, and it is the
            # last thing the gate writes before spinning.
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
        # Did it actually STOP, or just pass through the terminal status on its
        # way somewhere else? Watch a little longer and check WHERE it executes,
        # not how much: the halt is `wfi; j back`, so it keeps retiring -- about
        # one instruction every five cycles -- while never leaving those two
        # addresses. Retirement volume therefore cannot tell a spin from forward
        # progress, but PC locality can, and it is the stronger evidence: code
        # that continued into C would walk across hundreds of addresses.
        post_pcs: set[int] = set()
        post_status_moved = False
        if halted:
            for _ in range(_QUIESCE_CYCLES):
                await RisingEdge(dut.clk_i)
                if self.rd(dut.cpu_trace_valid_o):
                    post_pcs.add(self.rd(dut.cpu_trace_addr_o) << 1)
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

        # Guard the guard: the ROM must have executed at all, or every absence
        # check below is vacuously true. The console cannot serve as that evidence
        # -- on this path it is legitimately empty -- so instruction retirement is
        # the only liveness evidence available.
        assert retired, "core retired no instructions; the ROM never ran"

        # CHK-DFT-READ: the ROM read the injected word. scratch[10] carries it, so
        # this ties the rest of the run to our stimulus rather than to the tb's
        # default 0x03, and it is durable evidence: scratch[10] is readable over
        # JTAG on a part that is hung.
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
        # the terminal status below plus the quiescence check; the bypass arm would
        # instead have continued into C and produced console output, which
        # CHK-DFT-PRE-C already established did not happen.
        bypass_bit = (efuse_img.field_int("STATUS_RPT") >> 2) & 1
        assert bypass_bit == 0, (
            f"STATUS_RPT bit 2 (mem_repair bypass) is set in the eFuse image, so "
            f"the ROM was entitled to continue and this test proves nothing about "
            f"the enforced arm"
        )
        self.logger.info("CHK-DFT-NO-BYPASS: STATUS_RPT bit 2 unblown in the OTP")

        # CHK-DFT-TERMINAL: the error code, and a halt rather than a boot. Both
        # halves matter: the status word says *why* it stopped, the quiescence
        # check says it really did stop instead of reporting and carrying on.
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
