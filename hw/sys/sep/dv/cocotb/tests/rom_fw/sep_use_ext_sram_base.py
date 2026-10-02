# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared assertions for the four manifest ``use_ext_sram`` testcases.

Checks that flag_args bit 29 selects SEP EXT SRAM or SMC SRAM staging. The TB writes the
SMC window registers the ROM reads.
"""

from __future__ import annotations

from env import sep_manifest_mutate as mm
from rom_fw import sep_manifest_field_defect as fd

# The shipped images place the payload 0x1000 above the manifest.
SEP_SRAM_BASE = 0x1000_0000
SEP_PAYLOAD_OFFSET = 0x1000
SEP_PAYLOAD_DST = SEP_SRAM_BASE + SEP_PAYLOAD_OFFSET

SMC_SRAM_BASE = 0x4006_0000

# The window must clear the status ring buffer at the SMC SRAM base and stay 8-byte aligned.
SMC_WINDOW_OFFSET = 0x0002_0000
SMC_WINDOW_SIZE = 0x0002_0000
SMC_PAYLOAD_DST = SMC_SRAM_BASE + SMC_WINDOW_OFFSET

USING_SEP = "USING_SEP_SRAM"
USING_SMC = "USING_SMC_SRAM"
WAIT_MARKER = "EXT_SRAM_INIT_WAIT"

# SMC-arm refusals of an unusable window; none may appear when staging succeeds.
SMC_REFUSALS = (
    "SMC_WIN_OOB",
    "SMC_WIN_MISALIGNED",
    "PAYLOAD_NO_ROOM=",
    "PAYLOAD_DST_OT_OOB",
)


def sep_markers() -> tuple[tuple[str, ...], tuple[str, ...]]:
    return (
        (USING_SEP, f"PAYLOAD_DST=0x{SEP_PAYLOAD_DST:08x}"),
        (USING_SMC, WAIT_MARKER) + SMC_REFUSALS,
    )


def smc_markers() -> tuple[tuple[str, ...], tuple[str, ...]]:
    return (
        (WAIT_MARKER, USING_SMC, f"PAYLOAD_DST=0x{SMC_PAYLOAD_DST:08x}"),
        (USING_SEP,) + SMC_REFUSALS,
    )


def assert_stimulus(logger, buf: bytes, slot: str, *, want_set: bool) -> None:
    flags = mm.get_flag_args(buf, slot)
    bit = (flags >> mm.FLAG_ARGS_BIT_USE_EXT_SRAM) & 1
    assert bit == int(want_set), (
        f"{slot} manifest flag_args=0x{flags:08x} has use_ext_sram={bit}, "
        f"expected {int(want_set)}; the stimulus this testcase is named for is "
        f"not in the image the ROM will read"
    )
    logger.info(
        "CHK-STIMULUS-USE-EXT-SRAM: %s flag_args=0x%08x, use_ext_sram=%d -> the "
        "ROM must stage the payload in %s",
        slot,
        flags,
        bit,
        "SEP EXT SRAM" if bit else "SMC SRAM",
    )


def assert_destination(logger, console: list[str], *, expect_smc: bool) -> None:
    chosen, other = (USING_SMC, USING_SEP) if expect_smc else (USING_SEP, USING_SMC)
    want_dst = f"PAYLOAD_DST=0x{(SMC_PAYLOAD_DST if expect_smc else SEP_PAYLOAD_DST):08x}"

    n_chosen = fd.count(console, chosen)
    assert n_chosen == 1, (
        f"{chosen} appeared {n_chosen} times, expected exactly 1. Only one slot "
        f"stages a payload in this run. Console: {console}"
    )
    assert fd.count(console, other) == 0, (
        f"{other} appeared; the ROM staged into the region this testcase forbids. "
        f"Console: {console}"
    )

    i_branch = fd.first_index(console, chosen)
    i_dst = fd.first_index(console, want_dst)
    assert i_dst >= 0, (
        f"ROM never printed {want_dst}. It announced {chosen} but staged "
        f"somewhere else, so the branch and the transfer disagree. "
        f"Console: {console}"
    )
    assert i_branch < i_dst, (
        f"{chosen}@{i_branch} must precede {want_dst}@{i_dst}: the ROM announces the "
        f"branch before it transfers. Console: {console}"
    )

    if expect_smc:
        i_wait = fd.first_index(console, WAIT_MARKER)
        assert 0 <= i_wait < i_branch, (
            f"{WAIT_MARKER}@{i_wait} must precede {chosen}@{i_branch}: the ROM "
            f"waits for SRAM_INIT before it reads the window. Console: {console}"
        )
        logger.info(
            "CHK-SMC-STAGING: %s@%d -> %s@%d -> %s@%d -- the ROM waited for the "
            "SMC window, then staged at smc_sram_base+0x%x, which is the offset "
            "scratch[13] published and not a value it could have assumed",
            WAIT_MARKER,
            i_wait,
            chosen,
            i_branch,
            want_dst,
            i_dst,
            SMC_WINDOW_OFFSET,
        )
    else:
        logger.info(
            "CHK-SEP-STAGING: %s@%d -> %s@%d -- the ROM staged in its own SRAM "
            "and never entered the SMC arm, so bit 29 selected the destination",
            chosen,
            i_branch,
            want_dst,
            i_dst,
        )
