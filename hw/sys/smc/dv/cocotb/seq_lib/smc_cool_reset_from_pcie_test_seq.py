# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""cfg_flr_pf_active_i cool reset. No Force; not rst_cool_ni. BMC/primary-chiplet not claimed."""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import reset_unit_u32, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

SMC_REG = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_SMC_REG_BASE_ADDR")
SMCEN = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_SMCEN_REG_BASE_ADDR")
FLR_DELAY = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_COUNTER_VALUE_BASE_ADDR")
FLR_HOLD = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_RESET_COUNTER_VALUE_BASE_ADDR")
SCRATCH_COLD_WARM_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR")

SMC_BIT = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_SMC_REG__ISOLATE_REQ_SMC_REG_bm")

# Hold of 0/1 never starts the FSM (reset_unit.adoc). Keep values small.
_DELAY = 0x20
_HOLD = 0x10
_PIN_BOUND = 64
_COOL_ASSERT_BOUND = _DELAY + 128
_COOL_RELEASE_BOUND = _HOLD + 128
_CDC_REF = 64
_RECOVERY_REF = 50_000
_NO_COOL_BOUND = 32
_WARM_PAT = 0xA5A55A5A


class smc_cool_reset_from_pcie_test_seq(SmcCsrSeq):
    """cfg_flr_pf_active_i → isolate CSR / rst_cool_no / isolate_req_o."""

    def __init__(self, name: str = "smc_cool_reset_from_pcie_test_seq") -> None:
        super().__init__(name)
        self.zero_cnt_ok = False
        self.cool_ok = False
        self.iso_ok = False

    def _int(self, pin) -> int:
        if not pin.value.is_resolvable:
            raise AssertionError(f"X/Z on pin: {pin.value}")
        return int(pin.value)

    async def _await_smc_clk(self, sample, want: int, bound: int, label: str) -> None:
        last = None
        for _ in range(bound):
            await RisingEdge(cocotb.top.clk_smc_i)
            last = sample()
            if last == want:
                return
        raise AssertionError(f"{label}: stuck {last} want {want}")

    async def _await_cool(self, dut, want: int, bound: int, label: str) -> None:
        last = None
        for _ in range(bound):
            await RisingEdge(dut.clk_ref_i)
            last = self._int(dut.tb_rst_cool_from_flr) & 1
            if last == want:
                return
        raise AssertionError(f"{label}: rst_cool_from_flr stuck {last} want {want}")

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

        smc0 = await self.csr_read("SMC_REG_IDLE", SMC_REG, expected=0)
        assert self._int(dut.tb_isolate_req_o) == 0
        assert (self._int(dut.tb_rst_cool_from_flr) & 1) == 1
        cocotb.log.info(
            "CHK-FLR-IDLE: SMC_REG=0x%x iso=0x%x cool=%d skip=%d",
            smc0,
            self._int(dut.tb_isolate_req_o),
            self._int(dut.tb_rst_cool_from_flr) & 1,
            self._int(dut.tb_skip_mem_repair_o) & 1,
        )

        dut.tb_cfg_flr_pf_active.value = 1
        smc1 = await self._await_smc_bit(SMC_BIT, _PIN_BOUND, "SMC_REG_ZERO_CNT")
        assert self._int(dut.tb_isolate_req_o) == 0, "isolate_req_o without SMCEN"
        for _ in range(_NO_COOL_BOUND):
            await RisingEdge(dut.clk_ref_i)
            if (self._int(dut.tb_rst_cool_from_flr) & 1) == 0:
                raise AssertionError("cool asserted with FLR counters still 0")
        self.zero_cnt_ok = True
        cocotb.log.info("CHK-FLR-ZERO-CNT: SMC_REG=0x%x iso=0 cool stayed 1", smc1)

        dut.tb_cfg_flr_pf_active.value = 0
        await self.csr_write("SMC_REG_CLR", SMC_REG, 0)
        await self._await_smc_bit(0, _PIN_BOUND, "SMC_REG_CLR_RB")

        await self.csr_write("FLR_DELAY", FLR_DELAY, _DELAY)
        await self.csr_read("FLR_DELAY_RB", FLR_DELAY, expected=_DELAY)
        await self.csr_write("FLR_HOLD", FLR_HOLD, _HOLD)
        await self.csr_read("FLR_HOLD_RB", FLR_HOLD, expected=_HOLD)
        await self.csr_write("SCRATCH_PRE", SCRATCH_COLD_WARM_0, _WARM_PAT)
        await self.csr_read("SCRATCH_PRE", SCRATCH_COLD_WARM_0, expected=_WARM_PAT)
        for _ in range(_CDC_REF):
            await RisingEdge(dut.clk_ref_i)

        dut.tb_cfg_flr_pf_active.value = 1
        await self._await_cool(dut, 0, _COOL_ASSERT_BOUND, "COOL_ASSERT")
        await self._await_cool(dut, 1, _COOL_RELEASE_BOUND, "COOL_RELEASE")
        self.cool_ok = True
        cocotb.log.info(
            "CHK-FLR-COOL: rst_cool_from_flr 1→0→1 delay=0x%x hold=0x%x",
            _DELAY,
            _HOLD,
        )

        dut.tb_cfg_flr_pf_active.value = 0
        last_warm = None
        for _ in range(_RECOVERY_REF):
            await RisingEdge(dut.clk_smc_i)
            last_warm = self._int(dut.tb_rst_warm_smc_clk_n) & 1
            if last_warm == 1:
                break
        else:
            raise AssertionError(f"warm smc clk still 0 after FLR cool (last={last_warm})")
        warm = await self.csr_read("SCRATCH_POST", SCRATCH_COLD_WARM_0, expected=0)
        cocotb.log.info("CHK-FLR-WARM: SCRATCH_COLD_WARM_0=0x%x after FLR cool", warm)

        smc2 = await self.csr_read("SMC_REG_POST", SMC_REG)
        assert smc2 & SMC_BIT, f"SMC_REG dropped across cool: 0x{smc2:x}"
        await self.csr_write("SMCEN_ALL", SMCEN, 0xFFFFFFFF)
        await self._await_smc_clk(
            lambda: self._int(dut.tb_isolate_req_o),
            0xFFFFFFFF,
            _PIN_BOUND,
            "SMCEN isolate_req_o",
        )
        await self.csr_write("SMC_REG_SW_CLR", SMC_REG, 0)
        await self._await_smc_clk(
            lambda: self._int(dut.tb_isolate_req_o),
            0,
            _PIN_BOUND,
            "SW-CLR isolate_req_o",
        )
        self.iso_ok = True
        cocotb.log.info("CHK-FLR-ISO: isolate_req_o 0→0xffffffff→0 after SMCEN")
        cocotb.log.info(
            "CHK-FLR-BASIC: zero=%s cool=%s iso=%s",
            self.zero_cnt_ok,
            self.cool_ok,
            self.iso_ok,
        )
