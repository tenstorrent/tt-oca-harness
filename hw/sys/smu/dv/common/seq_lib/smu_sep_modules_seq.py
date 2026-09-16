# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Real SEP DV module-matrix firmware under the OSS SMU wrapper.

Boots hw/sys/sep/dv/fw/tests/sep_smu_modules. The image walks the SEP module
touch-points its stage mask enables -- AES, HMAC and KMAC in this build -- and
parks in a per-stage terminal loop, so the verdict names the module that failed
rather than just reporting "firmware did not pass".

The stage mask is compile-time, and the linker garbage-collects the loops for
disabled stages. The test therefore derives the watch set from the symbol table
instead of hard-coding it: a stage that is not built has no loop symbol, and a
stage that is built must have one.
"""

from __future__ import annotations

import os
from collections import Counter

import cocotb
from cocotb.triggers import RisingEdge

from seq_lib.esrc_noise import SmuEsrcNoiseDriver
from seq_lib.sep_fw_common import addr_of, format_pc_profile, load_syms

SEP_BOOT_ROM_BASE = 0x1004_0000
SEP_BOOT_ROM_END = 0x1005_0000
SEP_ICCM_BASE = 0xC000_0000
SEP_ICCM_END = 0xC004_0000

PASS_SYM = "smu_sep_modules_pass_loop"

# Every module the firmware can build a fail loop for. Present in the symbol
# table => that stage is enabled in this image and is watched; absent => the
# stage was compiled out and is reported as not covered.
FAIL_SYMS = {
    "dma": "smu_sep_modules_fail_dma_loop",
    "wdt": "smu_sep_modules_fail_wdt_loop",
    "aes": "smu_sep_modules_fail_aes_loop",
    # Prerequisite, not a module: the AES stage brings the entropy stack up
    # first, and a bring-up that never completed parks here instead of in the
    # AES loop so the two causes stay distinguishable.
    "entropy": "smu_sep_modules_fail_entropy_loop",
    "hmac": "smu_sep_modules_fail_hmac_loop",
    "kmac": "smu_sep_modules_fail_kmac_loop",
    "efuse": "smu_sep_modules_fail_efuse_loop",
}


class SmuSepModulesSeq:
    """Classify the run by which terminal loop the SEP parks in."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.log = test.logger

    async def run(self) -> None:
        # The HMAC and KMAC stages finish in a few thousand cycles, but the AES
        # stage first waits out the ESRC boot health-test window (2048 samples at
        # div64, ~131k core cycles) before its masking PRNG can reseed, so the
        # budget has to clear that with margin. A stage that polls forever is
        # caught here by the PC profile rather than waited out: the AES stage's
        # own timeout is 1e6 poll iterations, roughly 22M cycles, and ends in a
        # failure either way.
        max_cycles = int(os.environ.get("SMU_SEP_MODULES_MAX_CYCLES", "600000"), 0)
        heartbeat = max(1, max_cycles // 20)

        # AES masking reseeds from crypto-EDN, so this image runs the entropy
        # bring-up before its AES stage. The ring oscillators do not self-oscillate
        # under Verilator, so the raw noise has to come from the testbench -- the
        # same exception hw/sys/sep/dv takes, and the only forced signal involved.
        assert cocotb.plusargs.get("esrc_noise_force") is not None, (
            "+esrc_noise_force is required: the AES stage's entropy bring-up "
            "would stall at the ESRC boot gate without driven noise, and the "
            "failure would look like an AES defect"
        )
        SmuEsrcNoiseDriver(self.dut).start()

        sym_path = str(cocotb.plusargs.get("sep_sym", "sep_smu_modules.tcm.sym"))
        syms = load_syms(sym_path)
        assert syms, f"no usable symbol table at {sym_path}"

        pass_pc = addr_of(syms, PASS_SYM)
        built = {}
        skipped = []
        for module, sym in FAIL_SYMS.items():
            try:
                built[module] = addr_of(syms, sym)
            except AssertionError:
                skipped.append(module)

        assert built, (
            "no per-stage fail loops in the image -- every module stage is "
            "compiled out, so a PASS would prove nothing"
        )

        self.log.info("=" * 70)
        self.log.info("TEST: real SEP DV module matrix in the OSS SMU wrapper")
        self.log.info("=" * 70)
        self.log.info(
            "stages built into this image: %s (pass_loop=0x%08x)",
            ", ".join(f"{m}@0x{a:08x}" for m, a in sorted(built.items())),
            pass_pc,
        )
        if skipped:
            self.log.info(
                "stages compiled out of this image (NOT covered by this run): %s",
                ", ".join(sorted(skipped)),
            )

        fail_pc_to_module = {pc: m for m, pc in built.items()}

        first_boot_rom = None
        first_iccm = None
        first_pass = None
        first_pc = None
        traces = 0
        pc_hist: Counter[int] = Counter()
        verdict = None

        for cycle in range(max_cycles):
            await RisingEdge(self.dut.clk_smu_i)

            if self.test.read_int(self.dut.sep_trace_valid_o, "sep_trace_valid_o", allow_xz=True):
                pc = self.test.read_int(self.dut.sep_pc_o, "sep_pc_o", allow_xz=True) & 0xFFFF_FFFF
                traces += 1
                pc_hist[pc] += 1
                if first_pc is None:
                    first_pc = pc
                if first_boot_rom is None and SEP_BOOT_ROM_BASE <= pc < SEP_BOOT_ROM_END:
                    first_boot_rom = cycle
                if first_iccm is None and SEP_ICCM_BASE <= pc < SEP_ICCM_END:
                    first_iccm = cycle
                if first_pass is None and pc == pass_pc:
                    first_pass = cycle
                if verdict is None:
                    if pc == pass_pc:
                        verdict = ("pass", None)
                    elif pc in fail_pc_to_module:
                        verdict = ("fail", fail_pc_to_module[pc])

            if first_boot_rom is None and self.test.read_int(
                self.dut.sep_boot_rom_fetch_seen_o,
                "sep_boot_rom_fetch_seen_o",
                allow_xz=True,
            ):
                first_boot_rom = cycle
            if first_iccm is None and self.test.read_int(
                self.dut.sep_iccm_fetch_seen_o,
                "sep_iccm_fetch_seen_o",
                allow_xz=True,
            ):
                first_iccm = cycle

            # Terminal loops never exit, so stop at the first one reached.
            if verdict is not None:
                self.log.info(
                    "SEP parked in a terminal loop cycle=%d verdict=%s traces=%d distinct_pcs=%d",
                    cycle,
                    verdict,
                    traces,
                    len(pc_hist),
                )
                break

            if cycle and cycle % heartbeat == 0:
                self.log.info(
                    "modules heartbeat cycle=%d traces=%d distinct_pcs=%d boot_rom=%s iccm=%s",
                    cycle,
                    traces,
                    len(pc_hist),
                    first_boot_rom is not None,
                    first_iccm is not None,
                )

        for line in format_pc_profile(syms, pc_hist, traces):
            self.log.info("%s", line)

        errors: list[str] = []
        if verdict is None:
            errors.append(
                f"SEP reached no terminal loop within {max_cycles} cycles "
                f"(traces={traces} distinct_pcs={len(pc_hist)}) -- see the PC "
                "profile above for where it stalled"
            )
        elif verdict[0] == "fail":
            errors.append(
                f"firmware parked in the {verdict[1].upper()} fail loop -- that "
                "module's on-chip check did not pass"
            )
        if first_boot_rom is None:
            errors.append("SEP never fetched from the boot-ROM window")
        if first_iccm is None:
            errors.append("SEP never executed in the ICCM range")
        if first_pc is not None and not (SEP_BOOT_ROM_BASE <= first_pc < SEP_BOOT_ROM_END):
            errors.append(f"first retired PC 0x{first_pc:08x} is not the boot-ROM reset vector")
        if first_pass is not None:
            if first_boot_rom is None or first_iccm is None:
                errors.append(
                    f"boot_rom < iccm < pass_loop first-seen incomplete "
                    f"(first_boot_rom={first_boot_rom} first_iccm={first_iccm} "
                    f"first_pass={first_pass})"
                )
            elif not (first_boot_rom < first_iccm < first_pass):
                errors.append(
                    f"boot_rom < iccm < pass_loop order does not hold "
                    f"(first_boot_rom={first_boot_rom} first_iccm={first_iccm} "
                    f"first_pass={first_pass})"
                )
        elif verdict is not None and verdict[0] == "pass":
            errors.append("pass loop reached without a first-seen cycle")

        assert not errors, "SEP modules: " + "; ".join(errors)

        self.log.info(
            "CHK-SEP-MODULES-FRONTDOOR: PASS (first_pc=0x%08x boot_rom=1 iccm=1)",
            first_pc or 0,
        )
        self.log.info(
            "CHK-SEP-MODULES-MATRIX: PASS (%s all cleared on-chip; pass_loop "
            "0x%08x reached, no fail loop entered, traces=%d)",
            "/".join(sorted(built)),
            pass_pc,
            traces,
        )
        for token in ("SEP_REAL_FW_MODULES_OK", "SEP_MODULE_MATRIX_OK"):
            self.log.info("EVIDENCE: %s", token)
            self.log.info("EVIDENCE:%s", token)
            self.log.info("EVIDENCE:CHK-%s", token)
            self.log.info("EVIDENCE: CHK-%s", token)
        self.log.info("CHK-NONVAC: boot_rom < iccm < pass_loop ordering holds")
