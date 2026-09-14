# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Packed jtag_reset_ctrl_i cool and SS0 warm override. Not DTP IC_RESET or SW SS_WARM_RESET_N."""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import (
    jtag_smc_reset_ctrl_bit,
    jtag_smc_reset_ctrl_width,
    reset_unit_u32,
    smc_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq

SS_WARM = smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_WARM_RESET_N_BASE_ADDR")
SCRATCH_COLD_WARM_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR")
SS_WARM_RESET = reset_unit_u32("RESET_UNIT__SS_WARM_RESET_N__RESET_N_N0_SCAN_reset")
_WARM_PAT = 0xA5A55A5A
_PIN_BOUND = 64
_RECOVERY = 50_000


def _pack(*, cool_ovrd=0, cool_val=0, ss0_warm_ovrd=0, ss0_warm_val=0) -> int:
    v = 0
    if cool_ovrd:
        v |= 1 << jtag_smc_reset_ctrl_bit("cool_reset_n_ovrd")
    if cool_val:
        v |= 1 << jtag_smc_reset_ctrl_bit("cool_reset_n_val")
    if ss0_warm_ovrd:
        v |= 1 << jtag_smc_reset_ctrl_bit("ss_warm_reset_n_ovrd", 0)
    if ss0_warm_val:
        v |= 1 << jtag_smc_reset_ctrl_bit("ss_warm_reset_n_val", 0)
    return v


class smc_jtag_reset_ctrl_test_seq(SmcCsrSeq):
    """JTAG reset_ctrl mux: cool ovrd then SS0 warm ovrd, not SW/FLR/pin-cool."""

    def __init__(self, name: str = "smc_jtag_reset_ctrl_test_seq") -> None:
        super().__init__(name)
        self.cool_ok = False
        self.ss0_ok = False

    def _bit(self, sig, name: str) -> int:
        if not sig.value.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {sig.value}")
        return int(sig.value) & 1

    async def _await_bit(self, sig, name: str, want: int, bound: int, label: str) -> None:
        last = -1
        for _ in range(bound):
            await RisingEdge(cocotb.top.clk_smc_i)
            last = self._bit(sig, name)
            if last == want:
                return
        raise AssertionError(f"{label}: {name} stuck {last} want {want}")

    def _sources_idle(self, dut) -> None:
        assert self._bit(dut.rst_cool_ni, "rst_cool_ni") == 1, (
            "rst_cool_ni dropped; JTAG cool ovrd would be aliased"
        )
        assert self._bit(dut.tb_cfg_flr_pf_active, "tb_cfg_flr_pf_active") == 0, (
            "cfg_flr_pf_active_i high; JTAG cool ovrd would be aliased"
        )

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        assert hasattr(dut, "tb_jtag_reset_ctrl"), "tb_jtag_reset_ctrl missing"
        assert hasattr(dut, "tb_rst_cool_from_flr"), "tb_rst_cool_from_flr missing"
        assert hasattr(dut, "tb_ss0_warm_reset_n"), "tb_ss0_warm_reset_n missing"
        nbits = len(dut.tb_jtag_reset_ctrl.value)
        want_bits = jtag_smc_reset_ctrl_width()
        assert nbits == want_bits, (
            f"jtag_reset_ctrl width {nbits} want {want_bits} from the DV-owned IC_RESET slice "
            "table in smc_addr_map"
        )

        dut.rst_cool_ni.value = 1
        dut.tb_cfg_flr_pf_active.value = 0
        dut.tb_jtag_reset_ctrl.value = 0
        self._sources_idle(dut)
        await self._await_bit(
            dut.tb_rst_cool_from_flr, "tb_rst_cool_from_flr", 1, _PIN_BOUND, "IDLE_COOL"
        )
        await self._await_bit(
            dut.tb_ss0_warm_reset_n, "tb_ss0_warm_reset_n", 1, _PIN_BOUND, "IDLE_SS0"
        )
        await self.csr_write("SCRATCH_PRE", SCRATCH_COLD_WARM_0, _WARM_PAT)
        pre = await self.csr_read("SCRATCH_PRE", SCRATCH_COLD_WARM_0, expected=_WARM_PAT)
        cocotb.log.info(
            "CHK-JTAG-RST-IDLE: packed=0 cool=1 ss0_warm=1 rst_cool_ni=1 flr=0 scratch=0x%x",
            pre,
        )

        dut.tb_jtag_reset_ctrl.value = _pack(cool_ovrd=1, cool_val=0)
        await self._await_bit(
            dut.tb_rst_cool_from_flr, "tb_rst_cool_from_flr", 0, _PIN_BOUND, "COOL_ASSERT"
        )
        self._sources_idle(dut)
        dut.tb_jtag_reset_ctrl.value = _pack(cool_ovrd=1, cool_val=1)
        await self._await_bit(
            dut.tb_rst_cool_from_flr, "tb_rst_cool_from_flr", 1, _PIN_BOUND, "COOL_VAL1"
        )
        dut.tb_jtag_reset_ctrl.value = 0
        await self._await_bit(
            dut.tb_rst_cool_from_flr, "tb_rst_cool_from_flr", 1, _PIN_BOUND, "COOL_DROP"
        )
        last_warm = -1
        for _ in range(_RECOVERY):
            await RisingEdge(dut.clk_smc_i)
            last_warm = self._bit(dut.tb_rst_warm_smc_clk_n, "tb_rst_warm_smc_clk_n")
            if last_warm == 1:
                break
        else:
            raise AssertionError(f"warm smc clk still 0 after JTAG cool ovrd (last={last_warm})")
        self.cool_ok = True
        cocotb.log.info("CHK-JTAG-RST-COOL: rst_cool_no 1→0→1 via ovrd; rst_cool_ni=1 flr=0")
        got = await self.csr_read("SCRATCH_POST", SCRATCH_COLD_WARM_0, expected=0)
        cocotb.log.info(
            "CHK-JTAG-RST-WARM-SCRATCH: pre=0x%x post=0x%x (cool clear)",
            pre,
            got,
        )

        warm_csr = await self.csr_read("SS_WARM_PRE", SS_WARM, expected=SS_WARM_RESET)
        await self._await_bit(
            dut.tb_ss0_warm_reset_n, "tb_ss0_warm_reset_n", 1, _PIN_BOUND, "SS0_PRE"
        )
        dut.tb_jtag_reset_ctrl.value = _pack(ss0_warm_ovrd=1, ss0_warm_val=0)
        await self._await_bit(
            dut.tb_ss0_warm_reset_n, "tb_ss0_warm_reset_n", 0, _PIN_BOUND, "SS0_ASSERT"
        )
        assert self._bit(dut.tb_rst_cool_from_flr, "tb_rst_cool_from_flr") == 1, (
            "cool dropped during SS0 warm ovrd"
        )
        warm_hold = await self.csr_read("SS_WARM_HOLD", SS_WARM, expected=SS_WARM_RESET)
        dut.tb_jtag_reset_ctrl.value = _pack(ss0_warm_ovrd=1, ss0_warm_val=1)
        await self._await_bit(
            dut.tb_ss0_warm_reset_n, "tb_ss0_warm_reset_n", 1, _PIN_BOUND, "SS0_VAL1"
        )
        dut.tb_jtag_reset_ctrl.value = 0
        await self._await_bit(
            dut.tb_ss0_warm_reset_n, "tb_ss0_warm_reset_n", 1, _PIN_BOUND, "SS0_DROP"
        )
        self.ss0_ok = True
        cocotb.log.info(
            "CHK-JTAG-RST-SS0: pin 1→0→1 CSR stayed 0x%x→0x%x (not SW write)",
            warm_csr,
            warm_hold,
        )
        # Positive control for the two driven leaves of the DV-owned bit layout:
        # each moved its own reset pin (and the SS0 leaf left rst_cool_no
        # released), which a wrong position or a swapped ovrd/val half cannot do.
        cocotb.log.info(
            "JTAG reset_ctrl layout: cool_reset_n ovrd/val bits %d/%d moved rst_cool_no; "
            "ss_warm_reset_n[0] ovrd/val bits %d/%d moved ss0_warm_reset_n with rst_cool_no "
            "held; slice width %d",
            jtag_smc_reset_ctrl_bit("cool_reset_n_ovrd"),
            jtag_smc_reset_ctrl_bit("cool_reset_n_val"),
            jtag_smc_reset_ctrl_bit("ss_warm_reset_n_ovrd", 0),
            jtag_smc_reset_ctrl_bit("ss_warm_reset_n_val", 0),
            want_bits,
        )
        cocotb.log.info(
            "CHK-JTAG-RST-BASIC: cool=%s ss0=%s",
            self.cool_ok,
            self.ss0_ok,
        )
