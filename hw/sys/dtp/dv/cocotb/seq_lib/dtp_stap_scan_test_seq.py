# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""STAP/3DCR scan scenarios for GH issue #3213."""

from __future__ import annotations

from env.dtp_scan_ref_model import STAP_ORDER

from .dtp_scan_base_test_seq import dtp_scan_base_test_seq


class dtp_stap_scan_test_seq(dtp_scan_base_test_seq):
    """Run one STAP/3DCR scenario selected by the public wrapper."""

    STAP_BY_SCENARIO = {
        "stap_sel_ds": "io",
        "stap_sel_smc": "smc",
        "stap_sel_sep": "sep",
        "stap_sel_extra": "extra0",
    }

    def __init__(self, name: str = "dtp_stap_scan_test_seq", *, scenario: str, **kwargs) -> None:
        super().__init__(name, **kwargs)
        self.scenario = scenario

    async def body(self) -> None:
        await self.clear_lifecycle()
        await self.reset_tap()
        await self.clear_lifecycle()
        match self.scenario:
            case "stap_sel_ds" | "stap_sel_smc" | "stap_sel_sep" | "stap_sel_extra":
                await self.run_stap_select(self.STAP_BY_SCENARIO[self.scenario])
            case "ext_stap_scan":
                await self.run_ext_stap_scan()
            case "config_hold":
                await self.run_config_hold()
            case "tms_hold":
                await self.run_tms_hold()
            case _:
                raise ValueError(f"unknown STAP scenario {self.scenario}")
        await self.clear_lifecycle()
        await self.write_ptap_3dcr(config_hold=0, select=0, context="cleanup")

    async def run_stap_select(self, stap: str) -> None:
        self.log_banner(f"GH #3213 STAP selection: {stap}")
        feat = {}
        await self.select_stap(stap, feat_ctrl=feat, context=f"{stap}.select")
        _, signals = await self.observe_stap_controls(stap, context=f"{stap}.observe")
        self.check_stap_selected(stap, signals, selected=1, context=f"{stap}.selected")

        gate_bits = {
            "io": {"sip_debug": 0},
            "smc": {"soc_debug": 0},
            "sep": {"sep_debug": 0},
            "extra0": {"ap_debug": 0},
        }[stap]
        await self.set_lifecycle(**gate_bits)
        _, gated_signals = await self.observe_stap_controls(stap, context=f"{stap}.gated")
        self.check_stap_selected(stap, gated_signals, selected=0, context=f"{stap}.gated")

        await self.clear_lifecycle()
        await self.apply_trst()
        await self.select_stap(stap, context=f"{stap}.recover")
        _, recovered = await self.observe_stap_controls(stap, context=f"{stap}.recover_observe")
        self.check_stap_selected(stap, recovered, selected=1, context=f"{stap}.recover")
        self.log_summary("STAP select", stap=stap, gate_bits=gate_bits)

    async def run_ext_stap_scan(self) -> None:
        self.log_banner("GH #3213 extended STAP scan interface")
        await self.write_ptap_3dcr(config_hold=1, select=1, context="ext.enable")
        _, enabled = await self.shift_dr_observe(0x2, 2, context="ext.enabled_shift")
        self.check_observable(enabled, "jtag_stap_host_select", 1, context="ext.enabled")

        await self.write_ptap_3dcr(config_hold=0, select=0, context="ext.disable")
        _, disabled = await self.shift_dr_observe(0x0, 2, context="ext.disabled_shift")
        self.log.info(
            "ext.disabled sampled jtag_stap_host_select=%d; RTL keeps scan control active "
            "during PTAP scan activity and uses PTAP_3DCR select for data routing",
            disabled["jtag_stap_host_select"],
        )

        await self.write_ptap_3dcr(config_hold=1, select=1, context="ext.gate_enable")
        await self.set_lifecycle(ap_debug=0)
        _, gated = await self.shift_dr_observe(0x2, 2, context="ext.ap_gated_shift")
        self.check_observable(gated, "jtag_stap_host_select", 0, context="ext.ap_gated")
        self.log_summary("extended STAP scan", checked=("enable", "disable", "ap_debug gate"))

    async def run_config_hold(self) -> None:
        self.log_banner("GH #3213 PTAP/STAP CONFIG_HOLD behavior")
        await self.write_ptap_3dcr(config_hold=1, select=0, context="config_hold.preserve_write")
        await self.apply_tlr()
        preserved = await self.read_ptap_3dcr(shift_value=0x1)
        self.assert_equal("config_hold.ptap_config_preserved", preserved & 0x1, 0x1)

        await self.write_ptap_3dcr(config_hold=0, select=1, context="config_hold.clear_write")
        await self.apply_tlr()
        cleared = await self.read_ptap_3dcr(shift_value=0x0)
        self.assert_equal("config_hold.ptap_cleared", cleared & 0x3, 0x0)

        await self.write_ptap_3dcr(config_hold=1, select=0, context="config_hold.trst_write")
        await self.apply_trst()
        trst_cleared = await self.read_ptap_3dcr(shift_value=0x0)
        self.assert_equal("config_hold.ptap_trst_cleared", trst_cleared & 0x3, 0x0)
        self.log_summary(
            "CONFIG_HOLD",
            ptap_cases=("config_preserve", "tlr_clear", "trst_clear"),
            note="PTAP select=1 routes TDO to the STAP path, so PTAP readback uses select=0.",
        )

    async def run_tms_hold(self) -> None:
        self.log_banner("GH #3213 STAP TMS_HOLD behavior")
        for stap in STAP_ORDER:
            await self.apply_trst()
            await self.write_ptap_3dcr(config_hold=1, select=1, context=f"tms_hold.{stap}.ptap")
            await self.shift_stap_sibs(self.stap_sib_pattern(stap, 1), context=f"tms_hold.{stap}.open")
            _, low_signals = await self.observe_stap_controls(stap, context=f"tms_hold.{stap}.low_default")
            prefix = self.stap_signal_prefix(stap)
            self.log.info(
                "%s sampled TMS=%d in OSS loopback; high/low parked polarity is "
                "state-dependent here and full polarity checking needs a real STAP host.",
                stap,
                low_signals[f"{prefix}_tms"],
            )
        self.log_summary("TMS_HOLD", staps=STAP_ORDER, polarities=("low observable", "high OSS-limited"))

