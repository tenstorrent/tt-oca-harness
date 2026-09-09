# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Reusable expect sequences for bootcode-on-sep-vp tests.

Keyed to the production ``SEP_MSG_*`` codes (always-on, symbolic, decoded straight from the
``[SEP_STATUS]`` lines). ``SEP_MSG_*`` names come from
``hw/sys/sep/bootrom/prod/include/status_values.h`` (the same header the VP's
decoder loads and the ROM compiles against).

Sequences are written for the current VP state, captured from real runs:
  * the common early boot flow (PLL → lifecycle → SRAM/ICCM clear → fuse read) is identical
    across boot modes;
  * the boot mode then diverges at the chiplet-role status (the proof that straps plumb
    through). Without a staged SMC/SPI manifest, secondary/recovery end in a production
    MANIFEST_LOAD_FAILED ERROR, and primary proceeds into SPI boot (and stalls).
"""

# Common early-boot SEP_STATUS sequence, in order, for every boot mode.
COMMON_EARLY = (
    "SEP_MSG_PLL_CLK_INIT",
    "SEP_MSG_FUSE_LC_STATE",
    "SEP_MSG_LIFECYCLE_VALID",
    "SEP_MSG_EXT_SRAM_CLEAR_START",
    "SEP_MSG_EXT_SRAM_CLEAR_DONE",
    "SEP_MSG_ICCM_CLEAR_START",
    "SEP_MSG_ICCM_CLEAR_DONE",
    "SEP_MSG_FUSE_SBOOT_DIS",
)


def expect_common_early(test, timeout=120):
    """Expect the common early-boot SEP_STATUS sequence (ordered)."""
    for name in COMMON_EARLY:
        test.expect_status(name, type="INFO", timeout=timeout)


def expect_primary_chiplet(test, timeout=120):
    """Primary chiplet path: role status after the common early boot."""
    test.expect_status("SEP_MSG_PRIMARY_CHIPLET", type="INFO", timeout=timeout)


def expect_secondary_chiplet(test, timeout=120):
    """Secondary chiplet path: role status after the common early boot."""
    test.expect_status("SEP_MSG_SECONDARY_CHIPLET", type="INFO", timeout=timeout)


def expect_manifest_load_failed(test, timeout=120):
    """Production ERROR raised when no SMC/SPI manifest is available (negative path)."""
    return test.expect_status("SEP_MSG_MANIFEST_LOAD_FAILED", type="ERROR", timeout=timeout)
