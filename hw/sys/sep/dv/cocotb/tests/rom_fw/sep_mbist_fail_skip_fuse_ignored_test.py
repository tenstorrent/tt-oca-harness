# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""MEM_REPAIR reports failure with eFuse ``STATUS_RPT`` bit 2 blown, and BL0 still halts.

SEP-ROM-SMC-030 makes a failed memory check terminal unless the ``mem_repair_bypass`` strap is
set; no eFuse lets the boot continue. ``STATUS_RPT`` defines ``rpt[1:0]`` and keeps bits [31:2]
reserved (``sep_efuse_map.rdl``), so blowing bit 2 must not change the outcome. The stimulus is
the failure arm's: 0xFFFFFFFD clears only ``mem_repair_success``, so the gate in
``bootrom/prod/src/vector.S`` fails on the repair arm.

The test proves the halt three ways. cold_scratch[1] reaches the terminal ERROR word after the
WARN word and never changes again. Every PC retired after it is one of the two instructions of
the halt spin, taken from the disassembly of the ROM under test, so a jump into the DCCM scrub
loop that follows the gate cannot pass. The console never prints a C-runtime marker.
"""

from __future__ import annotations

import os
import re
import shutil

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from env.sep_efuse_image import LC_TEST_DEV, SepEfuseImage
from env.sep_rom_console import log_scratch_cold, rom_console_task
from env.sep_smc_mem import SMC_SCRATCH10_ADDR
from rom_fw.sep_firmware_mbist_fail_test import (
    _DOWNSTREAM_MARKERS,
    _MAX_RUN_CYCLES,
    _PRE_C_MARKERS,
    _PROGRESS_EVERY,
    _QUIESCE_CYCLES,
    _ROM_BASE,
    _STATUS_DFT_GATE_BLOCKED,
    _STATUS_MBIST_WARN,
    sep_firmware_mbist_fail_test,
)

# Reserved STATUS_RPT bit that the stimulus blows.
_STATUS_RPT_BIT2 = 2

# Every console marker that only the C runtime prints.
_C_RUNTIME_MARKERS = _PRE_C_MARKERS + _DOWNSTREAM_MARKERS

# objdump -d instruction line: "<addr>:\t<opcode>\t<mnemonic>\t<operands>".
_DIS_INSN = re.compile(r"^\s*([0-9a-f]+):\s+[0-9a-f]+\s+(\S+)\s*(\S*)")


def halt_spin_pcs(dis_path: str) -> tuple[int, int]:
    """Return the addresses of the `wfi; j` spin that ends ``mem_repair_fail_hang``."""
    with open(dis_path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.endswith("<mem_repair_fail_hang>:")), None
    )
    assert start is not None, f"mem_repair_fail_hang not found in {dis_path}; rebuild the ROM"
    insns = []
    for line in lines[start + 1 :]:
        if re.match(r"^[0-9a-f]+ <", line):
            break
        m = _DIS_INSN.match(line)
        if m:
            insns.append((int(m.group(1), 16), m.group(2), m.group(3)))
    for (addr, op, _), (next_addr, next_op, target) in zip(insns, insns[1:]):
        if op == "wfi":
            assert next_op == "j" and target == f"{addr:x}", (
                f"instruction after the halt wfi at 0x{addr:08x} is `{next_op} {target}`, "
                f"not a jump back to it"
            )
            return addr, next_addr
    raise AssertionError(f"no wfi in mem_repair_fail_hang in {dis_path}")


@pyuvm.test()
class sep_mbist_fail_skip_fuse_ignored_test(sep_firmware_mbist_fail_test):
    """MEM_REPAIR failed, STATUS_RPT bit 2 blown: warn, publish, and halt."""

    # The PC check rejects the scrub loop; the length only needs a few spin iterations.
    quiesce_cycles = _QUIESCE_CYCLES
    required_evidence = (
        "CHK-SKIP-FUSE-BLOWN",
        "CHK-DFT-PUBLISH",
        "CHK-DFT-DETECT",
        "CHK-DFT-TERMINAL",
        "CHK-DFT-STATUS-STABLE",
        "CHK-DFT-HALT-SPIN",
        "CHK-DFT-NO-PROGRESS",
    )

    def build_efuse_image(self) -> SepEfuseImage:
        image = SepEfuseImage()
        image.set_lc_state(LC_TEST_DEV)
        image.set_int("STATUS_RPT", 1 << _STATUS_RPT_BIT2)
        return image

    async def run_scenario(self) -> None:
        dut = cocotb.top

        injected = cocotb.plusargs.get("sep_dft_status")
        assert injected is not None, (
            "+sep_dft_status is not set: without the injection the DFT gate passes "
            "and this test proves nothing about the failure path"
        )
        assert int(str(injected), 16) == self.dft_status_injected, (
            f"+sep_dft_status={injected} does not match the word this test checks "
            f"for (0x{self.dft_status_injected:08x})"
        )
        self.check_stimulus_shape()

        efuse_img = self.build_efuse_image()
        status_rpt = efuse_img.field_int("STATUS_RPT")
        # CHK-SKIP-FUSE-BLOWN: without bit 2 this run repeats the failure arm.
        assert (status_rpt >> _STATUS_RPT_BIT2) & 1, (
            f"STATUS_RPT bit {_STATUS_RPT_BIT2} is clear in the OTP image "
            f"(STATUS_RPT=0x{status_rpt:08x}); blow it in build_efuse_image()"
        )
        self.logger.info(
            "CHK-SKIP-FUSE-BLOWN PASS: OTP STATUS_RPT = 0x%08x, bit %d = 1",
            status_rpt,
            _STATUS_RPT_BIT2,
        )
        self.write_efuse_image(efuse_img)

        spin_pcs = set(halt_spin_pcs(os.path.join(self.rom_build_dir, "boot_rom.dis")))
        self.logger.info("halt spin PCs: %s", [hex(p) for p in sorted(spin_pcs)])

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

        smc_mem = self.cfg.smc_mem
        assert smc_mem is not None, "SMC responder not bound (rom_boot target only)"
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
            s10 = smc_mem.read32(SMC_SCRATCH10_ADDR)
            if s10 != last_s10:
                last_s10 = s10
                scratch10_seq.append(s10)
            if self.rd(dut.cpu_trace_valid_o):
                retired += 1
            if status == _STATUS_DFT_GATE_BLOCKED:
                halted = True
                self.logger.info("terminal status at cycle %d", cycle)
                break
            if cycle - last_log >= _PROGRESS_EVERY:
                last_log = cycle
                self.logger.info(
                    "mbist gate poll cyc=%d status=0x%08x scratch10=0x%08x retired=%d",
                    cycle,
                    status,
                    s10,
                    retired,
                )

        post_pcs: set[int] = set()
        post_status: list[int] = []
        if halted:
            for _ in range(self.quiesce_cycles):
                await RisingEdge(dut.clk_i)
                if self.rd(dut.cpu_trace_valid_o):
                    post_pcs.add(self.rd(dut.cpu_trace_addr_o))
                status = (self.rd(dut.scratch_cold_probe_o) >> 32) & 0xFFFF_FFFF
                if status != (post_status[-1] if post_status else _STATUS_DFT_GATE_BLOCKED):
                    post_status.append(status)

        log_scratch_cold(self.logger)
        status_hex = [hex(v) for v in status_seq]
        s10_hex = [hex(v) for v in scratch10_seq]
        self.logger.info("cold_scratch[1] sequence: %s", status_hex)
        self.logger.info(
            "cold_scratch[1] after the terminal word: %s", [hex(v) for v in post_status]
        )
        self.logger.info("SMC scratch[10] sequence: %s", s10_hex)
        self.logger.info("PCs after the terminal word: %s", [hex(p) for p in sorted(post_pcs)])
        self.logger.info("ROM console: %s", console)

        assert retired, "core retired no instructions; the ROM never ran"

        # CHK-DFT-PUBLISH: the failure path published the raw status word it gated on.
        assert self.dft_status_injected in scratch10_seq, (
            f"SMC scratch[10] never held the injected DFT status "
            f"0x{self.dft_status_injected:08x}; observed {s10_hex}"
        )
        self.logger.info("CHK-DFT-PUBLISH PASS: SMC scratch[10] = 0x%08x", self.dft_status_injected)

        # CHK-DFT-DETECT: the gate took the failure path and warned.
        assert _STATUS_MBIST_WARN in status_seq, (
            f"cold_scratch[1] never held the WARN word 0x{_STATUS_MBIST_WARN:08x} "
            f"(SEP_MSG_MBIST_FAIL): the gate did not take the failure path. "
            f"Observed {status_hex}"
        )
        self.logger.info("CHK-DFT-DETECT PASS: cold_scratch[1] = 0x%08x (WARN)", _STATUS_MBIST_WARN)

        # CHK-DFT-TERMINAL: the ROM wrote ROM_ERR_DFT_GATE_BLOCKED after the WARN word.
        assert halted, (
            f"cold_scratch[1] never held ROM_ERR_DFT_GATE_BLOCKED "
            f"(0x{_STATUS_DFT_GATE_BLOCKED:08x}) within {_MAX_RUN_CYCLES} cycles, so the "
            f"boot left the gate with STATUS_RPT bit {_STATUS_RPT_BIT2} blown. "
            f"Observed {status_hex}"
        )
        assert status_seq.index(_STATUS_MBIST_WARN) < status_seq.index(_STATUS_DFT_GATE_BLOCKED), (
            f"ROM_ERR_DFT_GATE_BLOCKED preceded the WARN word; observed {status_hex}"
        )
        self.logger.info(
            "CHK-DFT-TERMINAL PASS: cold_scratch[1] = 0x%08x after WARN", _STATUS_DFT_GATE_BLOCKED
        )

        # CHK-DFT-STATUS-STABLE: nothing overwrites the terminal word.
        assert not post_status, (
            f"cold_scratch[1] changed to {[hex(v) for v in post_status]} after "
            f"ROM_ERR_DFT_GATE_BLOCKED, so the ROM kept running past the halt"
        )
        self.logger.info(
            "CHK-DFT-STATUS-STABLE PASS: cold_scratch[1] held 0x%08x for %d cycles",
            _STATUS_DFT_GATE_BLOCKED,
            self.quiesce_cycles,
        )

        # CHK-DFT-HALT-SPIN: the core only executes the halt spin.
        assert post_pcs, (
            f"core retired nothing in the {self.quiesce_cycles} cycles after the "
            f"terminal status; expected the `wfi; j` spin, so the trace probe is dead"
        )
        assert post_pcs <= spin_pcs, (
            f"after the terminal status the core retired "
            f"{[hex(p) for p in sorted(post_pcs - spin_pcs)]} outside the halt spin "
            f"{[hex(p) for p in sorted(spin_pcs)]}, so the ROM continued past the gate"
        )
        self.logger.info(
            "CHK-DFT-HALT-SPIN PASS: %d cycles inside %s",
            self.quiesce_cycles,
            [hex(p) for p in sorted(post_pcs)],
        )

        # CHK-DFT-NO-PROGRESS: the C runtime never started.
        for marker in _C_RUNTIME_MARKERS:
            assert not any(marker in line for line in console), (
                f"ROM printed {marker}, which only the C runtime emits: the boot "
                f"continued past a failed memory check. Console: {console}"
            )
        self.logger.info(
            "CHK-DFT-NO-PROGRESS PASS: none of %s printed", ", ".join(_C_RUNTIME_MARKERS)
        )
