# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""STAP/3DCR scan scenarios.

``stap_sel_{ds,smc,sep,extra}`` configure and select one STAP through
composed TAP_3DCR chain scans and prove it end to end against the downstream
``ocah_jtag_vip`` TAP the bench splices behind every STAP host port: the
downstream IDCODE and a written ``DS_TDR`` read back through the selected
STAP, the port's direct disable freezes the downstream register in
Test-Logic-Reset and blocks a gated 3DCR update, selection resumes without
reset, an unrelated STAP's downstream stays usable while the target is gated,
and a fresh configuration recovers fully. The host-port temporal windows
(``tdo_oen`` pulses, ``tms`` follows the live TMS or parks) corroborate the
downstream evidence. On a bench without attached downstream TAPs the same
flow runs against the wire loopbacks with the window and chain-readback
evidence only.

``config_hold`` and ``tms_hold`` drive STAP 3DCRs through composed TAP_3DCR
chain scans and judge the chain readback against the model: ``config_hold``
proves which fields survive Test-Logic-Reset per CONFIG_HOLD polarity (and
that TRST clears them at either polarity), ``tms_hold`` proves the parked
host TMS polarity of a deselected STAP through the host-port window, then
writes every 3DCR payload to all four STAPs and proves each port forwards
while its select is set and parks at its TMS_HOLD otherwise, and parks at
its stored TMS_HOLD under the four STAP disables.
``ext_stap_scan`` proves the extended STAP host scan interface against the
host segment the bench places behind it: the host scan controls and the PTAP
chain return follow the PTAP 3DCR select and ``stap_host``, and recover
without reset.
``stap_chain_hold`` proves that IR and DR scans under IDCODE and BYPASS leave
the STAP chain untouched while the PTAP 3DCR select is clear.
"""

from __future__ import annotations

from env.dtp_dbg_disable import STAP_DISABLE
from env.dtp_ijtag_sib_model import SCAN_MARKER_WIDTH
from env.dtp_stap_3dcr_model import STAP_HOST_SEGMENT_WIDTH, STAP_ORDER, DtpStap3dcrState
from env.dtp_stap_ds_agent import STAP_DS_TDR_NAME
from env.dtp_types import DTP_IR_WIDTH, DtpJtagInstr
from ocah_jtag_vip import OcahJtagState

from .dtp_jtag_base_test_seq import SCAN_LENGTH_CHECK_IDS
from .dtp_scan_base_test_seq import dtp_scan_base_test_seq


class dtp_stap_scan_test_seq(dtp_scan_base_test_seq):
    """Run one STAP/3DCR scenario selected by the public wrapper."""

    STAP_BY_SCENARIO = {
        "stap_sel_ds": "io",
        "stap_sel_smc": "smc",
        "stap_sel_sep": "sep",
        "stap_sel_extra": "extra0",
    }

    # Per-pass evidence every pass must record (SV-UVM twin:
    # dtp_stap_scan_test_seq.svh); the CHK-DS-* and CHK-SLAVE-* IDs need an
    # attached downstream TAP and are required only when the bench has one.
    STAP_SEL_REQUIRED_IDS = frozenset({"CHK-TAP-RESET-TLR", "CHK-SCAN-WIN", "CHK-SCAN-CHAIN"})
    STAP_SEL_DS_REQUIRED_IDS = frozenset(
        {
            "CHK-DS-IDCODE",
            "CHK-DS-TDR-READBACK",
            "CHK-DS-TDR-HOLD",
            "CHK-DS-PARKED-TLR",
            "CHK-DS-TDR-RESUME",
            "CHK-SLAVE-DR-UPDATE",
            "CHK-SLAVE-DR-UPDATE-COUNT",
        }
    )
    SCENARIO_REQUIRED_IDS = {
        "ext_stap_scan": frozenset(
            {"CHK-TAP-RESET-TLR", "CHK-SCAN-WIN", "CHK-SCAN-CHAIN", "CHK-SCAN-OBS"}
        ),
        "config_hold": frozenset({"CHK-TAP-RESET-TLR", "CHK-SCAN-CHAIN", "CHK-SCAN-OBS"}),
        "tms_hold": frozenset({"CHK-TAP-RESET-TLR", "CHK-SCAN-WIN", "CHK-SCAN-CHAIN"}),
        "stap_chain_hold": frozenset({"CHK-TAP-RESET-TLR", "CHK-SCAN-WIN", "CHK-SCAN-CHAIN"}),
    }

    def __init__(self, name: str = "dtp_stap_scan_test_seq", *, scenario: str, **kwargs) -> None:
        super().__init__(name, **kwargs)
        self.scenario = scenario

    def required_ids(self) -> set[str]:
        """Evidence IDs this pass must record, per scenario and bench attachment."""
        target = self.STAP_BY_SCENARIO.get(self.scenario)
        if target is None:
            if self.scenario not in self.SCENARIO_REQUIRED_IDS:
                raise ValueError(f"unknown STAP scenario {self.scenario}")
            return set(self.SCENARIO_REQUIRED_IDS[self.scenario])
        required = set(self.STAP_SEL_REQUIRED_IDS)
        if target in self.cfg.stap_ds_attach:
            required |= self.STAP_SEL_DS_REQUIRED_IDS
        return required

    async def body(self) -> None:
        await self.attach_family_checker(self.required_ids() | SCAN_LENGTH_CHECK_IDS)
        self.attach_downstream_taps()
        await self.enable_all_debug()
        await self.reset_to_tlr()
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
            case "stap_chain_hold":
                await self.run_stap_chain_hold()
            case _:
                raise ValueError(f"unknown STAP scenario {self.scenario}")
        await self.enable_all_debug()
        await self.write_ptap_3dcr(config_hold=0, select=0, context="cleanup")
        await self.finalize_family_checker()

    SELECTED_PAYLOAD = {"config_hold": 1, "stap_sel": 1, "tms_hold": 1}

    async def run_stap_select(self, stap: str) -> None:
        self.log_banner(f"STAP selection: {stap}")
        prefix = self.stap_signal_prefix(stap)
        watch = self.stap_forwarding_watch(stap)
        disable_field = STAP_DISABLE[stap]
        rng = self.rng(f"stap_gate_{stap}")
        neighbor = STAP_ORDER[(STAP_ORDER.index(stap) + 1) % len(STAP_ORDER)]
        n_prefix = self.stap_signal_prefix(neighbor)
        tdr = STAP_DS_TDR_NAME
        downstream = self.ds_attached(stap)
        ds_seq = self.stap_ds_seq(stap) if downstream else None
        tdr_width = self.stap_model.downstream[stap].reg(tdr).width if downstream else 0
        ds_rng = self.rng(f"stap_ds_{stap}")
        # Per-pass random downstream values: selected, isolation neighbor, recovery.
        v_select = ds_rng.getrandbits(tdr_width) if downstream else None
        v_recover = ds_rng.getrandbits(tdr_width) if downstream else None

        async def configure(context: str, dbg: dict[str, int] | None = None) -> None:
            """Open the STAP's SIB, then write its 3DCR to SELECTED_PAYLOAD."""
            await self.stap_chain_write(
                ptap_select=1,
                ptap_config_hold=1,
                sib_en={stap: 1},
                dbg_disable=dbg,
                context=f"{context}.open_sib",
            )
            await self.stap_chain_write(
                payloads={stap: self.SELECTED_PAYLOAD},
                dbg_disable=dbg,
                context=f"{context}.write_3dcr",
            )

        async def ds_write_and_readback(
            target: str,
            value: int,
            *,
            context: str,
            dbg: dict[str, int] | None = None,
            check_id: str = "CHK-DS-TDR-READBACK",
        ) -> None:
            """Load DS_TDR, write ``value``, prove the device latched exactly it
            once, then read it back through the chain (``dbg`` is the disable
            mask in force, which shapes the composed chain)."""
            seq = self.stap_ds_seq(target)
            await self.stap_ds_load_ir(target, tdr, dbg_disable=dbg, context=f"{context}.load_ir")
            seq.clear_updates()
            await self.stap_ds_write_tdr(target, value, dbg_disable=dbg, context=f"{context}.write")
            seq.check_last_update(tdr, self.ds_expected(value), context=f"{context} stap={target}")
            seq.check_update_count(
                self.ds_expected(1), reg_name=tdr, context=f"{context} stap={target}"
            )
            await self.stap_ds_read_tdr(
                target, check_id=check_id, dbg_disable=dbg, context=f"{context}.read"
            )

        self.log_step(1, "Configure and select %s via composed TAP_3DCR scans", stap)
        await self.stap_chain_flush(context=f"{stap}.flush")
        await configure(f"{stap}.select")
        window = self.start_scan_window(watch)
        captured = await self.stap_chain_maintain(context=f"{stap}.observe")
        edges, counts = self.check_scan_window(window, context=f"{stap}.selected_window")
        self.check_stap_forwarding(
            edges, counts, stap=stap, forwarding=True, context=f"{stap}.selected"
        )
        self.check_stap_chain_readback(captured, context=f"{stap}.selected_readback")
        if downstream:
            # End-to-end: the downstream IDCODE (selected since TRST) returns
            # through the spliced port, then a written DS_TDR reads back.
            await self.check_ds_idcode(stap, context=f"{stap}.selected_idcode")
            await ds_write_and_readback(stap, v_select, context=f"{stap}.selected_tdr")

        self.log_step(
            2, "Assert exactly %s: forwarding stops, gated update is ignored", disable_field
        )
        if downstream:
            # Step 1 leaves the device in Run-Test/Idle, in lockstep with the
            # PTAP, so the park has to move it into Test-Logic-Reset.
            ds_seq.check_state(
                self.ds_expected_state(OcahJtagState.RUN_TEST_IDLE),
                check_id="CHK-DS-PARKED-TLR",
                context=f"{stap}.pre_gate",
            )
        trst_n = f"{prefix}_trst_n"
        trst_count = f"{prefix}_trst_assert_count"
        trst_before = self.cfg.tb_if.sample(trst_count)
        await self.disable_debug_bits(disable_field)
        # A randomized deselecting payload attempted while gated must be ignored.
        attempt = {"config_hold": rng.randrange(0, 2), "stap_sel": 0, "tms_hold": 0}
        self.log.info("%s gated 3DCR update attempt %s", stap, attempt)
        if downstream:
            ds_seq.clear_updates()
        window = self.start_scan_window(watch + (trst_n,))
        captured = await self.stap_chain_write(
            payloads={stap: attempt},
            dbg_disable={disable_field: 1},
            context=f"{stap}.gated_update_attempt",
        )
        edges, counts = self.check_scan_window(window, context=f"{stap}.gated_window")
        trst_asserts = self.cfg.tb_if.sample(trst_count) - trst_before
        self.check_stap_forwarding(
            edges, counts, stap=stap, forwarding=False, context=f"{stap}.gated"
        )
        self.family_check(
            "CHK-SCAN-WIN",
            f"{trst_n} deasserted",
            counts[trst_n],
            edges,
            context=f"{stap}.gated edges={edges}",
        )
        self.family_check(
            "CHK-SCAN-WIN",
            f"{trst_n} not asserted across the gate",
            trst_asserts,
            0,
            context=f"{stap}.gated asserts={trst_asserts}",
        )
        self.check_stap_chain_readback(
            captured, dbg_disable={disable_field: 1}, context=f"{stap}.gated_readback"
        )
        if downstream:
            # The gated port parks its host TMS high with TRST deasserted. The
            # disable settle and the gated scan clock the parked TMS, walking
            # the downstream TAP from Run-Test/Idle into Test-Logic-Reset,
            # checked after the scan; it latches nothing and keeps the written
            # value.
            ds_seq.check_update_count(self.ds_expected(0), reg_name=tdr, context=f"{stap}.gated")
            ds_seq.check_register(
                tdr, self.ds_expected(v_select), check_id="CHK-DS-TDR-HOLD", context=f"{stap}.gated"
            )
            ds_seq.check_state(
                self.ds_expected_state(OcahJtagState.TEST_LOGIC_RESET),
                check_id="CHK-DS-PARKED-TLR",
                context=f"{stap}.gated",
            )

        self.log_step(
            3, "Clear %s without reset: selection resumes from stored state", disable_field
        )
        await self.enable_all_debug()
        if downstream:
            await self.settle_stap_release()
        window = self.start_scan_window(watch)
        captured = await self.stap_chain_maintain(context=f"{stap}.resume")
        edges, counts = self.check_scan_window(window, context=f"{stap}.resume_window")
        self.check_stap_forwarding(
            edges, counts, stap=stap, forwarding=True, context=f"{stap}.resume"
        )
        self.check_stap_chain_readback(captured, context=f"{stap}.resume_readback")
        if downstream:
            # Live splice and park-reset proven: the downstream answers IDCODE
            # again; reloading DS_TDR reads the pre-gate value.
            await self.check_ds_idcode(stap, context=f"{stap}.resume_idcode")
            await self.stap_ds_load_ir(stap, tdr, context=f"{stap}.resume_load_ir")
            await self.stap_ds_read_tdr(
                stap, check_id="CHK-DS-TDR-RESUME", context=f"{stap}.resume_tdr"
            )

        self.log_step(
            4, "With %s re-asserted, unrelated STAP %s stays usable", disable_field, neighbor
        )
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
        captured = await self.stap_chain_maintain(
            dbg_disable={disable_field: 1}, context=f"{stap}.isolation_observe"
        )
        self.check_scan_window(
            window,
            active=(f"{n_prefix}_tdo_oen",),
            quiet=(f"{prefix}_tdo_oen",),
            context=f"{stap}.isolation_window",
        )
        self.check_stap_chain_readback(
            captured, dbg_disable={disable_field: 1}, context=f"{stap}.isolation_readback"
        )
        if downstream:
            ds_seq.clear_updates()
        if self.ds_attached(neighbor):
            n_width = self.stap_model.downstream[neighbor].reg(tdr).width
            await ds_write_and_readback(
                neighbor,
                ds_rng.getrandbits(n_width),
                context=f"{stap}.isolation_neighbor",
                dbg={disable_field: 1},
            )
        if downstream:
            ds_seq.check_update_count(
                self.ds_expected(0), reg_name=tdr, context=f"{stap}.isolation"
            )

        self.log_step(5, "Full recovery: fresh configuration after clearing %s", disable_field)
        await self.enable_all_debug()
        if downstream:
            await self.settle_stap_release()
        await self.stap_chain_flush(context=f"{stap}.recover_flush")
        await configure(f"{stap}.recover")
        window = self.start_scan_window(watch)
        captured = await self.stap_chain_maintain(context=f"{stap}.recover_observe")
        edges, counts = self.check_scan_window(window, context=f"{stap}.recover_window")
        self.check_stap_forwarding(
            edges, counts, stap=stap, forwarding=True, context=f"{stap}.recover"
        )
        self.check_stap_chain_readback(captured, context=f"{stap}.recover_readback")
        if downstream:
            await ds_write_and_readback(stap, v_recover, context=f"{stap}.recover_tdr")

        await self.stap_chain_flush(context=f"{stap}.cleanup")
        self.log_summary(
            "STAP select",
            stap=stap,
            disable_field=disable_field,
            gated_update_attempt=attempt,
            isolation_neighbor=neighbor,
            downstream_tap=downstream,
            ds_tdr_values=(v_select, v_recover) if downstream else None,
        )

    async def run_ext_stap_scan(self) -> None:
        """Four legs of composed TAP_3DCR scans, each back in Run-Test/Idle
        and none followed by a reset once the chain is flushed. Ungated, the
        host segment is the chain return at the TDO end; gated, the last
        STAP's scan-out returns instead and the segment holds its value. The
        segment value is non-zero, so a gated scan that reached the segment
        would latch the zeros composed at its position and fail the release
        leg."""
        self.log_banner("extended STAP scan interface")
        assert self.stap_model.host_segment_attached, "the bench has no host segment attached"
        rng = self.rng("ext_stap")
        segment = rng.randrange(1, 1 << STAP_HOST_SEGMENT_WIDTH)
        marker = rng.getrandbits(SCAN_MARKER_WIDTH) | (1 << (SCAN_MARKER_WIDTH - 1))
        gate_hold = rng.randrange(2)
        gate = {"stap_host": 1}
        controls = self.HOST_SCAN_CONTROLS
        self.log.info(
            "ext host segment=0x%02x marker=0x%04x gate config_hold=%d", segment, marker, gate_hold
        )

        self.log_step(1, "PTAP_3DCR.SELECT=1: the host segment returns the chain")
        await self.stap_chain_flush(context="ext.flush")
        await self.stap_chain_write(
            ptap_select=1, ptap_config_hold=1, host_segment=segment, context="ext.enable"
        )
        window = self.start_scan_window(controls)
        captured = await self.stap_chain_maintain(marker=marker, context="ext.enabled_observe")
        self.check_scan_window(window, active=controls, context="ext.enabled_window")
        self.check_stap_chain_readback(captured, context="ext.enabled_readback")
        self.check_stap_chain_marker(captured, marker, context="ext.enabled_marker")

        self.log_step(2, "PTAP_3DCR.SELECT=0: TDO carries the PTAP 3DCR, the controls stay quiet")
        await self.stap_chain_write(ptap_select=0, context="ext.deselect")
        window = self.start_scan_window(controls)
        await self.read_ptap_3dcr_deselected(marker=marker, context="ext.deselected_readback")
        self.check_scan_window(window, quiet=controls, context="ext.deselected_window")

        self.log_step(3, "stap_host gated: the controls stay quiet and scan-in is bypassed")
        await self.stap_chain_write(
            ptap_select=1, ptap_config_hold=gate_hold, context="ext.gate_enable"
        )
        await self.disable_debug_bits("stap_host")
        window = self.start_scan_window(controls)
        captured = await self.stap_chain_maintain(
            dbg_disable=gate, marker=marker, context="ext.gated_observe"
        )
        self.check_scan_window(window, quiet=controls, context="ext.gated_window")
        self.check_stap_chain_readback(captured, dbg_disable=gate, context="ext.gated_readback")
        self.check_stap_chain_marker(captured, marker, dbg_disable=gate, context="ext.gated_marker")

        self.log_step(4, "stap_host released without reset: the segment returns its value")
        await self.enable_all_debug()
        window = self.start_scan_window(controls)
        captured = await self.stap_chain_maintain(marker=marker, context="ext.recover_observe")
        self.check_scan_window(window, active=controls, context="ext.recover_window")
        self.check_stap_chain_readback(captured, context="ext.recover_readback")
        self.check_stap_chain_marker(captured, marker, context="ext.recover_marker")
        self.log_summary(
            "extended STAP scan",
            host_segment=f"0x{segment:02x}",
            gate_config_hold=gate_hold,
            checked=("enable", "deselect", "stap_host gate", "recover without reset"),
        )

    # --- CONFIG_HOLD across Test-Logic-Reset and TRST --------------------------
    async def _config_hold_case(self, stap: str, hold: int, reset: str) -> None:
        """Program the PTAP 3DCR (select=1, config_hold=hold) and one STAP's
        3DCR (config_hold=hold, seeded select, tms_hold=1), apply ``reset``,
        and read every field back through composed chain scans against the
        model: with hold=1 a Test-Logic-Reset keeps the PTAP select and the
        STAP select/tms_hold, with hold=0 it clears them, and TRST clears
        them all."""
        ctx = f"config_hold.{stap}.hold{hold}.{reset}"
        rng = self.rng(ctx)
        payload = {"config_hold": hold, "stap_sel": rng.randrange(2), "tms_hold": 1}
        marker = rng.getrandbits(SCAN_MARKER_WIDTH) | (1 << (SCAN_MARKER_WIDTH - 1))
        self.log.info("%s STAP payload=%s", ctx, payload)
        await self.stap_chain_flush(context=f"{ctx}.flush")
        await self.stap_chain_write(
            ptap_select=1, ptap_config_hold=hold, sib_en={stap: 1}, context=f"{ctx}.open_sib"
        )
        await self.stap_chain_write(payloads={stap: payload}, context=f"{ctx}.write_3dcr")
        if reset == "tlr":
            await self.apply_tlr()
        else:
            await self.apply_trst()
        # The reset leaves IDCODE in the IR. While the PTAP select is set every
        # IR scan shifts through the STAP chain, so TAP_3DCR is reloaded with a
        # composed IR scan that rewrites the chain image it passes through.
        await self.stap_chain_ir_write(context=f"{ctx}.reload_ir")
        if self.stap_model.ptap_select:
            captured = await self.stap_chain_maintain(context=f"{ctx}.ptap_readback")
            self.check_stap_chain_readback(captured, context=f"{ctx}.ptap_readback")
        else:
            await self.read_ptap_3dcr_deselected(marker=marker, context=f"{ctx}.ptap_readback")
        # Re-select and reopen the SIB: the STAP's 3DCR fields join the chain
        # and read back as the model predicts after the reset.
        await self.stap_chain_write(ptap_select=1, sib_en={stap: 1}, context=f"{ctx}.reopen_sib")
        captured = await self.stap_chain_maintain(context=f"{ctx}.stap_readback")
        self.check_stap_chain_readback(captured, context=f"{ctx}.stap_readback")
        self.log.info(
            "%s after %s: ptap select=%d config_hold=%d stap=%s",
            ctx,
            reset,
            self.stap_model.ptap_select,
            self.stap_model.ptap_config_hold,
            self.stap_model.staps[stap],
        )

    async def run_config_hold(self) -> None:
        self.log_banner("PTAP/STAP CONFIG_HOLD across Test-Logic-Reset and TRST")
        rng = self.rng("config_hold_order")
        staps = list(STAP_ORDER)
        rng.shuffle(staps)
        for idx, stap in enumerate(staps, start=1):
            # Seeded per-pass order: each self-contained sub-case starts from
            # a flushed chain, so each loop proves a different sequencing of
            # preserve/clear behavior.
            cases = [(1, "tlr"), (0, "tlr"), (1, "trst"), (0, "trst")]
            rng.shuffle(cases)
            self.log_iteration(idx, len(staps), "STAP %s cases=%s", stap, cases)
            for step, (hold, reset) in enumerate(cases, start=1):
                self.log_step(
                    step, "STAP %s: CONFIG_HOLD=%d, then %s, then read back", stap, hold, reset
                )
                await self._config_hold_case(stap, hold, reset)
        self.log_summary(
            "CONFIG_HOLD", staps=staps, cases=("hold1+tlr", "hold0+tlr", "hold1+trst", "hold0+trst")
        )

    # --- TMS_HOLD parked polarity ------------------------------------------------
    async def _tms_hold_case(self, stap: str, hold: int) -> None:
        """Select the STAP with tms_hold=hold and prove the selected port
        forwards under the window the parked leg reuses (the positive control
        of the deny that follows), deselect it, then prove the deselected port
        drives its host TMS at that polarity for the whole maintain scan while
        tdo_oen stays quiet, and that the 3DCR reads back as written."""
        ctx = f"tms_hold.{stap}.hold{hold}"
        watch = self.stap_forwarding_watch(stap)
        await self.stap_chain_flush(context=f"{ctx}.flush")
        await self.stap_chain_write(ptap_select=1, sib_en={stap: 1}, context=f"{ctx}.open_sib")
        await self.stap_chain_write(
            payloads={stap: {"stap_sel": 1, "tms_hold": hold}}, context=f"{ctx}.select"
        )
        window = self.start_scan_window(watch)
        captured = await self.stap_chain_maintain(context=f"{ctx}.selected_observe")
        edges, counts = self.check_scan_window(window, context=f"{ctx}.selected_window")
        self.check_stap_forwarding(
            edges, counts, stap=stap, forwarding=True, context=f"{ctx}.selected"
        )
        self.check_stap_chain_readback(captured, context=f"{ctx}.selected_readback")
        await self.stap_chain_write(
            payloads={stap: {"stap_sel": 0, "tms_hold": hold}}, context=f"{ctx}.deselect"
        )
        window = self.start_scan_window(watch)
        captured = await self.stap_chain_maintain(context=f"{ctx}.observe")
        edges, counts = self.check_scan_window(window, context=f"{ctx}.window")
        self.check_stap_forwarding(
            edges, counts, stap=stap, forwarding=False, context=f"{ctx}.parked"
        )
        self.check_stap_chain_readback(captured, context=f"{ctx}.readback")

    async def run_tms_hold(self) -> None:
        self.log_banner("STAP TMS_HOLD parked polarity")
        rng = self.rng("tms_hold_order")
        # Seeded per-pass STAP and polarity order: each loop walks the ports
        # and the two parked polarities differently.
        staps = list(STAP_ORDER)
        rng.shuffle(staps)
        for idx, stap in enumerate(staps, start=1):
            polarities = [1, 0]
            rng.shuffle(polarities)
            self.log_iteration(idx, len(staps), "STAP %s tms_hold order=%s", stap, polarities)
            for step, hold in enumerate(polarities, start=1):
                self.log_step(
                    step, "STAP %s: select (forwarding), deselect with TMS_HOLD=%d", stap, hold
                )
                await self._tms_hold_case(stap, hold)
        await self._payload_sweep()
        self.log_summary("TMS_HOLD", staps=staps, polarities=(1, 0), payload_rounds=8)

    async def _payload_sweep(self) -> None:
        """Every 3DCR payload on every STAP, enabled and under the STAP
        disables. Round ``r`` writes payload ``(r + i) % 8`` (bit 0
        config_hold, bit 1 stap_sel, bit 2 tms_hold) to the i-th STAP in one
        composed scan. Enabled, a port forwards while its select is set and
        otherwise parks at its tms_hold; with the four STAP disables asserted
        every port parks at its stored tms_hold. Both chain readbacks match
        the model."""
        watch = tuple(sig for name in STAP_ORDER for sig in self.stap_forwarding_watch(name))
        gate = {STAP_DISABLE[name]: 1 for name in STAP_ORDER}
        rounds = list(range(8))
        self.rng("tms_hold_payload_sweep").shuffle(rounds)
        self.log.info("STAP 3DCR payload sweep, round order %s", rounds)
        await self.stap_chain_flush(context="sweep.flush")
        await self.stap_chain_write(
            ptap_select=1, sib_en={name: 1 for name in STAP_ORDER}, context="sweep.open_sibs"
        )
        for step, r in enumerate(rounds, start=1):
            ctx = f"sweep.round{r}"
            payloads = {
                name: vars(DtpStap3dcrState.from_value((r + idx) % 8))
                for idx, name in enumerate(STAP_ORDER)
            }
            self.log_step(step, "STAP 3DCR payloads %s, enabled then gated", payloads)
            await self.stap_chain_write(payloads=payloads, context=f"{ctx}.write")
            window = self.start_scan_window(watch)
            captured = await self.stap_chain_maintain(context=f"{ctx}.observe")
            edges, counts = self.check_scan_window(window, context=f"{ctx}.window")
            for name in STAP_ORDER:
                self.check_stap_forwarding(
                    edges,
                    counts,
                    stap=name,
                    forwarding=bool(payloads[name]["stap_sel"]),
                    context=f"{ctx}.{name}",
                )
            self.check_stap_chain_readback(captured, context=f"{ctx}.readback")
            await self.set_dbg_disable_vector(gate)
            window = self.start_scan_window(watch)
            captured = await self.stap_chain_maintain(dbg_disable=gate, context=f"{ctx}.gated")
            edges, counts = self.check_scan_window(window, context=f"{ctx}.gated_window")
            for name in STAP_ORDER:
                self.check_stap_forwarding(
                    edges, counts, stap=name, forwarding=False, context=f"{ctx}.gated.{name}"
                )
            self.check_stap_chain_readback(
                captured, dbg_disable=gate, context=f"{ctx}.gated_readback"
            )
            await self.enable_all_debug()
        await self.stap_chain_flush(context="sweep.cleanup")

    # --- STAP chain holds while the PTAP select is clear -----------------------
    CHAIN_HOLD_DR_WIDTHS = (3, 4, 8)

    async def run_stap_chain_hold(self) -> None:
        """Scan under IDCODE and BYPASS with the PTAP 3DCR select clear and
        all-ones data, which would open every SIB and select every STAP were
        the chain clocked. No host scan control pulses, no STAP forwards
        (tdo_oen quiet, tms parked at the reset tms_hold of 0), and once the
        select is set on its own the chain reads back with every SIB closed."""
        self.log_banner("STAP chain holds while the PTAP 3DCR select is clear")
        rng = self.rng("stap_chain_hold")
        widths = (*self.CHAIN_HOLD_DR_WIDTHS, rng.randrange(9, 33))
        watch = list(self.HOST_SCAN_CONTROLS)
        for name in STAP_ORDER:
            prefix = self.stap_signal_prefix(name)
            watch += [f"{prefix}_tdo_oen", f"{prefix}_tms"]
        await self.stap_chain_flush(context="hold.flush")
        window = self.start_scan_window(tuple(watch))
        self.log_step(1, "IDCODE DR scans of %s bits", widths)
        await self.load_ir(DtpJtagInstr.IDCODE)
        for width in widths:
            await self.shift_dr(self.bit_mask(width), width)
        self.log_step(2, "BYPASS IR and DR scans of all ones, %s bits", widths)
        await self.shift_ir(self.bit_mask(DTP_IR_WIDTH), DTP_IR_WIDTH)
        for width in widths:
            await self.shift_dr(self.bit_mask(width), width)
        self.check_scan_window(window, quiet=tuple(watch), context="hold.window")
        self.log_step(3, "Set the PTAP select alone, then read the chain back")
        await self.load_ir(DtpJtagInstr.TAP_3DCR)
        await self.stap_chain_write(ptap_select=1, ptap_config_hold=0, context="hold.select")
        captured = await self.stap_chain_maintain(context="hold.readback")
        self.check_stap_chain_readback(captured, context="hold.readback")
        await self.stap_chain_flush(context="hold.cleanup")
        self.log_summary("STAP chain hold", dr_widths=widths)
