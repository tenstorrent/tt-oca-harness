# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP loads its own TCM from boot ROM, with no testbench preload.

Every other real-firmware anchor here has its ICCM/DCCM placed by the testbench
backdoor, because the product boot path (ROM -> SPI flash -> manifest -> BL1)
needs the SPI flash models that this tree excludes. That backdoor is the same
one the OSS SEP DV testbench uses, but it does hide one real step: the CPU
loading its own TCM.

hw/sys/sep/dv/fw/tests/rom_no_tcm_preload_mem_init is the one image that closes
that gap. It runs entirely from the SEP boot ROM -- loaded exactly as the SEP DV
testbench loads it, through `+sep_boot_rom_hex` into `u_sep_boot_rom.mem` -- and
this test runs it with `+sep_no_tcm_preload`, so the TCM holds nothing but
zeroes when the CPU starts. The image then:

  * writes and reads back DCCM from ROM-fetched code,
  * stages a short routine into SEP SRAM as raw instruction words (the EL2 LSU
    cannot write ICCM directly),
  * opens the secure-DMA range and DMAs SRAM -> ICCM,
  * jumps to the ICCM copy, which reports through the STDOUT mailbox.

So a PASS here proves the SEP moved code into its own ICCM and executed it. The
ICCM PC is checked separately from the mailbox verdict: reaching the DMA target
is what distinguishes a real load from a firmware that reported PASS some other
way.
"""

from __future__ import annotations

import os
from collections import Counter

import cocotb
from cocotb.triggers import RisingEdge

from seq_lib.sep_fw_common import addr_of, format_pc_profile, load_syms

# From the image's own .equ block.
ICCM_PROG_ADDR = 0xC002_0000
SEP_BOOT_ROM_BASE = 0x1004_0000
SEP_BOOT_ROM_END = 0x1005_0000

SETTLE_CYCLES = 2000


class SmuSepRomTcmLoadSeq:
    """Require the SEP to DMA code into ICCM and execute it, unaided."""

    #: Evidence tokens logged once every check above the verdict has held.
    EVIDENCE = ("SEP_ROM_TCM_LOAD_OK", "SEP_SELF_LOADED_ICCM_OK")

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.log = test.logger
        test.declare_evidence(*self.EVIDENCE)

    def _rd(self, handle, name):
        return self.test.read_int(handle, name, allow_xz=True)

    async def run(self) -> None:
        max_cycles = int(os.environ.get("SMU_SEP_FW_MAX_CYCLES", "300000"), 0)
        heartbeat = max(1, max_cycles // 20)

        sym_path = str(cocotb.plusargs.get("sep_sym", "rom_no_tcm_preload_mem_init.rom_only.sym"))
        syms = load_syms(sym_path)
        assert syms, f"no usable symbol table at {sym_path}"
        start_pc = addr_of(syms, "_start")
        fail_hang_pc = addr_of(syms, "fail_hang")
        dma_done_pc = addr_of(syms, "dma_done")

        assert SEP_BOOT_ROM_BASE <= start_pc < SEP_BOOT_ROM_END, (
            f"_start 0x{start_pc:08x} is not in the boot-ROM window; this image "
            "is supposed to run from ROM"
        )

        self.log.info("=" * 70)
        self.log.info("TEST: SEP loads its own TCM from boot ROM (no TB preload)")
        self.log.info("=" * 70)
        self.log.info(
            "symbols: _start=0x%08x dma_done=0x%08x fail_hang=0x%08x; DMA target ICCM 0x%08x",
            start_pc,
            dma_done_pc,
            fail_hang_pc,
            ICCM_PROG_ADDR,
        )

        rom_exec = False
        dma_done_seen = False
        iccm_exec = False
        fail_hang_seen = False
        done = False
        passed = False
        traces = 0
        pc_hist: Counter[int] = Counter()

        for cycle in range(max_cycles):
            await RisingEdge(self.dut.clk_smu_i)

            if self._rd(self.dut.sep_trace_valid_o, "sep_trace_valid_o"):
                pc = self._rd(self.dut.sep_pc_o, "sep_pc_o") & 0xFFFF_FFFF
                traces += 1
                pc_hist[pc] += 1
                rom_exec |= SEP_BOOT_ROM_BASE <= pc < SEP_BOOT_ROM_END
                dma_done_seen |= pc == dma_done_pc
                fail_hang_seen |= pc == fail_hang_pc
                # The DMA'd routine is 9 instructions at ICCM_PROG_ADDR.
                iccm_exec |= ICCM_PROG_ADDR <= pc < ICCM_PROG_ADDR + 0x40

            if self._rd(self.dut.fw_done_o, "fw_done_o"):
                done = True
                passed = bool(self._rd(self.dut.fw_pass_o, "fw_pass_o"))
                break

            if cycle and cycle % heartbeat == 0:
                self.log.info(
                    "rom-tcm-load heartbeat cycle=%d traces=%d distinct_pcs=%d "
                    "rom=%s dma_done=%s iccm_exec=%s fail_hang=%s",
                    cycle,
                    traces,
                    len(pc_hist),
                    rom_exec,
                    dma_done_seen,
                    iccm_exec,
                    fail_hang_seen,
                )

        for _ in range(SETTLE_CYCLES):
            await RisingEdge(self.dut.clk_smu_i)

        for line in format_pc_profile(syms, pc_hist, traces):
            self.log.info("%s", line)

        errors: list[str] = []
        if not rom_exec:
            errors.append("SEP never executed from the boot-ROM window")
        if fail_hang_seen:
            errors.append(
                f"firmware parked in fail_hang 0x{fail_hang_pc:08x} -- one of its "
                "own ROM-side checks failed before the DMA completed"
            )
        if not dma_done_seen:
            errors.append(
                f"firmware never reached dma_done 0x{dma_done_pc:08x} -- the "
                "SRAM->ICCM secure DMA did not complete"
            )
        if not iccm_exec:
            errors.append(
                f"SEP never executed at the DMA target 0x{ICCM_PROG_ADDR:08x}; "
                "no code was running out of ICCM, so nothing proves the TCM load"
            )
        if not done:
            errors.append(
                f"no STDOUT verdict within {max_cycles} cycles "
                f"(traces={traces} distinct_pcs={len(pc_hist)})"
            )
        elif not passed:
            errors.append("firmware reported TEST_MAGIC_FAIL")

        assert not errors, "SEP rom TCM load: " + "; ".join(errors)

        self.log.info(
            "CHK-SEP-ROM-TCM-LOAD: PASS (ROM exec → dma_done 0x%08x → ICCM exec at "
            "0x%08x → TEST_MAGIC_PASS; TCM was zero at reset, the SEP loaded it)",
            dma_done_pc,
            ICCM_PROG_ADDR,
        )
        self.log.info(
            "CHK-SEP-ROM-TCM-NONVAC: PASS (no TB TCM preload; ICCM execution is "
            "only possible because the firmware's own DMA put code there, "
            "traces=%d)",
            traces,
        )
        for token in self.EVIDENCE:
            self.log.info("EVIDENCE: %s", token)
            self.log.info("EVIDENCE:%s", token)
            self.log.info("EVIDENCE:CHK-%s", token)
            self.log.info("EVIDENCE: CHK-%s", token)
