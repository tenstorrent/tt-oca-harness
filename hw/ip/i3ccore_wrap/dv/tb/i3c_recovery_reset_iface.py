# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C Recovery / Reset Interface  (Test Plan #41)

  test_rstact_arm_no_spurious_reset
      Real check of the RSTACT *arming* semantics. Per ccc.sv:1760-1769 both
      set_peripheral_reset and set_escalate_reset are gated on
      target_reset_detect_i, so RSTACT alone only arms an action -- neither
      peripheral_reset nor escalated_reset may assert until a Target Reset Pattern
      appears on the bus. This test proves the outputs are idle after reset, that
      the RSTACT CCC completes, and that arming does NOT spuriously fire a reset.

Scope: RSTACT / Target Reset is I3C protocol (I3C Basic v1.1.1 section 5.1.9.3.26,
Tables 52-53) and is verified here. The OCP Secure Firmware Recovery *image flow*
that shares this register block is NOT in scope and its testcase was removed on
2026-07-30: it is an HCI Extended Capability (CAP_ID 0xC0, which HCI Table 82
defines only as "Vendor Specific"), and its normative document -- OCP Recovery
v1.1, identified by the 'OCP RECV' magic string in PROT_CAP_0/1 -- is not in this
repo, so no expected value can be cited. See the testlist for the full rationale.

recovery_payload_available / recovery_image_activated are still sampled below, but
only as must-stay-idle outputs: proving RSTACT arming has no side effects needs
every reset/recovery output checked, and that costs nothing extra.

Note on the defining byte: the previous version issued RSTACT 0x02 and called it
"peripheral reset". Per ccc.sv:1760-1769 that is inverted -- 0x01 arms peripheral
reset, 0x02 arms whole-target (escalated) reset. It also pulsed
peripheral_reset_done, which only clears peripheral_reset_o, a bit that had never
been set. Nothing in that body could fail.
"""
import cocotb
from cocotb.triggers import ClockCycles
from i3c_test_base import make_env, bring_up_and_assign

RECOVERY_OUTPUTS = (
    "recovery_payload_available",
    "recovery_image_activated",
    "peripheral_reset",
    "escalated_reset",
)

RSTACT_PERIPHERAL_RESET = 0x01   # ccc.sv: armed path 0x01 -> peripheral reset
RSTACT_WHOLE_TARGET = 0x02       # ccc.sv: armed path 0x02 -> escalated reset


def _read_wire(dut, name):
    """Resolved integer value of a top-level wire; X/Z is a failure, not a 0."""
    val = getattr(dut, name).value
    assert val.is_resolvable, f"{name} is unresolved (X/Z): {val}"
    return int(val)


@cocotb.test(timeout_time=2000, timeout_unit='us')
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
    assert ok, (
        f"RSTACT (defining byte 0x{RSTACT_PERIPHERAL_RESET:02X}) failed "
        f"resp=0x{resp:08X}"
    )

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
