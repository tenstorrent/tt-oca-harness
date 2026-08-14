# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C Hot-Join  (Test Plan #35)

SKIPPED: hot-join is not implemented in the vendored i3c-core, so no result from
this test could be interpreted.

RTL evidence (vendor/chipsalliance/i3c-core/upstream/src):
  - ctrl/controller_standby_i3c.sv:284-289 -- under the comment "Drive all unused
    inputs here", `hotjoin_done` is tied off: `assign hotjoin_done = 1'b0;`
  - ctrl/i3c_target_fsm.sv:852-855 -- state `DoHotJoin` only leaves on
    `is_hotjoin_done_i`, which is that constant 0. Entering it is terminal.
  - No RTL anywhere consumes TTI_CONTROL.hj_en; the field exists only in the
    generated CSR (csr/I3CCSR.sv:2991) and is driven by the ENEC/DISEC HJ CCCs
    (hci/tti.sv:261-262), but nothing acts on it.

The previous version of this test never drove a hot-join request at all, yet
reported PASS. It would have passed identically against RTL that never implements
hot-join, which is exactly the situation above. It is marked skip rather than left
green so the regression cannot bank a PASS for a feature that does not exist.

Note: hj_en is not the obstacle -- TTI_CONTROL's reset value is 0x1400, so hj_en
(bit 10) is already set out of reset. The obstacle is the RTL tie-off above.

When hot-join support lands in the core, this test must:
  1. program the target's TTI_CONTROL.hj_en by symbol from the generated header,
  2. drive a real hot-join request (target with no dynamic address, hj_en set),
  3. assert the controller latches PIO_INTR_STATUS.ibi_status_thld_stat, and
  4. assert the IBI Status Descriptor identifies it as a hot-join, per HCI v1.2
     section 8.6.3 rule 7615ff:
       - IBI_ID bits[15:9] == 7'h02   (the reserved Hot-Join Address)
       - IBI_ID bit[8]     == 1'b0    (RnW = 0; this is what distinguishes a
                                       hot-join / controller-role request from a
                                       regular IBI, which uses RnW = 1)
       - IBI_STS           == 1'b0    (ACKed; 1'b1 means the HC NACKed it)
       - STATUS_TYPE       == 3'b000  (REGULAR_IBI)
       - ERROR, TS, LAST_STATUS, DATA_LENGTH all 0 (a hot-join carries no payload)

     NOTE: there is deliberately no "HotJoin" STATUS_TYPE encoding -- HCI 7615
     requires hot-join to report STATUS_TYPE = REGULAR_IBI, so asserting a distinct
     status_type value would be asserting a field value that does not exist. An
     earlier revision of this docstring said exactly that and was wrong.
"""
import cocotb


@cocotb.test(
    skip=True,
    timeout_time=2000,
    timeout_unit='us',
)
async def test_hotjoin(dut):
    """SKIPPED: hot-join is tied off in the vendored core (see module docstring)."""
    raise NotImplementedError(
        "hot-join is not implemented in the vendored i3c-core: "
        "controller_standby_i3c.sv ties hotjoin_done to 1'b0 and i3c_target_fsm.sv "
        "DoHotJoin only exits on that signal, so a hot-join request can never complete"
    )
