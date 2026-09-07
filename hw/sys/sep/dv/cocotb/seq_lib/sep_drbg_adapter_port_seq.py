# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Port-level AW/W/AR arbitration on drbg_axil64_lane_adapter.

The fabric-driven leaves (`sep_drbg_axil_concurrent_*`) reach the DUT's own
lane adapters, but only one channel ordering: `CHK-CONCURRENT-CAL` measures
AW and W leaving the master in the SAME cycle and arriving at the adapter port
one cycle apart, and the order survives whatever the master presents, so the
crossbar re-serializes every write to AW-then-W. A same-cycle AW/W/AR
presentation and a W-before-AW presentation are therefore not producible at a
DUT adapter port from the fabric side.

This drives a TB-owned second instance of the same module (`u_tbadp_vehicle`
in tb_top) directly, with no fabric in front of it, so every legal ordering is
presentable to the cycle. What it proves is the MODULE's arbitration contract;
the SEP integration half stays with the fabric-driven leaves.

Because the vehicle has its own reset, a wedged cell is cleared without
resetting the DUT, so all three orderings run in one leaf and each verdict is
independent.

Every ordering here is legal AXI: AW, W and AR are independent channels
(AMBA IHI 0022 A3.3), and a master may not deassert a VALID before its
handshake completes (A3.2.1), which is what makes a stall unrecoverable.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

# Bit positions in tbadp_chan_o.
AW_VALID, W_VALID, AR_VALID, AW_READY, W_READY, AR_READY = (1 << i for i in range(6))
VALID_BITS = AW_VALID | W_VALID | AR_VALID
READY_BITS = AW_READY | W_READY | AR_READY

# Cycles a cell waits for both accesses to retire. The adapter forwards to an
# always-ready responder, so a healthy cell retires in a handful of cycles;
# the failure this bounds is unbounded by construction.
RETIRE_TIMEOUT_CYCLES = 200

# (name, aw_offset, w_offset, ar_offset) in cycles from the cell's start.
# These are ABSOLUTE offsets, driven pin-level, so the presentation is exactly
# what is asked for -- the point of driving the port instead of the fabric.
#
# A non-zero gap gives the leading channel time to handshake first, which is
# what makes a partially-committed cell different from a same-cycle one.
PORT_ORDERS: tuple[tuple[str, int, int, int], ...] = (
    ("all-same-cycle", 0, 0, 0),
    ("aw-then-ar", 0, 4, 2),
    ("w-then-ar", 4, 0, 2),
)
ORDER_NAMES = tuple(name for name, *_o in PORT_ORDERS)

# The access must be one the adapter SUPPORTS, or it never forwards anything.
# write_supported() in drbg_axil64_lane_adapter.sv requires addr[1:0]==0 and
# then strb==8'h0F for addr[2]==0, or strb==8'hF0 for addr[2]==1. An
# unsupported write is answered SLVERR straight out of StIdle with no
# downstream request at all -- and it retires just as promptly as a real one,
# so a control built on an unsupported access would "pass" while proving only
# that the reject path works. addr[2]==0 paired with the low lane strobe.
WR_ADDR = 0x0000_0000
WR_STRB = 0x0F
# read_supported() needs only addr[1:0]==0.
RD_ADDR = 0x0000_0008
WR_DATA = 0xDEAD_BEEF_CAFE_0001

RESP_OKAY = 0


class AdapterPortVehicle:
    """Drives one ordering at the vehicle port and reports what happened."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top

    def _chan(self) -> int | None:
        try:
            return int(self.dut.tbadp_chan_o.value)
        except ValueError:
            return None

    async def reset(self) -> None:
        """Clear the vehicle, including a wedge left by a previous cell."""
        d = self.dut
        d.tbadp_rst_ni_i.value = 0
        d.tbadp_aw_valid_i.value = 0
        d.tbadp_w_valid_i.value = 0
        d.tbadp_ar_valid_i.value = 0
        d.tbadp_aw_addr_i.value = 0
        d.tbadp_ar_addr_i.value = 0
        d.tbadp_w_data_i.value = 0
        d.tbadp_w_strb_i.value = 0
        # Response channels always ready: the contract under test is request
        # arbitration, so response backpressure must not be able to stall it.
        d.tbadp_b_ready_i.value = 1
        d.tbadp_r_ready_i.value = 1
        await ClockCycles(d.clk_i, 5)
        d.tbadp_rst_ni_i.value = 1
        await ClockCycles(d.clk_i, 2)

    async def run_control(self) -> dict:
        """A lone write, then a lone read. Both MUST retire.

        Without this the stall cells prove nothing: a vehicle that cannot
        complete any access at all would report every ordering as stalled and
        look like the defect. The control is what makes the stalls attributable
        to the channel overlap rather than to this driver or to the axil32
        responder behind the adapter.
        """
        d = self.dut
        out: dict = {}

        # Lone write: AW and W together, no AR. Nothing gates the write side
        # when ar_valid is low, so this must complete.
        await self.reset()
        obs = await self.run_order("control-write", 0, 0, None)
        out["write"] = obs

        # Lone read: AR only. Nothing gates the read side when aw_valid and
        # w_valid are low.
        await self.reset()
        obs = await self.run_order("control-read", None, None, 0)
        out["read"] = obs
        return out

    async def run_order(
        self,
        order: str,
        aw_off: int | None,
        w_off: int | None,
        ar_off: int | None,
    ) -> dict:
        """Present one ordering. Returns the observation, never raises.

        A None offset means that channel is never presented, which is how the
        control cells drive one side on its own.
        """
        d = self.dut
        await self.reset()

        obs = {
            "order": order,
            "valid": {"aw": None, "w": None, "ar": None},
            "hs": {"aw": None, "w": None, "ar": None},
            "b_valid": None,
            "r_valid": None,
            "b_resp": None,
            "r_resp": None,
            "max_stall_run": 0,
            "presented": None,
        }
        stall_run = 0
        aw_done = w_done = ar_done = False
        b_seen = r_seen = False

        for cyc in range(RETIRE_TIMEOUT_CYCLES):
            # Assert each channel at its offset and HOLD it until its own
            # handshake: AXI forbids withdrawing a VALID, and withdrawing one
            # would also hide the stall this cell is looking for.
            if aw_off is not None and cyc >= aw_off and not aw_done:
                d.tbadp_aw_valid_i.value = 1
                d.tbadp_aw_addr_i.value = WR_ADDR
            if w_off is not None and cyc >= w_off and not w_done:
                d.tbadp_w_valid_i.value = 1
                d.tbadp_w_data_i.value = WR_DATA
                d.tbadp_w_strb_i.value = WR_STRB
            if ar_off is not None and cyc >= ar_off and not ar_done:
                d.tbadp_ar_valid_i.value = 1
                d.tbadp_ar_addr_i.value = RD_ADDR

            await RisingEdge(d.clk_i)
            chan = self._chan()
            if chan is None:
                continue

            for name, vbit, rbit in (
                ("aw", AW_VALID, AW_READY),
                ("w", W_VALID, W_READY),
                ("ar", AR_VALID, AR_READY),
            ):
                if chan & vbit and obs["valid"][name] is None:
                    obs["valid"][name] = cyc
                if chan & vbit and chan & rbit and obs["hs"][name] is None:
                    obs["hs"][name] = cyc

            if obs["hs"]["aw"] is not None and not aw_done:
                aw_done = True
                d.tbadp_aw_valid_i.value = 0
            if obs["hs"]["w"] is not None and not w_done:
                w_done = True
                d.tbadp_w_valid_i.value = 0
            if obs["hs"]["ar"] is not None and not ar_done:
                ar_done = True
                d.tbadp_ar_valid_i.value = 0

            up = chan & VALID_BITS
            if up and not (chan & READY_BITS):
                stall_run += 1
                obs["max_stall_run"] = max(obs["max_stall_run"], stall_run)
            else:
                stall_run = 0

            if int(self.dut.tbadp_b_valid_o.value) and obs["b_valid"] is None:
                obs["b_valid"] = cyc
                obs["b_resp"] = int(self.dut.tbadp_b_resp_o.value)
                b_seen = True
            if int(self.dut.tbadp_r_valid_o.value) and obs["r_valid"] is None:
                obs["r_valid"] = cyc
                obs["r_resp"] = int(self.dut.tbadp_r_resp_o.value)
                r_seen = True
            want_b = aw_off is not None and w_off is not None
            want_r = ar_off is not None
            if (b_seen or not want_b) and (r_seen or not want_r):
                break

        obs["presented"] = self._classify(obs["valid"])
        obs["retired"] = (b_seen or aw_off is None or w_off is None) and (
            r_seen or ar_off is None
        )
        return obs

    @staticmethod
    def _classify(valid: dict) -> str | None:
        aw, w, ar = valid["aw"], valid["w"], valid["ar"]
        if aw is None or w is None or ar is None:
            return None
        if aw == w == ar:
            return "all-same-cycle"
        if aw <= ar <= w:
            return "aw-then-ar"
        if w <= ar <= aw:
            return "w-then-ar"
        return f"other(aw={aw},w={w},ar={ar})"

    @staticmethod
    def summary(obs: dict) -> str:
        v, h = obs["valid"], obs["hs"]
        return (
            f"valid(aw={v['aw']},w={v['w']},ar={v['ar']}) "
            f"hs(aw={h['aw']},w={h['w']},ar={h['ar']}) "
            f"b_valid={obs['b_valid']}(resp={obs['b_resp']}) "
            f"r_valid={obs['r_valid']}(resp={obs['r_resp']}) "
            f"max_all_ready_low={obs['max_stall_run']}cyc"
        )
