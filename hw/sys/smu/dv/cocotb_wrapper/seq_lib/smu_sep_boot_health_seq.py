# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Real SEP DV boot-health firmware under the OSS SMU wrapper.

Runs hw/sys/sep/dv/fw/tests/sep_smu_boot_health instead of this DV root's
minimal freestanding smoke. The firmware itself carries the verdict: it parks
in one of two named terminal loops, so the test classifies the run by which
loop PC the SEP settles on rather than by any TB-side inference.

Symbol addresses come from the staged .sym, so the contract survives a firmware
relink. SEP-local cold scratch7 (0x10802038) marker observation is out of scope
here.
"""

from __future__ import annotations

import os

import cocotb
from cocotb.triggers import RisingEdge

from seq_lib.sep_fw_common import addr_of, load_syms

SEP_BOOT_ROM_BASE = 0x1004_0000
SEP_BOOT_ROM_END = 0x1005_0000
SEP_ICCM_BASE = 0xC000_0000
SEP_ICCM_END = 0xC004_0000

PASS_SYM = "sep_smu_boot_health_pass_loop"
FAIL_SYM = "sep_smu_boot_health_fail_loop"
START_SYM = "_start"


class SmuSepBootHealthSeq:
    """Prove the real SEP DV firmware boots and reaches its pass loop."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.log = test.logger

    async def run(self) -> None:
        max_cycles = int(os.environ.get("SMU_SEP_BOOT_MAX_CYCLES", "300000"), 0)
        heartbeat = max(1, max_cycles // 20)

        sym_path = str(cocotb.plusargs.get("sep_sym", "sep_smu_boot_health.tcm.sym"))
        syms = load_syms(sym_path)
        assert syms, f"no usable symbol table at {sym_path}"
        pass_pc = addr_of(syms, PASS_SYM)
        fail_pc = addr_of(syms, FAIL_SYM)
        start_pc = addr_of(syms, START_SYM)

        self.log.info("=" * 70)
        self.log.info("TEST: real SEP DV boot-health firmware in the OSS SMU wrapper")
        self.log.info("=" * 70)
        self.log.info(
            "SEP loop symbols: _start=0x%08x pass=0x%08x fail=0x%08x",
            start_pc,
            pass_pc,
            fail_pc,
        )

        # The firmware entry must be the address the boot-ROM trampoline jumps to,
        # otherwise a PASS would only prove the trampoline ran.
        assert start_pc == SEP_ICCM_BASE, (
            f"boot_health _start 0x{start_pc:08x} != ICCM base 0x{SEP_ICCM_BASE:08x}; "
            "the boot-ROM trampoline would not reach it"
        )
        assert SEP_ICCM_BASE <= pass_pc < SEP_ICCM_END, (
            f"pass loop 0x{pass_pc:08x} outside the ICCM window"
        )

        first_boot_rom = None
        first_iccm = None
        first_pass = None
        pass_seen = False
        fail_seen = False
        first_pc = None
        traces = 0
        pcs: set[int] = set()

        for cycle in range(max_cycles):
            await RisingEdge(self.dut.clk_smu_i)
            valid = self.test.read_int(
                self.dut.sep_trace_valid_o, "sep_trace_valid_o", allow_xz=True
            )
            if valid:
                pc = self.test.read_int(self.dut.sep_pc_o, "sep_pc_o", allow_xz=True)
                pc &= 0xFFFF_FFFF
                traces += 1
                pcs.add(pc)
                if first_pc is None:
                    first_pc = pc
                if first_boot_rom is None and SEP_BOOT_ROM_BASE <= pc < SEP_BOOT_ROM_END:
                    first_boot_rom = cycle
                if first_iccm is None and SEP_ICCM_BASE <= pc < SEP_ICCM_END:
                    first_iccm = cycle
                if first_pass is None and pc == pass_pc:
                    first_pass = cycle
                pass_seen |= pc == pass_pc
                fail_seen |= pc == fail_pc

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

            # The fail loop is terminal: stop as soon as it is entered so the
            # failure reports the firmware's own verdict, not a timeout.
            if fail_seen:
                break
            if pass_seen and first_boot_rom is not None and first_iccm is not None:
                self.log.info(
                    "SEP boot-health reached the pass loop cycle=%d first_pc=0x%08x "
                    "traces=%d distinct_pcs=%d",
                    cycle,
                    first_pc or 0,
                    traces,
                    len(pcs),
                )
                break

            if cycle and cycle % heartbeat == 0:
                self.log.info(
                    "boot-health heartbeat cycle=%d traces=%d distinct_pcs=%d "
                    "boot_rom=%s iccm=%s pass=%s fail=%s",
                    cycle,
                    traces,
                    len(pcs),
                    first_boot_rom is not None,
                    first_iccm is not None,
                    pass_seen,
                    fail_seen,
                )

        errors: list[str] = []
        if fail_seen:
            errors.append(
                f"firmware parked in its FAIL loop (0x{fail_pc:08x}) -- cold "
                "scratch7 read-back mismatched inside the SEP"
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
        elif pass_seen:
            errors.append("pass loop reached without a first-seen cycle")
        if not pass_seen:
            observed = ", ".join(f"0x{p:08x}" for p in sorted(pcs))
            errors.append(
                f"firmware never reached its pass loop 0x{pass_pc:08x} "
                f"(traces={traces} distinct_pcs={len(pcs)} pcs=[{observed}])"
            )

        assert not errors, "SEP boot-health: " + "; ".join(errors)

        self.log.info(
            "CHK-SEP-BOOT-HEALTH-FRONTDOOR: PASS (first_pc=0x%08x boot_rom=1 iccm=1 entry=0x%08x)",
            first_pc or 0,
            start_pc,
        )
        self.log.info(
            "CHK-SEP-BOOT-HEALTH-VERDICT: PASS (pass_loop=0x%08x reached, "
            "fail_loop=0x%08x never entered, traces=%d distinct_pcs=%d)",
            pass_pc,
            fail_pc,
            traces,
            len(pcs),
        )
        for token in ("SEP_REAL_FW_BOOT_OK", "SEP_REAL_FW_PASS_LOOP_OK"):
            self.log.info("EVIDENCE: %s", token)
            self.log.info("EVIDENCE:%s", token)
            self.log.info("EVIDENCE:CHK-%s", token)
            self.log.info("EVIDENCE: CHK-%s", token)
        self.log.info("CHK-NONVAC: boot_rom < iccm < pass_loop ordering holds")
