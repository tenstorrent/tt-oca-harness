# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
 I3C Recovery / Reset Interface

  test_rstact_arm_no_spurious_reset
      RSTACT alone only arms an action. Neither peripheral_reset nor
      escalated_reset may assert until a Target Reset Pattern appears on the bus.

Scope: RSTACT / Target Reset is I3C protocol (I3C Basic v1.1.1 section 5.1.9.3.26,
Tables 52-53) and is verified here. OCP Secure Firmware Recovery image flow is
not in scope.

recovery_payload_available / recovery_image_activated are sampled as
must-stay-idle outputs because RSTACT arming must not affect reset/recovery
outputs.

RSTACT defining byte 0x01 arms peripheral reset; 0x02 arms whole-target
(escalated) reset.
"""

import cocotb
from cocotb.triggers import ClockCycles
from env.i3c_test_base import bring_up_and_assign, make_env

RECOVERY_OUTPUTS = (
    "recovery_payload_available",
    "recovery_image_activated",
    "peripheral_reset",
    "escalated_reset",
)

RSTACT_PERIPHERAL_RESET = 0x01  # Arms peripheral reset
RSTACT_WHOLE_TARGET = 0x02  # Arms whole-target reset


def _read_wire(dut, name):
    """Resolved integer value of a top-level wire; X/Z is a failure, not a 0."""
    val = getattr(dut, name).value
    assert val.is_resolvable, f"{name} is unresolved (X/Z): {val}"
    return int(val)


@cocotb.test(timeout_time=2000, timeout_unit="us")
async def test_rstact_arm_no_spurious_reset(dut):
    """RSTACT arms an action; with no Target Reset Pattern nothing may fire."""
    tb, helper, ctrl, tgt = await make_env(dut)
    await bring_up_and_assign(ctrl, tgt)

    # Every recovery/reset output must be idle out of reset.
    for name in RECOVERY_OUTPUTS:
        val = _read_wire(dut, name)
        tb.log.info(f"{name:28s} = {val}")
        assert val == 0, f"{name} = {val} after reset, expected 0"

    # Arm peripheral reset. rstact returns (success, resp) -- unpack, or `ok` is a
    # truthy tuple for every outcome including failure.
    ok, resp = await ctrl.rstact(RSTACT_PERIPHERAL_RESET, dat_idx=0)
    tb.log.info(f"RSTACT arm peripheral-reset ok={ok} resp=0x{resp:08X}")
    assert ok, f"RSTACT (defining byte 0x{RSTACT_PERIPHERAL_RESET:02X}) failed resp=0x{resp:08X}"

    # Arming is not triggering: no Target Reset Pattern was driven, so both reset
    # outputs must still be low.
    await ClockCycles(dut.clk, 200)
    for name in ("peripheral_reset", "escalated_reset"):
        val = _read_wire(dut, name)
        assert val == 0, (
            f"{name} = {val} after RSTACT arming alone; ccc.sv gates it on "
            f"target_reset_detect_i and no Target Reset Pattern was driven"
        )
    tb.log.info("RSTACT armed without asserting either reset output (as specified)")
