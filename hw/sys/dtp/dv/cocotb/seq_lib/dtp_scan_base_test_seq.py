# SPDX-License-Identifier: Apache-2.0
"""Shared iJTAG/STAP scan helpers for DTP scan scenarios."""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from env.dtp_scan_ref_model import (
    DtpIjtagSibModel,
    DtpStap3dcrModel,
    IJTAG_SIB_COUNT,
    IJTAG_SIB_ORDER,
    STAP_ORDER,
)
from env.dtp_types import DtpJtagInstr

from .dtp_jtag_base_test_seq import dtp_jtag_base_test_seq


class dtp_scan_base_test_seq(dtp_jtag_base_test_seq):
    """Helpers for IEEE 1687 SIB and IEEE 1838 STAP/3DCR checks."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.ijtag_model = DtpIjtagSibModel()
        self.stap_model = DtpStap3dcrModel()

    # --- lifecycle -----------------------------------------------------------
    async def set_lifecycle(self, **bits: int) -> None:
        """Drive active-high lifecycle enable bits exposed by tb_top."""
        dut = cocotb.top
        for name, value in bits.items():
            signal = f"feat_ctrl_{name}"
            if not hasattr(dut, signal):
                raise AttributeError(f"{signal} is not exposed by tb_top")
            getattr(dut, signal).value = value & 0x1
            self.log.info("Lifecycle enable %s=%d", signal, value & 0x1)
        # Feature-control bits cross into TCK through two sync flops.
        for _ in range(4):
            await self.tms_step(0)
        await ClockCycles(dut.clk_i, 4)

    async def enable_all_lifecycle(self) -> None:
        await self.set_lifecycle(
            sip_debug=1,
            soc_debug=1,
            ap_debug=1,
            sep_debug=1,
            fuse_test=1,
        )

    async def clear_lifecycle(self) -> None:
        """Legacy restore helper: all protected lifecycle features enabled."""
        await self.enable_all_lifecycle()

    async def gate_lifecycle_bits(self, **bits: bool) -> None:
        values = {
            "sip_debug": 1,
            "soc_debug": 1,
            "ap_debug": 1,
            "sep_debug": 1,
            "fuse_test": 1,
        }
        for name, gated in bits.items():
            if name not in values:
                raise ValueError(f"unknown lifecycle feature {name!r}")
            if gated:
                values[name] = 0
        await self.set_lifecycle(**values)

    # --- generic observable checks ------------------------------------------
    async def sample_signals(self) -> dict[str, int]:
        return (await self.sample_observables()).signals

    def check_observable(self, signals: dict[str, int], name: str, expected: int, *, context: str) -> None:
        assert name in signals, f"{name} is not exposed by the DTP JTAG driver"
        self.assert_equal(name, signals[name], expected, context)

    async def finish_dr_update(self) -> None:
        """Leave Shift-DR by pulsing Update-DR and returning to RTI."""
        await self.tms_step(1)
        await self.tms_step(1)
        await self.tms_step(0)

    async def shift_dr_observe(self, value: int, width: int, *, context: str) -> tuple[int, dict[str, int]]:
        """Shift DR while staying in Shift-DR long enough to sample controls."""
        item = await self.shift_dr(value, width, back_to_rti=False)
        signals = await self.sample_signals()
        self.log.info("%s observed TDO=0x%x width=%d signals=%s", context, item.result, width, signals)
        await self.finish_dr_update()
        return item.result, signals

    # --- iJTAG ---------------------------------------------------------------
    async def program_ijtag_sibs(
        self,
        pattern: int,
        *,
        context: str,
        feat_ctrl: dict[str, int] | None = None,
    ):
        """Update the three iJTAG SIB bits in LSB-first RTL order."""
        feat = dict(feat_ctrl or {})
        state = self.ijtag_model.state(pattern, **feat)
        self.log.info(
            "%s SIB pattern=0x%x requested=%s gated=%s effective=%s chain_len=%d",
            context,
            pattern,
            state.requested,
            state.gated,
            state.effective,
            state.chain_len,
        )
        await self.load_ir(DtpJtagInstr.SELECT_IJTAG)
        await self.shift_dr(pattern, IJTAG_SIB_COUNT)
        return state

    async def observe_ijtag_controls(self, pattern: int, *, context: str) -> tuple[int, dict[str, int]]:
        await self.load_ir(DtpJtagInstr.SELECT_IJTAG)
        return await self.shift_dr_observe(pattern, IJTAG_SIB_COUNT, context=context)

    def check_ijtag_controls(self, state, signals: dict[str, int], *, context: str) -> None:
        signal_prefix = {
            "dft_secure": "jtag_dft_secure",
            "dft": "jtag_dft",
            "dfd": "jtag_dfd",
        }
        for name in IJTAG_SIB_ORDER:
            prefix = signal_prefix[name]
            expected_select = state.effective[name]
            self.check_observable(signals, f"{prefix}_select", expected_select, context=f"{context}.{name}")

    # --- STAP / 3DCR ---------------------------------------------------------
    @staticmethod
    def stap_index(name: str) -> int:
        return STAP_ORDER.index(name)

    @staticmethod
    def stap_signal_prefix(name: str) -> str:
        return {
            "io": "jtag_stap_io",
            "smc": "jtag_stap_smc",
            "sep": "jtag_stap_sep",
            "extra0": "jtag_stap_extra0",
        }[name]

    async def write_ptap_3dcr(self, *, config_hold: int, select: int, context: str) -> None:
        value = self.stap_model.ptap_3dcr_value(config_hold=config_hold, select=select)
        self.log.info("%s PTAP_3DCR config_hold=%d select=%d raw=0x%x", context, config_hold, select, value)
        self.stap_model.update_ptap(value)
        await self.write_tdr("TAP_3DCR", value)
        await self.tms_step(0)
        await self.tms_step(0)

    async def read_ptap_3dcr(self, *, shift_value: int = 0) -> int:
        return await self.read_tdr("TAP_3DCR", shift_value=shift_value)

    def stap_sib_pattern(self, name: str, enabled: int) -> int:
        return (enabled & 0x1) << (len(STAP_ORDER) - 1 - self.stap_index(name))

    async def shift_stap_sibs(self, pattern: int, *, context: str) -> None:
        self.log.info("%s STAP SIB pattern=0x%x order=%s", context, pattern, STAP_ORDER)
        await self.load_ir(DtpJtagInstr.TAP_3DCR)
        await self.shift_dr(pattern, len(STAP_ORDER))

    async def write_stap_3dcr(
        self,
        name: str,
        *,
        config_hold: int,
        stap_sel: int,
        tms_hold: int,
        close_sib: int = 1,
        feat_ctrl: dict[str, int] | None = None,
        context: str,
    ) -> None:
        """Write one downstream STAP 3DCR after its SIB has been opened.

        Packing follows the jtag_stap RTL testbench: SIB bit first, then
        config_hold, stap_sel, tms_hold in LSB-first scan order.
        """
        gates = self.stap_model.gates(**dict(feat_ctrl or {}))
        payload = self.stap_model.stap_3dcr_value(
            config_hold=config_hold,
            stap_sel=stap_sel,
            tms_hold=tms_hold,
        )
        value = (close_sib & 0x1) << (len(STAP_ORDER) - 1 - self.stap_index(name))
        value |= payload << len(STAP_ORDER)
        width = len(STAP_ORDER) + 3
        self.log.info(
            "%s STAP %s 3DCR config_hold=%d stap_sel=%d tms_hold=%d close_sib=%d raw=0x%x",
            context,
            name,
            config_hold,
            stap_sel,
            tms_hold,
            close_sib,
            value,
        )
        self.stap_model.update_stap(name, payload, gated=gates[name])
        await self.load_ir(DtpJtagInstr.TAP_3DCR)
        await self.shift_dr(value, width)

    async def select_stap(
        self,
        name: str,
        *,
        feat_ctrl: dict[str, int] | None = None,
        context: str,
    ) -> None:
        await self.write_ptap_3dcr(config_hold=1, select=1, context=f"{context}.ptap_select")
        await self.shift_stap_sibs(self.stap_sib_pattern(name, 1), context=f"{context}.open_sib")
        await self.write_stap_3dcr(
            name,
            config_hold=1,
            stap_sel=1,
            tms_hold=1,
            close_sib=0,
            feat_ctrl=feat_ctrl,
            context=f"{context}.write_stap_3dcr",
        )

    async def observe_stap_controls(self, name: str, *, context: str) -> tuple[int, dict[str, int]]:
        await self.load_ir(DtpJtagInstr.TAP_3DCR)
        return await self.shift_dr_observe(0, len(STAP_ORDER), context=context)

    def check_stap_selected(
        self,
        name: str,
        signals: dict[str, int],
        *,
        selected: int,
        context: str,
    ) -> None:
        prefix = self.stap_signal_prefix(name)
        self.check_observable(signals, f"{prefix}_trst_n", 1, context=context)
        self.log.info("%s selected=%d sampled_%s_tdo_oen=%d", context, selected, prefix, signals[f"{prefix}_tdo_oen"])

    async def apply_tlr(self) -> None:
        for _ in range(5):
            await self.tms_step(1)
        await self.tms_step(0)
        self.stap_model.tlr()

    async def apply_trst(self) -> None:
        await self.assert_trst(cycles=5)
        await self.deassert_trst(cycles=2)
        self.stap_model.trst()

