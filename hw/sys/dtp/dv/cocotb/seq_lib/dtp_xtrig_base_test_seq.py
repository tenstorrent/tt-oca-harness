# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared XTRIG helpers and full VPLAN scenario sequences."""

from __future__ import annotations

from cocotb.triggers import ClockCycles, ReadOnly
from env.dtp_xtrig_agent import DtpXtrigActivityWindow
from env.dtp_xtrig_types import (
    XTRIG_CTM_SELECT_MASK,
    XTRIG_CTP_CONFIG_MASK,
    XTRIG_CTP_MODE_P2P,
    XTRIG_CTP_MODE_WIRE_OR,
    XTRIG_CTP_STATUS_BUSY,
    XTRIG_CTP_STATUS_REQ_OUT,
    XTRIG_CTP_STRETCH_MASK,
    XTRIG_NUM_CTM_PORTS,
    XTRIG_NUM_CTP,
    XTRIG_NUM_INT_CT,
    XTRIG_UNMAPPED_BASE,
    DtpCtmRefModel,
    apply_wstrb,
    ctm_config_addr,
    ctp_config_addr,
    ctp_mask,
    ctp_status_addr,
    ctp_stretch_addr,
    external_ctp_port,
    internal_ct_mask,
    internal_ct_port,
    pack_ctp_config,
    project_ctp_mask,
    project_internal_mask,
)
from ocah_checker import OcahChecker
from ocah_lib import OcahKnobs

from .dtp_base_test_seq import dtp_base_test_seq


class dtp_xtrig_base_test_seq(dtp_base_test_seq):
    """Helpers and scenario bodies for DTP XTRIG, CTP, and CTM tests.

    ``CT_SRC[k].CONFIG_0.CT_DST_SELECT`` (cross_trigger_matrix.rdl) selects the
    CT_Dst input ports whose pulses are OR'd onto CT_Src output ``k``: CT_Src
    ports are matrix outputs, CT_Dst ports are matrix inputs. The route helpers
    therefore program ``output_port <- input_port_mask`` and log both the VPLAN
    source/destination intent and the concrete CSR mapping.
    """

    AXI_OKAY = 0
    AXI_DECERR = 3
    QUIET_GROUPS = (
        "xtrig_ctm_src_req",
        "xtrig_ctm_dst_ack",
        "xtrig_ctp_req_out_dout_en",
        "xtrig_ctp_ack_out_dout_en",
    )
    # Observables a routed pulse can reach; the activity window ORs them per
    # cycle from before the input pulse until the drain tail ends.
    OUTPUT_SIGNALS = (
        "xtrig_ctm_src_req",
        "xtrig_ctp_req_out_dout",
        "xtrig_ctp_req_out_dout_en",
    )
    # Cycles the window stays open after the last expected output, so a late
    # or stretched pulse on any port is inside it.
    ISOLATION_TAIL_CYCLES = 6

    # Named-evidence IDs recorded by the shared helpers below. finalize() at
    # the end of body() rejects a zero-check run and any missing required ID,
    # so a scenario whose checks were silently skipped fails.
    CHK_CSR = "CHK-XTRIG-CSR"
    CHK_SIGNAL = "CHK-XTRIG-SIGNAL"
    CHK_ROUTE_MODEL = "CHK-XTRIG-ROUTE-MODEL"
    CHK_ISOLATION = "CHK-XTRIG-ISOLATION"
    CHK_QUIET = "CHK-XTRIG-QUIET"
    CHK_STRETCH = "CHK-XTRIG-STRETCH"
    CHK_AXIL = "CHK-XTRIG-AXIL"

    _ROUTE_IDS = (CHK_CSR, CHK_SIGNAL, CHK_ROUTE_MODEL, CHK_ISOLATION)
    SCENARIO_REQUIRED_IDS = {
        "reg_stall": (CHK_CSR, CHK_QUIET, CHK_AXIL),
        "axi_channel_skew": (CHK_CSR, CHK_AXIL),
        "axi_channel_skew_demux_aw_lock_release": (CHK_AXIL,),
        "axi_channel_skew_read_decode_backpressure": (CHK_AXIL,),
        "ctp_csr_sweep": (CHK_CSR,),
        "ctm_csr_sweep": (CHK_CSR,),
        "ctm_all_source_select": (CHK_CSR,),
        "wire_or": (CHK_CSR, CHK_SIGNAL, CHK_STRETCH),
        "p2p": (CHK_CSR, CHK_SIGNAL),
        "random": (CHK_CSR, CHK_SIGNAL),
        "reset": _ROUTE_IDS + (CHK_QUIET,),
        "dst_port_sweep": _ROUTE_IDS,
        "ctm_wire_or_cla_to_ctp": _ROUTE_IDS,
        "ctm_wire_or_ctp_to_cla": _ROUTE_IDS,
        "ctm_wire_or_cla_to_cla": _ROUTE_IDS,
        "ctm_wire_or_ctp_to_ctp": _ROUTE_IDS,
        "ctm_p2p_cla_to_ctp": _ROUTE_IDS,
        "ctm_p2p_ctp_to_cla": _ROUTE_IDS,
        "ctm_p2p_cla_to_cla": _ROUTE_IDS,
        "ctm_p2p_ctp_to_ctp": _ROUTE_IDS,
        "ctm_reset_wire_or_mode": _ROUTE_IDS + (CHK_QUIET,),
        "ctm_reset_p2p_mode": _ROUTE_IDS + (CHK_QUIET,),
        "ctm_reset_all_modes": _ROUTE_IDS + (CHK_QUIET,),
        "ctm_rand_all_scenarios": _ROUTE_IDS,
        "ctm_rand_wire_or_only": _ROUTE_IDS,
        "ctm_rand_p2p_only": _ROUTE_IDS,
        "ctm_rand_cla_to_ctp": _ROUTE_IDS,
        "ctm_rand_ctp_to_cla": _ROUTE_IDS,
    }

    def __init__(
        self,
        name: str = "dtp_xtrig_base_test_seq",
        *,
        scenario: str = "reg_stall",
        **kwargs,
    ) -> None:
        super().__init__(name, **kwargs)
        self.scenario = scenario
        self.ctm_model = DtpCtmRefModel()
        # Named-evidence checker: every route observation, CSR readback, quiet
        # window, and stretch measurement lands one evidence record; body()
        # finalizes so a check-free pass cannot report PASS.
        self.checker = OcahChecker(
            name=f"dtp_xtrig_checker[{name}]",
            required_ids=self.SCENARIO_REQUIRED_IDS.get(scenario, (self.CHK_CSR,)),
            logger=self.log,
        )

    @property
    def axil(self):
        assert self.cfg.xtrig_axil is not None, "XTRIG AXI-Lite BFM is not ready"
        return self.cfg.xtrig_axil

    @property
    def xtrig(self):
        assert self.cfg.xtrig_bfm is not None, "XTRIG GPIO BFM is not ready"
        return self.cfg.xtrig_bfm

    async def body(self) -> None:
        scenario_fn = getattr(self, f"run_{self.scenario}", None)
        if scenario_fn is None:
            raise ValueError(f"unknown XTRIG scenario {self.scenario}")
        await scenario_fn()
        # End-of-sequence enforcement: zero recorded checks or a missing
        # required evidence ID fails the pass — a silently skipped check net
        # cannot report PASS.
        self.checker.finalize()

    def check_evidence(
        self, check_id: str, name: str, observed: int, expected: int, *, context: str = ""
    ) -> None:
        """Record one named evidence comparison (raises on mismatch)."""
        self.checker.expect_equal(check_id, observed, expected, context=f"{name} {context}".strip())

    # ------------------------------------------------------------------
    # CSR helpers
    # ------------------------------------------------------------------
    async def csr_write(self, addr: int, data: int, *, wstrb: int = 0xF, label: str = "") -> int:
        resp = await self.axil.write(addr, data, strb=wstrb)
        self.log.info(
            "XTRIG CSR WRITE %-34s addr=0x%03x data=0x%08x wstrb=0x%x resp=%d",
            label,
            addr,
            data & 0xFFFFFFFF,
            wstrb & 0xF,
            resp,
        )
        self.assert_equal(f"{label or hex(addr)}.bresp", resp, self.AXI_OKAY)
        return resp

    async def csr_read(self, addr: int, *, label: str = "") -> int:
        result = await self.axil.read_result(addr)
        data, resp = result.data, result.resp
        self.log.info(
            "XTRIG CSR READ  %-34s addr=0x%03x data=0x%08x resp=%d",
            label,
            addr,
            data,
            resp,
        )
        self.assert_equal(f"{label or hex(addr)}.rresp", resp, self.AXI_OKAY)
        return data

    async def write_read_check(
        self,
        addr: int,
        data: int,
        expected: int,
        *,
        wstrb: int = 0xF,
        mask: int = 0xFFFFFFFF,
        label: str = "",
    ) -> int:
        await self.csr_write(addr, data, wstrb=wstrb, label=label)
        observed = await self.csr_read(addr, label=label)
        self.check_evidence(
            self.CHK_CSR,
            label or f"csr_0x{addr:x}",
            observed & mask,
            expected & mask,
            context=f"addr=0x{addr:03x} wstrb=0x{wstrb:x}",
        )
        return observed

    async def program_ctp(
        self,
        ctp_idx: int,
        *,
        mode: int = XTRIG_CTP_MODE_WIRE_OR,
        invert: int = 0,
        reset: int = 0,
        stretch: int = 0,
    ) -> None:
        cfg = pack_ctp_config(mode=mode, invert=invert, reset=reset)
        self.cfg.xtrig_ctp_shadow.note(ctp_idx, mode=mode, invert=invert)
        self.log.info(
            "Configure CTP[%d]: mode=%s invert=%d reset=%d stretch=%d",
            ctp_idx,
            "p2p" if mode else "wire_or",
            invert,
            reset,
            stretch,
        )
        await self.write_read_check(
            ctp_config_addr(ctp_idx),
            cfg,
            cfg,
            mask=XTRIG_CTP_CONFIG_MASK,
            label=f"ctp{ctp_idx}.config",
        )
        await self.write_read_check(
            ctp_stretch_addr(ctp_idx),
            stretch,
            stretch,
            mask=XTRIG_CTP_STRETCH_MASK,
            label=f"ctp{ctp_idx}.stretch",
        )

    async def program_ctm_src(self, output_port: int, input_mask: int) -> None:
        input_mask &= XTRIG_CTM_SELECT_MASK
        model_mask = input_mask
        # DTP_XTRIG_CHECKER_NEGATIVE=1 is the documented negative-validation
        # hook: the reference model is programmed with an INVERTED select so
        # CHK-XTRIG-ROUTE-MODEL must fail, proving the model comparison gates
        # pass/fail end to end (route scenarios only).
        if OcahKnobs.is_set("DTP_XTRIG_CHECKER_NEGATIVE"):
            model_mask = (~input_mask) & XTRIG_CTM_SELECT_MASK
            self.log.warning(
                "NEGATIVE VALIDATION: CTM model select 0x%x instead of 0x%x",
                model_mask,
                input_mask,
            )
        self.ctm_model.program(output_port, model_mask)
        await self.write_read_check(
            ctm_config_addr(output_port),
            input_mask,
            input_mask,
            mask=XTRIG_CTM_SELECT_MASK,
            label=f"ctm.output{output_port}.select",
        )

    async def clear_ctm_routes(self) -> None:
        self.ctm_model = DtpCtmRefModel()
        for src_idx in range(XTRIG_NUM_CTM_PORTS):
            await self.csr_write(ctm_config_addr(src_idx), 0, label=f"clear.ctm{src_idx}")

    async def clear_xtrig(self) -> None:
        await self.xtrig.clear_inputs()
        self.cfg.xtrig_ctp_shadow.clear()
        for ctp_idx in range(XTRIG_NUM_CTP):
            await self.csr_write(ctp_config_addr(ctp_idx), 0, label=f"cleanup.ctp{ctp_idx}.cfg")
            await self.csr_write(
                ctp_stretch_addr(ctp_idx), 0, label=f"cleanup.ctp{ctp_idx}.stretch"
            )
        await self.clear_ctm_routes()

    async def pulse_reset(self, cycles: int = 3) -> None:
        """System reset with idle inputs; every XTRIG CSR returns to its reset value."""
        await self.xtrig.pulse_reset(cycles=cycles)
        self.ctm_model = DtpCtmRefModel()
        self.cfg.xtrig_ctp_shadow.clear()

    # ------------------------------------------------------------------
    # Protocol helpers
    # ------------------------------------------------------------------
    @staticmethod
    def is_ctp_port(port: int) -> bool:
        return 0 <= port < XTRIG_NUM_CTP

    @staticmethod
    def int_idx_from_port(port: int) -> int:
        return port - XTRIG_NUM_CTP

    async def sample_xtrig(self, label: str) -> dict[str, int]:
        sample = await self.xtrig.sample()
        self.log.info(
            "XTRIG SAMPLE %-28s ctm_src_req=0x%03x req_out_en=0x%04x req_out=0x%04x ack_out=0x%04x",
            label,
            sample.get("xtrig_ctm_src_req", 0),
            sample.get("xtrig_ctp_req_out_dout_en", 0),
            sample.get("xtrig_ctp_req_out_dout", 0),
            sample.get("xtrig_ctp_ack_out_dout", 0),
        )
        return sample

    async def wait_signal_mask(
        self,
        name: str,
        mask: int,
        expected: int,
        *,
        cycles: int = 60,
        label: str = "",
    ) -> int:
        observed = 0
        for _ in range(cycles):
            await ReadOnly()
            observed = self.xtrig.sample_signal(name) & mask
            await ClockCycles(self.xtrig.clk, 1)
            if observed == (expected & mask):
                self.log.info("Observed %s mask=0x%x expected=0x%x %s", name, mask, expected, label)
                break
        else:
            await ReadOnly()
            observed = self.xtrig.sample_signal(name) & mask
        self.check_evidence(
            self.CHK_SIGNAL, f"{name}.mask", observed, expected & mask, context=label
        )
        return observed

    async def check_quiet(self, label: str, *, cycles: int = 4) -> None:
        activity = await self.xtrig.assert_quiet(self.QUIET_GROUPS, cycles=cycles)
        for name, value in activity.items():
            self.check_evidence(
                self.CHK_QUIET, f"quiet.{label}.{name}", value, 0, context=f"cycles={cycles}"
            )

    async def configure_ctp_mode_for_port(self, port: int, mode: int, *, stretch: int = 1) -> None:
        """Program an external CTP port for a route; internal ports have no CONFIG."""
        if not self.is_ctp_port(port):
            return
        if mode == XTRIG_CTP_MODE_P2P:
            # The handshake sender latches every delivered trigger whatever the
            # mode, and only an acknowledge or CONFIG.RESET releases it, so a
            # port entering P2P mode would otherwise present a request left
            # pending from wire-OR routing. RESET is a level: assert, then program.
            await self.csr_write(
                ctp_config_addr(port),
                pack_ctp_config(mode=mode, reset=1),
                label=f"ctp{port}.handshake_reset",
            )
        await self.program_ctp(port, mode=mode, stretch=stretch)

    async def configure_ctp_modes_for_route(
        self, input_port: int, output_mask: int, mode: int
    ) -> None:
        await self.configure_ctp_mode_for_port(input_port, mode, stretch=1)
        for port in range(XTRIG_NUM_CTM_PORTS):
            if (output_mask >> port) & 1:
                await self.configure_ctp_mode_for_port(port, mode, stretch=1)

    async def program_route(self, input_port: int, output_mask: int, *, label: str) -> None:
        self.log.info(
            "Program CTM route %-20s input_port=%d output_mask=0x%08x (CSR output selects input)",
            label,
            input_port,
            output_mask,
        )
        await self.clear_ctm_routes()
        for output_port in range(XTRIG_NUM_CTM_PORTS):
            if (output_mask >> output_port) & 1:
                await self.program_ctm_src(output_port, 1 << input_port)

    async def drive_input_port(self, input_port: int, mode: int, *, cycles: int = 2) -> None:
        if self.is_ctp_port(input_port):
            if mode == XTRIG_CTP_MODE_P2P:
                await self.xtrig.drive_ctp_p2p_req_in(input_port, 1)
                await ClockCycles(self.xtrig.clk, cycles)
                await self.xtrig.drive_ctp_p2p_req_in(input_port, 0)
            else:
                await self.xtrig.drive_ctp_req_out_din_pulse(input_port, cycles=cycles)
        else:
            await self.xtrig.drive_internal_dst_pulse(
                self.int_idx_from_port(input_port), cycles=cycles
            )

    def _ctp_p2p_mask(self) -> int:
        return self.cfg.xtrig_ctp_shadow.p2p_mask

    def _ctp_invert_mask(self) -> int:
        return self.cfg.xtrig_ctp_shadow.invert_mask

    def fired_vector(self, activity: dict[str, int], hold: dict[str, int]) -> int:
        """CTM-port vector of every output that requested at some cycle of the window.

        A wire-OR CTP requests through its output enable; a P2P CTP through its
        request level, which idles low (or high when inverted). Internal ports
        request through ``xtrig_ctm_src_req``.
        """
        all_ctp = (1 << XTRIG_NUM_CTP) - 1
        p2p = self._ctp_p2p_mask()
        inverted = self._ctp_invert_mask()
        dout_any = activity.get("xtrig_ctp_req_out_dout", 0)
        dout_all = hold.get("xtrig_ctp_req_out_dout", 0)
        p2p_fired = ((dout_any & ~inverted) | (~dout_all & inverted)) & p2p
        wire_or_fired = activity.get("xtrig_ctp_req_out_dout_en", 0) & ~p2p
        int_fired = activity.get("xtrig_ctm_src_req", 0) & ((1 << XTRIG_NUM_INT_CT) - 1)
        return ((p2p_fired | wire_or_fired) & all_ctp) | (int_fired << XTRIG_NUM_CTP)

    def level_vector(self, sample: dict[str, int]) -> int:
        """CTM-port vector of every output requesting in one sample."""
        all_ctp = (1 << XTRIG_NUM_CTP) - 1
        p2p = self._ctp_p2p_mask()
        inverted = self._ctp_invert_mask()
        p2p_level = (sample.get("xtrig_ctp_req_out_dout", 0) ^ inverted) & p2p
        wire_or_level = sample.get("xtrig_ctp_req_out_dout_en", 0) & ~p2p
        int_level = sample.get("xtrig_ctm_src_req", 0) & ((1 << XTRIG_NUM_INT_CT) - 1)
        return ((p2p_level | wire_or_level) & all_ctp) | (int_level << XTRIG_NUM_CTP)

    async def await_selected_outputs(self, output_mask: int, mode: int, *, label: str) -> None:
        """Wait for every selected output to request, acknowledging P2P CTP outputs."""
        ctp_outputs = project_ctp_mask(output_mask)
        int_outputs = project_internal_mask(output_mask)
        if ctp_outputs:
            signal = (
                "xtrig_ctp_req_out_dout"
                if mode == XTRIG_CTP_MODE_P2P
                else "xtrig_ctp_req_out_dout_en"
            )
            await self.wait_signal_mask(signal, ctp_outputs, ctp_outputs, label=f"{label}.ctp")
            if mode == XTRIG_CTP_MODE_P2P:
                self.xtrig.set_ctp_ack_in_din(ctp_outputs)
                await ClockCycles(self.xtrig.clk, 3)
                self.xtrig.set_ctp_ack_in_din(0)
        if int_outputs:
            await self.wait_signal_mask(
                "xtrig_ctm_src_req", int_outputs, int_outputs, label=f"{label}.internal"
            )

    async def check_output_mask(
        self,
        output_mask: int,
        mode: int,
        *,
        predicted: int,
        window: DtpXtrigActivityWindow,
        label: str,
    ) -> None:
        """Judge one route: selected outputs fire, the window matches the model, nothing else moves."""
        await self.await_selected_outputs(output_mask, mode, label=label)
        await ClockCycles(self.xtrig.clk, self.ISOLATION_TAIL_CYCLES)
        activity, hold, last = await window.stop()
        fired = self.fired_vector(activity, hold)
        intent = output_mask & XTRIG_CTM_SELECT_MASK
        self.log.info(
            "XTRIG WINDOW %-28s fired=0x%07x predicted=0x%07x intent=0x%07x p2p_ctps=0x%04x "
            "cycles=%d rose=%s",
            label,
            fired,
            predicted & XTRIG_CTM_SELECT_MASK,
            intent,
            self._ctp_p2p_mask(),
            window.cycles,
            window.first_seen_text(),
        )
        # Reference model against the DUT: the outputs that fired anywhere in
        # the window, and only those, are the model's prediction.
        self.check_evidence(
            self.CHK_ROUTE_MODEL,
            f"{label}.model_route",
            fired,
            predicted & XTRIG_CTM_SELECT_MASK,
            context=f"mode={mode}",
        )
        # Isolation: no unselected output fired anywhere in the window, and the
        # selected outputs are idle again at its end.
        self.check_evidence(
            self.CHK_ISOLATION,
            f"{label}.unselected_quiet",
            fired & ~intent,
            0,
            context=f"mode={mode}",
        )
        self.check_evidence(
            self.CHK_ISOLATION,
            f"{label}.selected_deasserted",
            self.level_vector(last) & intent,
            0,
            context=f"mode={mode}",
        )

    async def verify_route(
        self, input_port: int, output_mask: int, mode: int, *, label: str
    ) -> None:
        """Program one route, pulse its input, and judge the output window."""
        await self.configure_ctp_modes_for_route(input_port, output_mask, mode)
        await self.program_route(input_port, output_mask, label=label)
        # The model programmed alongside the CSRs predicts the DUT output
        # vector of this pulse. Under the negative-validation knob the model
        # is corrupted, so the comparison against the DUT must fail.
        predicted = self.ctm_model.route(1 << input_port)
        await self.xtrig.clear_inputs()
        await ClockCycles(self.xtrig.clk, 2)
        window = self.xtrig.activity_window(self.OUTPUT_SIGNALS)
        window.start()
        await self.drive_input_port(input_port, mode)
        await self.check_output_mask(
            output_mask, mode, predicted=predicted, window=window, label=label
        )

    async def verify_route_cases(
        self, cases: list[tuple[int, int]], mode: int, *, label: str
    ) -> None:
        for idx, (input_port, output_mask) in enumerate(cases, start=1):
            self.log_iteration(
                idx, len(cases), "%s input=%d output_mask=0x%x", label, input_port, output_mask
            )
            await self.verify_route(input_port, output_mask, mode, label=f"{label}.{idx}")

    async def check_all_ctm_cleared(self, label: str) -> None:
        for src_idx in range(XTRIG_NUM_CTM_PORTS):
            observed = await self.csr_read(ctm_config_addr(src_idx), label=f"{label}.ctm{src_idx}")
            self.assert_equal(f"{label}.ctm{src_idx}.default", observed & XTRIG_CTM_SELECT_MASK, 0)

    # ------------------------------------------------------------------
    # CTP scenarios
    # ------------------------------------------------------------------
    async def run_wire_or(self) -> None:
        self.log_banner("DTP XTRIG CTP wire-OR pulse stretching and sync")
        # Seeded per-pass port pair and an extra random stretch: per spec every
        # CTP behaves identically, so each loop proves the same properties on a
        # different CTP/internal pair and stretch width.
        rng = self.rng("xtrig_wire_or")
        ctp_idx = rng.randrange(XTRIG_NUM_CTP)
        int_idx = rng.randrange(XTRIG_NUM_INT_CT)
        int_port = internal_ct_port(int_idx)
        ctp_port = external_ctp_port(ctp_idx)

        for stretch in (15, 0, rng.randint(1, 14)):
            self.log_step(
                "setup", "Configure wire-OR stretch=%d and route internal CT to CTP", stretch
            )
            await self.program_ctp(ctp_idx, mode=XTRIG_CTP_MODE_WIRE_OR, stretch=stretch)
            await self.program_route(int_port, 1 << ctp_port, label=f"wire_or.stretch{stretch}")
            await self.xtrig.clear_inputs()
            await self.xtrig.drive_internal_dst_pulse(int_idx, cycles=1)
            width = await self.xtrig.measure_mask_width("xtrig_ctp_req_out_dout_en", 1 << ctp_idx)
            self.check_evidence(
                self.CHK_STRETCH, f"wire_or.stretch{stretch}.width", width, stretch + 1
            )
            status = await self.csr_read(
                ctp_status_addr(ctp_idx), label=f"wire_or.stretch{stretch}.status"
            )
            self.log.info(
                "wire_or stretch=%d decoded status %s", stretch, self.xtrig.decode_status(status)
            )
            await ClockCycles(self.xtrig.clk, stretch + 4)
            status = await self.csr_read(
                ctp_status_addr(ctp_idx), label=f"wire_or.stretch{stretch}.status_clear"
            )
            self.check_evidence(
                self.CHK_STRETCH,
                f"wire_or.stretch{stretch}.busy_clear",
                int(bool(status & XTRIG_CTP_STATUS_BUSY)),
                0,
            )

        self.log_step("sync", "Drive external CT_Req_out input and expect internal CT delivery")
        await self.program_ctp(ctp_idx, mode=XTRIG_CTP_MODE_WIRE_OR, stretch=0)
        await self.program_route(ctp_port, 1 << int_port, label="wire_or.external_to_internal")
        await self.xtrig.drive_ctp_req_out_din_pulse(ctp_idx, cycles=2)
        await self.wait_signal_mask(
            "xtrig_ctm_src_req", 1 << int_idx, 1 << int_idx, label="wire_or.external_sync"
        )
        self.log_summary("wire_or", ctp=ctp_idx, internal=int_idx, checked_stretches="15,0,random")

    async def run_p2p(self) -> None:
        self.log_banner("DTP XTRIG CTP point-to-point handshakes")
        # Seeded per-pass port pair: each loop proves the P2P handshakes on a
        # different CTP/internal combination.
        rng = self.rng("xtrig_p2p")
        ctp_idx = rng.randrange(XTRIG_NUM_CTP)
        int_idx = rng.randrange(XTRIG_NUM_INT_CT)
        ctp_port = external_ctp_port(ctp_idx)
        int_port = internal_ct_port(int_idx)
        await self.program_ctp(ctp_idx, mode=XTRIG_CTP_MODE_P2P, stretch=0)

        self.log_step(1, "Internal trigger should assert CT_Req_out until CT_Ack_in")
        await self.program_route(int_port, 1 << ctp_port, label="p2p.internal_to_ctp")
        await self.xtrig.pulse_ctm_dst_req(1 << int_idx, cycles=2)
        await self.wait_signal_mask(
            "xtrig_ctp_req_out_dout", 1 << ctp_idx, 1 << ctp_idx, label="p2p.req_out"
        )
        status = await self.csr_read(ctp_status_addr(ctp_idx), label="p2p.status_busy")
        self.check_evidence(
            self.CHK_CSR, "p2p.status.req_out", int(bool(status & XTRIG_CTP_STATUS_REQ_OUT)), 1
        )
        await self.xtrig.drive_ctp_p2p_ack_in(ctp_idx, 1)
        await ClockCycles(self.xtrig.clk, 3)
        await self.xtrig.drive_ctp_p2p_ack_in(ctp_idx, 0)
        await self.wait_signal_mask(
            "xtrig_ctp_req_out_dout", 1 << ctp_idx, 0, label="p2p.req_out_clear"
        )

        self.log_step(2, "External CT_Req_in should assert CT_Ack_out and deliver internal trigger")
        await self.program_route(ctp_port, 1 << int_port, label="p2p.ctp_to_internal")
        await self.xtrig.drive_ctp_p2p_req_in(ctp_idx, 1)
        await self.wait_signal_mask(
            "xtrig_ctp_ack_out_dout", 1 << ctp_idx, 1 << ctp_idx, label="p2p.ack_out"
        )
        await self.wait_signal_mask(
            "xtrig_ctm_src_req", 1 << int_idx, 1 << int_idx, label="p2p.internal_delivery"
        )
        await self.xtrig.drive_ctp_p2p_req_in(ctp_idx, 0)
        await ClockCycles(self.xtrig.clk, 3)
        self.log_summary("p2p", ctp=ctp_idx)

    async def run_reset(self) -> None:
        self.log_banner("DTP XTRIG CTP reset recovery")
        # Seeded per-pass ports: each loop deadlocks and recovers a different
        # CTP, and system-resets a different second CTP.
        rng = self.rng("xtrig_reset")
        ctp_idx = rng.randrange(XTRIG_NUM_CTP)
        int_idx = rng.randrange(XTRIG_NUM_INT_CT)
        ctp_b = rng.choice([c for c in range(XTRIG_NUM_CTP) if c != ctp_idx])
        int_b = rng.choice([i for i in range(XTRIG_NUM_INT_CT) if i != int_idx])
        ctp_port = external_ctp_port(ctp_idx)
        int_port = internal_ct_port(int_idx)
        await self.program_ctp(ctp_idx, mode=XTRIG_CTP_MODE_P2P)
        await self.program_route(int_port, 1 << ctp_port, label="reset.deadlock_setup")
        await self.xtrig.pulse_ctm_dst_req(1 << int_idx, cycles=2)
        await self.wait_signal_mask(
            "xtrig_ctp_req_out_dout", 1 << ctp_idx, 1 << ctp_idx, label="reset.stuck_req"
        )
        status = await self.csr_read(ctp_status_addr(ctp_idx), label="reset.busy_before")
        self.check_evidence(
            self.CHK_CSR, "reset.busy_before", int(bool(status & XTRIG_CTP_STATUS_BUSY)), 1
        )

        await self.program_ctp(ctp_idx, mode=XTRIG_CTP_MODE_P2P, reset=1)
        await ClockCycles(self.xtrig.clk, 3)
        await self.wait_signal_mask(
            "xtrig_ctp_req_out_dout", 1 << ctp_idx, 0, label="reset.config_reset_clear"
        )
        await self.program_ctp(ctp_idx, mode=XTRIG_CTP_MODE_P2P, reset=0)
        await self.verify_route(
            int_port, 1 << ctp_port, XTRIG_CTP_MODE_P2P, label="reset.post_config_reset"
        )

        await self.program_ctp(
            ctp_b, mode=XTRIG_CTP_MODE_WIRE_OR, invert=1, stretch=rng.randint(1, 15)
        )
        await self.program_ctm_src(ctp_b, 1 << internal_ct_port(int_b))
        await self.pulse_reset(cycles=3)
        await self.write_read_check(
            ctp_config_addr(ctp_b),
            0,
            0,
            mask=XTRIG_CTP_CONFIG_MASK,
            label=f"reset.ctp{ctp_b}.default_cfg",
        )
        await self.write_read_check(
            ctp_stretch_addr(ctp_b),
            0,
            0,
            mask=XTRIG_CTP_STRETCH_MASK,
            label=f"reset.ctp{ctp_b}.default_stretch",
        )
        await self.check_all_ctm_cleared("reset.system")
        await self.check_quiet("system_reset")
        self.log_summary("reset", ctp=ctp_idx)

    async def run_random(self) -> None:
        self.log_banner("DTP XTRIG seeded random CTP configuration")
        rng = self.rng("xtrig_random")
        for idx in range(self.random_count):
            ctp_idx = rng.randrange(XTRIG_NUM_CTP)
            mode = rng.randrange(2)
            invert = rng.randrange(2)
            stretch = rng.randrange(0, 8)
            int_idx = rng.randrange(XTRIG_NUM_INT_CT)
            self.log_iteration(
                idx + 1,
                self.random_count,
                "ctp=%d mode=%d invert=%d stretch=%d internal=%d",
                ctp_idx,
                mode,
                invert,
                stretch,
                int_idx,
            )
            await self.program_ctp(ctp_idx, mode=mode, invert=invert, stretch=stretch)
            await self.program_route(
                internal_ct_port(int_idx), 1 << external_ctp_port(ctp_idx), label=f"random.{idx}"
            )
            await self.xtrig.pulse_ctm_dst_req(1 << int_idx, cycles=1)
            if mode == XTRIG_CTP_MODE_P2P:
                await self.wait_signal_mask(
                    "xtrig_ctp_req_out_dout_en",
                    1 << ctp_idx,
                    1 << ctp_idx,
                    label=f"random.{idx}.oen",
                )
                sample = await self.sample_xtrig(f"random.{idx}.p2p_active")
                self.log.info(
                    "random P2P CTP[%d] active data=0x%x invert=%d (pad polarity is logged for debug)",
                    ctp_idx,
                    sample.get("xtrig_ctp_req_out_dout", 0) & (1 << ctp_idx),
                    invert,
                )
                await self.xtrig.drive_ctp_p2p_ack_in(ctp_idx, 1)
                await ClockCycles(self.xtrig.clk, 2)
                await self.xtrig.drive_ctp_p2p_ack_in(ctp_idx, 0)
            else:
                await self.wait_signal_mask(
                    "xtrig_ctp_req_out_dout_en",
                    1 << ctp_idx,
                    1 << ctp_idx,
                    label=f"random.{idx}.wire_en",
                )
                expected_data = (1 << ctp_idx) if invert else 0
                await self.wait_signal_mask(
                    "xtrig_ctp_req_out_dout",
                    1 << ctp_idx,
                    expected_data,
                    label=f"random.{idx}.wire_polarity",
                )
        self.log_summary("random", iterations=self.random_count)

    async def run_ctp_csr_sweep(self) -> None:
        self.log_banner("DTP XTRIG CTP deterministic CSR and byte-strobe sweep")
        patterns = [
            pack_ctp_config(mode=XTRIG_CTP_MODE_WIRE_OR),
            pack_ctp_config(mode=XTRIG_CTP_MODE_WIRE_OR, invert=1),
            pack_ctp_config(mode=XTRIG_CTP_MODE_P2P),
            pack_ctp_config(mode=XTRIG_CTP_MODE_P2P, invert=1, reset=1),
        ]
        # Seeded per-pass order and an extra random stretch value: the sweep
        # stays exhaustive while each loop exercises different write orders.
        rng = self.rng("ctp_csr_sweep")
        rng.shuffle(patterns)
        stretch_values = (0, 1, 0x55AA, 0xFFFF, rng.getrandbits(16))
        for ctp_idx in range(XTRIG_NUM_CTP):
            for pat_idx, config_word in enumerate(patterns):
                self.log_iteration(
                    ctp_idx * len(patterns) + pat_idx + 1,
                    XTRIG_NUM_CTP * len(patterns),
                    "CTP[%d] cfg=0x%x",
                    ctp_idx,
                    config_word,
                )
                await self.write_read_check(
                    ctp_config_addr(ctp_idx),
                    config_word,
                    config_word,
                    mask=XTRIG_CTP_CONFIG_MASK,
                    label=f"ctp{ctp_idx}.cfg{pat_idx}",
                )
            for stretch in stretch_values:
                await self.write_read_check(
                    ctp_stretch_addr(ctp_idx),
                    stretch,
                    stretch,
                    mask=XTRIG_CTP_STRETCH_MASK,
                    label=f"ctp{ctp_idx}.stretch{stretch:04x}",
                )
            base = pack_ctp_config(mode=XTRIG_CTP_MODE_WIRE_OR)
            await self.csr_write(ctp_config_addr(ctp_idx), base, label=f"ctp{ctp_idx}.byte_base")
            expected = apply_wstrb(base, pack_ctp_config(mode=XTRIG_CTP_MODE_P2P, invert=1), 0x1)
            await self.write_read_check(
                ctp_config_addr(ctp_idx),
                pack_ctp_config(mode=XTRIG_CTP_MODE_P2P, invert=1),
                expected,
                wstrb=0x1,
                mask=XTRIG_CTP_CONFIG_MASK,
                label=f"ctp{ctp_idx}.byte0",
            )
        self.log_summary("ctp_csr_sweep", ctp_count=XTRIG_NUM_CTP)

    async def run_dst_port_sweep(self) -> None:
        self.log_banner("DTP XTRIG deterministic destination-port sweep")
        # Seeded per-pass source: the output sweep stays exhaustive while each
        # loop drives it from a different internal CT.
        input_port = internal_ct_port(self.rng("dst_port_sweep").randrange(XTRIG_NUM_INT_CT))
        for output_port in range(XTRIG_NUM_CTM_PORTS):
            self.log_iteration(
                output_port + 1,
                XTRIG_NUM_CTM_PORTS,
                "input port %d -> output port %d",
                input_port,
                output_port,
            )
            mode = (
                XTRIG_CTP_MODE_WIRE_OR if self.is_ctp_port(output_port) else XTRIG_CTP_MODE_WIRE_OR
            )
            await self.verify_route(
                input_port, 1 << output_port, mode, label=f"dst_sweep.port{output_port}"
            )
            if not self.is_ctp_port(output_port):
                ack_mask = 1 << self.int_idx_from_port(output_port)
                self.xtrig.set_ctm_src_ack(ack_mask)
                await ClockCycles(self.xtrig.clk, 1)
                self.xtrig.set_ctm_src_ack(0)
        self.log_summary("dst_port_sweep", outputs=XTRIG_NUM_CTM_PORTS)

    # ------------------------------------------------------------------
    # AXI-Lite skew/default path scenarios
    # ------------------------------------------------------------------
    async def run_reg_stall(self) -> None:
        self.log_banner("DTP XTRIG accepted-path CSR access and stall rationale")
        # Seeded per-pass CSR payloads: each loop writes different values down
        # the accepted path.
        rng = self.rng("reg_stall")
        stretch = rng.getrandbits(16)
        select = rng.randint(1, XTRIG_CTM_SELECT_MASK)
        await self.write_read_check(
            ctp_config_addr(0),
            pack_ctp_config(invert=1),
            pack_ctp_config(invert=1),
            mask=XTRIG_CTP_CONFIG_MASK,
            label="regstall.ctp0.config",
        )
        await self.write_read_check(
            ctp_stretch_addr(0),
            stretch,
            stretch,
            mask=XTRIG_CTP_STRETCH_MASK,
            label="regstall.ctp0.stretch",
        )
        await self.write_read_check(
            ctm_config_addr(0), select, select, mask=XTRIG_CTM_SELECT_MASK, label="regstall.ctm0"
        )
        await self.check_quiet("reg_stall_accepted")
        sample = await self.sample_xtrig("accepted_path")
        self.check_evidence(
            self.CHK_AXIL,
            "regstall.awvalid_count_nonzero",
            int(sample["xtrig_axil_awvalid_count"] > 0),
            1,
        )
        self.check_evidence(
            self.CHK_AXIL,
            "regstall.arvalid_count_nonzero",
            int(sample["xtrig_axil_arvalid_count"] > 0),
            1,
        )
        self.log_summary(
            "reg_stall",
            rationale="local regblock stall path documented as structurally unreachable",
        )

    async def run_axi_channel_skew(self) -> None:
        self.log_banner("DTP XTRIG manual AXI-Lite AW/W and RREADY skew")
        # Seeded per-pass payloads and skew timing: each loop exercises the
        # channel-skew paths with different data, gaps, and READY delays.
        rng = self.rng("axi_channel_skew")
        d1, d2, d3 = (rng.getrandbits(16) for _ in range(3))
        addr = ctp_stretch_addr(rng.randrange(XTRIG_NUM_CTP))
        result = await self.axil.write_skewed_result(
            addr, d1, w_valid_delay=rng.randint(3, 7), b_ready_delay=rng.randint(1, 4)
        )
        self.check_evidence(self.CHK_AXIL, "axi_skew.aw_before_w.bresp", result.resp, self.AXI_OKAY)
        await self.write_read_check(
            addr, d2, d2, mask=XTRIG_CTP_STRETCH_MASK, label="axi_skew.normal_after_aw"
        )
        result = await self.axil.write_skewed_result(
            addr,
            d3,
            aw_valid_delay=rng.randint(3, 7),
            b_ready_delay=rng.randint(1, 4),
        )
        self.check_evidence(self.CHK_AXIL, "axi_skew.w_before_aw.bresp", result.resp, self.AXI_OKAY)
        observed = await self.csr_read(addr, label="axi_skew.final_read")
        self.check_evidence(
            self.CHK_AXIL, "axi_skew.final_stretch", observed & XTRIG_CTP_STRETCH_MASK, d3
        )
        held = await self.axil.read_hold_result(addr, rng.randint(3, 7))
        self.check_evidence(self.CHK_AXIL, "axi_skew.rresp", held.resp, self.AXI_OKAY)
        self.check_evidence(self.CHK_AXIL, "axi_skew.rstable", int(held.hold_stable), 1)
        self.check_evidence(self.CHK_AXIL, "axi_skew.rdata", held.data & XTRIG_CTP_STRETCH_MASK, d3)
        self.log_summary("axi_channel_skew", final=f"0x{held.data:08x}")

    async def run_axi_channel_skew_demux_aw_lock_release(self) -> None:
        self.log_banner("DTP XTRIG AXI-Lite demux AW-lock release")
        # Seeded per-pass targets, payloads, and skew timing.
        rng = self.rng("demux_aw_lock")
        ctp_a, ctp_b = rng.sample(range(XTRIG_NUM_CTP), 2)
        cases = (
            (
                ctp_config_addr(ctp_a),
                pack_ctp_config(mode=rng.randrange(2), invert=rng.randrange(2)),
                True,
            ),
            (
                ctp_config_addr(ctp_b),
                pack_ctp_config(mode=rng.randrange(2), invert=rng.randrange(2)),
                True,
            ),
            (
                ctm_config_addr(rng.randrange(XTRIG_NUM_CTM_PORTS)),
                rng.randint(1, XTRIG_CTM_SELECT_MASK),
                False,
            ),
        )
        for idx, (addr, data, aw_first) in enumerate(cases, start=1):
            self.log_iteration(idx, 3, "addr=0x%x data=0x%x aw_first=%d", addr, data, aw_first)
            gap = rng.randint(4, 8)
            result = await self.axil.write_skewed_result(
                addr,
                data,
                aw_valid_delay=0 if aw_first else gap,
                w_valid_delay=gap if aw_first else 0,
                b_ready_delay=rng.randint(1, 4),
            )
            self.check_evidence(
                self.CHK_AXIL, f"demux_aw_lock.{idx}.bresp", result.resp, self.AXI_OKAY
            )
            observed = await self.csr_read(addr, label=f"demux_aw_lock.{idx}.readback")
            mask = XTRIG_CTP_CONFIG_MASK if addr >= 0x200 else XTRIG_CTM_SELECT_MASK
            self.check_evidence(
                self.CHK_AXIL, f"demux_aw_lock.{idx}.readback", observed & mask, data & mask
            )
        self.log_summary("axi_channel_skew_demux_aw_lock_release", writes=3)

    async def run_axi_channel_skew_read_decode_backpressure(self) -> None:
        self.log_banner("DTP XTRIG AXI-Lite read decode backpressure")
        # Seeded per-pass unmapped offsets and RREADY hold width.
        rng = self.rng("read_decode_backpressure")
        offsets = sorted(rng.sample(range(0, 0x40), 2))
        for idx, addr in enumerate(
            (XTRIG_UNMAPPED_BASE + offsets[0] * 4, XTRIG_UNMAPPED_BASE + offsets[1] * 4), start=1
        ):
            held = await self.axil.read_hold_result(addr, rng.randint(4, 8))
            self.log_iteration(
                idx,
                2,
                "unmapped addr=0x%x data=0x%x resp=%d stable=%d",
                addr,
                held.data,
                held.resp,
                int(held.hold_stable),
            )
            self.check_evidence(
                self.CHK_AXIL, f"read_decode.{idx}.resp", held.resp, self.AXI_DECERR
            )
            self.check_evidence(
                self.CHK_AXIL, f"read_decode.{idx}.stable", int(held.hold_stable), 1
            )
        self.log_summary(
            "axi_channel_skew_read_decode_backpressure", unmapped_base=f"0x{XTRIG_UNMAPPED_BASE:x}"
        )

    # ------------------------------------------------------------------
    # CTM route scenarios
    # ------------------------------------------------------------------
    # Seeded per-pass port picks: every source/destination CTP and internal CT
    # is interchangeable per spec, so each loop proves the route class on a
    # different port set. Inputs are kept out of the output masks so the
    # isolation check stays meaningful.
    async def run_ctm_wire_or_cla_to_ctp(self) -> None:
        rng = self.rng("ctm_wire_or_cla_to_ctp")
        int_in, int_ovl = rng.sample(range(XTRIG_NUM_INT_CT), 2)
        outs = rng.sample(range(XTRIG_NUM_CTP), 3)
        await self.run_ctm_wire_or_route_class(
            "cla_to_ctp",
            internal_ct_port(int_in),
            ctp_mask(*outs),
            overlap_input=internal_ct_port(int_ovl),
            overlap_output=external_ctp_port(rng.choice(outs)),
        )

    async def run_ctm_wire_or_ctp_to_cla(self) -> None:
        rng = self.rng("ctm_wire_or_ctp_to_cla")
        ctp_in, ctp_ovl = rng.sample(range(XTRIG_NUM_CTP), 2)
        outs = rng.sample(range(XTRIG_NUM_INT_CT), 3)
        await self.run_ctm_wire_or_route_class(
            "ctp_to_cla",
            external_ctp_port(ctp_in),
            internal_ct_mask(*outs),
            overlap_input=external_ctp_port(ctp_ovl),
            overlap_output=internal_ct_port(rng.choice(outs)),
        )

    async def run_ctm_wire_or_cla_to_cla(self) -> None:
        rng = self.rng("ctm_wire_or_cla_to_cla")
        picks = rng.sample(range(XTRIG_NUM_INT_CT), 5)
        int_in, int_ovl, outs = picks[0], picks[1], picks[2:5]
        await self.run_ctm_wire_or_route_class(
            "cla_to_cla",
            internal_ct_port(int_in),
            internal_ct_mask(*outs),
            overlap_input=internal_ct_port(int_ovl),
            overlap_output=internal_ct_port(rng.choice(outs)),
        )

    async def run_ctm_wire_or_ctp_to_ctp(self) -> None:
        rng = self.rng("ctm_wire_or_ctp_to_ctp")
        picks = rng.sample(range(XTRIG_NUM_CTP), 5)
        ctp_in, ctp_ovl, outs = picks[0], picks[1], picks[2:5]
        await self.run_ctm_wire_or_route_class(
            "ctp_to_ctp",
            external_ctp_port(ctp_in),
            ctp_mask(*outs),
            overlap_input=external_ctp_port(ctp_ovl),
            overlap_output=external_ctp_port(rng.choice(outs)),
        )

    async def run_ctm_wire_or_route_class(
        self,
        name: str,
        input_port: int,
        output_mask: int,
        *,
        overlap_input: int,
        overlap_output: int,
    ) -> None:
        self.log_banner(f"DTP CTM wire-OR routing {name}")
        await self.verify_route(
            input_port, output_mask, XTRIG_CTP_MODE_WIRE_OR, label=f"wire_or.{name}.main"
        )
        await self.clear_ctm_routes()
        await self.configure_ctp_modes_for_route(
            input_port, output_mask | (1 << overlap_output), XTRIG_CTP_MODE_WIRE_OR
        )
        await self.configure_ctp_mode_for_port(overlap_input, XTRIG_CTP_MODE_WIRE_OR, stretch=1)
        await self.program_ctm_src(overlap_output, (1 << input_port) | (1 << overlap_input))
        predicted = self.ctm_model.route((1 << input_port) | (1 << overlap_input))
        window = self.xtrig.activity_window(self.OUTPUT_SIGNALS)
        window.start()
        await self.drive_input_port(input_port, XTRIG_CTP_MODE_WIRE_OR)
        await self.drive_input_port(overlap_input, XTRIG_CTP_MODE_WIRE_OR)
        await self.check_output_mask(
            1 << overlap_output,
            XTRIG_CTP_MODE_WIRE_OR,
            predicted=predicted,
            window=window,
            label=f"wire_or.{name}.overlap",
        )
        self.log_summary(f"ctm_wire_or_{name}", input=input_port, outputs=f"0x{output_mask:x}")

    # Seeded per-pass pairs: each loop proves the P2P route class on three
    # different source/destination combinations (source != destination).
    async def run_ctm_p2p_cla_to_ctp(self) -> None:
        rng = self.rng("ctm_p2p_cla_to_ctp")
        pairs = [
            (internal_ct_port(i), external_ctp_port(c))
            for i, c in zip(
                rng.sample(range(XTRIG_NUM_INT_CT), 3), rng.sample(range(XTRIG_NUM_CTP), 3)
            )
        ]
        await self.run_ctm_p2p_route_class("cla_to_ctp", pairs)

    async def run_ctm_p2p_ctp_to_cla(self) -> None:
        rng = self.rng("ctm_p2p_ctp_to_cla")
        pairs = [
            (external_ctp_port(c), internal_ct_port(i))
            for c, i in zip(
                rng.sample(range(XTRIG_NUM_CTP), 3), rng.sample(range(XTRIG_NUM_INT_CT), 3)
            )
        ]
        await self.run_ctm_p2p_route_class("ctp_to_cla", pairs)

    async def run_ctm_p2p_cla_to_cla(self) -> None:
        rng = self.rng("ctm_p2p_cla_to_cla")
        picks = rng.sample(range(XTRIG_NUM_INT_CT), 6)
        pairs = [(internal_ct_port(picks[k]), internal_ct_port(picks[k + 3])) for k in range(3)]
        await self.run_ctm_p2p_route_class("cla_to_cla", pairs)

    async def run_ctm_p2p_ctp_to_ctp(self) -> None:
        rng = self.rng("ctm_p2p_ctp_to_ctp")
        picks = rng.sample(range(XTRIG_NUM_CTP), 6)
        pairs = [(external_ctp_port(picks[k]), external_ctp_port(picks[k + 3])) for k in range(3)]
        await self.run_ctm_p2p_route_class("ctp_to_ctp", pairs)

    async def run_ctm_p2p_route_class(self, name: str, pairs: list[tuple[int, int]]) -> None:
        self.log_banner(f"DTP CTM point-to-point routing {name}")
        for idx, (input_port, output_port) in enumerate(pairs, start=1):
            self.log_iteration(
                idx, len(pairs), "%s input=%d output=%d", name, input_port, output_port
            )
            await self.verify_route(
                input_port, 1 << output_port, XTRIG_CTP_MODE_P2P, label=f"p2p.{name}.{idx}"
            )
        self.log_summary(f"ctm_p2p_{name}", pairs=len(pairs))

    # ------------------------------------------------------------------
    # CTM reset and random scenarios
    # ------------------------------------------------------------------
    async def run_ctm_reset_wire_or_mode(self) -> None:
        await self.run_ctm_reset_mode("wire_or", XTRIG_CTP_MODE_WIRE_OR)

    async def run_ctm_reset_p2p_mode(self) -> None:
        await self.run_ctm_reset_mode("p2p", XTRIG_CTP_MODE_P2P)

    async def run_ctm_reset_all_modes(self) -> None:
        self.log_banner("DTP CTM reset across wire-OR and P2P modes")
        # Seeded per-pass ports: each loop resets and recovers different routes.
        rng = self.rng("ctm_reset_all_modes")
        int_a, int_b = rng.sample(range(XTRIG_NUM_INT_CT), 2)
        ctps = rng.sample(range(XTRIG_NUM_CTP), 4)
        await self.verify_route(
            internal_ct_port(int_a),
            ctp_mask(ctps[0], ctps[1]),
            XTRIG_CTP_MODE_WIRE_OR,
            label="reset_all.pre_wire",
        )
        await self.verify_route(
            internal_ct_port(int_b),
            1 << external_ctp_port(ctps[2]),
            XTRIG_CTP_MODE_P2P,
            label="reset_all.pre_p2p",
        )
        await self.pulse_reset(cycles=3)
        await self.check_all_ctm_cleared("reset_all")
        await self.check_quiet("reset_all")
        await self.verify_route(
            internal_ct_port(int_a),
            1 << external_ctp_port(ctps[0]),
            XTRIG_CTP_MODE_WIRE_OR,
            label="reset_all.post_wire",
        )
        await self.verify_route(
            internal_ct_port(int_b),
            1 << external_ctp_port(ctps[3]),
            XTRIG_CTP_MODE_P2P,
            label="reset_all.post_p2p",
        )
        self.log_summary("ctm_reset_all_modes")

    async def run_ctm_reset_mode(self, name: str, mode: int) -> None:
        self.log_banner(f"DTP CTM reset in {name} mode")
        # Seeded per-pass ports: each loop resets and recovers different routes.
        rng = self.rng(f"ctm_reset_{name}")
        int_a, int_b = rng.sample(range(XTRIG_NUM_INT_CT), 2)
        ctps = rng.sample(range(XTRIG_NUM_CTP), 3)
        output_mask = (
            ctp_mask(ctps[0], ctps[1])
            if mode == XTRIG_CTP_MODE_WIRE_OR
            else 1 << external_ctp_port(ctps[0])
        )
        await self.verify_route(
            internal_ct_port(int_a), output_mask, mode, label=f"reset_{name}.pre"
        )
        await self.pulse_reset(cycles=3)
        await self.check_all_ctm_cleared(f"reset_{name}")
        await self.check_quiet(f"reset_{name}")
        await self.verify_route(
            internal_ct_port(int_b),
            1 << external_ctp_port(ctps[2]),
            mode,
            label=f"reset_{name}.post",
        )
        self.log_summary(f"ctm_reset_{name}")

    async def run_ctm_rand_all_scenarios(self) -> None:
        await self.run_ctm_random(
            "all_scenarios", source_class="all", dest_class="all", multicast=True, p2p=True
        )

    async def run_ctm_rand_wire_or_only(self) -> None:
        await self.run_ctm_random(
            "wire_or_only", source_class="all", dest_class="all", multicast=True, p2p=False
        )

    async def run_ctm_rand_p2p_only(self) -> None:
        await self.run_ctm_random(
            "p2p_only", source_class="all", dest_class="all", multicast=False, p2p=True
        )

    async def run_ctm_rand_cla_to_ctp(self) -> None:
        await self.run_ctm_random(
            "cla_to_ctp", source_class="internal", dest_class="ctp", multicast=True, p2p=True
        )

    async def run_ctm_rand_ctp_to_cla(self) -> None:
        await self.run_ctm_random(
            "ctp_to_cla", source_class="ctp", dest_class="internal", multicast=True, p2p=True
        )

    async def run_ctm_random(
        self, name: str, *, source_class: str, dest_class: str, multicast: bool, p2p: bool
    ) -> None:
        self.log_banner(f"DTP CTM seeded random routing {name}")
        rng = self.rng(f"ctm_random_{name}")
        source_pool = self.port_pool(source_class)
        dest_pool = self.port_pool(dest_class)
        for idx in range(self.random_count):
            input_port = rng.choice(source_pool)
            mode = (
                XTRIG_CTP_MODE_P2P
                if (p2p and (not multicast or rng.randrange(2)))
                else XTRIG_CTP_MODE_WIRE_OR
            )
            if mode == XTRIG_CTP_MODE_P2P:
                selected = [rng.choice([d for d in dest_pool if d != input_port] or dest_pool)]
            else:
                choices = [d for d in dest_pool if d != input_port]
                rng.shuffle(choices)
                selected = choices[: max(2, min(4, len(choices)))]
            output_mask = sum(1 << port for port in selected)
            self.log_iteration(
                idx + 1,
                self.random_count,
                "input=%d mode=%d outputs=0x%x",
                input_port,
                mode,
                output_mask,
            )
            await self.verify_route(input_port, output_mask, mode, label=f"rand.{name}.{idx}")
        self.log_summary(f"ctm_rand_{name}", iterations=self.random_count)

    @staticmethod
    def port_pool(port_class: str) -> list[int]:
        if port_class == "ctp":
            return list(range(XTRIG_NUM_CTP))
        if port_class == "internal":
            return [internal_ct_port(idx) for idx in range(XTRIG_NUM_INT_CT)]
        return list(range(XTRIG_NUM_CTM_PORTS))

    async def run_ctm_csr_sweep(self) -> None:
        self.log_banner("DTP CTM deterministic CSR byte-strobe and mask sweep")
        # Seeded per-pass extra pattern and byte-strobe payloads on top of the
        # deterministic sweep.
        rng = self.rng("ctm_csr_sweep")
        patterns = [
            0,
            1,
            1 << external_ctp_port(0),
            1 << internal_ct_port(0),
            XTRIG_CTM_SELECT_MASK,
            0x0155_AA55 & XTRIG_CTM_SELECT_MASK,
            rng.randint(1, XTRIG_CTM_SELECT_MASK),
        ]
        for src_idx in range(XTRIG_NUM_CTM_PORTS):
            for pat_idx, dst_mask in enumerate(patterns):
                await self.write_read_check(
                    ctm_config_addr(src_idx),
                    dst_mask,
                    dst_mask,
                    mask=XTRIG_CTM_SELECT_MASK,
                    label=f"ctm{src_idx}.pat{pat_idx}",
                )
            old_mask = rng.getrandbits(8)
            new_mask = rng.getrandbits(8) << 8
            await self.program_ctm_src(src_idx, old_mask)
            expected = apply_wstrb(old_mask, new_mask, 0x2) & XTRIG_CTM_SELECT_MASK
            await self.write_read_check(
                ctm_config_addr(src_idx),
                new_mask,
                expected,
                wstrb=0x2,
                mask=XTRIG_CTM_SELECT_MASK,
                label=f"ctm{src_idx}.byte1",
            )
        self.log_summary("ctm_csr_sweep", sources=XTRIG_NUM_CTM_PORTS)

    async def run_ctm_all_source_select(self) -> None:
        self.log_banner("DTP CTM all-source select coverage")
        # Seeded per-pass extra mask on top of the deterministic per-source set.
        rng = self.rng("ctm_all_source_select")
        for src_idx in range(XTRIG_NUM_CTM_PORTS):
            masks = [
                1 << (src_idx % XTRIG_NUM_CTM_PORTS),
                (1 << src_idx) | (1 << ((src_idx + 1) % XTRIG_NUM_CTM_PORTS)),
                (~(1 << src_idx)) & XTRIG_CTM_SELECT_MASK,
                rng.randint(1, XTRIG_CTM_SELECT_MASK),
            ]
            neighbor = ctm_config_addr((src_idx + 1) % XTRIG_NUM_CTM_PORTS)
            before_neighbor = await self.csr_read(
                neighbor, label=f"allsrc{src_idx}.neighbor_before"
            )
            for mask_idx, dst_mask in enumerate(masks):
                await self.write_read_check(
                    ctm_config_addr(src_idx),
                    dst_mask,
                    dst_mask,
                    mask=XTRIG_CTM_SELECT_MASK,
                    label=f"allsrc{src_idx}.mask{mask_idx}",
                )
            after_neighbor = await self.csr_read(neighbor, label=f"allsrc{src_idx}.neighbor_after")
            if ((src_idx + 1) % XTRIG_NUM_CTM_PORTS) != src_idx:
                self.assert_equal(
                    f"allsrc{src_idx}.neighbor_no_alias",
                    after_neighbor & XTRIG_CTM_SELECT_MASK,
                    before_neighbor & XTRIG_CTM_SELECT_MASK,
                )
        self.log_summary("ctm_all_source_select", sources=XTRIG_NUM_CTM_PORTS)
