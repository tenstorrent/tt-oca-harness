# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Boot the real SMC production ROM and follow its POST code to OCCP_PROC.

Runs product firmware rather than a DV stub: the image is
hw/sys/smc/bootrom/prod built with I3C_CORE=chipsalliance and preloaded into the CPU ROM
array via +rom_bin64.

The ROM publishes its own progress. smc_post_code_set_boot_phase() writes
scratch register 1 (CPU_CTRL_SCRATCH_1, 0xC0039088) with boot phase in bits
[31:28], per hw/sys/smc/bootrom/prod/lib/include/smc_post_code.h. Those phase
encodings are the contract this sequence checks against -- nothing here
hardcodes a value the ROM does not document.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_cpu_vip_utils import (
    CPU_CTRL_SCRATCH_0,
    CPU_RESET_VECTOR_ROM,
    _release_held_cpu_boot,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_prod_rom_defs import (
    POST_CODE_BOOT_PHASE,
    POST_CODE_BOOT_PHASE_ERROR,
    POST_CODE_BOOT_PHASE_NAMES,
    POST_CODE_BOOT_PHASE_OCCP_PROC,
    POST_CODE_ERROR,
    POST_CODE_ERROR_NAMES,
    SCRATCH_POST_CODE,
    post_code_boot_phase,
    post_code_error,
)


class smc_prod_rom_boot_seq(SmcCsrSeq):
    """Release the CPU onto the production ROM, then track its POST code."""

    # Each poll costs one CSR read over SEP_IN AXI; the ROM walks strap/fuse
    # read, security checks, interface map and OCCP init before it reaches the
    # command loop, so give it room without making a hang cheap to miss.
    POST_POLL_ITERS = 4000
    POST_POLL_CYCLES = 200

    def __init__(self, name: str = "smc_prod_rom_boot_seq") -> None:
        super().__init__(name)
        self.post_code: int = 0
        self.phase_trace: list[int] = []
        self.reached_phase: int = -1

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    async def read_post_code(self) -> int:
        """One POST-code sample through the real SEP_IN AXI CSR path."""
        self.post_code = await self.csr_read("PROD_ROM_POST_CODE", SCRATCH_POST_CODE)
        return self.post_code

    async def boot_prod_rom(self) -> None:
        """Program the ROM reset vector and drop boot_stall.

        Requires +smc_hold_cpu_boot so boot_stall holds the tiles in fuse-reset
        from t=0; otherwise the cores fetch before the vector is set. Mirrors
        smc_cpu_firmware_boot_test's first-boot path.
        """
        if "smc_hold_cpu_boot" not in cocotb.plusargs:
            raise AssertionError(
                "smc_prod_rom_boot_seq requires +smc_hold_cpu_boot so the reset "
                "vector is programmed before the cores fetch"
            )
        if "rom_bin64" not in cocotb.plusargs:
            raise AssertionError(
                "smc_prod_rom_boot_seq requires +rom_bin64=<prod_rom.bin64>; the "
                "production ROM is 16384 64-bit words and only loads through "
                "OCAH4CORECluster_rom_ext's $readmemb path"
            )

        # Clear the SIM pass/fail scratch the ROM also writes, so a stale value
        # can never be mistaken for this boot's result.
        await self.csr_write("PROD_ROM_SCRATCH0_CLEAR", CPU_CTRL_SCRATCH_0, 0)

        self._log(
            f"STEP prod_rom boot: vector={CPU_RESET_VECTOR_ROM:#010x} "
            f"image={cocotb.plusargs.get('rom_bin64')}"
        )
        await _release_held_cpu_boot(self, CPU_RESET_VECTOR_ROM)

    async def wait_for_boot_phase(self, target_phase: int) -> int:
        """Poll the POST code until the ROM reports target_phase.

        Fails on the ROM's own ERROR phase rather than waiting out the bound:
        the ROM parks in a wfi loop on error, so a timeout would report far less
        than the error phase plus its error code already tell us.
        """
        dut = cocotb.top
        rom_reads_start = int(dut.tb_cpu_rom_read_count.value)

        for _ in range(self.POST_POLL_ITERS):
            await ClockCycles(dut.clk_smc_i, self.POST_POLL_CYCLES)
            code = await self.read_post_code()
            phase = post_code_boot_phase(code)
            if not self.phase_trace or self.phase_trace[-1] != phase:
                self.phase_trace.append(phase)
                self._log(
                    f"prod_rom POST code {code:#010x} boot_phase="
                    f"{POST_CODE_BOOT_PHASE_NAMES.get(phase, hex(phase))}"
                )
            if phase == POST_CODE_BOOT_PHASE_ERROR:
                err = post_code_error(code)
                raise AssertionError(
                    "production ROM entered its ERROR boot phase: POST code "
                    f"{code:#010x} error="
                    f"{POST_CODE_ERROR_NAMES.get(err, hex(err))} "
                    f"phase_trace={[hex(p) for p in self.phase_trace]}"
                )
            if phase == target_phase:
                rom_reads = int(dut.tb_cpu_rom_read_count.value)
                assert rom_reads > rom_reads_start, (
                    "POST code advanced without any CPU ROM fetch: "
                    f"tb_cpu_rom_read_count {rom_reads_start}->{rom_reads}. "
                    "The phase cannot have come from the ROM executing."
                )
                self.reached_phase = phase
                self._log(
                    "CHK-PROD-ROM-OCCP-PROC: POST code "
                    f"{code:#010x} boot_phase="
                    f"{POST_CODE_BOOT_PHASE_NAMES.get(phase, hex(phase))} "
                    f"(scratch1 {SCRATCH_POST_CODE:#010x}, phase field "
                    f"{POST_CODE_BOOT_PHASE.hi}:{POST_CODE_BOOT_PHASE.lo}); "
                    f"tb_cpu_rom_read_count {rom_reads_start}->{rom_reads}; "
                    f"phase_trace={[hex(p) for p in self.phase_trace]}"
                )
                return code

        raise AssertionError(
            "production ROM never reported boot phase "
            f"{POST_CODE_BOOT_PHASE_NAMES.get(target_phase, hex(target_phase))} "
            f"within {self.POST_POLL_ITERS}x{self.POST_POLL_CYCLES} clk_smc_i: "
            f"last POST code {self.post_code:#010x} "
            f"phase_trace={[hex(p) for p in self.phase_trace]} "
            f"rom_reads={int(dut.tb_cpu_rom_read_count.value)} "
            f"(started {rom_reads_start}) "
            f"wb_pc0={int(dut.tb_cpu_wb_pc0.value):#x}"
        )

    async def body(self) -> None:
        await self.boot_prod_rom()
        await self.wait_for_boot_phase(POST_CODE_BOOT_PHASE_OCCP_PROC)
        # POST_CODE_ERROR must still read clean at the milestone: reaching the
        # command loop with a latched error code would not be a healthy boot.
        err = post_code_error(self.post_code)
        assert err == 0, (
            f"production ROM reached the OCCP command loop with error code "
            f"{POST_CODE_ERROR_NAMES.get(err, hex(err))} latched in POST code "
            f"{self.post_code:#010x} (field {POST_CODE_ERROR.hi}:"
            f"{POST_CODE_ERROR.lo})"
        )
