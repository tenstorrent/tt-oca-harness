# SPDX-License-Identifier: Apache-2.0
"""JTAG protocol-VIP helpers for SMC OSS tests.

These helpers drive the public CPU JTAG TAP via ``cocotbext.jtag`` and verify
the IDCODE register returns the expected value composed from the
``smc_cpu_jtag_{mfr_id,part_number,version}_i`` straps wired in
``tb_top.sv``. After the upgrade the old line-level pull-low pattern is
subsumed by the full TAP reset + IDCODE capture.

API surface kept compatible with the previous helpers so the JTAG triplet
tests do not need touching beyond import paths.
"""

from __future__ import annotations

from typing import Optional

import cocotb

from .smc_jtag_protocol_vip import (
    EXPECTED_CPU_TAP_IDCODE,
    SmcJtagTap,
    SmcJtagTapError,
)


# Module-level cache so multiple helper calls inside one test share one driver.
_TAP_SINGLETON: Optional[SmcJtagTap] = None


def _get_tap() -> SmcJtagTap:
    global _TAP_SINGLETON
    if _TAP_SINGLETON is None:
        _TAP_SINGLETON = SmcJtagTap()
        _TAP_SINGLETON.init_signals()
    return _TAP_SINGLETON


async def check_cpu_jtag_pin_vip() -> None:
    """Drive a full TAP reset + IDCODE + DTMCS captures against the CPU TAP.

    Verifies that ``tb_cpu_jtag_tdo`` is resolvable and the captured IDCODE
    matches ``EXPECTED_CPU_TAP_IDCODE`` = 0x10CA0555, the composition of the
    JEP106 straps in ``tb_top.sv`` (mfr=0x2AA, part=0x0CA0, version=0x1).
    Also reads the DTMCS register (IR=0x10) to prove IR/DR access beyond
    the default post-reset IDCODE latch. DTMCS is logged but not asserted
    on so the same helper works across TAP flavours in bring-up.

    Confirmed 2026-06-30 on Xcelium 25.03.001 for ``smc_ijtag_basic_test``.
    """
    dut = cocotb.top
    tap = _get_tap()
    await tap.reset_tap()
    idcode = await tap.read_idcode(check=True)
    assert dut.tb_cpu_jtag_tdo.value.is_resolvable, "CPU JTAG TDO is not resolvable"
    cocotb.log.info(
        "CPU JTAG pin VIP captured IDCODE=0x%08X (expected 0x%08X, MATCH)",
        idcode, EXPECTED_CPU_TAP_IDCODE,
    )
    dtmcs = await tap.read_dtmcs()
    version = dtmcs & 0xF
    assert version == 0x1, (
        f"CPU JTAG DTMCS version=0x{version:X} != 0x1 (expected RISC-V Debug "
        f"Spec 0.13); full DTMCS=0x{dtmcs:08X}"
    )
    cocotb.log.info(
        "CPU JTAG pin VIP captured DTMCS=0x%08X (RISC-V Debug 0.13, MATCH)",
        dtmcs,
    )


async def check_cpu_jtag_idcode_and_bypass() -> int:
    """Capture IDCODE then load BYPASS; return IDCODE for downstream checks."""
    tap = _get_tap()
    await tap.reset_tap()
    idcode = await tap.read_idcode(check=True)
    await tap.bypass()
    return idcode


async def check_cpu_jtag_dtmcs() -> int:
    """Shift DTMCS after IDCODE — proves IR/DR access beyond IDCODE.

    Returns the raw DTMCS word for downstream sanity checks. Non-fatal by
    default so early-bringup DUTs with different TAP flavours still pass.
    """
    tap = _get_tap()
    await tap.reset_tap()
    idcode = await tap.read_idcode(check=True)
    dtmcs = await tap.read_dtmcs()
    cocotb.log.info(
        "CPU JTAG TAP IR/DR proof: IDCODE=0x%08X, DTMCS=0x%08X", idcode, dtmcs
    )
    return dtmcs


__all__ = [
    "EXPECTED_CPU_TAP_IDCODE",
    "SmcJtagTap",
    "SmcJtagTapError",
    "check_cpu_jtag_pin_vip",
    "check_cpu_jtag_idcode_and_bypass",
]
