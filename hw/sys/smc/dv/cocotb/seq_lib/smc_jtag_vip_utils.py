# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG protocol-VIP helpers for SMC OSS tests.

These helpers drive the public CPU JTAG TAP via ``cocotbext.jtag`` and verify
the IDCODE register returns the expected value composed from the
``smc_cpu_jtag_{mfr_id,part_number,version}_i`` straps wired in
``tb_top.sv`` through a full TAP reset + IDCODE capture.
"""

from __future__ import annotations

from typing import Optional

import cocotb
from cocotb.triggers import RisingEdge

from .smc_jtag_protocol_vip import (
    _DMI_DR_WIDTH,
    EXPECTED_CPU_TAP_IDCODE,
    SmcJtagTap,
    SmcJtagTapError,
)

# --- DTMCS expectation, RISC-V External Debug Support v0.13.2 sec. 6.1.4 ---
# dtmcs = {reserved[31:18], dmihardreset[17], dmireset[16], reserved[15],
#          idle[14:12], dmistat[11:10], abits[9:4], version[3:0]}
DTMCS_VERSION_0_13 = 0x1
# ``dmistat`` after a TAP reset with no DMI operation issued: 0 = no error.
DTMCS_DMISTAT_NO_ERROR = 0x0
# ``abits`` is fixed by the TB's own DMI scan contract, not read out of the RTL:
# the DMI DR is {addr[abits], data[32], op[2]}, so abits = DR width - 34. Taken
# from the VIP constant that actually shifts those scans, so a VIP change can
# never diverge silently from the value asserted here.
EXPECTED_DTMCS_ABITS = _DMI_DR_WIDTH - 34
# ``dmireset``/``dmihardreset`` are W1 (read back 0) and everything from bit 15
# up is reserved-zero in v0.13.2, so the whole [31:15] slice must read 0.
DTMCS_RESERVED_HI_SHIFT = 15


# --- Scan-activity floor for check_cpu_jtag_pin_vip -------------------------
# The JTAG scans this helper drives carry their own activity floor.
# `min_csr_accesses` cannot serve as one: it counts SEP_IN AXI CSR traffic
# issued by an unrelated sequence, so a TAP driver that silently shifted nothing
# would still produce a record that looked checked
# ([EVIDENCE-TOKEN-CONDITIONAL]).
#
# The observation is measured at the DUT-facing pin -- rising edges counted on
# `tb_cpu_jtag_tck` while this helper runs -- and is therefore independent of the
# VIP's own bookkeeping: an `OcahJtagMasterDriver` that returned early, or a
# GatedClock/RX-FSM desync that stopped driving TCK, collapses the count.
#
# The floor is the payload-bit contract of the two scans below,
# ignoring every TAP-reset, state-navigation and idle-delay cycle so it stays a
# strict lower bound on any correct execution:
#   IR width 5 (IEEE 1149.1 5-bit instruction register, SmcCpuTapDevice)
#   + IDCODE DR 32 (IEEE 1149.1 device identification register)
# and again for
#   IR width 5 + DTMCS DR 32 (RISC-V External Debug Support v0.13.2 sec. 6.1.4)
#   => 2 x (5 + 32) = 74 TCK cycles minimum.
_CPU_TAP_IR_WIDTH = 5
_IDCODE_DR_WIDTH = 32
_DTMCS_DR_WIDTH = 32
MIN_CPU_JTAG_TCK_EDGES = (_CPU_TAP_IR_WIDTH + _IDCODE_DR_WIDTH) + (
    _CPU_TAP_IR_WIDTH + _DTMCS_DR_WIDTH
)


class _TckEdgeCounter:
    """Count rising edges of a clock-like signal while a scan sequence runs.

    Pin-level and passive: it samples a top-level TB pin and drives nothing.
    (Twin of ``smc_efuse_vip_utils.count_probe_high_cycles`` / ``stop_sampler``
    for the probe-sampling case.)
    """

    def __init__(self, sig) -> None:
        self._sig = sig
        self.edges = 0
        self._task = None

    async def _run(self) -> None:
        while True:
            await RisingEdge(self._sig)
            self.edges += 1

    def start(self) -> "_TckEdgeCounter":
        self._task = cocotb.start_soon(self._run())
        return self

    def stop(self) -> int:
        if self._task is not None:
            self._task.cancel()
            self._task = None
        return self.edges


# Module-level cache so multiple helper calls inside one test share one driver.
_TAP_SINGLETON: Optional[SmcJtagTap] = None


def _get_tap() -> SmcJtagTap:
    global _TAP_SINGLETON
    if _TAP_SINGLETON is None:
        _TAP_SINGLETON = SmcJtagTap()
        _TAP_SINGLETON.init_signals()
    return _TAP_SINGLETON


async def check_cpu_jtag_pin_vip() -> int:
    """Drive a full TAP reset + IDCODE + DTMCS captures against the CPU TAP.

    Verifies that ``tb_cpu_jtag_tdo`` is resolvable and the captured IDCODE
    matches ``EXPECTED_CPU_TAP_IDCODE`` = 0x10CA0555, the composition of the
    JEP106 straps in ``tb_top.sv`` (mfr=0x2AA, part=0x0CA0, version=0x1).
    Also reads the DTMCS register (IR=0x10) to prove IR/DR access beyond the
    default post-reset IDCODE latch. Every DTMCS bit except the advisory
    ``idle`` hint is asserted against an expectation sourced outside the DUT
    (v0.13.2 field layout + the TB's own DMI scan width), and the evidence
    token is emitted only after those asserts pass.

    Returns the number of ``tb_cpu_jtag_tck`` rising edges measured while the
    scans ran, and asserts it against :data:`MIN_CPU_JTAG_TCK_EDGES` so the scan
    activity itself is floored rather than only the caller's CSR traffic.
    """
    dut = cocotb.top
    tap = _get_tap()
    # Count TCK at the pin across BOTH scans (see MIN_CPU_JTAG_TCK_EDGES).
    tck_counter = _TckEdgeCounter(dut.tb_cpu_jtag_tck).start()
    await tap.reset_tap()
    # ``check=False``: read_idcode() enforces the IEEE 1149.1 plausibility rules
    # (not 0/all-ones, bit[0] == 1); the exact 32-bit comparison against
    # EXPECTED_CPU_TAP_IDCODE is made once, here ([NO-DUMMY-DEAD-CODE]).
    idcode = await tap.read_idcode(check=False)
    assert dut.tb_cpu_jtag_tdo.value.is_resolvable, "CPU JTAG TDO is not resolvable"
    assert idcode == EXPECTED_CPU_TAP_IDCODE, (
        f"CPU JTAG IDCODE=0x{idcode:08X} != expected 0x{EXPECTED_CPU_TAP_IDCODE:08X}"
    )
    cocotb.log.info(
        "CHK-CPU-JTAG-IDCODE: captured IDCODE=0x%08X == expected 0x%08X "
        "(full 32-bit match; tb_cpu_jtag_tdo resolvability is also asserted but "
        "is not DUT-sensitive evidence on a 2-state Verilator build)",
        idcode,
        EXPECTED_CPU_TAP_IDCODE,
    )

    dtmcs = await tap.read_dtmcs()
    version = dtmcs & 0xF
    abits = (dtmcs >> 4) & 0x3F
    dmistat = (dtmcs >> 10) & 0x3
    idle = (dtmcs >> 12) & 0x7
    reserved_hi = dtmcs >> DTMCS_RESERVED_HI_SHIFT
    assert version == DTMCS_VERSION_0_13, (
        f"CPU JTAG DTMCS version=0x{version:X} != 0x{DTMCS_VERSION_0_13:X} "
        f"(expected RISC-V Debug Spec 0.13); full DTMCS=0x{dtmcs:08X}"
    )
    assert abits == EXPECTED_DTMCS_ABITS, (
        f"CPU JTAG DTMCS abits={abits} != {EXPECTED_DTMCS_ABITS} required by the "
        f"TB DMI scan width ({_DMI_DR_WIDTH} bits = abits+34); every DMI access "
        f"this VIP issues would be misaligned; full DTMCS=0x{dtmcs:08X}"
    )
    assert dmistat == DTMCS_DMISTAT_NO_ERROR, (
        f"CPU JTAG DTMCS dmistat={dmistat} != {DTMCS_DMISTAT_NO_ERROR} after TAP "
        f"reset with no DMI operation issued; full DTMCS=0x{dtmcs:08X}"
    )
    assert reserved_hi == 0, (
        f"CPU JTAG DTMCS[31:{DTMCS_RESERVED_HI_SHIFT}]=0x{reserved_hi:X} != 0 "
        f"(reserved + W1-only dmireset/dmihardreset must read 0); "
        f"full DTMCS=0x{dtmcs:08X}"
    )
    cocotb.log.info(
        "CHK-CPU-JTAG-DTMCS: DTMCS=0x%08X version=0x%X==0x%X abits=%d==%d "
        "dmistat=%d==%d reserved[31:%d]=0 (idle=%d advisory hint, not asserted)",
        dtmcs,
        version,
        DTMCS_VERSION_0_13,
        abits,
        EXPECTED_DTMCS_ABITS,
        dmistat,
        DTMCS_DMISTAT_NO_ERROR,
        DTMCS_RESERVED_HI_SHIFT,
        idle,
    )

    tck_edges = tck_counter.stop()
    assert tck_edges >= MIN_CPU_JTAG_TCK_EDGES, (
        f"CPU JTAG scan activity floor: only {tck_edges} tb_cpu_jtag_tck rising "
        f"edge(s) measured across the TAP reset + IDCODE + DTMCS scans, below "
        f"the {MIN_CPU_JTAG_TCK_EDGES}-cycle payload-bit minimum "
        f"(2 x (IR {_CPU_TAP_IR_WIDTH} + DR 32)). The captured values compared "
        f"clean, so the TAP driver returned data without shifting it out of the "
        f"DUT -- treat the IDCODE/DTMCS evidence above as void"
    )
    cocotb.log.info(
        "CHK-CPU-JTAG-SCAN-ACTIVITY: %d tb_cpu_jtag_tck rising edges measured "
        "at the pin across the TAP reset + IDCODE + DTMCS scans >= floor %d "
        "(2 x (IR %d + DR 32) payload bits; reset/navigation/idle cycles "
        "deliberately excluded from the floor)",
        tck_edges,
        MIN_CPU_JTAG_TCK_EDGES,
        _CPU_TAP_IR_WIDTH,
    )
    return tck_edges


async def check_cpu_jtag_idcode_and_bypass() -> int:
    """Capture IDCODE then load BYPASS; return IDCODE for downstream checks."""
    tap = _get_tap()
    await tap.reset_tap()
    idcode = await tap.read_idcode(check=True)
    await tap.bypass()
    return idcode


__all__ = [
    "EXPECTED_CPU_TAP_IDCODE",
    "MIN_CPU_JTAG_TCK_EDGES",
    "SmcJtagTap",
    "SmcJtagTapError",
    "check_cpu_jtag_pin_vip",
    "check_cpu_jtag_idcode_and_bypass",
]
