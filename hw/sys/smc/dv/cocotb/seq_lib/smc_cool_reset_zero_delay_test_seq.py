# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""An FLR cool reset with no pre-reset delay programmed.

`reset_unit.rdl` splits the FLR cool into two programmable phases:
`ISOLATE_REQ_FLR_COUNTER_VALUE` is "number of cycles post `cfg_flr_pf_active`
assertion is waited until `cool_reset_n` is asserted", and
`ISOLATE_REQ_FLR_RESET_COUNTER_VALUE` is how long it is held, with the note
that "the cool reset flow requires this value to be greater than 0; a value of
0 will prevent initiation, regardless of `ISOLATE_REQ_FLR_COUNTER_VALUE`'s
value".

So the hold counter alone decides whether a cool happens, and the pre-delay
only decides when. `smc_cool_reset_from_pcie_test` always programs a non-zero
pre-delay, so the case this sequence drives -- pre-delay 0 with a non-zero hold
-- has never been asked of the reset unit.

The two legs are a pair, and the first is the live control for the second: with
both counters at their reset 0 the FLR request latches but no cool may follow,
and with the same pre-delay of 0 and a non-zero hold the cool has to follow.
A reset unit that refused to start without a pre-delay fails the second leg
while passing the first.

The cool is real, so the sequence does what `smc_cool_reset_from_pcie_test`
does around it: the isolate-request pad is held low throughout so the FLR path
is the only isolation source, `cfg_flr_pf_active_i` is dropped before the
recovery wait so its rising edge cannot restart the flow, the warm reset is
waited for before any further CSR access, and the latched request is cleared at
the end. A warm-domain scratch register written before the cool has to read 0
after it, which is the DUT-side evidence that a cool -- not merely a pin
wiggle -- went through.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import reset_unit_u32, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_isolate_pin_utils import await_skip_mem_repair, drive_isolate_pin

SMC_REG = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_SMC_REG_BASE_ADDR")
FLR_DELAY = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_COUNTER_VALUE_BASE_ADDR")
FLR_HOLD = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_RESET_COUNTER_VALUE_BASE_ADDR")
SCRATCH_COLD_WARM_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR")

SMC_BIT = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_SMC_REG__ISOLATE_REQ_SMC_REG_bm")

# The pre-delay this sequence is about. 0 is the value the FSM has never been
# given together with a hold that lets the flow start.
_DELAY = 0
# Hold long enough to be observed on the reference clock and short enough that
# the recovery below is not a wait for nothing.
_HOLD = 0x10
_PIN_BOUND = 64
# Reference-clock edges the counter values are given to cross into the
# reference-clock domain before the FLR request is raised.
_CDC_REF = 64
# With the pre-delay at 0 the only thing between the request and the cool is
# that same synchroniser, so the assertion bound is the CDC allowance rather
# than a programmed count: a reset unit that waited a programmed number of
# cycles anyway runs past it and fails.
_COOL_ASSERT_BOUND = _CDC_REF
_COOL_RELEASE_BOUND = _HOLD + 128
# Reference-clock edges allowed to pass with both counters at 0 before the deny
# leg is satisfied. A cool inside this window fails it.
_NO_COOL_BOUND = 64
_RECOVERY_REF = 50_000
_WARM_PAT = 0xA5A5_5A5A


class smc_cool_reset_zero_delay_test_seq(SmcCsrSeq):
    """FLR with the pre-reset delay at 0: no cool without a hold, cool with one."""

    def __init__(self, name: str = "smc_cool_reset_zero_delay_test_seq") -> None:
        super().__init__(name)
        self.deny_ok = False
        self.cool_ok = False
        #: Reference-clock edges from the FLR request to the cool assertion.
        self.assert_edges = -1
        #: Reference-clock edges the cool was held for.
        self.hold_edges = -1

    def _int(self, pin) -> int:
        if not pin.value.is_resolvable:
            raise AssertionError(f"X/Z on pin: {pin.value}")
        return int(pin.value)

    async def _await_cool(self, dut, want: int, bound: int, label: str) -> int:
        last = None
        for edge in range(1, bound + 1):
            await RisingEdge(dut.clk_ref_i)
            last = self._int(dut.tb_rst_cool_from_flr) & 1
            if last == want:
                return edge
        raise AssertionError(
            f"{label}: rst_cool_from_flr stuck at {last}, want {want}, after {bound} "
            f"clk_ref_i edges with FLR_COUNTER_VALUE=0x{_DELAY:x} and "
            f"FLR_RESET_COUNTER_VALUE=0x{_HOLD:x}"
        )

    async def _await_smc_bit(self, want: int, bound: int, label: str) -> int:
        last = 0
        for _ in range(bound):
            last = await self.csr_read(label, SMC_REG)
            if (last & SMC_BIT) == want:
                return last
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(f"{label}: SMC_REG=0x{last:x} want bit={want}")

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        assert hasattr(dut, "tb_cfg_flr_pf_active"), "tb_cfg_flr_pf_active missing"
        dut.tb_cfg_flr_pf_active.value = 0
        dut.rst_cool_ni.value = 1
        # The pin isolation source is quiet for the whole sequence, so every
        # observation below belongs to the FLR path.
        drive_isolate_pin(dut, 0)
        await await_skip_mem_repair(dut, 0, "isolate pin low, no FLR")

        await self.csr_read("SMC_REG_IDLE", SMC_REG, expected=0)
        await self.csr_read("FLR_DELAY_RESET", FLR_DELAY, expected=0)
        await self.csr_read("FLR_HOLD_RESET", FLR_HOLD, expected=0)
        assert (self._int(dut.tb_rst_cool_from_flr) & 1) == 1, (
            "rst_cool_from_flr is already asserted before this sequence signalled an FLR"
        )

        # Deny leg: hold at its reset 0. The request has to latch and no cool
        # may follow, whatever the pre-delay is.
        dut.tb_cfg_flr_pf_active.value = 1
        latched = await self._await_smc_bit(SMC_BIT, _PIN_BOUND, "SMC_REG_HOLD_ZERO")
        for _ in range(_NO_COOL_BOUND):
            await RisingEdge(dut.clk_ref_i)
            assert (self._int(dut.tb_rst_cool_from_flr) & 1) == 1, (
                "a cool reset started with FLR_RESET_COUNTER_VALUE at 0, which the RDL "
                "says prevents initiation regardless of FLR_COUNTER_VALUE"
            )
        self.deny_ok = True
        cocotb.log.info(
            "CHK-FLR-ZERO-DELAY-DENY: the FLR request latched (ISOLATE_REQ_SMC_REG=0x%x) "
            "with both counters at their reset 0, and no cool followed within %d clk_ref_i "
            "edges, which is the RDL's 'a value of 0 will prevent initiation' for the hold "
            "counter",
            latched,
            _NO_COOL_BOUND,
        )

        dut.tb_cfg_flr_pf_active.value = 0
        await self.csr_write("SMC_REG_CLR", SMC_REG, 0)
        await self._await_smc_bit(0, _PIN_BOUND, "SMC_REG_CLR_RB")

        # Allow leg: the same pre-delay of 0, now with a hold that lets the
        # flow start.
        await self.csr_write("FLR_DELAY_ZERO", FLR_DELAY, _DELAY)
        await self.csr_read("FLR_DELAY_ZERO_RB", FLR_DELAY, expected=_DELAY)
        await self.csr_write("FLR_HOLD", FLR_HOLD, _HOLD)
        await self.csr_read("FLR_HOLD_RB", FLR_HOLD, expected=_HOLD)
        await self.csr_write("SCRATCH_PRE", SCRATCH_COLD_WARM_0, _WARM_PAT)
        await self.csr_read("SCRATCH_PRE_RB", SCRATCH_COLD_WARM_0, expected=_WARM_PAT)
        for _ in range(_CDC_REF):
            await RisingEdge(dut.clk_ref_i)

        dut.tb_cfg_flr_pf_active.value = 1
        self.assert_edges = await self._await_cool(dut, 0, _COOL_ASSERT_BOUND, "COOL_ASSERT")
        self.hold_edges = await self._await_cool(dut, 1, _COOL_RELEASE_BOUND, "COOL_RELEASE")
        self.cool_ok = True

        dut.tb_cfg_flr_pf_active.value = 0
        last_warm = None
        for _ in range(_RECOVERY_REF):
            await RisingEdge(dut.clk_smc_i)
            last_warm = self._int(dut.tb_rst_warm_smc_clk_n) & 1
            if last_warm == 1:
                break
        else:
            raise AssertionError(f"warm smc clk still 0 after the FLR cool (last={last_warm})")

        warm = await self.csr_read("SCRATCH_POST", SCRATCH_COLD_WARM_0, expected=0)
        assert warm == 0, (
            f"the warm-domain scratch register still reads 0x{warm:x} after the cool; "
            f"0x{_WARM_PAT:x} was written into it beforehand, so no cool went through"
        )
        cocotb.log.info(
            "CHK-FLR-ZERO-DELAY-COOL: with FLR_COUNTER_VALUE=0x%x and "
            "FLR_RESET_COUNTER_VALUE=0x%x the cool asserted %d clk_ref_i edge(s) after the "
            "FLR request -- inside the %d-edge synchroniser allowance, so no programmed "
            "pre-delay was counted -- was held for %d more, and the warm-domain scratch "
            "register that carried 0x%x before it reads 0 afterwards, so a cool really ran",
            _DELAY,
            _HOLD,
            self.assert_edges,
            _COOL_ASSERT_BOUND,
            self.hold_edges,
            _WARM_PAT,
        )

        post = await self.csr_read("SMC_REG_POST", SMC_REG)
        assert post & SMC_BIT, f"ISOLATE_REQ_SMC_REG dropped across the cool: 0x{post:x}"
        await self.csr_write("SMC_REG_SW_CLR", SMC_REG, 0)
        await self._await_smc_bit(0, _PIN_BOUND, "SMC_REG_SW_CLR_RB")
        await self.csr_write("FLR_HOLD_CLR", FLR_HOLD, 0)
        await self.csr_read("FLR_HOLD_CLR_RB", FLR_HOLD, expected=0)
        drive_isolate_pin(dut, None)
