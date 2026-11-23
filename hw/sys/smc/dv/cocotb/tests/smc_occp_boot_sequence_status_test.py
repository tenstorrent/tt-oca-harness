# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The SMC ROM's boot-mode status entries must match the role and recovery straps it sampled.

Each seed draws the target's PRIMARY_CHIPLET and BOOT_RECOVERY independently. The target's
chiplet_is_primary pin follows PRIMARY_CHIPLET, the controller stays primary, and
STATUS_RPT_DISABLE is clear so GetStatus answers. The selection reaches the controller
firmware through controller scratch 14; the firmware drains the SMC status ring once and
grades that one drain (format, required and forbidden codes, exact boot order), then reports
what it saw in controller scratch 15. A passing leaf records its {primary, recovery} cell in
smc_rom_mode_coverage.json for the four-cell merge.

Plusargs:
    +rom_bin64=<image>        target production ROM                       (required)
    +bfm_rom_hex=<image>      occp_boot_sequence_status_test controller    (required)
    +FORCE_STATUS_REPORTING   required: the checks need the status ring
"""

from __future__ import annotations

import random
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles
from env.smc_rom_mode_coverage import ARTIFACT_NAME, write_leaf_artifact
from smc_dual_base_test import DualCsr, SmcDualHarness, dual_test, random_seed
from smc_occp_dual_defs import (
    SCRATCH_PASS_FAIL,
    SCRATCH_STATUS_MODE,
    SCRATCH_STATUS_SUMMARY,
    STATUS_CHECKS_ALL,
    STATUS_SEEN_PRIMARY,
    STATUS_SEEN_RECOVERY,
    STATUS_SEEN_SECONDARY,
    STATUS_SUMMARY_MAGIC,
    STRAP_BITS,
    STRAP_PRIMARY_CHIPLET,
    TEST_PASS,
    expected_boot_statuses,
    status_mode_word,
    strap_reg_addr,
)
from smc_occp_rom_only_test import run_occp_rom_only
from smc_reg import SMC_CPU_CTRL_SMC_ATTRIBUTES_REG_ADDR

CASE = "smc_occp_boot_sequence_status_test"
CONTROLLER_VERDICT_POLLS = 100
CONTROLLER_VERDICT_POLL_CYCLES = 200
REQUIRED_EVIDENCE = (
    "CHK-OCCP-SANITY",
    "CHK-ROM-STATUS-MODE-STIMULUS",
    "CHK-ROM-STATUS-RAW-SEQUENCE",
    "CHK-ROM-STATUS-REQUIRED-FORBIDDEN",
    "CHK-ROM-STATUS-FORMAT-ORDER",
)


def draw_mode(seed: int) -> tuple[bool, bool]:
    rng = random.Random(f"smc-rom-status-{seed}")
    primary = rng.choice((False, True))
    recovery = rng.choice((False, True))
    return primary, recovery


@dual_test(REQUIRED_EVIDENCE)
async def smc_occp_boot_sequence_status_test(harness: SmcDualHarness) -> None:
    if cocotb.plusargs.get("FORCE_STATUS_REPORTING") is None:
        raise AssertionError(f"{CASE} needs +FORCE_STATUS_REPORTING; it grades the status ring")
    seed = random_seed()
    primary, recovery = draw_mode(seed)
    mode_word = status_mode_word(primary, recovery)
    cocotb.log.info(
        "%s (RANDOM_SEED=%d): target PRIMARY_CHIPLET=%d BOOT_RECOVERY=%d, mode word %#010x",
        CASE,
        seed,
        primary,
        recovery,
        mode_word,
    )

    async def attribute_mode(dut_csr: DualCsr, _bfm_csr: DualCsr) -> None:
        captured = {}
        for name, bit in (
            ("PRIMARY_CHIPLET", STRAP_PRIMARY_CHIPLET),
            ("BOOT_RECOVERY", STRAP_BITS["BOOT_RECOVERY"]),
            ("STATUS_RPT_DISABLE", STRAP_BITS["STATUS_RPT_DISABLE"]),
        ):
            addr, pos = strap_reg_addr(bit)
            captured[name] = (await dut_csr.read(f"STRAPS_{name}", addr) >> pos) & 1
        attributes = await dut_csr.read("SMC_ATTRIBUTES", SMC_CPU_CTRL_SMC_ATTRIBUTES_REG_ADDR)
        pin = attributes & 1
        want = {"PRIMARY_CHIPLET": int(primary), "BOOT_RECOVERY": int(recovery)}
        want["STATUS_RPT_DISABLE"] = 0
        wrong = [f"{k}={captured[k]} (want {v})" for k, v in want.items() if captured[k] != v]
        if pin != int(primary):
            wrong.append(f"SMC_ATTRIBUTES.chiplet_is_primary={pin} (want {int(primary)})")
        if wrong:
            raise AssertionError(f"{CASE}: target captured {', '.join(wrong)}")
        cocotb.log.info(
            "CHK-ROM-STATUS-MODE-STIMULUS: target captured PRIMARY_CHIPLET=%d BOOT_RECOVERY=%d "
            "STATUS_RPT_DISABLE=0 and SMC_ATTRIBUTES.chiplet_is_primary=%d, as drawn; the "
            "controller gets mode word %#010x in its scratch 14",
            captured["PRIMARY_CHIPLET"],
            captured["BOOT_RECOVERY"],
            pin,
            mode_word,
        )

    result = await run_occp_rom_only(
        harness,
        case=CASE,
        bring_up_kwargs={"dut_primary": primary, "dut_recovery": recovery},
        before_release=attribute_mode,
        bfm_preload=((SCRATCH_STATUS_MODE, mode_word),),
    )
    # The firmware writes the target's scratch 0 over OCCP, then its own.
    controller_scratch0 = result.controller_scratch0
    for _ in range(CONTROLLER_VERDICT_POLLS):
        if controller_scratch0 == TEST_PASS:
            break
        await ClockCycles(harness.dut.clk_smc_i, CONTROLLER_VERDICT_POLL_CYCLES)
        controller_scratch0 = await result.bfm_csr.read("CTRL_PASS", SCRATCH_PASS_FAIL)
    if result.target_scratch0 != TEST_PASS or controller_scratch0 != TEST_PASS:
        raise AssertionError(
            f"{CASE}: target scratch 0 = {result.target_scratch0:#010x}, controller scratch 0 = "
            f"{controller_scratch0:#010x}; the firmware writes {TEST_PASS:#010x} to both"
        )

    summary = await result.bfm_csr.read("STATUS_SUMMARY", SCRATCH_STATUS_SUMMARY)
    magic = summary & 0xFF00_0000
    boot_codes = (summary >> 16) & 0xFF
    checks = (summary >> 8) & 0xFF
    seen = summary & 0xFF
    expected = expected_boot_statuses(primary, recovery)
    want_seen = (STATUS_SEEN_PRIMARY if primary else STATUS_SEEN_SECONDARY) | (
        STATUS_SEEN_RECOVERY if recovery else 0
    )
    if magic != STATUS_SUMMARY_MAGIC or boot_codes != len(expected):
        raise AssertionError(
            f"{CASE}: controller summary {summary:#010x}; want magic {STATUS_SUMMARY_MAGIC:#010x} "
            f"and {len(expected)} boot entries in the one drain"
        )
    cocotb.log.info(
        "CHK-ROM-STATUS-RAW-SEQUENCE: the controller drained the ring once and kept %d boot "
        "entries (raw words in its console above); expected order %s",
        boot_codes,
        ", ".join(f"{word:#010x}" for word in expected),
    )
    if seen != want_seen:
        raise AssertionError(
            f"{CASE}: the drain held mode codes {seen:#04x}, the straps need {want_seen:#04x} "
            f"(primary {STATUS_SEEN_PRIMARY:#x}, secondary {STATUS_SEEN_SECONDARY:#x}, "
            f"recovery {STATUS_SEEN_RECOVERY:#x})"
        )
    if checks != STATUS_CHECKS_ALL:
        raise AssertionError(f"{CASE}: controller check mask {checks:#04x}, want all set")
    cocotb.log.info(
        "CHK-ROM-STATUS-REQUIRED-FORBIDDEN: mode codes seen %#04x match PRIMARY_CHIPLET=%d "
        "BOOT_RECOVERY=%d; no forbidden boot code",
        seen,
        primary,
        recovery,
    )
    cocotb.log.info(
        "CHK-ROM-STATUS-FORMAT-ORDER: every entry carries firmware ID 0x03 and a defined type, "
        "and the boot entries match the expected order exactly (check mask %#04x)",
        checks,
    )

    artifact = write_leaf_artifact(
        Path.cwd() / ARTIFACT_NAME, seed=seed, primary=primary, recovery=recovery
    )
    cocotb.log.info("%s PASS; mode cell recorded in %s", CASE, artifact)
