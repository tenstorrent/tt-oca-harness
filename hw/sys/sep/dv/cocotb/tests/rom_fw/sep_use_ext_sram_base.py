# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared assertions for the four manifest ``use_ext_sram`` testcases.

The manifest's ``flag_args`` bit 29 picks where the ROM
stages the payload it reads out of flash: set means SEP EXT SRAM, clear means
wait for SMC SRAM and stage there (``manifest_load.c``). The four
testcases are primary/backup crossed with set/clear.

WHAT THESE ACTUALLY PROVE. Declaring the same ``expected_patterns`` for the set
and clear members of a pair, without asserting which SRAM was used, would pass
against a ROM that ignores the bit entirely. These members therefore assert the two
console values that only the chosen branch can produce, and forbid the other
branch's:

  * ``USING_SEP_SRAM`` (0x99) or ``USING_SMC_SRAM`` (0x98), exactly one of them,
    exactly once, and the other zero times;
  * ``PAYLOAD_DST=`` at an address inside the region that branch selected. The
    ROM prints its own staging destination after the transfer, so this is the
    destination itself rather than a proxy for it.

The clear members additionally require ``EXT_SRAM_INIT_WAIT`` (0x39), which only
the SMC arm emits, and prove the ROM consumed the window SMC published rather
than assuming one: the TB supplies scratch[13]/[14] through
``+sep_smc_scratch13`` / ``+sep_smc_scratch14`` and the destination must equal
``smc_sram_base + scratch[13]``.

SCOPE LIMIT, and it is not small. ``u_smc_mem`` is a flat ``axi_sim_mem``, so a
pass here says the ROM reads the window at the offsets
``sep_smc_interface.h`` names and acts on the value correctly. It says nothing
about whether SMC firmware publishes those registers, when, or with what --
the TB writes where the ROM reads, so this environment cannot falsify the
offsets. Do not book these rows as covering the SMC-side contract.
"""

from __future__ import annotations

from env import sep_manifest_mutate as mm
from rom_fw import sep_manifest_field_defect as fd

# SEP EXT SRAM: the manifest sits at the base and the payload at
# base + payload_offset (manifest_load.c). The shipped images use 0x1000.
SEP_SRAM_BASE = 0x1000_0000
SEP_PAYLOAD_OFFSET = 0x1000
SEP_PAYLOAD_DST = SEP_SRAM_BASE + SEP_PAYLOAD_OFFSET

# SMC SRAM: smc_base + SMC_SRAM_OFFSET (sep_smc_interface.h).
SMC_SRAM_BASE = 0x4006_0000

# The window the TB publishes for the SMC-staging members. 0x20000 clears the
# status ring buffer, which sits at the SMC SRAM base, and is 8-byte aligned so
# it passes the ROM's alignment check. The size dwarfs the ~5.8 KiB payload, so
# the capacity check is not what is under test here.
SMC_WINDOW_OFFSET = 0x0002_0000
SMC_WINDOW_SIZE = 0x0002_0000
SMC_PAYLOAD_DST = SMC_SRAM_BASE + SMC_WINDOW_OFFSET

USING_SEP = "USING_SEP_SRAM"
USING_SMC = "USING_SMC_SRAM"
WAIT_MARKER = "EXT_SRAM_INIT_WAIT"

# Verdicts the SMC arm produces when the published window is unusable. None may
# appear in a member that is supposed to stage successfully.
SMC_REFUSALS = (
    "SMC_WIN_OOB", "SMC_WIN_MISALIGNED", "PAYLOAD_NO_ROOM=", "PAYLOAD_DST_OT_OOB",
)


def sep_markers() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Required/forbidden markers for a member that must stage in SEP SRAM."""
    return (
        (USING_SEP, f"PAYLOAD_DST=0x{SEP_PAYLOAD_DST:08x}"),
        (USING_SMC, WAIT_MARKER) + SMC_REFUSALS,
    )


def smc_markers() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Required/forbidden markers for a member that must stage in SMC SRAM."""
    return (
        (WAIT_MARKER, USING_SMC, f"PAYLOAD_DST=0x{SMC_PAYLOAD_DST:08x}"),
        (USING_SEP,) + SMC_REFUSALS,
    )


def assert_stimulus(logger, buf: bytes, slot: str, *, want_set: bool) -> None:
    """Prove the served manifest carries the bit value this testcase is named for.

    Without this the testcase cannot tell "the ROM took the branch I asked for"
    from "the image happened to ask for the branch I expected".
    """
    flags = mm.get_flag_args(buf, slot)
    bit = (flags >> mm.FLAG_ARGS_BIT_USE_EXT_SRAM) & 1
    assert bit == int(want_set), (
        f"{slot} manifest flag_args=0x{flags:08x} has use_ext_sram={bit}, "
        f"expected {int(want_set)}; the stimulus this testcase is named for is "
        f"not in the image the ROM will read"
    )
    logger.info(
        "CHK-STIMULUS-USE-EXT-SRAM: %s flag_args=0x%08x, use_ext_sram=%d -> the "
        "ROM must stage the payload in %s", slot, flags, bit,
        "SEP EXT SRAM" if bit else "SMC SRAM",
    )


def assert_destination(logger, console: list[str], *, expect_smc: bool) -> None:
    """One branch ran, the other did not, and the payload landed where it said."""
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
        f"{chosen}@{i_branch} must precede {want_dst}@{i_dst}: manifest_load.c "
        f"announces the branch before it transfers. Console: {console}"
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
            WAIT_MARKER, i_wait, chosen, i_branch, want_dst, i_dst,
            SMC_WINDOW_OFFSET,
        )
    else:
        logger.info(
            "CHK-SEP-STAGING: %s@%d -> %s@%d -- the ROM staged in its own SRAM "
            "and never entered the SMC arm, so bit 29 selected the destination",
            chosen, i_branch, want_dst, i_dst,
        )
