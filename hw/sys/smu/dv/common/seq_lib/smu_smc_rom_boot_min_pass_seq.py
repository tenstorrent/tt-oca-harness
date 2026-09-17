# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Does the SMC ROM interface carry an instruction stream on this wrapper?

Every toolchain-free leaf on this bench loads the zero-filled
``smc_rom_default.hex``, so ``smc_rom_intf_rsp.rdata`` never leaves 0 and the
ROM read port between smc_ip_integration's macro and the SMC CPU is only ever
observed idle. The one leaf that does boot the SMC CPU from a real image,
smu_smc_smoke_test, links its ROM with the RISC-V toolchain and is therefore
outside the toolchain-free set.

hw/sys/smc/dv/assets/min_pass.rom.hex is a checked-in eight-instruction RV64
stub linked at the ROM window (hw/sys/smu/dv/fw/common/smc_rom.ld,
ORIGIN 0xC004_0000). It builds 0xC003_9080 -- SMC CPU_CTRL scratch0 -- in t0,
0xACAF_ACA1 in t1, stores one to the other and parks. That store is what
tb_wrapper_top.sv turns into ``smc_test_pass_o``, so the image and the
testbench's pass predicate agree without a toolchain.

The claim is the whole path: reset release, ROM fetch, execution, and the CSR
write landing. It fails if the CPU never fetches (the read counter stays at 0),
if it fetches but never reaches the store (timeout), or if the scratch word
that comes back is not the image's magic.

The last step reads the same CSR back over the SMC fabric JTAG2AXI bridge.
``smc_test_pass_o`` and ``smc_scratch_0_o`` are both hierarchical probes into
one register, so on their own they cannot separate "the CPU wrote the CSR" from
"the testbench is looking at a mirror". An external master reading the
architectural address can.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    jtag2axi_single_read,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)

#: The word hw/sys/smc/dv/assets/min_pass.rom.hex stores, and the value
#: tb_wrapper_top.sv compares scratch0 against for smc_test_pass_o.
MIN_PASS_MAGIC = 0xACAF_ACA1

#: SMC CPU_CTRL scratch0, SMC-local: the address the ROM stub builds in t0.
SMC_SCRATCH0_ADDR = 0xC003_9080

BOOT_MAX_CYCLES = 600_000
HEARTBEAT_CYCLES = 50_000


class SmuSmcRomBootMinPassSeq:
    """SMC CPU boots the checked-in ROM stub and lands its PASS magic in scratch0."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.log = test.logger

    def _rd(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on the wrapper tb top")
        return self.test.read_int(pin, name, allow_xz=True)

    async def run(self) -> None:
        sb = self.test.env.scoreboard

        rom_hex = cocotb.plusargs.get("smc_rom_hex") or cocotb.plusargs.get("rom_hex")
        assert rom_hex is not None, "+smc_rom_hex / +rom_hex is required: it names the image"
        self.log.info("SMC ROM image under test: %s", rom_hex)

        first_reads = self._rd("smc_rom_read_count_o")
        rom_reads = first_reads
        for cycle in range(BOOT_MAX_CYCLES):
            await RisingEdge(self.dut.clk_smu_i)
            rom_reads = self._rd("smc_rom_read_count_o")
            if self._rd("smc_test_fail_o"):
                raise AssertionError(
                    f"SMC scratch0 took the FAIL magic at cycle={cycle} rom_reads={rom_reads}"
                )
            if self._rd("smc_test_pass_o"):
                self.log.info(
                    "SMC ROM boot reached the store at cycle=%d rom_reads=%d", cycle, rom_reads
                )
                break
            if cycle and cycle % HEARTBEAT_CYCLES == 0:
                self.log.info("SMC ROM boot heartbeat cycle=%d rom_reads=%d", cycle, rom_reads)
        else:
            raise AssertionError(
                f"SMC CPU did not reach the ROM stub's store within {BOOT_MAX_CYCLES} "
                f"clk_smu cycles: rom_reads={rom_reads} "
                f"scratch0=0x{self._rd('smc_scratch_0_o'):08x}"
            )

        # scratch0 is what smc_test_pass_o is derived from, but reading it back
        # names the value: a pass predicate wired to the wrong constant, or a
        # scratch bank that answers with something else, does not survive this.
        scratch0 = self._rd("smc_scratch_0_o")
        sb.expect_eq(
            "SMC CPU_CTRL scratch0 carries the ROM stub's magic",
            scratch0,
            MIN_PASS_MAGIC,
            evidence="CHK-SMC-ROM-BOOT-MAGIC",
        )
        # The instruction stream came out of the ROM macro, not from a residual
        # scratch image: the ROM read counter advanced over the run.
        sb.expect_true(
            f"SMC ROM read port advanced during the boot ({first_reads} -> {rom_reads})",
            rom_reads > first_reads,
            evidence="CHK-SMC-ROM-BOOT-FETCH",
        )

        # Same word, read at its architectural address by an external master.
        jtag = make_smu_jtag_tap(self.dut, self.test.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        idcode = await jtag.read_idcode()
        require_jtag_tdo_resolved("IDCODE")
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"TAP not answering: IDCODE 0x{idcode:08x}")
        status, rdata = await jtag2axi_single_read(
            jtag, SMC_SCRATCH0_ADDR, size=SMC_DBG_AXSIZE_4B, require_complete=True
        )
        require_jtag_tdo_resolved("J2A RD SMC scratch0")
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"JTAG2AXI read of scratch0 status={status} want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        self.log.info(
            "JTAG2AXI read of SMC scratch0 @0x%08x -> 0x%08x",
            SMC_SCRATCH0_ADDR,
            int(rdata) & 0xFFFF_FFFF,
        )
        sb.expect_eq(
            "SMC scratch0 read at its architectural address by an external master",
            int(rdata) & 0xFFFF_FFFF,
            MIN_PASS_MAGIC,
            evidence="CHK-SMC-ROM-BOOT-CSR-VISIBLE",
        )
