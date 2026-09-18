# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Bootcode (boot_rom.elf) on sep-vp, asserted via the production SEP_STATUS path.

These exercise the harness end-to-end: straps select the boot mode, and the decoded
``[SEP_STATUS]`` stream proves the firmware took the matching path. With no SMC/SPI manifest
staged, secondary/recovery deterministically end in a production ``MANIFEST_LOAD_FAILED``
ERROR (a real negative assertion), and primary proceeds into SPI boot.

Reaching ``SEP_MSG_STARTING_BL1`` needs a real PTOC manifest staged in SMC SRAM / SPI flash;
that test is skipped until manifest staging lands (see test_full_boot_to_bl1).
"""

import pytest
import shared
from sepvp.config import SimConfig
from sepvp.harness import SEP_STATUS_ANY_RE, SIM_OUT_PREFIX

pytestmark = pytest.mark.bootcode

TIMEOUT = 120


def _cfg(name, elf, **kw):
    return SimConfig(name=name, elf=elf, boot_timeout=TIMEOUT, **kw)


def test_common_early_boot(vp, bootcode_elf):
    """The common early-boot SEP_STATUS sequence appears, in order, with no ERROR."""
    t = vp(_cfg("boot_common_early", bootcode_elf, boot="primary"))
    t.spawn()
    shared.expect_common_early(t, timeout=TIMEOUT)
    t.close()


def test_primary_chiplet_strap(vp, bootcode_elf):
    """--boot primary -> the firmware reports the PRIMARY_CHIPLET role (strap plumbing)."""
    t = vp(_cfg("boot_primary", bootcode_elf, boot="primary"))
    t.spawn()
    shared.expect_common_early(t, timeout=TIMEOUT)
    shared.expect_primary_chiplet(t, timeout=TIMEOUT)
    t.close()


def test_secondary_chiplet_strap_and_manifest_error(vp, bootcode_elf):
    """--boot secondary -> SECONDARY_CHIPLET, then a production MANIFEST_LOAD_FAILED ERROR.

    Proves both the (mutually exclusive) strap path and the harness's production-ERROR
    negative assertion (expect_status type='ERROR').
    """
    t = vp(_cfg("boot_secondary", bootcode_elf, boot="secondary"))
    t.spawn()
    shared.expect_common_early(t, timeout=TIMEOUT)
    shared.expect_secondary_chiplet(t, timeout=TIMEOUT)
    match = shared.expect_manifest_load_failed(t, timeout=TIMEOUT)
    assert "ERROR" in match.group(0)
    t.close()


def test_recovery_strap(vp, bootcode_elf):
    """--recovery -> PRIMARY_CHIPLET then BOOT_RECOVERY (recovery strap on a primary chiplet)."""
    t = vp(_cfg("boot_recovery", bootcode_elf, boot="primary", recovery=True))
    t.spawn()
    shared.expect_common_early(t, timeout=TIMEOUT)
    shared.expect_primary_chiplet(t, timeout=TIMEOUT)
    t.expect_status("SEP_MSG_BOOT_RECOVERY", type="INFO", timeout=TIMEOUT)
    t.close()


def test_rotate_update_strap(vp, bootcode_elf):
    """--rotate-update -> the primary path reports ROTATE_UPDATE after the chiplet role.

    NOTE: the ROM reports SEP_MSG_ROTATE_UPDATE unconditionally (the latched value
    follows in an INFO_EXT), so this proves the report point is reached — the strap
    VALUE itself is not asserted."""
    t = vp(_cfg("boot_rotate", bootcode_elf, boot="primary", rotate_update=True))
    t.spawn()
    shared.expect_common_early(t, timeout=TIMEOUT)
    shared.expect_primary_chiplet(t, timeout=TIMEOUT)
    t.expect_status("SEP_MSG_ROTATE_UPDATE", type="INFO", timeout=TIMEOUT)
    t.close()


@pytest.mark.needs_debug
def test_strap_readback_sim_out(vp, bootcode_elf):
    """DEBUG build: the SIM_OUT console echoes the latched primary strap.

    This repo's ROM echoes only `STRAP primary=` (the old repo's ROM also echoed
    recovery/rotate); asserting the primary echo still proves the SIM_OUT strap
    readback channel end-to-end."""
    t = vp(_cfg("boot_straps_simout", bootcode_elf, boot="primary"))
    t.spawn()
    t.expect(SIM_OUT_PREFIX + r"STRAP primary=1", timeout=TIMEOUT)
    t.close()


def test_sep_status_can_be_disabled(vp, bootcode_elf):
    """--no-sep-status (sep_status.enable=false) suppresses [SEP_STATUS]; SIM_OUT still flows.

    We confirm SIM_OUT reaches an early milestone but no [SEP_STATUS] line precedes it.
    """
    t = vp(_cfg("boot_no_status", bootcode_elf, boot="primary", sep_status=False))
    t.spawn()
    # 'COLD' is an early SIM_OUT marker; assert it arrives and that no SEP_STATUS line did.
    # Status lines are now bare (no "[SEP_STATUS] - " tag), so the negative assertion matches
    # the decoded line *shape* instead of the vanished prefix.
    t.expect(SIM_OUT_PREFIX + r"\bCOLD\b", error_patterns=[SEP_STATUS_ANY_RE], timeout=TIMEOUT)
    t.close()


# The full-boot-to-BL1 milestone this file used to hold as a skipped placeholder
# now lives in test_bootcode_oca.py, which stages real signed and encrypted OCA
# images and reaches SEP_MSG_STARTING_BL1. Keeping the placeholder would report a
# coverage gap that has been closed.
