# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Walk the jtag_reset_ctrl_i overrides smc_jtag_reset_ctrl_test leaves idle.

The sibling drives the cool override, the warm override released and the
subsystem-0 warm override. This leaf takes the other 65 override muxes --
ss_warm[1..31], ss_cold[0..31], fuse and cold -- through ovrd=1/val=0,
ovrd=1/val=1, ovrd=0/val=1 and idle, with the overridden reset both released
and asserted by its own source where the bench can arrange that, and requires
the reset that mux feeds, and only that one, to follow. The warm override is
also driven asserted. The cold leg comes last: its override resets the whole
SMC, so the leaf waits for the cold chain and the fuse sense to come back and
reads the cold scratch register cleared. The cold mux is never asked to
release a cold reset the pin asserts, since that would reset the bench models
clocked from `rst_cold_ni` while the SMC keeps running.
"""

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

SS_COLD = smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_COLD_RESET_N_BASE_ADDR")
SS_WARM = smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_WARM_RESET_N_BASE_ADDR")
SCRATCH_COLD_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_BASE_ADDR")
SCRATCH_COLD_WARM_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR")
SS_COLD_RESET = reset_unit_u32("RESET_UNIT__SS_COLD_RESET_N__RESET_N_N0_SCAN_reset")
SS_WARM_RESET = reset_unit_u32("RESET_UNIT__SS_WARM_RESET_N__RESET_N_N0_SCAN_reset")
SS_COUNT = reset_unit_u32("RESET_UNIT__SS_COLD_RESET_N__RESET_N_N0_SCAN_bw")
_SS_ALL_RELEASED = (1 << SS_COUNT) - 1
_SS_ALL_ASSERTED = 0
_COLD_PAT = 0xC01DC01D
_WARM_PAT = 0xA5A55A5A
_PIN_BOUND = 64
_SYNC_BOUND = 256
_COLD_ASSERT_BOUND = 2048
_RECOVERY = 50_000


def _pack(leaf: str, idx: int, *, ovrd: int, val: int) -> int:
    v = 0
    if ovrd:
        v |= 1 << jtag_smc_reset_ctrl_bit(f"{leaf}_ovrd", idx)
    if val:
        v |= 1 << jtag_smc_reset_ctrl_bit(f"{leaf}_val", idx)
    return v


class smc_jtag_reset_ovrd_walk_test_seq(SmcCsrSeq):
    """Fuse, cold, warm and every subsystem cold/warm JTAG reset override through its mux."""

    def __init__(self, name: str = "smc_jtag_reset_ovrd_walk_test_seq") -> None:
        super().__init__(name)
        self.ss_warm_ok = False
        self.ss_cold_ok = False
        self.warm_ok = False
        self.fuse_ok = False
        self.cold_ok = False

    def _val(self, sig, name: str) -> int:
        if not sig.value.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {sig.value}")
        return int(sig.value)

    def _bit(self, sig, name: str) -> int:
        return self._val(sig, name) & 1

    async def _await_val(self, sig, name: str, want: int, bound: int, label: str) -> None:
        last = -1
        for _ in range(bound):
            await RisingEdge(cocotb.top.clk_smc_i)
            last = self._val(sig, name)
            if last == want:
                return
        raise AssertionError(f"{label}: {name} stuck 0x{last:x} want 0x{want:x}")

    async def _hold_val(self, sig, name: str, want: int, cycles: int, label: str) -> None:
        for cycle in range(cycles):
            await RisingEdge(cocotb.top.clk_smc_i)
            got = self._val(sig, name)
            assert got == want, f"{label}: {name} read 0x{got:x} at cycle {cycle} want 0x{want:x}"

    def _sources_idle(self, dut) -> None:
        assert self._bit(dut.rst_cold_ni, "rst_cold_ni") == 1, "rst_cold_ni dropped"
        assert self._bit(dut.rst_cool_ni, "rst_cool_ni") == 1, "rst_cool_ni dropped"
        assert self._bit(dut.powergood_i, "powergood_i") == 1, "powergood_i dropped"
        assert self._bit(dut.tb_cfg_flr_pf_active, "tb_cfg_flr_pf_active") == 0, (
            "cfg_flr_pf_active_i high"
        )
        assert self._bit(dut.tb_sep_wdt_reset_n, "tb_sep_wdt_reset_n") == 1, "sep_wdt_reset_n_i low"

    def _top_level_released(self, dut, label: str) -> None:
        for name in ("rst_primary_smc_clk_no", "tb_rst_warm_smc_clk_n", "tb_rst_cool_from_flr"):
            assert self._bit(getattr(dut, name), name) == 1, f"{label}: {name} dropped"

    async def _walk_ss_released(
        self, dut, leaf: str, vec, vec_name: str, idx: int, label: str
    ) -> None:
        """Pin idx follows the override while its source and the other pins stay released."""
        others = _SS_ALL_RELEASED & ~(1 << idx)
        dut.tb_jtag_reset_ctrl.value = _pack(leaf, idx, ovrd=1, val=0)
        await self._await_val(vec, vec_name, others, _PIN_BOUND, f"{label}_ASSERT")
        self._top_level_released(dut, f"{label}_ASSERT")
        dut.tb_jtag_reset_ctrl.value = _pack(leaf, idx, ovrd=1, val=1)
        await self._await_val(vec, vec_name, _SS_ALL_RELEASED, _PIN_BOUND, f"{label}_VAL1")
        dut.tb_jtag_reset_ctrl.value = _pack(leaf, idx, ovrd=0, val=1)
        await self._hold_val(vec, vec_name, _SS_ALL_RELEASED, 4, f"{label}_OVRD0")
        dut.tb_jtag_reset_ctrl.value = 0
        await self._hold_val(vec, vec_name, _SS_ALL_RELEASED, 4, f"{label}_IDLE")

    async def _walk_ss_asserted(
        self, dut, leaf: str, vec, vec_name: str, idx: int, rest: int, label: str
    ) -> None:
        """Override val=1 releases pin idx while its register asserts it; the rest hold `rest`."""
        held = rest & ~(1 << idx)
        await self._hold_val(vec, vec_name, held, 4, f"{label}_SRC_ASSERT")
        dut.tb_jtag_reset_ctrl.value = _pack(leaf, idx, ovrd=1, val=1)
        await self._await_val(vec, vec_name, held | (1 << idx), _PIN_BOUND, f"{label}_RELEASE")
        self._top_level_released(dut, f"{label}_RELEASE")
        dut.tb_jtag_reset_ctrl.value = _pack(leaf, idx, ovrd=0, val=1)
        await self._await_val(vec, vec_name, held, _PIN_BOUND, f"{label}_OVRD0")
        dut.tb_jtag_reset_ctrl.value = 0
        await self._hold_val(vec, vec_name, held, 4, f"{label}_IDLE")

    async def _warm_only(self, dut, leaf: str, label: str) -> None:
        """Override val=0 asserts only the warm reset; val=1 and the release return it."""
        dut.tb_jtag_reset_ctrl.value = _pack(leaf, 0, ovrd=1, val=0)
        await self._await_val(
            dut.tb_rst_warm_smc_clk_n, "tb_rst_warm_smc_clk_n", 0, _SYNC_BOUND, f"{label}_ASSERT"
        )
        self._sources_idle(dut)
        for name in ("rst_primary_smc_clk_no", "tb_rst_cool_from_flr", "tb_fuse_reset_n"):
            await self._hold_val(getattr(dut, name), name, 1, 4, f"{label}_ASSERT")
        dut.tb_jtag_reset_ctrl.value = _pack(leaf, 0, ovrd=1, val=1)
        await self._await_val(
            dut.tb_rst_warm_smc_clk_n, "tb_rst_warm_smc_clk_n", 1, _SYNC_BOUND, f"{label}_VAL1"
        )
        dut.tb_jtag_reset_ctrl.value = _pack(leaf, 0, ovrd=0, val=1)
        await self._hold_val(
            dut.tb_rst_warm_smc_clk_n, "tb_rst_warm_smc_clk_n", 1, _SYNC_BOUND, f"{label}_OVRD0"
        )
        dut.tb_jtag_reset_ctrl.value = 0
        await self._hold_val(
            dut.tb_rst_warm_smc_clk_n, "tb_rst_warm_smc_clk_n", 1, _SYNC_BOUND, f"{label}_IDLE"
        )
        await self.csr_read(f"SCRATCH_WARM_POST_{label}", SCRATCH_COLD_WARM_0, expected=0)
        await self.csr_read(f"SCRATCH_COLD_POST_{label}", SCRATCH_COLD_0, expected=_COLD_PAT)

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        for name in ("tb_jtag_reset_ctrl", "tb_ss_cold_reset_n", "tb_ss_warm_reset_n"):
            assert hasattr(dut, name), f"{name} missing"
        nbits = len(dut.tb_jtag_reset_ctrl.value)
        want_bits = jtag_smc_reset_ctrl_width()
        assert nbits == want_bits, f"jtag_reset_ctrl width {nbits} want {want_bits}"
        for vec, name in (
            (dut.tb_ss_cold_reset_n, "tb_ss_cold_reset_n"),
            (dut.tb_ss_warm_reset_n, "tb_ss_warm_reset_n"),
        ):
            assert len(vec.value) == SS_COUNT, f"{name} width {len(vec.value)} want {SS_COUNT}"
        assert SS_WARM_RESET == _SS_ALL_RELEASED, (
            f"SS_WARM_RESET_N reset 0x{SS_WARM_RESET:x} does not release every subsystem"
        )
        assert SS_COLD_RESET == _SS_ALL_ASSERTED, (
            f"SS_COLD_RESET_N reset 0x{SS_COLD_RESET:x} does not assert every subsystem"
        )

        dut.tb_jtag_reset_ctrl.value = 0
        self._sources_idle(dut)
        await self._await_val(
            dut.tb_ss_warm_reset_n, "tb_ss_warm_reset_n", SS_WARM_RESET, _PIN_BOUND, "IDLE_SS_WARM"
        )
        await self._await_val(
            dut.tb_ss_cold_reset_n, "tb_ss_cold_reset_n", SS_COLD_RESET, _PIN_BOUND, "IDLE_SS_COLD"
        )
        self._top_level_released(dut, "IDLE")
        await self.csr_read("SS_WARM_IDLE", SS_WARM, expected=SS_WARM_RESET)
        await self.csr_read("SS_COLD_IDLE", SS_COLD, expected=SS_COLD_RESET)
        cocotb.log.info(
            "CHK-JTAG-OVRD-WALK-IDLE: packed=0 ss_warm=0x%x ss_cold=0x%x primary=1 warm=1 "
            "cool=1; rst_cold_ni=1 rst_cool_ni=1 powergood=1 flr=0 sep_wdt=1",
            SS_WARM_RESET,
            SS_COLD_RESET,
        )

        warm_vec, warm_name = dut.tb_ss_warm_reset_n, "tb_ss_warm_reset_n"
        for idx in range(1, SS_COUNT):
            await self._walk_ss_released(
                dut, "ss_warm_reset_n", warm_vec, warm_name, idx, f"SS_WARM{idx}"
            )
        await self.csr_read("SS_WARM_POST", SS_WARM, expected=SS_WARM_RESET)
        for idx in range(SS_COUNT):
            await self.csr_write_readback(
                f"SS_WARM_ASSERT{idx}", SS_WARM, _SS_ALL_RELEASED & ~(1 << idx)
            )
            await self._walk_ss_asserted(
                dut,
                "ss_warm_reset_n",
                warm_vec,
                warm_name,
                idx,
                _SS_ALL_RELEASED,
                f"SS_WARM{idx}",
            )
        await self.csr_restore("SS_WARM", SS_WARM, SS_WARM_RESET)
        await self._await_val(warm_vec, warm_name, SS_WARM_RESET, _PIN_BOUND, "SS_WARM_RESTORE")
        self.ss_warm_ok = True
        cocotb.log.info(
            "CHK-JTAG-OVRD-WALK-SS-WARM: ss_warm_reset_n[1..%d] each 1→0→1 through its override "
            "with the other %d pins held 1 and SS_WARM_RESET_N unchanged; with SS_WARM_RESET_N "
            "asserting one subsystem at a time, ss_warm_reset_n[0..%d] each 0→1→0 through "
            "ovrd=1/val=1; register restored to 0x%x",
            SS_COUNT - 1,
            SS_COUNT - 1,
            SS_COUNT - 1,
            SS_WARM_RESET,
        )

        cold_vec, cold_name = dut.tb_ss_cold_reset_n, "tb_ss_cold_reset_n"
        for idx in range(SS_COUNT):
            await self._walk_ss_asserted(
                dut,
                "ss_cold_reset_n",
                cold_vec,
                cold_name,
                idx,
                _SS_ALL_ASSERTED,
                f"SS_COLD{idx}",
            )
        await self.csr_read("SS_COLD_HELD", SS_COLD, expected=SS_COLD_RESET)
        await self.csr_write_readback("SS_COLD_RELEASE", SS_COLD, _SS_ALL_RELEASED)
        await self._await_val(cold_vec, cold_name, _SS_ALL_RELEASED, _PIN_BOUND, "SS_COLD_RELEASE")
        for idx in range(SS_COUNT):
            await self._walk_ss_released(
                dut, "ss_cold_reset_n", cold_vec, cold_name, idx, f"SS_COLD{idx}"
            )
        await self.csr_read("SS_COLD_POST", SS_COLD, expected=_SS_ALL_RELEASED)
        await self.csr_restore("SS_COLD", SS_COLD, SS_COLD_RESET)
        await self._await_val(cold_vec, cold_name, SS_COLD_RESET, _PIN_BOUND, "SS_COLD_RESTORE")
        self.ss_cold_ok = True
        cocotb.log.info(
            "CHK-JTAG-OVRD-WALK-SS-COLD: with SS_COLD_RESET_N at its reset 0x%x each "
            "ss_cold_reset_n[0..%d] 0→1→0 through ovrd=1/val=1 alone; with it written 0x%x each "
            "1→0→1 through its override with the other %d pins held 1; register restored",
            SS_COLD_RESET,
            SS_COUNT - 1,
            _SS_ALL_RELEASED,
            SS_COUNT - 1,
        )

        await self.csr_write_readback("SCRATCH_COLD_PRE", SCRATCH_COLD_0, _COLD_PAT)
        await self.csr_write_readback("SCRATCH_WARM_PRE_WARM", SCRATCH_COLD_WARM_0, _WARM_PAT)
        assert self._bit(dut.tb_fuse_reset_n, "tb_fuse_reset_n") == 1, "fuse_reset_n not released"
        await self._warm_only(dut, "warm_reset_n", "WARM")
        self.warm_ok = True
        cocotb.log.info(
            "CHK-JTAG-OVRD-WALK-WARM: warm override 1→0→1 asserted only the warm reset "
            "(primary, cool and the delayed fuse_reset_n stayed 1); SCRATCH_COLD_WARM_0 "
            "0x%x→0 and SCRATCH_COLD_0 kept 0x%x",
            _WARM_PAT,
            _COLD_PAT,
        )

        await self.csr_write_readback("SCRATCH_WARM_PRE_FUSE", SCRATCH_COLD_WARM_0, _WARM_PAT)
        await self._warm_only(dut, "fuse_reset_n", "FUSE")
        self.fuse_ok = True
        cocotb.log.info(
            "CHK-JTAG-OVRD-WALK-FUSE: fuse override 1→0→1 asserted only the warm reset "
            "(primary, cool and the delayed fuse_reset_n stayed 1); SCRATCH_COLD_WARM_0 "
            "0x%x→0 and SCRATCH_COLD_0 kept 0x%x",
            _WARM_PAT,
            _COLD_PAT,
        )

        await self.csr_write_readback("SCRATCH_WARM_PRE_COLD", SCRATCH_COLD_WARM_0, _WARM_PAT)
        dut.tb_jtag_reset_ctrl.value = _pack("cold_reset_n", 0, ovrd=1, val=0)
        await self._await_val(
            dut.rst_cold_stable_ref_clk_no,
            "rst_cold_stable_ref_clk_no",
            0,
            _COLD_ASSERT_BOUND,
            "COLD_ASSERT",
        )
        self._sources_idle(dut)
        for name in ("rst_primary_smc_clk_no", "tb_rst_warm_smc_clk_n"):
            await self._hold_val(getattr(dut, name), name, 0, 4, "COLD_ASSERT")
        await self._hold_val(dut.powergood_stable_o, "powergood_stable_o", 1, 4, "COLD_ASSERT")
        dut.tb_jtag_reset_ctrl.value = _pack("cold_reset_n", 0, ovrd=1, val=1)
        await self._await_val(
            dut.rst_cold_stable_ref_clk_no,
            "rst_cold_stable_ref_clk_no",
            1,
            _RECOVERY,
            "COLD_VAL1",
        )
        dut.tb_jtag_reset_ctrl.value = _pack("cold_reset_n", 0, ovrd=0, val=1)
        await self._hold_val(
            dut.rst_cold_stable_ref_clk_no, "rst_cold_stable_ref_clk_no", 1, 4, "COLD_OVRD0"
        )
        dut.tb_jtag_reset_ctrl.value = 0
        await self._await_val(
            dut.rst_primary_smc_clk_no, "rst_primary_smc_clk_no", 1, _RECOVERY, "COLD_PRIMARY"
        )
        # The eFuse controller re-senses after the primary reset and holds the
        # warm reset until it finishes; the fuse override releases it first.
        assert self._bit(dut.tb_fuse_sense_done, "tb_fuse_sense_done") == 0, (
            "fuse sense already done when the primary reset released"
        )
        dut.tb_jtag_reset_ctrl.value = _pack("fuse_reset_n", 0, ovrd=1, val=1)
        await self._await_val(
            dut.tb_rst_warm_smc_clk_n, "tb_rst_warm_smc_clk_n", 1, _SYNC_BOUND, "FUSE_EARLY"
        )
        for name in ("tb_fuse_sense_done", "tb_fuse_reset_n"):
            assert self._bit(getattr(dut, name), name) == 0, (
                f"FUSE_EARLY: {name} already 1 when the warm reset released"
            )
        await self.wait_fuse_sense_done()
        dut.tb_jtag_reset_ctrl.value = 0
        await self._hold_val(
            dut.tb_rst_warm_smc_clk_n, "tb_rst_warm_smc_clk_n", 1, _SYNC_BOUND, "FUSE_EARLY_IDLE"
        )
        await self._await_val(cold_vec, cold_name, SS_COLD_RESET, _PIN_BOUND, "COLD_SS")
        await self.csr_read("SCRATCH_COLD_POST_COLD", SCRATCH_COLD_0, expected=0)
        await self.csr_read("SCRATCH_WARM_POST_COLD", SCRATCH_COLD_WARM_0, expected=0)
        await self.csr_write_readback("SCRATCH_COLD_REWRITE", SCRATCH_COLD_0, _COLD_PAT)
        await self.csr_restore("SCRATCH_COLD", SCRATCH_COLD_0)
        self.cold_ok = True
        cocotb.log.info(
            "CHK-JTAG-OVRD-WALK-COLD: cold override 1→0→1 took rst_cold_stable_ref_clk_no, "
            "primary and warm low with powergood_stable_o held 1 and every source idle; after "
            "release the fuse override val=1 released the warm reset before the fuse sense "
            "finished, the chain and sense came back and SCRATCH_COLD_0 read 0 then took 0x%x",
            _COLD_PAT,
        )

        cocotb.log.info(
            "JTAG reset_ctrl layout: fuse ovrd/val bits %d/%d, cold %d/%d, warm %d/%d, "
            "ss_cold[0] %d/%d, ss_warm[1] %d/%d; slice width %d",
            jtag_smc_reset_ctrl_bit("fuse_reset_n_ovrd"),
            jtag_smc_reset_ctrl_bit("fuse_reset_n_val"),
            jtag_smc_reset_ctrl_bit("cold_reset_n_ovrd"),
            jtag_smc_reset_ctrl_bit("cold_reset_n_val"),
            jtag_smc_reset_ctrl_bit("warm_reset_n_ovrd"),
            jtag_smc_reset_ctrl_bit("warm_reset_n_val"),
            jtag_smc_reset_ctrl_bit("ss_cold_reset_n_ovrd", 0),
            jtag_smc_reset_ctrl_bit("ss_cold_reset_n_val", 0),
            jtag_smc_reset_ctrl_bit("ss_warm_reset_n_ovrd", 1),
            jtag_smc_reset_ctrl_bit("ss_warm_reset_n_val", 1),
            want_bits,
        )
        cocotb.log.info(
            "CHK-JTAG-OVRD-WALK-BASIC: ss_warm=%s ss_cold=%s warm=%s fuse=%s cold=%s",
            self.ss_warm_ok,
            self.ss_cold_ok,
            self.warm_ok,
            self.fuse_ok,
            self.cold_ok,
        )
