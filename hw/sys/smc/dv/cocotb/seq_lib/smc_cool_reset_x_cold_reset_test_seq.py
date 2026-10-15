# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""cfg_flr_pf_active_i overlapped with rst_cold_ni; cold wins. BMC pin-cool not claimed."""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

SMC_REG = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_SMC_REG_BASE_ADDR")
SMCEN = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_SMCEN_REG_BASE_ADDR")
FLR_DELAY = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_COUNTER_VALUE_BASE_ADDR")
FLR_HOLD = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_RESET_COUNTER_VALUE_BASE_ADDR")
SCRATCH_COLD_WARM_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR")
# misc_wrap.rdl instantiates two scratch banks (`scratch scratch_cold @0x0` and
# `scratch scratch_cold_warm @0x80`), both `scratch.rdl` SCRATCH[8] sw=rw
# reset 0x0; both are swept. The FLR cool clears both banks
# (CHK-FLR-COOL-SCRATCH-CLEAR), so no scratch register in this map separates
# the cool from the cold reset that overlaps it, and the post-cold leg claims
# only that the banks were cleared across the overlap.
SCRATCH_COLD_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_BASE_ADDR")

# Hold of 0/1 never starts the FSM. Keep hold long enough to overlap cold.
_DELAY = 0x20
_HOLD = 0x40
_SMCEN = 0xFFFFFFFF
_CDC_REF = 64
_COOL_ASSERT_BOUND = _DELAY + 128
_COOL_RELEASE_BOUND = _HOLD + 128
_ISO_BOUND = 64
_WINS_BOUND = 256
_RECOVERY_REF = 50_000
_WARM_PAT = 0xA5A55A5A
_COLD_PAT = 0x5A5AA5A5
_SCRATCH_RESET = 0x0


class smc_cool_reset_x_cold_reset_test_seq(SmcCsrSeq):
    """FLR cool then cold: isolate and chiplet-cool drop (cold wins)."""

    def __init__(self, name: str = "smc_cool_reset_x_cold_reset_test_seq") -> None:
        super().__init__(name)
        # Measured observables, not "did we get here" flags. The test module's
        # final gate compares these, so a wrong isolate word or a scratch value
        # that survived the cold reset fails even though the body ran to the end.
        self.iso_live: int | None = None
        self.iso_last: int | None = None
        self.cool_last: int | None = None
        self.cool_scratch_before: tuple[int, int] | None = None
        self.cool_scratch_after: tuple[int, int] | None = None
        self.cold_scratch_pre: tuple[int, int] | None = None
        self.cold_scratch_post: tuple[int, int] | None = None

    def _int(self, pin) -> int:
        if not pin.value.is_resolvable:
            raise AssertionError(f"X/Z on pin: {pin.value}")
        return int(pin.value)

    def _cool(self, dut) -> int:
        return self._int(dut.tb_rst_cool_from_flr) & 1

    async def _await_cool(self, dut, want: int, bound: int, label: str) -> None:
        last = None
        for _ in range(bound):
            await RisingEdge(dut.clk_ref_i)
            last = self._cool(dut)
            if last == want:
                return
        raise AssertionError(f"{label}: rst_cool_from_flr stuck {last} want {want}")

    async def _await_iso(self, dut, pred, bound: int, label: str) -> int:
        last = None
        for _ in range(bound):
            await RisingEdge(dut.clk_smc_i)
            last = self._int(dut.tb_isolate_req_o)
            if pred(last):
                return last
        raise AssertionError(f"{label}: isolate_req_o stuck 0x{last:x}")

    async def _await_warm(self, dut, label: str) -> None:
        last = None
        for _ in range(_RECOVERY_REF):
            await RisingEdge(dut.clk_smc_i)
            last = self._int(dut.tb_rst_warm_smc_clk_n) & 1
            if last == 1:
                return
        raise AssertionError(f"{label}: warm smc clk still 0 (last={last})")

    async def _arm_scratch(self, label: str) -> tuple[int, int]:
        """Write a distinct non-zero pattern into both scratch banks and prove
        the readback, so any later `expected=0` compare has a measured non-zero
        starting point in the same run instead of resting on the reset value."""
        await self.csr_write(f"{label}_SCRATCH_WARM", SCRATCH_COLD_WARM_0, _WARM_PAT)
        warm = await self.csr_read(
            f"{label}_SCRATCH_WARM_RB", SCRATCH_COLD_WARM_0, expected=_WARM_PAT
        )
        await self.csr_write(f"{label}_SCRATCH_COLD", SCRATCH_COLD_0, _COLD_PAT)
        cold = await self.csr_read(f"{label}_SCRATCH_COLD_RB", SCRATCH_COLD_0, expected=_COLD_PAT)
        return (warm, cold)

    async def _read_scratch(self, label: str, expected: int) -> tuple[int, int]:
        warm = await self.csr_read(f"{label}_SCRATCH_WARM", SCRATCH_COLD_WARM_0, expected=expected)
        cold = await self.csr_read(f"{label}_SCRATCH_COLD", SCRATCH_COLD_0, expected=expected)
        return (warm, cold)

    async def _program_flr_counters(self) -> None:
        await self.csr_write("FLR_DELAY", FLR_DELAY, _DELAY)
        await self.csr_read("FLR_DELAY_RB", FLR_DELAY, expected=_DELAY)
        await self.csr_write("FLR_HOLD", FLR_HOLD, _HOLD)
        await self.csr_read("FLR_HOLD_RB", FLR_HOLD, expected=_HOLD)

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        assert hasattr(dut, "tb_cfg_flr_pf_active"), "tb_cfg_flr_pf_active missing"
        dut.tb_cfg_flr_pf_active.value = 0
        dut.rst_cool_ni.value = 1
        assert self._int(dut.rst_cool_ni) & 1 == 1, (
            "rst_cool_ni dropped; FLR×cold would be aliased to pin-cool"
        )

        await self._program_flr_counters()
        self.cool_scratch_before = await self._arm_scratch("PRE_COOL")
        for _ in range(_CDC_REF):
            await RisingEdge(dut.clk_ref_i)

        dut.tb_cfg_flr_pf_active.value = 1
        await self._await_cool(dut, 0, _COOL_ASSERT_BOUND, "POS_COOL_ASSERT")
        assert self._int(dut.rst_cool_ni) & 1 == 1
        cocotb.log.info("CHK-FLR-COLD-POS-COOL: FLR-only rst_cool_from_flr=0 rst_cool_ni=1")
        dut.tb_cfg_flr_pf_active.value = 0
        await self._await_cool(dut, 1, _COOL_RELEASE_BOUND, "POS_COOL_RELEASE")
        await self._await_warm(dut, "POS_WARM")
        # FLR-cool effect on the scratch banks. Fail-capable: both banks were
        # written and read back non-zero immediately above, so a design where
        # the cool reset does not reach them fails here.
        self.cool_scratch_after = await self._read_scratch("AFTER_COOL", _SCRATCH_RESET)
        cocotb.log.info(
            "CHK-FLR-COOL-SCRATCH-CLEAR: the FLR-only cool cleared BOTH scratch "
            "banks: SCRATCH_COLD_WARM_0 0x%08x->0x%x and SCRATCH_COLD_0 "
            "0x%08x->0x%x. No scratch register in this map survives a cool, "
            "which is why the post-cold leg below claims 'cleared across the "
            "overlap' and not 'cleared by the cold reset'",
            self.cool_scratch_before[0],
            self.cool_scratch_after[0],
            self.cool_scratch_before[1],
            self.cool_scratch_after[1],
        )
        await self.csr_write("SMC_REG_CLR", SMC_REG, 0)

        await self.csr_write("SMCEN_ALL", SMCEN, _SMCEN)
        await self.csr_read("SMCEN_RB", SMCEN, expected=_SMCEN)
        # Re-arm both banks so the post-overlap `expected=0` compare starts from
        # a MEASURED non-zero value in this run rather than from the reset value.
        self.cold_scratch_pre = await self._arm_scratch("PRE_COLD")
        for _ in range(_CDC_REF):
            await RisingEdge(dut.clk_ref_i)

        dut.tb_cfg_flr_pf_active.value = 1
        self.iso_live = await self._await_iso(dut, lambda v: v == _SMCEN, _ISO_BOUND, "ISO_LIVE")
        await self._await_cool(dut, 0, _COOL_ASSERT_BOUND, "OVERLAP_COOL_HELD")
        cocotb.log.info(
            "CHK-FLR-COLD-ISO-LIVE: isolate_req_o=0x%x cool=0 before cold",
            self.iso_live,
        )

        dut.rst_cold_ni.value = 0
        iso_last = None
        cool_last = None
        iso_cleared = False
        cool_released = False
        for _ in range(_WINS_BOUND):
            await RisingEdge(dut.clk_ref_i)
            iso_last = self._int(dut.tb_isolate_req_o)
            cool_last = self._cool(dut)
            if iso_last == 0:
                iso_cleared = True
            if cool_last == 1:
                cool_released = True
            if iso_cleared and cool_released:
                break
        else:
            raise AssertionError(
                f"cold-wins expired iso=0x{iso_last:x} cool={cool_last} "
                f"iso_cleared={iso_cleared} cool_released={cool_released}"
            )
        assert self._int(dut.rst_cool_ni) & 1 == 1
        self.iso_last = iso_last
        self.cool_last = cool_last
        cocotb.log.info(
            "CHK-FLR-COLD-WINS: isolate_req_o=0x%x rst_cool_from_flr=%d "
            "(cold wins; rst_cool_ni stayed 1)",
            iso_last,
            cool_last,
        )

        # Drop FLR before releasing cold so the posedge does not restart the FSM.
        dut.tb_cfg_flr_pf_active.value = 0
        for _ in range(8):
            await RisingEdge(dut.clk_ref_i)
        dut.rst_cold_ni.value = 1
        await self._await_warm(dut, "POST_COLD_WARM")
        await self.wait_fuse_sense_done()
        self.cold_scratch_post = await self._read_scratch("POST_COLD", _SCRATCH_RESET)
        cocotb.log.info(
            "CHK-FLR-COLD-SCRATCH: across the FLR-cool x cold overlap the two "
            "scratch banks went 0x%08x/0x%08x (measured immediately before the "
            "overlap) to 0x%x/0x%x, and the CSR path answers again after the "
            "cold release. ATTRIBUTION: the overlapping FLR cool alone also "
            "clears both banks (CHK-FLR-COOL-SCRATCH-CLEAR), so this leg proves "
            "they were cleared across the overlap -- it does NOT attribute the "
            "clear to the cold reset",
            self.cold_scratch_pre[0],
            self.cold_scratch_pre[1],
            self.cold_scratch_post[0],
            self.cold_scratch_post[1],
        )
