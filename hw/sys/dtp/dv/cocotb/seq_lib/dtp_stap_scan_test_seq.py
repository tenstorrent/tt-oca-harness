# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""STAP/3DCR scan scenarios."""

from __future__ import annotations

from env.dtp_dbg_disable import STAP_DISABLE
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
        await self.enable_all_debug()
        await self.reset_tap()
        await self.enable_all_debug()
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
        await self.enable_all_debug()
        await self.write_ptap_3dcr(config_hold=0, select=0, context="cleanup")

    SELECTED_PAYLOAD = {"config_hold": 1, "stap_sel": 1, "tms_hold": 1}

    def check_stap_forwarding(
        self,
        edges: int,
        counts: dict[str, int],
        *,
        prefix: str,
        forwarding: bool,
        context: str,
    ) -> None:
        """A selected STAP forwards: tdo_oen pulses during shifts and tms
        follows the live TMS (mixed samples). A deselected or gated STAP
        with tms_hold=1 stored parks its tms high and never drives tdo_oen."""
        tdo_oen = counts[f"{prefix}_tdo_oen"]
        tms = counts[f"{prefix}_tms"]
        if forwarding:
            assert tdo_oen > 0, f"{context}: {prefix}_tdo_oen never pulsed while selected"
            assert 0 < tms < edges, (
                f"{context}: {prefix}_tms must follow the live TMS while "
                f"selected (got {tms}/{edges} high samples)"
            )
        else:
            assert tdo_oen == 0, (
                f"{context}: {prefix}_tdo_oen pulsed {tdo_oen}x while deselected/gated"
            )
            assert tms == edges, (
                f"{context}: {prefix}_tms must park at the stored tms_hold=1 "
                f"(got {tms}/{edges} high samples)"
            )

    async def run_stap_select(self, stap: str) -> None:
        self.log_banner(f"STAP selection: {stap}")
        prefix = self.stap_signal_prefix(stap)
        watch = (f"{prefix}_tdo_oen", f"{prefix}_tms")
        disable_field = STAP_DISABLE[stap]
        rng = self.rng(f"stap_gate_{stap}")

        async def configure(context: str, dbg: dict[str, int] | None = None) -> None:
            await self.stap_chain_write(
                ptap_select=1, ptap_config_hold=1, sib_en={stap: 1},
                dbg_disable=dbg, context=f"{context}.open_sib",
            )
            await self.stap_chain_write(
                payloads={stap: self.SELECTED_PAYLOAD},
                dbg_disable=dbg, context=f"{context}.write_3dcr",
            )

        self.log_step(1, "Configure and select %s via composed TAP_3DCR scans", stap)
        await self.stap_chain_flush(context=f"{stap}.flush")
        await configure(f"{stap}.select")
        window = self.start_scan_window(watch)
        captured = await self.stap_chain_maintain(context=f"{stap}.observe")
        edges, counts = self.check_scan_window(window, context=f"{stap}.selected_window")
        self.check_stap_forwarding(edges, counts, prefix=prefix, forwarding=True, context=f"{stap}.selected")
        self.check_stap_chain_readback(captured, context=f"{stap}.selected_readback")

        self.log_step(2, "Assert exactly %s: forwarding stops, gated update is ignored", disable_field)
        await self.disable_debug_bits(disable_field)
        # A randomized deselecting payload attempted while gated must be ignored.
        attempt = {"config_hold": rng.randrange(0, 2), "stap_sel": 0, "tms_hold": 0}
        self.log.info("%s gated 3DCR update attempt %s", stap, attempt)
        window = self.start_scan_window(watch)
        captured = await self.stap_chain_write(
            payloads={stap: attempt},
            dbg_disable={disable_field: 1},
            context=f"{stap}.gated_update_attempt",
        )
        edges, counts = self.check_scan_window(window, context=f"{stap}.gated_window")
        self.check_stap_forwarding(edges, counts, prefix=prefix, forwarding=False, context=f"{stap}.gated")
        self.check_stap_chain_readback(captured, dbg_disable={disable_field: 1}, context=f"{stap}.gated_readback")

        self.log_step(3, "Clear %s without reset: selection resumes from stored state", disable_field)
        await self.enable_all_debug()
        window = self.start_scan_window(watch)
        captured = await self.stap_chain_maintain(context=f"{stap}.resume")
        edges, counts = self.check_scan_window(window, context=f"{stap}.resume_window")
        self.check_stap_forwarding(edges, counts, prefix=prefix, forwarding=True, context=f"{stap}.resume")
        self.check_stap_chain_readback(captured, context=f"{stap}.resume_readback")

        neighbor = STAP_ORDER[(STAP_ORDER.index(stap) + 1) % len(STAP_ORDER)]
        n_prefix = self.stap_signal_prefix(neighbor)
        self.log_step(4, "With %s re-asserted, unrelated STAP %s stays usable", disable_field, neighbor)
        await self.disable_debug_bits(disable_field)
        await self.stap_chain_write(
            sib_en={stap: 1, neighbor: 1},
            dbg_disable={disable_field: 1},
            context=f"{stap}.isolation_open",
        )
        await self.stap_chain_write(
            payloads={neighbor: self.SELECTED_PAYLOAD},
            dbg_disable={disable_field: 1},
            context=f"{stap}.isolation_3dcr",
        )
        window = self.start_scan_window((f"{prefix}_tdo_oen", f"{n_prefix}_tdo_oen"))
        await self.stap_chain_maintain(dbg_disable={disable_field: 1}, context=f"{stap}.isolation_observe")
        self.check_scan_window(
            window,
            active=(f"{n_prefix}_tdo_oen",),
            quiet=(f"{prefix}_tdo_oen",),
            context=f"{stap}.isolation_window",
        )

        self.log_step(5, "Full recovery: fresh configuration after clearing %s", disable_field)
        await self.enable_all_debug()
        await self.stap_chain_flush(context=f"{stap}.recover_flush")
        await configure(f"{stap}.recover")
        window = self.start_scan_window(watch)
        captured = await self.stap_chain_maintain(context=f"{stap}.recover_observe")
        edges, counts = self.check_scan_window(window, context=f"{stap}.recover_window")
        self.check_stap_forwarding(edges, counts, prefix=prefix, forwarding=True, context=f"{stap}.recover")
        self.check_stap_chain_readback(captured, context=f"{stap}.recover_readback")

        await self.stap_chain_flush(context=f"{stap}.cleanup")
        self.log_summary(
            "STAP select",
            stap=stap,
            disable_field=disable_field,
            gated_update_attempt=attempt,
            isolation_neighbor=neighbor,
        )

    HOST_SCAN_CONTROLS = (
        "jtag_stap_host_select",
        "jtag_stap_host_shift_en",
        "jtag_stap_host_capture_en",
        "jtag_stap_host_update_en",
    )

    async def run_ext_stap_scan(self) -> None:
        self.log_banner("extended STAP scan interface")
        await self.write_ptap_3dcr(config_hold=1, select=1, context="ext.enable")
        window = self.start_scan_window(self.HOST_SCAN_CONTROLS)
        _, enabled = await self.shift_dr_observe(0x2, 2, context="ext.enabled_shift")
        self.check_scan_window(
            window,
            active=("jtag_stap_host_select", "jtag_stap_host_shift_en"),
            context="ext.enabled_window",
        )
        self.check_observable(enabled, "jtag_stap_host_select", 1, context="ext.enabled")

        await self.write_ptap_3dcr(config_hold=0, select=0, context="ext.disable")
        _, disabled = await self.shift_dr_observe(0x0, 2, context="ext.disabled_shift")
        self.log.info(
            "ext.disabled sampled jtag_stap_host_select=%d; RTL keeps scan control active "
            "during PTAP scan activity and uses PTAP_3DCR select for data routing",
            disabled["jtag_stap_host_select"],
        )

        await self.write_ptap_3dcr(config_hold=1, select=1, context="ext.gate_enable")
        await self.disable_debug_bits("stap_host")
        window = self.start_scan_window(self.HOST_SCAN_CONTROLS)
        # Seeded per-pass gated attempt: any value with the select bit set is
        # an equally valid attempt that must be ignored while gated.
        gated_attempt = self.rng("ext_stap_gate").choice([0x2, 0x3])
        _, gated = await self.shift_dr_observe(gated_attempt, 2, context="ext.host_gated_shift")
        self.check_scan_window(
            window,
            quiet=self.HOST_SCAN_CONTROLS,
            context="ext.host_gated_window",
        )
        self.check_observable(gated, "jtag_stap_host_select", 0, context="ext.host_gated")

        # Recovery without reset: normal host scan control resumes once the
        # disable clears.
        await self.enable_all_debug()
        window = self.start_scan_window(self.HOST_SCAN_CONTROLS)
        _, recovered = await self.shift_dr_observe(0x2, 2, context="ext.recover_shift")
        self.check_scan_window(
            window,
            active=("jtag_stap_host_select", "jtag_stap_host_shift_en"),
            context="ext.recover_window",
        )
        self.check_observable(recovered, "jtag_stap_host_select", 1, context="ext.recover")
        self.log_summary(
            "extended STAP scan",
            checked=("enable", "disable", "stap_host gate window", "recover without reset"),
        )

    async def _config_hold_preserve(self) -> None:
        await self.write_ptap_3dcr(config_hold=1, select=0, context="config_hold.preserve_write")
        await self.apply_tlr()
        preserved = await self.read_ptap_3dcr(shift_value=0x1)
        self.assert_equal("config_hold.ptap_config_preserved", preserved & 0x1, 0x1)

    async def _config_hold_tlr_clear(self) -> None:
        await self.write_ptap_3dcr(config_hold=0, select=1, context="config_hold.clear_write")
        await self.apply_tlr()
        cleared = await self.read_ptap_3dcr(shift_value=0x0)
        self.assert_equal("config_hold.ptap_cleared", cleared & 0x3, 0x0)

    async def _config_hold_trst_clear(self) -> None:
        await self.write_ptap_3dcr(config_hold=1, select=0, context="config_hold.trst_write")
        await self.apply_trst()
        trst_cleared = await self.read_ptap_3dcr(shift_value=0x0)
        self.assert_equal("config_hold.ptap_trst_cleared", trst_cleared & 0x3, 0x0)

    async def run_config_hold(self) -> None:
        self.log_banner("PTAP/STAP CONFIG_HOLD behavior")
        # Seeded per-pass order: each self-contained sub-case starts with its
        # own 3DCR write and reset, so each loop proves a different sequencing
        # of preserve/clear behavior.
        cases = [
            self._config_hold_preserve,
            self._config_hold_tlr_clear,
            self._config_hold_trst_clear,
        ]
        self.rng("config_hold_order").shuffle(cases)
        for case in cases:
            await case()
        self.log_summary(
            "CONFIG_HOLD",
            ptap_cases=("config_preserve", "tlr_clear", "trst_clear"),
            note="PTAP select=1 routes TDO to the STAP path, so PTAP readback uses select=0.",
        )

    async def run_tms_hold(self) -> None:
        self.log_banner("STAP TMS_HOLD behavior")
        # Seeded per-pass STAP order: each loop walks the ports differently.
        staps = list(STAP_ORDER)
        self.rng("tms_hold_order").shuffle(staps)
        for stap in staps:
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

