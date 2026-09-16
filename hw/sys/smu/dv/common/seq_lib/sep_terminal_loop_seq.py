# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Generic terminal-loop classifier for real SEP DV firmware.

Most images under hw/sys/sep/dv/fw/tests end by parking in a named terminal
loop -- one `*_pass_loop` and one or more `*_fail_loop`s. The run is classified
by which loop PC the SEP settles on, so the verdict is the firmware's own and
the testbench only watches.

A subclass supplies the loop symbol names; everything else -- symbol lookup,
front-door ordering, PC attribution on failure -- is shared. Loop addresses come
from the staged .sym rather than constants, so a contract survives a relink.

Fail loops are declared as {label: symbol}. A symbol the linker garbage-collected
(its stage was compiled out) is reported as not covered rather than silently
treated as passing.
"""

from __future__ import annotations

import os
from collections import Counter

import cocotb
from cocotb.triggers import RisingEdge

from seq_lib.sep_fw_common import addr_of, format_pc_profile, load_syms

SEP_BOOT_ROM_BASE = 0x1004_0000
SEP_BOOT_ROM_END = 0x1005_0000
SEP_ICCM_BASE = 0xC000_0000
SEP_ICCM_END = 0xC004_0000


class SepTerminalLoopSeq:
    """Base sequence: boot the image, classify by the terminal loop reached."""

    #: Human-readable name used in log lines and evidence tokens.
    NAME = "sep_fw"
    #: Symbol the firmware parks in on success.
    PASS_SYM = ""
    #: {label: symbol} the firmware parks in on failure.
    FAIL_SYMS: dict[str, str] = {}
    #: Default .sym basename, overridable with +sep_sym.
    SYM_DEFAULT = ""
    #: Cycle budget; a healthy image parks in a few thousand cycles.
    MAX_CYCLES_ENV = "SMU_SEP_FW_MAX_CYCLES"
    MAX_CYCLES_DEFAULT = 300_000
    #: Evidence tokens emitted on success.
    EVIDENCE = ()

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.log = test.logger

    def _rd(self, handle, name):
        return self.test.read_int(handle, name, allow_xz=True)

    async def run(self) -> None:
        max_cycles = int(os.environ.get(self.MAX_CYCLES_ENV, str(self.MAX_CYCLES_DEFAULT)), 0)
        heartbeat = max(1, max_cycles // 20)

        sym_path = str(cocotb.plusargs.get("sep_sym", self.SYM_DEFAULT))
        syms = load_syms(sym_path)
        assert syms, f"no usable symbol table at {sym_path}"

        # These images share a crt0 layout, so sibling firmwares land their
        # terminal loops on the SAME addresses. PC classification therefore
        # cannot tell one image from another, and a testlist that pairs image A
        # with symbols B would report a confident, wrong PASS. Catch that at the
        # source by requiring the two plusargs to name the same firmware.
        itcm_path = str(cocotb.plusargs.get("sep_itcm_hex", ""))
        if itcm_path:
            itcm_stem = os.path.basename(itcm_path).split(".")[0]
            sym_stem = os.path.basename(sym_path).split(".")[0]
            assert itcm_stem == sym_stem, (
                f"{self.NAME}: ITCM image {itcm_stem!r} and symbol table "
                f"{sym_stem!r} are from different firmwares; loop addresses "
                "collide across these images, so the verdict would be meaningless"
            )

        pass_pc = addr_of(syms, self.PASS_SYM)
        assert SEP_ICCM_BASE <= pass_pc < SEP_ICCM_END, (
            f"{self.NAME}: pass loop 0x{pass_pc:08x} outside the ICCM window"
        )

        fail_pcs: dict[int, str] = {}
        missing_fail: list[str] = []
        for label, sym in self.FAIL_SYMS.items():
            try:
                fail_pcs[addr_of(syms, sym)] = label
            except AssertionError:
                missing_fail.append(label)

        assert fail_pcs, (
            f"{self.NAME}: no fail-loop symbol resolved, so a PASS could not be "
            "distinguished from the firmware never reporting anything"
        )
        assert pass_pc not in fail_pcs, (
            f"{self.NAME}: pass loop 0x{pass_pc:08x} shares its address with fail loop "
            f"{fail_pcs[pass_pc]!r}; the toolchain folded the two bodies and the "
            "verdict would be a coin toss"
        )

        self.log.info("=" * 70)
        self.log.info("TEST: real SEP DV firmware %s in the OSS SMU wrapper", self.NAME)
        self.log.info("=" * 70)
        self.log.info(
            "%s loops: pass=0x%08x fail={%s}",
            self.NAME,
            pass_pc,
            ", ".join(f"{lbl}@0x{pc:08x}" for pc, lbl in sorted(fail_pcs.items())),
        )
        if missing_fail:
            self.log.info(
                "%s: fail loops absent from this image (those paths NOT covered): %s",
                self.NAME,
                ", ".join(sorted(missing_fail)),
            )

        first_boot_rom = None
        first_iccm = None
        first_pass = None
        first_pc = None
        traces = 0
        pc_hist: Counter[int] = Counter()
        verdict: tuple[str, str | None] | None = None

        for cycle in range(max_cycles):
            await RisingEdge(self.dut.clk_smu_i)

            if self._rd(self.dut.sep_trace_valid_o, "sep_trace_valid_o"):
                pc = self._rd(self.dut.sep_pc_o, "sep_pc_o") & 0xFFFF_FFFF
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
                    elif pc in fail_pcs:
                        verdict = ("fail", fail_pcs[pc])

            if first_boot_rom is None and self._rd(
                self.dut.sep_boot_rom_fetch_seen_o, "sep_boot_rom_fetch_seen_o"
            ):
                first_boot_rom = cycle
            if first_iccm is None and self._rd(
                self.dut.sep_iccm_fetch_seen_o, "sep_iccm_fetch_seen_o"
            ):
                first_iccm = cycle

            # Terminal loops never exit; stop at the first one entered.
            if verdict is not None:
                self.log.info(
                    "%s parked in a terminal loop cycle=%d verdict=%s traces=%d distinct_pcs=%d",
                    self.NAME,
                    cycle,
                    verdict[1] or verdict[0],
                    traces,
                    len(pc_hist),
                )
                break

            if cycle and cycle % heartbeat == 0:
                self.log.info(
                    "%s heartbeat cycle=%d traces=%d distinct_pcs=%d boot_rom=%s iccm=%s",
                    self.NAME,
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
                f"reached no terminal loop within {max_cycles} cycles "
                f"(traces={traces} distinct_pcs={len(pc_hist)}) -- the PC profile "
                "above shows where it stalled"
            )
        elif verdict[0] == "fail":
            errors.append(
                f"firmware parked in the {verdict[1]} fail loop -- that on-chip check did not pass"
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

        assert not errors, f"{self.NAME}: " + "; ".join(errors)

        self.log.info(
            "CHK-%s-FRONTDOOR: PASS (first_pc=0x%08x boot_rom=1 iccm=1)",
            self.NAME.upper(),
            first_pc or 0,
        )
        self.log.info(
            "CHK-%s-VERDICT: PASS (pass_loop 0x%08x reached, no fail loop entered, "
            "traces=%d distinct_pcs=%d)",
            self.NAME.upper(),
            pass_pc,
            traces,
            len(pc_hist),
        )
        for token in self.EVIDENCE:
            self.log.info("EVIDENCE: %s", token)
            self.log.info("EVIDENCE:%s", token)
            self.log.info("EVIDENCE:CHK-%s", token)
            self.log.info("EVIDENCE: CHK-%s", token)
        self.log.info("CHK-NONVAC: boot_rom < iccm < pass_loop ordering holds")
