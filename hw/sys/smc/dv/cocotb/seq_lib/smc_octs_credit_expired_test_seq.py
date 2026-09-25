# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The OCTS timer's CREDIT_EXPIRED register as a secondary that stops receiving credits.

`system_timer_octs.rdl` describes `CREDIT_EXPIRED.MAX_CYCLES_EXPIRED` as the
maximum number of clock cycles since a count credit expired, on a secondary
only: a secondary that has not received a credit pulse in a while shows a high
value. "To reset the value of this register, write anything to it." No leaf
had written it; the external-stall leaf only reads it.

The timer is strapped SECONDARY and given a sync and two credits, as
`smc_octs_dual_sync_test` does, and then no more credits. The register has to
grow while the credits stay away. One late credit restarts the live count
while the register keeps its maximum, and a write then has to bring it back
below that maximum.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_octs_dual_sync_test_seq import (
    _OCTS_CREDIT_VAL,
    _OCTS_CTRL,
    _OCTS_CTRL_VAL,
    _OCTS_PRESET_HI,
    _OCTS_PRESET_LO,
    _OCTS_PRESET_VAL,
    _OCTS_PULSE_WIDTH,
    _OCTS_STATUS,
    _OCTS_STATUS_MODE,
    _OCTS_TIMER_GPIO_ENABLE,
)
from .smc_octs_sync_bfm import drive_secondary_sync_then_credits

CREDIT_EXPIRED = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_CREDIT_EXPIRED_BASE_ADDR")
#: How long the credits stay away between the two samples, in SMC clocks: many
#: credit periods.
STARVE_CYCLES = 40 * _OCTS_CREDIT_VAL


class smc_octs_credit_expired_test_seq(SmcCsrSeq):
    """Starve a secondary of credits, watch CREDIT_EXPIRED grow, and reset it by a write."""

    async def body(self) -> None:
        dut = cocotb.top
        clk = dut.clk_smc_i
        dut.tb_chiplet_is_primary.value = 0
        dut.tb_octs_sync_load_ext.value = 0
        dut.tb_octs_cnt_credit_ext.value = 0
        await ClockCycles(clk, 8)
        await self.csr_write("OCTS_CTRL", _OCTS_CTRL, _OCTS_CTRL_VAL)
        await self.csr_write("OCTS_GPIO_ENABLE", _OCTS_TIMER_GPIO_ENABLE, 1)
        await self.csr_write("OCTS_PRESET_LO", _OCTS_PRESET_LO, _OCTS_PRESET_VAL)
        await self.csr_write("OCTS_PRESET_HI", _OCTS_PRESET_HI, 0)
        status = await self.csr_read("OCTS_STATUS", _OCTS_STATUS)
        assert status & _OCTS_STATUS_MODE, f"STATUS.MODE is not SECONDARY (0x{status:08x})"

        await drive_secondary_sync_then_credits(
            dut,
            clk,
            pulse_width=max(4, _OCTS_PULSE_WIDTH + 2),
            num_credits=2,
            credit_gap_cycles=_OCTS_CREDIT_VAL + 4,
        )
        await ClockCycles(clk, STARVE_CYCLES)
        early = await self.csr_read("EXPIRED_EARLY", CREDIT_EXPIRED)
        await ClockCycles(clk, STARVE_CYCLES)
        late = await self.csr_read("EXPIRED_LATE", CREDIT_EXPIRED)
        assert 0 < early < late, (
            f"CREDIT_EXPIRED read 0x{early:x} then 0x{late:x} while no credit arrived; a "
            f"starved secondary's count grows"
        )
        # One more credit restarts the live count; the register keeps its maximum.
        await drive_secondary_sync_then_credits(
            dut,
            clk,
            pulse_width=max(4, _OCTS_PULSE_WIDTH + 2),
            num_credits=1,
            credit_gap_cycles=_OCTS_CREDIT_VAL + 4,
        )
        held = await self.csr_read("EXPIRED_HELD", CREDIT_EXPIRED)
        assert held >= late, (
            f"CREDIT_EXPIRED dropped from 0x{late:x} to 0x{held:x} when a credit arrived; it "
            f"holds the maximum until written"
        )
        await self.csr_write("EXPIRED_RESET", CREDIT_EXPIRED, 0xFFFF_FFFF)
        after = await self.csr_read("EXPIRED_AFTER", CREDIT_EXPIRED)
        assert after < late, (
            f"CREDIT_EXPIRED read 0x{after:x} after the write, not below the 0x{late:x} maximum "
            f"it held; a write resets it"
        )
        dut.tb_chiplet_is_primary.value = 1
        await ClockCycles(clk, 8)
        cocotb.log.info(
            "CHK-OCTS-CREDIT-EXPIRED: on a SECONDARY starved of credits CREDIT_EXPIRED grew "
            "from 0x%x to 0x%x and held 0x%x after a late credit restarted the count; a write "
            "then brought it back to 0x%x",
            early,
            late,
            held,
            after,
        )
