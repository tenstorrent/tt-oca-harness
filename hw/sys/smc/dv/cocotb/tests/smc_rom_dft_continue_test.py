# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The target ROM must keep booting past a bypassed or ignored memory-health result.

hardware-initialization.adoc, "MBIST and memory repair": a bypass strap skips its check and
records its bypass code; with eFuse SMC_CONFIG.dft_ignore_error set, a memory-repair or MBIST
failure records its failure code and boot continues. +dft_continue_case selects one row:

    case               DFT lines         straps                ignore  scratch 15
    mem_repair_bypass  mem_repair_fail   MEM_REPAIR_BYPASS     0       0x12340001
    mbist_bypass       mbist_timeout     MEM_BIST_BYPASS       0       0x12340002
    both_bypasses      mbist_timeout     both                  0       0x12340001
    mem_repair_ignore  mem_repair_fail   none                  1       0xBADC0FFE
    mbist_ignore       mbist_fail        none                  1       0xDEADBEEF

Both bypass straps leave 0x12340001 because the repair check runs second and replaces the
MBIST-bypass code. The MBIST bypass rows report an abort, so only the strap can explain the
continued boot. An abort with dft_ignore_error set is not graded: the specification has not
settled it.

Continuation is proven by the controller's OCCP exchange (occp_sanity writes TEST_PASS into
target scratch 0, which only a serviced WriteData can do), the target POST at OCCP_PROC, and
hart 0 retiring outside both DFT halt loops and the park loop.

Plusargs:
    +rom_bin64=<image>            target production ROM               (required)
    +bfm_rom_hex=<image>          occp_sanity controller image        (required)
    +dft_continue_case=<name>     row of the table above              (required)
    +fuse_dft_ignore_error=0|1    must match the row                  (required)
    +MEM_REPAIR_BYPASS, +MEM_BIST_BYPASS  must match the row
"""

from __future__ import annotations

from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles
from env.smc_cpu_trace_monitor import symbol_file_for_image
from env.smc_dft_status_driver import (
    DFX_CTRL_STATUS_SMU,
    MBIST_STATUS_MBIST_FAIL,
    MBIST_STATUS_MEM_BIST_BYPASSED,
    MBIST_STATUS_MEM_REPAIR_BYPASSED,
    MBIST_STATUS_MEM_REPAIR_FAIL,
    SmcDftStatusDriver,
)
from smc_dual_base_test import DualCsr, SmcDualHarness, dual_test
from smc_occp_dual_defs import (
    POST_CODE_BOOT_PHASE_OCCP_PROC,
    SCRATCH_MBIST_STATUS,
    STRAP_BITS,
    TEST_PASS,
    describe_post_code,
    post_code_boot_phase,
    post_code_error,
    required_plusarg,
    strap_reg_addr,
)
from smc_occp_rom_only_test import run_occp_rom_only
from smc_reg import SMC_EFUSE_WRAP_SMC_EFUSE_MAP_SMC_CONFIG_REG_ADDR
from smc_rom_park_defs import park_loop_pcs

CASE = "smc_rom_dft_continue_test"

SCENARIOS = {
    "mem_repair_bypass": {
        "dft": "mem_repair_fail",
        "scratch15": MBIST_STATUS_MEM_REPAIR_BYPASSED,
        "MEM_REPAIR_BYPASS": 1,
        "MEM_BIST_BYPASS": 0,
        "ignore": 0,
    },
    "mbist_bypass": {
        "dft": "mbist_timeout",
        "scratch15": MBIST_STATUS_MEM_BIST_BYPASSED,
        "MEM_REPAIR_BYPASS": 0,
        "MEM_BIST_BYPASS": 1,
        "ignore": 0,
    },
    "both_bypasses": {
        "dft": "mbist_timeout",
        "scratch15": MBIST_STATUS_MEM_REPAIR_BYPASSED,
        "MEM_REPAIR_BYPASS": 1,
        "MEM_BIST_BYPASS": 1,
        "ignore": 0,
    },
    "mem_repair_ignore": {
        "dft": "mem_repair_fail",
        "scratch15": MBIST_STATUS_MEM_REPAIR_FAIL,
        "MEM_REPAIR_BYPASS": 0,
        "MEM_BIST_BYPASS": 0,
        "ignore": 1,
    },
    "mbist_ignore": {
        "dft": "mbist_fail",
        "scratch15": MBIST_STATUS_MBIST_FAIL,
        "MEM_REPAIR_BYPASS": 0,
        "MEM_BIST_BYPASS": 0,
        "ignore": 1,
    },
}

SMC_CONFIG_DFT_IGNORE_ERROR = 1 << 15

# The early checks' terminal loops, from boot/mbist_check_override.S and
# boot/memory_repair_check_override.S.
DFT_HALT_SYMBOLS = ("mbist_halt_loop", "memory_repair_halt_loop")

SENSE_WAIT_CYCLES = 200_000
LOCALITY_WINDOW_CYCLES = 4000
LOCALITY_SAMPLE_CYCLES = 20
REQUIRED_EVIDENCE = ("CHK-OCCP-SANITY", "CHK-ROM-DFT-STIMULUS", "CHK-ROM-DFT-CONTINUE")


def _case_evidence(case: str) -> str:
    return "CHK-ROM-DFT-" + case.upper().replace("_", "-")


def _rom_symbol_ranges(names: tuple[str, ...]) -> dict[str, tuple[int, int]]:
    """[start, next symbol) of each named label in the staged production ROM symbols."""
    rom = cocotb.plusargs.get("rom_bin64")
    sym = symbol_file_for_image("rom_bin64", str(rom)) if rom is not None else None
    if sym is None or not Path(sym).exists():
        raise AssertionError(f"no symbol file for +rom_bin64={rom!r}; cannot locate {names}")
    # `nm -B -n` lines, sorted by address: "<addr> <type> <name>".
    addrs = sorted(
        {
            (int(parts[0], 16), parts[2])
            for parts in (line.split() for line in Path(sym).read_text().splitlines())
            if len(parts) >= 3
        }
    )
    ranges: dict[str, tuple[int, int]] = {}
    for idx, (addr, name) in enumerate(addrs):
        if name in names:
            following = [a for a, _ in addrs[idx + 1 :] if a > addr]
            if not following:
                raise AssertionError(f"{sym}: {name} is the last symbol; its extent is unknown")
            ranges[name] = (addr, following[0])
    missing = [name for name in names if name not in ranges]
    if missing:
        raise AssertionError(f"{sym} has no {', '.join(missing)}")
    return ranges


def _check_plusargs(case: str, row: dict) -> None:
    named = int(required_plusarg("fuse_dft_ignore_error", CASE), 0)
    if named != row["ignore"]:
        raise AssertionError(
            f"{case} needs +fuse_dft_ignore_error={row['ignore']}, the entry passes {named}"
        )
    for strap in ("MEM_REPAIR_BYPASS", "MEM_BIST_BYPASS"):
        given = int(cocotb.plusargs.get(strap) is not None)
        if given != row[strap]:
            raise AssertionError(
                f"{case} needs +{strap} {'set' if row[strap] else 'absent'}; the entry "
                f"{'passes' if given else 'omits'} it"
            )


async def _await_sense_done(dut) -> None:
    for _ in range(SENSE_WAIT_CYCLES):
        if int(dut.dut_fuse_sense_done_o.value):
            return
        await ClockCycles(dut.clk_smc_i, 1)
    raise AssertionError(f"target fuse_sense_done never rose within {SENSE_WAIT_CYCLES} clk_smc_i")


async def _require_running_outside(dut, harness, excluded: dict[str, tuple[int, int]]) -> int:
    """Sample hart 0's retired PC and fail if it sits in any excluded range."""
    seen: set[int] = set()
    for _ in range(LOCALITY_WINDOW_CYCLES // LOCALITY_SAMPLE_CYCLES):
        await ClockCycles(dut.clk_smc_i, LOCALITY_SAMPLE_CYCLES)
        pc = int(dut.dut_wb_pc0.value)
        seen.add(pc)
        for name, (start, end) in excluded.items():
            if start <= pc < end:
                raise AssertionError(
                    f"target hart 0 retired {pc:#x} inside {name} [{start:#x}, {end:#x}); the "
                    f"ROM stopped instead of continuing.\nCPU state:\n{harness.cpu_trace_report()}"
                )
    return len(seen)


@dual_test(REQUIRED_EVIDENCE)
async def smc_rom_dft_continue_test(harness: SmcDualHarness) -> None:
    dut = harness.dut
    case = required_plusarg("dft_continue_case", CASE)
    if case not in SCENARIOS:
        raise AssertionError(
            f"+dft_continue_case={case!r} is not one of {', '.join(sorted(SCENARIOS))}"
        )
    row = SCENARIOS[case]
    _check_plusargs(case, row)
    harness.required_evidence += (_case_evidence(case),)
    excluded = _rom_symbol_ranges(DFT_HALT_SYMBOLS)
    park = sorted(park_loop_pcs())
    excluded["smc_park_hart0_wfi"] = (park[0], park[-1] + 1)

    async def report_and_attribute(dut_csr: DualCsr, _bfm_csr: DualCsr) -> None:
        driver = SmcDftStatusDriver(harness, "dut", dut_csr, dut.clk_smc_i)
        # Before the target fetches: the ROM reads DFX_CTRL_STATUS once, early in boot.
        driver.report(row["dft"])
        await _await_sense_done(dut)
        dfx = await dut_csr.read("DFX_CTRL_STATUS_SMU", DFX_CTRL_STATUS_SMU)
        driver.check_status_register(row["dft"], dfx)
        straps = {}
        for strap in ("MEM_REPAIR_BYPASS", "MEM_BIST_BYPASS"):
            addr, bit = strap_reg_addr(STRAP_BITS[strap])
            straps[strap] = (await dut_csr.read(f"STRAPS_{strap}", addr) >> bit) & 1
        smc_config = await dut_csr.read(
            "SMC_CONFIG", SMC_EFUSE_WRAP_SMC_EFUSE_MAP_SMC_CONFIG_REG_ADDR
        )
        ignore = int(bool(smc_config & SMC_CONFIG_DFT_IGNORE_ERROR))
        wrong = [f"{strap}={straps[strap]}" for strap in straps if straps[strap] != row[strap]]
        if ignore != row["ignore"] or harness.efuse.dft_ignore_error != row["ignore"]:
            wrong.append(
                f"SMC_CONFIG shadow {smc_config:#010x} (image bit 15 = "
                f"{harness.efuse.dft_ignore_error})"
            )
        if wrong:
            raise AssertionError(
                f"{case}: the target captured {', '.join(wrong)}; the row needs "
                f"MEM_REPAIR_BYPASS={row['MEM_REPAIR_BYPASS']} "
                f"MEM_BIST_BYPASS={row['MEM_BIST_BYPASS']} dft_ignore_error={row['ignore']}"
            )
        cocotb.log.info(
            "CHK-ROM-DFT-STIMULUS: %s before target fetch: DFX_CTRL_STATUS_SMU=%#010x (%s), "
            "captured MEM_REPAIR_BYPASS=%d MEM_BIST_BYPASS=%d, SMC_CONFIG shadow=%#010x "
            "(dft_ignore_error=%d)",
            case,
            dfx,
            row["dft"],
            straps["MEM_REPAIR_BYPASS"],
            straps["MEM_BIST_BYPASS"],
            smc_config,
            ignore,
        )

    result = await run_occp_rom_only(
        harness,
        case=case,
        bring_up_kwargs={"dft_low": ("dut",)},
        before_release=report_and_attribute,
    )

    if result.target_scratch0 != TEST_PASS:
        raise AssertionError(
            f"{case}: target scratch 0 = {result.target_scratch0:#010x}, not {TEST_PASS:#010x}; "
            "only the controller's serviced WriteData writes it"
        )
    phase = post_code_boot_phase(result.target_post_code)
    error = post_code_error(result.target_post_code)
    if phase != POST_CODE_BOOT_PHASE_OCCP_PROC or error:
        raise AssertionError(
            f"{case}: target POST {describe_post_code(result.target_post_code)} after the OCCP "
            "exchange; continued boot ends in OCCP_PROC with no error"
        )
    distinct = await _require_running_outside(dut, harness, excluded)
    cocotb.log.info(
        "CHK-ROM-DFT-CONTINUE: %s target scratch0=%#010x from the controller's WriteData, POST "
        "%s, %d distinct hart-0 PCs in %d cycles, none in %s",
        case,
        result.target_scratch0,
        describe_post_code(result.target_post_code),
        distinct,
        LOCALITY_WINDOW_CYCLES,
        ", ".join(f"{name} [{lo:#x}, {hi:#x})" for name, (lo, hi) in excluded.items()),
    )

    status = await result.dut_csr.read("MBIST_STATUS", SCRATCH_MBIST_STATUS)
    if status != row["scratch15"]:
        raise AssertionError(
            f"{case}: target scratch 15 = {status:#010x}, expected {row['scratch15']:#010x}"
        )
    cocotb.log.info(
        "%s: %s recorded scratch 15 = %#010x and kept booting",
        _case_evidence(case),
        case,
        status,
    )
    cocotb.log.info("%s (%s) PASS", CASE, case)
