# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C IBI when Disabled

With target IBI generation NOT enabled, a real IBI attempt must not be serviced:
the controller's PIO_INTR_STATUS.ibi_status_thld_stat has to stay clear.

The test uses two cases so the negative result is checked against a positive control:

  1. Negative case -- target IBI mode is disabled, an IBI descriptor is queued
     anyway, and the controller must NOT latch an IBI over the observation window.
  2. Positive control -- target IBI mode is then enabled and the IBI IS serviced.
     Without this leg a permanently dead IBI path would produce the same clear
     status as correctly-suppressed IBI generation.

TTI_CONTROL.ibi_en resets asserted, so the test explicitly clears and verifies
the bit before the negative case.
"""

import os
import sys

import cocotb
from cocotb.triggers import ClockCycles
from env.i3c_api import PioIntrStatus
from env.i3c_test_base import bring_up_and_assign, make_env

# Authoritative register map (generated) — no hand-copied offsets.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../regs/gen/py"))
import oca_i3c_wrap_reg as _csr  # noqa: E402

OBSERVE_CYCLES = 2000  # window the disabled target gets to (not) transmit
MDB = 0xA5


@cocotb.test(timeout_time=2000, timeout_unit="us")
async def test_ibi_nack_disabled(dut):
    tb, helper, ctrl, tgt = await make_env(dut)
    await bring_up_and_assign(ctrl, tgt)

    # Enable controller IBI reception before explicitly disabling target generation.
    await ctrl.enable_ibi_interrupts(ibi_threshold=1)

    # Run a normal transfer to confirm the bus is still healthy
    data = [0xCA, 0xFE, 0xBA, 0xBE]
    ok, resp, rx = await ctrl.private_write(data, tgt, dat_idx=0)
    assert ok, f"transfer failed resp=0x{resp:08X}"
    assert rx == data, "data mismatch"

    # --- Negative leg: request an IBI with target IBI generation disabled ---
    # ibi_en is SET at reset (TTI_CONTROL default 0x1400), so it has to be cleared
    # explicitly; the read-back is asserted so the leg cannot run with IBI enabled.
    ibi_en = await tgt.disable_ibi_mode()
    assert ibi_en == 0, (
        f"TTI_CONTROL.ibi_en read back as {ibi_en} after disable_ibi_mode(); the "
        f"disabled-IBI premise of this test does not hold"
    )

    payload = [0x11, 0x22, 0x33, 0x44]
    assert await tgt.write_ibi(MDB, payload), (
        "queuing the IBI descriptor failed, so the disabled-IBI property was never "
        "actually requested"
    )
    tb.log.info(f"queued IBI mdb=0x{MDB:02X} with TTI_CONTROL.ibi_en verified 0 by read-back")

    await ClockCycles(dut.clk, OBSERVE_CYCLES)
    status = await helper.read_into(
        ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_PIO_INTR_STATUS_REG_ADDR, PioIntrStatus
    )
    tb.log.info(f"PIO_INTR_STATUS (IBI disabled) = 0x{status.val:08X}")
    assert not status.f.ibi_status_thld_stat, (
        f"spurious IBI latched with target IBI generation disabled: "
        f"0x{status.val:08X} (ibi_status_thld_stat set)"
    )

    # --- Positive control: same path, IBI enabled, must now be serviced ---
    # The DAT ibi_payload policy has to be programmed too, else the controller aborts
    # inbound IBIs (ibi_abort = ibi_reject | ~ibi_payload) and this control would
    # "prove" a live path was dead.
    ibi_payload_bit = await ctrl.configure_target_ibi(0, 0x10, 0x10)
    assert ibi_payload_bit, "DAT ibi_payload bit not set (GETBCR likely failed)"
    await tgt.enable_ibi_mode()
    assert await tgt.write_ibi(MDB, payload), "write_ibi failed on the positive control"

    # Either the descriptor queued above or this one may be the one serviced; the claim
    # is only that the path CAN deliver an IBI once enabled.
    ok, _reg = await ctrl.wait_ibi_received()
    assert ok, (
        "positive control failed: no IBI reached the controller even with "
        "TTI_CONTROL.ibi_en set, so the disabled-leg result above proves nothing"
    )
    tb.log.info("positive control: IBI serviced once enabled")

    tb.log.info("IBI-disabled test complete (negative leg + positive control)")
