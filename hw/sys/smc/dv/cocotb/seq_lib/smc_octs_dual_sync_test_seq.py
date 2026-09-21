# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""U4-5 OCTS dual-chiplet sync: SECONDARY inject then PRIMARY outbound.

The DUT PRIMARY drives OCTS sync/credit pads and the master BFM tracks the
SECONDARY side. This sequence:

  1. Strap SECONDARY, inject ordered sync then credit on pad2core[55/56],
     hard-gate COUNT / STATUS.MODE.
  2. Strap PRIMARY, TIMER_START, hard-gate rising edges on DUT pad observe.

Secondary-before-primary avoids RTL ExpectedCountValid_A when switching
modes with a live COUNT (primary count >> expected).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_octs_sync_bfm import (
    count_rising_edges,
    drive_secondary_sync_then_credits,
)

_OCTS_TIMER_START = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_START_BASE_ADDR")
_OCTS_CTRL = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_CTRL_BASE_ADDR")
_OCTS_STATUS = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_STATUS_BASE_ADDR")
_OCTS_PRESET_LO = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_PRESET_LO_BASE_ADDR")
_OCTS_PRESET_HI = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_PRESET_HI_BASE_ADDR")
_OCTS_COUNT_LO = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_COUNT_LO_BASE_ADDR")
_OCTS_COUNT_HI = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_COUNT_HI_BASE_ADDR")
_OCTS_TIMER_GPIO_ENABLE = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_GPIO_ENABLE_BASE_ADDR")

# CTRL: CREDIT_VAL=0x10, PULSE_WIDTH=0x02, STEP=0x01.
_OCTS_CTRL_VAL = 0x0001_0210
_OCTS_CREDIT_VAL = 0x10
_OCTS_PULSE_WIDTH = 0x02
_OCTS_PRESET_VAL = 0x1000
_OCTS_STATUS_MODE = 0x1
_OCTS_STATUS_RUNNING = 0x10
_OCTS_PRIMARY_WAIT = 256
# COUNT lands a few ticks past PRESET by the time the reload read returns.
_OCTS_RELOAD_SLACK = 0x100
# STEP=1, so the advance over the edge-count window is bounded by it.
_OCTS_MAX_ADVANCE = 4 * _OCTS_PRIMARY_WAIT


class smc_octs_dual_sync_test_seq(SmcCsrSeq):
    """OCTS dual-chiplet sync hard-gates (secondary inject + primary pads)."""

    async def _read_count(self) -> int:
        lo = await self.csr_read("OCTS_COUNT_LO", _OCTS_COUNT_LO)
        hi = await self.csr_read("OCTS_COUNT_HI", _OCTS_COUNT_HI)
        return (hi << 32) | lo

    async def body(self) -> None:
        dut = cocotb.top
        clk = dut.clk_smc_i

        assert hasattr(dut, "tb_chiplet_is_primary"), (
            "tb_chiplet_is_primary missing; rebuild after OCTS dual-sync TB lift"
        )
        assert hasattr(dut, "tb_octs_sync_load_ext"), (
            "tb_octs_sync_load_ext missing; rebuild after OCTS dual-sync TB lift"
        )

        # --- Phase B first: SECONDARY pad inject (sync before credit).
        dut.tb_chiplet_is_primary.value = 0
        dut.tb_octs_sync_load_ext.value = 0
        dut.tb_octs_cnt_credit_ext.value = 0
        await ClockCycles(clk, 8)

        await self.csr_write("OCTS_CTRL", _OCTS_CTRL, _OCTS_CTRL_VAL)
        await self.csr_write("OCTS_TIMER_GPIO_ENABLE", _OCTS_TIMER_GPIO_ENABLE, 1)
        await self.csr_write("OCTS_PRESET_LO", _OCTS_PRESET_LO, _OCTS_PRESET_VAL)
        await self.csr_write("OCTS_PRESET_HI", _OCTS_PRESET_HI, 0)

        status = await self.csr_read("OCTS_STATUS_MODE", _OCTS_STATUS)
        assert status & _OCTS_STATUS_MODE, (
            f"OCTS STATUS.MODE != SECONDARY after strap: STATUS=0x{status:08x}"
        )

        # Pulse wider than CTRL.PULSE_WIDTH so pad/CDC flops see a clean edge.
        await drive_secondary_sync_then_credits(
            dut,
            clk,
            pulse_width=max(4, _OCTS_PULSE_WIDTH + 2),
            num_credits=2,
            credit_gap_cycles=_OCTS_CREDIT_VAL + 4,
        )

        await ClockCycles(clk, 4)
        count_after = await self._read_count()
        status = await self.csr_read("OCTS_STATUS_RUNNING", _OCTS_STATUS)
        assert status & _OCTS_STATUS_RUNNING, (
            f"OCTS STATUS.RUNNING not set after secondary sync (STATUS=0x{status:08x})"
        )
        # After sync+credits: COUNT near PRESET + N*CREDIT_VAL (N=2).
        expected_lo = _OCTS_PRESET_VAL + _OCTS_CREDIT_VAL
        expected_hi = _OCTS_PRESET_VAL + 2 * _OCTS_CREDIT_VAL + 16
        assert expected_lo <= count_after <= expected_hi, (
            f"OCTS secondary COUNT out of range: got 0x{count_after:x}, "
            f"expected [{expected_lo:#x}, {expected_hi:#x}]"
        )
        cocotb.log.info(
            "OCTS secondary inject PASS: STATUS=0x%x COUNT=0x%x (preset=0x%x credit=0x%x)",
            status,
            count_after,
            _OCTS_PRESET_VAL,
            _OCTS_CREDIT_VAL,
        )

        # --- Phase A: PRIMARY outbound sync/credit pad edges.
        dut.tb_octs_sync_load_ext.value = 0
        dut.tb_octs_cnt_credit_ext.value = 0
        dut.tb_chiplet_is_primary.value = 1
        await ClockCycles(clk, 8)

        status = await self.csr_read("OCTS_STATUS_PRIMARY", _OCTS_STATUS)
        assert (status & _OCTS_STATUS_MODE) == 0, (
            f"OCTS STATUS.MODE != PRIMARY after strap: STATUS=0x{status:08x}"
        )

        await self.csr_write("OCTS_CTRL", _OCTS_CTRL, _OCTS_CTRL_VAL)
        await self.csr_write("OCTS_TIMER_GPIO_ENABLE", _OCTS_TIMER_GPIO_ENABLE, 1)
        await self.csr_write("OCTS_PRESET_LO", _OCTS_PRESET_LO, _OCTS_PRESET_VAL)
        await self.csr_write("OCTS_PRESET_HI", _OCTS_PRESET_HI, 0)

        edge_task_sync = cocotb.start_soon(
            count_rising_edges(dut.tb_octs_sync_load_from_dut, clk, _OCTS_PRIMARY_WAIT)
        )
        edge_task_credit = cocotb.start_soon(
            count_rising_edges(dut.tb_octs_cnt_credit_from_dut, clk, _OCTS_PRIMARY_WAIT)
        )
        # COUNT is already running above PRESET here, left there by the
        # secondary phase. TIMER_START reloads it, so the reload -- not the
        # absolute value -- is what this write can be shown to have caused.
        count_before_start = await self._read_count()
        await self.csr_write("OCTS_TIMER_START", _OCTS_TIMER_START, 1)
        count_reloaded = await self._read_count()

        sync_edges = await edge_task_sync
        credit_edges = await edge_task_credit
        assert sync_edges >= 1, f"OCTS primary pad55 sync_load edges={sync_edges}, need >= 1"
        assert credit_edges >= 2, f"OCTS primary pad56 cnt_credit edges={credit_edges}, need >= 2"

        count_pri = await self._read_count()
        # Anchored to values this run measured, not to the PRESET this sequence
        # programmed: COUNT enters this phase above PRESET, so an absolute
        # comparison against PRESET would hold with or without the TIMER_START
        # write.
        assert count_reloaded < count_before_start, (
            f"OCTS TIMER_START did not reload COUNT: 0x{count_before_start:x} -> "
            f"0x{count_reloaded:x} (a free-running counter only increases)"
        )
        assert count_reloaded - _OCTS_PRESET_VAL <= _OCTS_RELOAD_SLACK, (
            f"OCTS COUNT reloaded to 0x{count_reloaded:x}, not to PRESET "
            f"0x{_OCTS_PRESET_VAL:x} (+{_OCTS_RELOAD_SLACK} read latency)"
        )
        advance = count_pri - count_reloaded
        assert 1 <= advance <= _OCTS_MAX_ADVANCE, (
            f"OCTS COUNT advanced {advance} from 0x{count_reloaded:x} over "
            f"{_OCTS_PRIMARY_WAIT} clk_smc_i, expected 1..{_OCTS_MAX_ADVANCE}"
        )
        cocotb.log.info(
            "CHK-OCTS-DUAL-SYNC: SECONDARY strap: STATUS.MODE set, pad2core sync then "
            "%d credits gave STATUS.RUNNING and COUNT=0x%x within [0x%x, 0x%x]; PRIMARY "
            "strap: STATUS.MODE clear, %d sync_load and %d cnt_credit rising edges on "
            "the DUT pads over %d clk_smc_i, TIMER_START reloaded COUNT 0x%x -> 0x%x "
            "(PRESET 0x%x) and it advanced %d afterwards",
            2,
            count_after,
            expected_lo,
            expected_hi,
            sync_edges,
            credit_edges,
            _OCTS_PRIMARY_WAIT,
            count_before_start,
            count_reloaded,
            _OCTS_PRESET_VAL,
            advance,
        )
