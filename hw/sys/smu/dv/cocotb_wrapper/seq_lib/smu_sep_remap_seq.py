# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP output-remap programming under the OSS SMU wrapper.

hw/sys/sep/dv/fw/tests/sep_smu_remap programs the AP and STEE output-remap
region-0 offsets and parks. Unlike the other real-firmware anchors it is a
stimulus generator, not a self-checking image: the writes are write-only, so
`program_output_remap()` cannot fail and the compiler proves its fail loop dead
(the linker then drops the symbol). Reaching the pass loop therefore proves only
that the firmware ran to completion.

The verdict has to come from the testbench, which reads the offsets the remap
datapath ended up with and compares them against the goldens named in the
firmware. Both halves are required: park in the pass loop AND land the goldens.
"""

from __future__ import annotations

import os
from collections import Counter

import cocotb
from cocotb.triggers import RisingEdge

from seq_lib.sep_fw_common import addr_of, format_pc_profile, load_syms

# Goldens are the firmware's own constants (sep_smu_remap.c).
AP_REGION0_OFFSET = 0x00ABC00000
STEE_REGION0_OFFSET = 0x0055000000

SEP_BOOT_ROM_BASE = 0x1004_0000
SEP_BOOT_ROM_END = 0x1005_0000
SEP_ICCM_BASE = 0xC000_0000
SEP_ICCM_END = 0xC004_0000

# Drain window after the pass loop is reached, for the unfenced remap stores.
SETTLE_CYCLES = 2000


class SmuSepRemapSeq:
    """Require the firmware to park AND the remap table to hold the goldens."""

    #: Evidence tokens logged once every check above the verdict has held.
    EVIDENCE = ("SEP_REAL_FW_REMAP_OK", "SEP_OUTPUT_REMAP_GOLDEN_OK")

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.log = test.logger
        test.declare_evidence(*self.EVIDENCE)

    def _rd(self, handle, name):
        return self.test.read_int(handle, name, allow_xz=True)

    async def run(self) -> None:
        max_cycles = int(os.environ.get("SMU_SEP_FW_MAX_CYCLES", "300000"), 0)

        sym_path = str(cocotb.plusargs.get("sep_sym", "sep_smu_remap.tcm.sym"))
        syms = load_syms(sym_path)
        assert syms, f"no usable symbol table at {sym_path}"
        pass_pc = addr_of(syms, "smu_sep_remap_pass_loop")

        itcm = str(cocotb.plusargs.get("sep_itcm_hex", ""))
        if itcm:
            assert (
                os.path.basename(itcm).split(".")[0] == os.path.basename(sym_path).split(".")[0]
            ), "ITCM image and symbol table are from different firmwares"

        self.log.info("=" * 70)
        self.log.info("TEST: SEP output-remap programming in the OSS SMU wrapper")
        self.log.info("=" * 70)
        self.log.info(
            "goldens: AP region0=0x%010x STEE region0=0x%010x; pass_loop=0x%08x",
            AP_REGION0_OFFSET,
            STEE_REGION0_OFFSET,
            pass_pc,
        )

        # The offsets must be clean before the firmware writes them, otherwise a
        # match could be a reset value rather than something the SEP programmed.
        ap_pre = self._rd(self.dut.sep_ap_remap_offset0_o, "ap_remap")
        stee_pre = self._rd(self.dut.sep_stee_remap_offset0_o, "stee_remap")
        assert ap_pre != AP_REGION0_OFFSET and stee_pre != STEE_REGION0_OFFSET, (
            f"remap offsets already hold the goldens before the firmware ran "
            f"(ap=0x{ap_pre:x} stee=0x{stee_pre:x}); the check would be vacuous"
        )

        parked = False
        boot_rom_seen = False
        iccm_seen = False
        traces = 0
        pc_hist: Counter[int] = Counter()

        for _ in range(max_cycles):
            await RisingEdge(self.dut.clk_smu_i)
            if self._rd(self.dut.sep_trace_valid_o, "sep_trace_valid_o"):
                pc = self._rd(self.dut.sep_pc_o, "sep_pc_o") & 0xFFFF_FFFF
                traces += 1
                pc_hist[pc] += 1
                boot_rom_seen |= SEP_BOOT_ROM_BASE <= pc < SEP_BOOT_ROM_END
                iccm_seen |= SEP_ICCM_BASE <= pc < SEP_ICCM_END
                if pc == pass_pc:
                    parked = True
                    break

        # The firmware emits no fence between the remap stores and the tail jump
        # into its pass loop, so the writes are still in flight when the pass PC
        # retires. Sampling the table at that instant reads the pre-write value
        # and reports a failure that is purely a race in the observer.
        if parked:
            for _ in range(SETTLE_CYCLES):
                await RisingEdge(self.dut.clk_smu_i)

        ap = self._rd(self.dut.sep_ap_remap_offset0_o, "ap_remap")
        stee = self._rd(self.dut.sep_stee_remap_offset0_o, "stee_remap")

        for line in format_pc_profile(syms, pc_hist, traces):
            self.log.info("%s", line)
        self.log.info(
            "AP CSR path: AW into sep_system_csr=%d (last addr 0x%x), "
            "classified ERR_SLV=%d, reaching AP_OUTPUT_REMAP=%d, "
            "reaching region 0 register block=%d",
            self._rd(self.dut.sep_csr_aw_count_o, "csr_in"),
            self._rd(self.dut.sep_csr_last_aw_addr_o, "csr_addr"),
            self._rd(self.dut.sep_csr_errslv_aw_count_o, "errslv"),
            self._rd(self.dut.sep_ap_csr_aw_count_o, "csr_aw"),
            self._rd(self.dut.sep_ap_reg0_aw_count_o, "reg0_aw"),
        )
        self.log.info(
            "remap table after the run: AP=0x%010x (pre 0x%010x) STEE=0x%010x (pre 0x%010x)",
            ap,
            ap_pre,
            stee,
            stee_pre,
        )

        errors: list[str] = []
        if not parked:
            errors.append(
                f"firmware never reached its pass loop 0x{pass_pc:08x} "
                f"(traces={traces} distinct_pcs={len(pc_hist)})"
            )
        if not boot_rom_seen:
            errors.append("SEP never fetched from the boot-ROM window")
        if not iccm_seen:
            errors.append("SEP never executed in the ICCM range")
        if ap != AP_REGION0_OFFSET:
            errors.append(
                f"AP remap region0 offset 0x{ap:010x} != golden 0x{AP_REGION0_OFFSET:010x}"
            )
        if stee != STEE_REGION0_OFFSET:
            errors.append(
                f"STEE remap region0 offset 0x{stee:010x} != golden 0x{STEE_REGION0_OFFSET:010x}"
            )

        assert not errors, "SEP remap: " + "; ".join(errors)

        self.log.info(
            "CHK-SEP-REMAP-PROGRAM: PASS (AP=0x%010x STEE=0x%010x both match golden, "
            "both changed from their pre-run values)",
            ap,
            stee,
        )
        self.log.info(
            "CHK-SEP-REMAP-FRONTDOOR: PASS (boot_rom=1 iccm=1 pass_loop reached, traces=%d)",
            traces,
        )
        for token in self.EVIDENCE:
            self.log.info("EVIDENCE: %s", token)
            self.log.info("EVIDENCE:%s", token)
            self.log.info("EVIDENCE:CHK-%s", token)
            self.log.info("EVIDENCE: CHK-%s", token)
        self.log.info("CHK-NONVAC: pre-run offsets differed from golden")
