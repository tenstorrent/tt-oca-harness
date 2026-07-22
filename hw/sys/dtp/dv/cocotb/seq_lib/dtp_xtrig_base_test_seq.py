# SPDX-License-Identifier: Apache-2.0
"""Shared XTRIG helpers and full VPLAN scenario sequences."""

from __future__ import annotations

from cocotb.triggers import ClockCycles, ReadOnly

from env.dtp_xtrig_types import (
    DtpCtmRefModel,
    XTRIG_CTM_SELECT_MASK,
    XTRIG_CTP_CONFIG_MASK,
    XTRIG_CTP_MODE_P2P,
    XTRIG_CTP_MODE_WIRE_OR,
    XTRIG_CTP_STATUS_BUSY,
    XTRIG_CTP_STATUS_REQ_OUT,
    XTRIG_CTP_STRETCH_MASK,
    XTRIG_NUM_CTP,
    XTRIG_NUM_INT_CT,
    XTRIG_NUM_CTM_PORTS,
    XTRIG_UNMAPPED_BASE,
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

from .dtp_base_test_seq import dtp_base_test_seq


class dtp_xtrig_base_test_seq(dtp_base_test_seq):
    """Helpers and scenario bodies for DTP XTRIG, CTP, and CTM tests.

    CTM register names use the RTL convention: CT_SRC[i].CT_DST_SELECT selects
    which CTM destination-input bits feed output/source port i. The helpers below
    therefore program routes as ``output_port <- input_port_mask`` and log both
    the VPLAN source/destination intent and the concrete CSR mapping.
    """

    AXI_OKAY = 0
    AXI_DECERR = 3
    QUIET_GROUPS = (
        "xtrig_ctm_src_req",
        "xtrig_ctm_dst_ack",
        "xtrig_ctp_req_out_dout_en",
        "xtrig_ctp_ack_out_dout_en",
    )

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

    # ------------------------------------------------------------------
    # CSR helpers
    # ------------------------------------------------------------------
    async def csr_write(self, addr: int, data: int, *, wstrb: int = 0xF, label: str = "") -> int:
        resp = await self.axil.write(addr, data, wstrb=wstrb)
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
        data, resp = await self.axil.read(addr)
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
        self.assert_equal(label or f"csr_0x{addr:x}", observed & mask, expected & mask)
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
        self.ctm_model.program(output_port, input_mask)
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
        for ctp_idx in range(XTRIG_NUM_CTP):
            await self.csr_write(ctp_config_addr(ctp_idx), 0, label=f"cleanup.ctp{ctp_idx}.cfg")
            await self.csr_write(ctp_stretch_addr(ctp_idx), 0, label=f"cleanup.ctp{ctp_idx}.stretch")
        await self.clear_ctm_routes()

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
        for _ in range(cycles):
            await ReadOnly()
            observed = int(getattr(self.xtrig.dut, name).value) & mask
            await ClockCycles(self.xtrig.clk, 1)
            if observed == (expected & mask):
                self.log.info("Observed %s mask=0x%x expected=0x%x %s", name, mask, expected, label)
                return observed
        await ReadOnly()
        observed = int(getattr(self.xtrig.dut, name).value) & mask
        self.assert_equal(f"{name}.mask", observed, expected & mask, label)
        return observed

    async def check_quiet(self, label: str, *, cycles: int = 4) -> None:
        activity = await self.xtrig.assert_quiet(self.QUIET_GROUPS, cycles=cycles)
        for name, value in activity.items():
            self.assert_equal(f"quiet.{label}.{name}", value, 0)

    async def configure_ctp_mode_for_port(self, port: int, mode: int, *, stretch: int = 1) -> None:
        if self.is_ctp_port(port):
            await self.program_ctp(port, mode=mode, stretch=stretch)

    async def configure_ctp_modes_for_route(self, input_port: int, output_mask: int, mode: int) -> None:
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
            await self.xtrig.drive_internal_dst_pulse(self.int_idx_from_port(input_port), cycles=cycles)

    async def check_output_mask(self, output_mask: int, mode: int, *, label: str) -> None:
        ctp_outputs = project_ctp_mask(output_mask)
        int_outputs = project_internal_mask(output_mask)
        if ctp_outputs:
            signal = "xtrig_ctp_req_out_dout" if mode == XTRIG_CTP_MODE_P2P else "xtrig_ctp_req_out_dout_en"
            await self.wait_signal_mask(signal, ctp_outputs, ctp_outputs, label=f"{label}.ctp")
            if mode == XTRIG_CTP_MODE_P2P:
                self.xtrig.dut.xtrig_ctp_ack_in_din.value = ctp_outputs
                await ClockCycles(self.xtrig.clk, 3)
                self.xtrig.dut.xtrig_ctp_ack_in_din.value = 0
        if int_outputs:
            await self.wait_signal_mask("xtrig_ctm_src_req", int_outputs, int_outputs, label=f"{label}.internal")

        # Negative check: after the event drains, no selected-output residue should remain.
        await ClockCycles(self.xtrig.clk, 6)
        sample = await self.sample_xtrig(f"{label}.post")
        self.assert_equal(
            f"{label}.unselected_internal_quiet",
            sample.get("xtrig_ctm_src_req", 0) & ~int_outputs,
            0,
        )

    async def verify_route(self, input_port: int, output_mask: int, mode: int, *, label: str) -> None:
        await self.configure_ctp_modes_for_route(input_port, output_mask, mode)
        await self.program_route(input_port, output_mask, label=label)
        await self.xtrig.clear_inputs()
        await ClockCycles(self.xtrig.clk, 2)
        await self.drive_input_port(input_port, mode)
        await self.check_output_mask(output_mask, mode, label=label)

    async def verify_route_cases(self, cases: list[tuple[int, int]], mode: int, *, label: str) -> None:
        for idx, (input_port, output_mask) in enumerate(cases, start=1):
            self.log_iteration(idx, len(cases), "%s input=%d output_mask=0x%x", label, input_port, output_mask)
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
        ctp_idx = 0
        int_port = internal_ct_port(0)
        ctp_port = external_ctp_port(ctp_idx)

        for stretch in (15, 0):
            self.log_step("setup", "Configure wire-OR stretch=%d and route internal CT to CTP", stretch)
            await self.program_ctp(ctp_idx, mode=XTRIG_CTP_MODE_WIRE_OR, stretch=stretch)
            await self.program_route(int_port, 1 << ctp_port, label=f"wire_or.stretch{stretch}")
            await self.xtrig.clear_inputs()
            await self.xtrig.drive_internal_dst_pulse(0, cycles=1)
            width = await self.xtrig.measure_mask_width("xtrig_ctp_req_out_dout_en", 1 << ctp_idx)
            self.assert_equal(f"wire_or.stretch{stretch}.width", width, stretch + 1)
            status = await self.csr_read(ctp_status_addr(ctp_idx), label=f"wire_or.stretch{stretch}.status")
            self.log.info("wire_or stretch=%d decoded status %s", stretch, self.xtrig.decode_status(status))
            await ClockCycles(self.xtrig.clk, stretch + 4)
            status = await self.csr_read(ctp_status_addr(ctp_idx), label=f"wire_or.stretch{stretch}.status_clear")
            self.assert_equal(f"wire_or.stretch{stretch}.busy_clear", int(bool(status & XTRIG_CTP_STATUS_BUSY)), 0)

        self.log_step("sync", "Drive external CT_Req_out input and expect internal CT delivery")
        await self.program_ctp(ctp_idx, mode=XTRIG_CTP_MODE_WIRE_OR, stretch=0)
        await self.program_route(ctp_port, 1 << int_port, label="wire_or.external_to_internal")
        await self.xtrig.drive_ctp_req_out_din_pulse(ctp_idx, cycles=2)
        await self.wait_signal_mask("xtrig_ctm_src_req", 1 << 0, 1 << 0, label="wire_or.external_sync")
        self.log_summary("wire_or", ctp=ctp_idx, checked_stretches="15,0")

    async def run_p2p(self) -> None:
        self.log_banner("DTP XTRIG CTP point-to-point handshakes")
        ctp_idx = 0
        ctp_port = external_ctp_port(ctp_idx)
        int_port = internal_ct_port(0)
        await self.program_ctp(ctp_idx, mode=XTRIG_CTP_MODE_P2P, stretch=0)

        self.log_step(1, "Internal trigger should assert CT_Req_out until CT_Ack_in")
        await self.program_route(int_port, 1 << ctp_port, label="p2p.internal_to_ctp")
        await self.xtrig.pulse_ctm_dst_req(1 << 0, cycles=2)
        await self.wait_signal_mask("xtrig_ctp_req_out_dout", 1 << ctp_idx, 1 << ctp_idx, label="p2p.req_out")
        status = await self.csr_read(ctp_status_addr(ctp_idx), label="p2p.status_busy")
        self.assert_equal("p2p.status.req_out", int(bool(status & XTRIG_CTP_STATUS_REQ_OUT)), 1)
        await self.xtrig.drive_ctp_p2p_ack_in(ctp_idx, 1)
        await ClockCycles(self.xtrig.clk, 3)
        await self.xtrig.drive_ctp_p2p_ack_in(ctp_idx, 0)
        await self.wait_signal_mask("xtrig_ctp_req_out_dout", 1 << ctp_idx, 0, label="p2p.req_out_clear")

        self.log_step(2, "External CT_Req_in should assert CT_Ack_out and deliver internal trigger")
        await self.program_route(ctp_port, 1 << int_port, label="p2p.ctp_to_internal")
        await self.xtrig.drive_ctp_p2p_req_in(ctp_idx, 1)
        await self.wait_signal_mask("xtrig_ctp_ack_out_dout", 1 << ctp_idx, 1 << ctp_idx, label="p2p.ack_out")
        await self.wait_signal_mask("xtrig_ctm_src_req", 1 << 0, 1 << 0, label="p2p.internal_delivery")
        await self.xtrig.drive_ctp_p2p_req_in(ctp_idx, 0)
        await ClockCycles(self.xtrig.clk, 3)
        self.log_summary("p2p", ctp=ctp_idx)

    async def run_reset(self) -> None:
        self.log_banner("DTP XTRIG CTP reset recovery")
        ctp_idx = 0
        ctp_port = external_ctp_port(ctp_idx)
        int_port = internal_ct_port(0)
        await self.program_ctp(ctp_idx, mode=XTRIG_CTP_MODE_P2P)
        await self.program_route(int_port, 1 << ctp_port, label="reset.deadlock_setup")
        await self.xtrig.pulse_ctm_dst_req(1 << 0, cycles=2)
        await self.wait_signal_mask("xtrig_ctp_req_out_dout", 1 << ctp_idx, 1 << ctp_idx, label="reset.stuck_req")
        status = await self.csr_read(ctp_status_addr(ctp_idx), label="reset.busy_before")
        self.assert_equal("reset.busy_before", int(bool(status & XTRIG_CTP_STATUS_BUSY)), 1)

        await self.program_ctp(ctp_idx, mode=XTRIG_CTP_MODE_P2P, reset=1)
        await ClockCycles(self.xtrig.clk, 3)
        await self.wait_signal_mask("xtrig_ctp_req_out_dout", 1 << ctp_idx, 0, label="reset.config_reset_clear")
        await self.program_ctp(ctp_idx, mode=XTRIG_CTP_MODE_P2P, reset=0)
        await self.verify_route(int_port, 1 << ctp_port, XTRIG_CTP_MODE_P2P, label="reset.post_config_reset")

        await self.program_ctp(1, mode=XTRIG_CTP_MODE_WIRE_OR, invert=1, stretch=7)
        await self.program_ctm_src(1, 1 << internal_ct_port(1))
        await self.xtrig.pulse_reset(cycles=3)
        await self.write_read_check(ctp_config_addr(1), 0, 0, mask=XTRIG_CTP_CONFIG_MASK, label="reset.ctp1.default_cfg")
        await self.write_read_check(ctp_stretch_addr(1), 0, 0, mask=XTRIG_CTP_STRETCH_MASK, label="reset.ctp1.default_stretch")
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
            await self.program_route(internal_ct_port(int_idx), 1 << external_ctp_port(ctp_idx), label=f"random.{idx}")
            await self.xtrig.pulse_ctm_dst_req(1 << int_idx, cycles=1)
            if mode == XTRIG_CTP_MODE_P2P:
                await self.wait_signal_mask("xtrig_ctp_req_out_dout_en", 1 << ctp_idx, 1 << ctp_idx, label=f"random.{idx}.oen")
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
                await self.wait_signal_mask("xtrig_ctp_req_out_dout_en", 1 << ctp_idx, 1 << ctp_idx, label=f"random.{idx}.wire_en")
                expected_data = (1 << ctp_idx) if invert else 0
                await self.wait_signal_mask("xtrig_ctp_req_out_dout", 1 << ctp_idx, expected_data, label=f"random.{idx}.wire_polarity")
        self.log_summary("random", iterations=self.random_count)

    async def run_ctp_csr_sweep(self) -> None:
        self.log_banner("DTP XTRIG CTP deterministic CSR and byte-strobe sweep")
        patterns = [
            pack_ctp_config(mode=XTRIG_CTP_MODE_WIRE_OR),
            pack_ctp_config(mode=XTRIG_CTP_MODE_WIRE_OR, invert=1),
            pack_ctp_config(mode=XTRIG_CTP_MODE_P2P),
            pack_ctp_config(mode=XTRIG_CTP_MODE_P2P, invert=1, reset=1),
        ]
        for ctp_idx in range(XTRIG_NUM_CTP):
            for pat_idx, config_word in enumerate(patterns):
                self.log_iteration(ctp_idx * len(patterns) + pat_idx + 1, XTRIG_NUM_CTP * len(patterns), "CTP[%d] cfg=0x%x", ctp_idx, config_word)
                await self.write_read_check(ctp_config_addr(ctp_idx), config_word, config_word, mask=XTRIG_CTP_CONFIG_MASK, label=f"ctp{ctp_idx}.cfg{pat_idx}")
            for stretch in (0, 1, 0x55AA, 0xFFFF):
                await self.write_read_check(ctp_stretch_addr(ctp_idx), stretch, stretch, mask=XTRIG_CTP_STRETCH_MASK, label=f"ctp{ctp_idx}.stretch{stretch:04x}")
            base = pack_ctp_config(mode=XTRIG_CTP_MODE_WIRE_OR)
            await self.csr_write(ctp_config_addr(ctp_idx), base, label=f"ctp{ctp_idx}.byte_base")
            expected = apply_wstrb(base, pack_ctp_config(mode=XTRIG_CTP_MODE_P2P, invert=1), 0x1)
            await self.write_read_check(ctp_config_addr(ctp_idx), pack_ctp_config(mode=XTRIG_CTP_MODE_P2P, invert=1), expected, wstrb=0x1, mask=XTRIG_CTP_CONFIG_MASK, label=f"ctp{ctp_idx}.byte0")
        self.log_summary("ctp_csr_sweep", ctp_count=XTRIG_NUM_CTP)

    async def run_dst_port_sweep(self) -> None:
        self.log_banner("DTP XTRIG deterministic destination-port sweep")
        input_port = internal_ct_port(0)
        for output_port in range(XTRIG_NUM_CTM_PORTS):
            self.log_iteration(output_port + 1, XTRIG_NUM_CTM_PORTS, "input internal0 -> output port %d", output_port)
            mode = XTRIG_CTP_MODE_WIRE_OR if self.is_ctp_port(output_port) else XTRIG_CTP_MODE_WIRE_OR
            await self.verify_route(input_port, 1 << output_port, mode, label=f"dst_sweep.port{output_port}")
            if not self.is_ctp_port(output_port):
                ack_mask = 1 << self.int_idx_from_port(output_port)
                self.xtrig.dut.xtrig_ctm_src_ack.value = ack_mask
                await ClockCycles(self.xtrig.clk, 1)
                self.xtrig.dut.xtrig_ctm_src_ack.value = 0
        self.log_summary("dst_port_sweep", outputs=XTRIG_NUM_CTM_PORTS)

    # ------------------------------------------------------------------
    # AXI-Lite skew/default path scenarios
    # ------------------------------------------------------------------
    async def run_reg_stall(self) -> None:
        self.log_banner("DTP XTRIG accepted-path CSR access and stall rationale")
        await self.write_read_check(ctp_config_addr(0), pack_ctp_config(invert=1), pack_ctp_config(invert=1), mask=XTRIG_CTP_CONFIG_MASK, label="regstall.ctp0.config")
        await self.write_read_check(ctp_stretch_addr(0), 0x1234, 0x1234, mask=XTRIG_CTP_STRETCH_MASK, label="regstall.ctp0.stretch")
        await self.write_read_check(ctm_config_addr(0), (1 << internal_ct_port(0)) | (1 << external_ctp_port(1)), (1 << internal_ct_port(0)) | (1 << external_ctp_port(1)), mask=XTRIG_CTM_SELECT_MASK, label="regstall.ctm0")
        await self.check_quiet("reg_stall_accepted")
        sample = await self.sample_xtrig("accepted_path")
        self.assert_equal("regstall.awvalid_count_nonzero", int(sample["xtrig_axil_awvalid_count"] > 0), 1)
        self.assert_equal("regstall.arvalid_count_nonzero", int(sample["xtrig_axil_arvalid_count"] > 0), 1)
        self.log_summary("reg_stall", rationale="local regblock stall path documented as structurally unreachable")

    async def run_axi_channel_skew(self) -> None:
        self.log_banner("DTP XTRIG manual AXI-Lite AW/W and RREADY skew")
        addr = ctp_stretch_addr(0)
        resp = await self.axil.write_skewed(addr, 0x0000002A, aw_before_w=True, gap_cycles=4, bready_delay=3)
        self.assert_equal("axi_skew.aw_before_w.bresp", resp, self.AXI_OKAY)
        await self.write_read_check(addr, 0x00000055, 0x00000055, mask=XTRIG_CTP_STRETCH_MASK, label="axi_skew.normal_after_aw")
        resp = await self.axil.write_skewed(addr, 0x00000033, aw_before_w=False, gap_cycles=5, bready_delay=2)
        self.assert_equal("axi_skew.w_before_aw.bresp", resp, self.AXI_OKAY)
        observed = await self.csr_read(addr, label="axi_skew.final_read")
        self.assert_equal("axi_skew.final_stretch", observed & XTRIG_CTP_STRETCH_MASK, 0x33)
        data, rresp, stable = await self.axil.read_with_rready_hold(addr, hold_cycles=5)
        self.assert_equal("axi_skew.rresp", rresp, self.AXI_OKAY)
        self.assert_equal("axi_skew.rstable", stable, 1)
        self.assert_equal("axi_skew.rdata", data & XTRIG_CTP_STRETCH_MASK, 0x33)
        self.log_summary("axi_channel_skew", final=f"0x{data:08x}")

    async def run_axi_channel_skew_demux_aw_lock_release(self) -> None:
        self.log_banner("DTP XTRIG AXI-Lite demux AW-lock release")
        for idx, (addr, data, aw_first) in enumerate(
            (
                (ctp_config_addr(0), pack_ctp_config(mode=XTRIG_CTP_MODE_P2P), True),
                (ctp_config_addr(1), pack_ctp_config(mode=XTRIG_CTP_MODE_WIRE_OR, invert=1), True),
                (ctm_config_addr(2), 1 << internal_ct_port(0), False),
            ),
            start=1,
        ):
            self.log_iteration(idx, 3, "addr=0x%x data=0x%x aw_first=%d", addr, data, aw_first)
            resp = await self.axil.write_skewed(addr, data, aw_before_w=aw_first, gap_cycles=6, bready_delay=2)
            self.assert_equal(f"demux_aw_lock.{idx}.bresp", resp, self.AXI_OKAY)
            observed = await self.csr_read(addr, label=f"demux_aw_lock.{idx}.readback")
            mask = XTRIG_CTP_CONFIG_MASK if addr >= 0x200 else XTRIG_CTM_SELECT_MASK
            self.assert_equal(f"demux_aw_lock.{idx}.readback", observed & mask, data & mask)
        self.log_summary("axi_channel_skew_demux_aw_lock_release", writes=3)

    async def run_axi_channel_skew_read_decode_backpressure(self) -> None:
        self.log_banner("DTP XTRIG AXI-Lite read decode backpressure")
        for idx, addr in enumerate((XTRIG_UNMAPPED_BASE, XTRIG_UNMAPPED_BASE + 0x40), start=1):
            data, resp, stable = await self.axil.read_with_rready_hold(addr, hold_cycles=6)
            self.log_iteration(idx, 2, "unmapped addr=0x%x data=0x%x resp=%d stable=%d", addr, data, resp, stable)
            self.assert_equal(f"read_decode.{idx}.resp", resp, self.AXI_DECERR)
            self.assert_equal(f"read_decode.{idx}.stable", stable, 1)
        self.log_summary("axi_channel_skew_read_decode_backpressure", unmapped_base=f"0x{XTRIG_UNMAPPED_BASE:x}")

    # ------------------------------------------------------------------
    # CTM route scenarios
    # ------------------------------------------------------------------
    async def run_ctm_wire_or_cla_to_ctp(self) -> None:
        await self.run_ctm_wire_or_route_class("cla_to_ctp", internal_ct_port(0), ctp_mask(0, 5, 15), overlap_input=internal_ct_port(1), overlap_output=external_ctp_port(5))

    async def run_ctm_wire_or_ctp_to_cla(self) -> None:
        await self.run_ctm_wire_or_route_class("ctp_to_cla", external_ctp_port(0), internal_ct_mask(0, 1, 3), overlap_input=external_ctp_port(1), overlap_output=internal_ct_port(1))

    async def run_ctm_wire_or_cla_to_cla(self) -> None:
        await self.run_ctm_wire_or_route_class("cla_to_cla", internal_ct_port(0), internal_ct_mask(1, 2, 4), overlap_input=internal_ct_port(3), overlap_output=internal_ct_port(2))

    async def run_ctm_wire_or_ctp_to_ctp(self) -> None:
        await self.run_ctm_wire_or_route_class("ctp_to_ctp", external_ctp_port(0), ctp_mask(1, 2, 7), overlap_input=external_ctp_port(3), overlap_output=external_ctp_port(2))

    async def run_ctm_wire_or_route_class(self, name: str, input_port: int, output_mask: int, *, overlap_input: int, overlap_output: int) -> None:
        self.log_banner(f"DTP CTM wire-OR routing {name}")
        await self.verify_route(input_port, output_mask, XTRIG_CTP_MODE_WIRE_OR, label=f"wire_or.{name}.main")
        await self.clear_ctm_routes()
        await self.configure_ctp_modes_for_route(input_port, output_mask | (1 << overlap_output), XTRIG_CTP_MODE_WIRE_OR)
        await self.configure_ctp_mode_for_port(overlap_input, XTRIG_CTP_MODE_WIRE_OR, stretch=1)
        await self.program_ctm_src(overlap_output, (1 << input_port) | (1 << overlap_input))
        await self.drive_input_port(input_port, XTRIG_CTP_MODE_WIRE_OR)
        await self.drive_input_port(overlap_input, XTRIG_CTP_MODE_WIRE_OR)
        await self.check_output_mask(1 << overlap_output, XTRIG_CTP_MODE_WIRE_OR, label=f"wire_or.{name}.overlap")
        self.log_summary(f"ctm_wire_or_{name}", input=input_port, outputs=f"0x{output_mask:x}")

    async def run_ctm_p2p_cla_to_ctp(self) -> None:
        await self.run_ctm_p2p_route_class("cla_to_ctp", [(internal_ct_port(0), external_ctp_port(0)), (internal_ct_port(2), external_ctp_port(5)), (internal_ct_port(4), external_ctp_port(15))])

    async def run_ctm_p2p_ctp_to_cla(self) -> None:
        await self.run_ctm_p2p_route_class("ctp_to_cla", [(external_ctp_port(0), internal_ct_port(0)), (external_ctp_port(5), internal_ct_port(2)), (external_ctp_port(15), internal_ct_port(4))])

    async def run_ctm_p2p_cla_to_cla(self) -> None:
        await self.run_ctm_p2p_route_class("cla_to_cla", [(internal_ct_port(0), internal_ct_port(1)), (internal_ct_port(2), internal_ct_port(3)), (internal_ct_port(4), internal_ct_port(5))])

    async def run_ctm_p2p_ctp_to_ctp(self) -> None:
        await self.run_ctm_p2p_route_class("ctp_to_ctp", [(external_ctp_port(0), external_ctp_port(1)), (external_ctp_port(3), external_ctp_port(7)), (external_ctp_port(8), external_ctp_port(15))])

    async def run_ctm_p2p_route_class(self, name: str, pairs: list[tuple[int, int]]) -> None:
        self.log_banner(f"DTP CTM point-to-point routing {name}")
        for idx, (input_port, output_port) in enumerate(pairs, start=1):
            self.log_iteration(idx, len(pairs), "%s input=%d output=%d", name, input_port, output_port)
            await self.verify_route(input_port, 1 << output_port, XTRIG_CTP_MODE_P2P, label=f"p2p.{name}.{idx}")
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
        await self.verify_route(internal_ct_port(0), ctp_mask(0, 1), XTRIG_CTP_MODE_WIRE_OR, label="reset_all.pre_wire")
        await self.verify_route(internal_ct_port(1), 1 << external_ctp_port(2), XTRIG_CTP_MODE_P2P, label="reset_all.pre_p2p")
        await self.xtrig.pulse_reset(cycles=3)
        await self.check_all_ctm_cleared("reset_all")
        await self.check_quiet("reset_all")
        await self.verify_route(internal_ct_port(0), 1 << external_ctp_port(0), XTRIG_CTP_MODE_WIRE_OR, label="reset_all.post_wire")
        await self.verify_route(internal_ct_port(1), 1 << external_ctp_port(1), XTRIG_CTP_MODE_P2P, label="reset_all.post_p2p")
        self.log_summary("ctm_reset_all_modes")

    async def run_ctm_reset_mode(self, name: str, mode: int) -> None:
        self.log_banner(f"DTP CTM reset in {name} mode")
        output_mask = ctp_mask(0, 4) if mode == XTRIG_CTP_MODE_WIRE_OR else 1 << external_ctp_port(3)
        await self.verify_route(internal_ct_port(0), output_mask, mode, label=f"reset_{name}.pre")
        await self.xtrig.pulse_reset(cycles=3)
        await self.check_all_ctm_cleared(f"reset_{name}")
        await self.check_quiet(f"reset_{name}")
        await self.verify_route(internal_ct_port(1), 1 << external_ctp_port(1), mode, label=f"reset_{name}.post")
        self.log_summary(f"ctm_reset_{name}")

    async def run_ctm_rand_all_scenarios(self) -> None:
        await self.run_ctm_random("all_scenarios", source_class="all", dest_class="all", multicast=True, p2p=True)

    async def run_ctm_rand_wire_or_only(self) -> None:
        await self.run_ctm_random("wire_or_only", source_class="all", dest_class="all", multicast=True, p2p=False)

    async def run_ctm_rand_p2p_only(self) -> None:
        await self.run_ctm_random("p2p_only", source_class="all", dest_class="all", multicast=False, p2p=True)

    async def run_ctm_rand_cla_to_ctp(self) -> None:
        await self.run_ctm_random("cla_to_ctp", source_class="internal", dest_class="ctp", multicast=True, p2p=True)

    async def run_ctm_rand_ctp_to_cla(self) -> None:
        await self.run_ctm_random("ctp_to_cla", source_class="ctp", dest_class="internal", multicast=True, p2p=True)

    async def run_ctm_random(self, name: str, *, source_class: str, dest_class: str, multicast: bool, p2p: bool) -> None:
        self.log_banner(f"DTP CTM seeded random routing {name}")
        rng = self.rng(f"ctm_random_{name}")
        source_pool = self.port_pool(source_class)
        dest_pool = self.port_pool(dest_class)
        for idx in range(self.random_count):
            input_port = rng.choice(source_pool)
            mode = XTRIG_CTP_MODE_P2P if (p2p and (not multicast or rng.randrange(2))) else XTRIG_CTP_MODE_WIRE_OR
            if mode == XTRIG_CTP_MODE_P2P:
                selected = [rng.choice([d for d in dest_pool if d != input_port] or dest_pool)]
            else:
                choices = [d for d in dest_pool if d != input_port]
                rng.shuffle(choices)
                selected = choices[: max(2, min(4, len(choices)))]
            output_mask = sum(1 << port for port in selected)
            self.log_iteration(idx + 1, self.random_count, "input=%d mode=%d outputs=0x%x", input_port, mode, output_mask)
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
        patterns = [0, 1, 1 << external_ctp_port(0), 1 << internal_ct_port(0), XTRIG_CTM_SELECT_MASK, 0x0155_AA55 & XTRIG_CTM_SELECT_MASK]
        for src_idx in range(XTRIG_NUM_CTM_PORTS):
            for pat_idx, dst_mask in enumerate(patterns):
                await self.write_read_check(ctm_config_addr(src_idx), dst_mask, dst_mask, mask=XTRIG_CTM_SELECT_MASK, label=f"ctm{src_idx}.pat{pat_idx}")
            old_mask = 0x0000_00AA
            new_mask = 0x0000_5500
            await self.program_ctm_src(src_idx, old_mask)
            expected = apply_wstrb(old_mask, new_mask, 0x2) & XTRIG_CTM_SELECT_MASK
            await self.write_read_check(ctm_config_addr(src_idx), new_mask, expected, wstrb=0x2, mask=XTRIG_CTM_SELECT_MASK, label=f"ctm{src_idx}.byte1")
        self.log_summary("ctm_csr_sweep", sources=XTRIG_NUM_CTM_PORTS)

    async def run_ctm_all_source_select(self) -> None:
        self.log_banner("DTP CTM all-source select coverage")
        for src_idx in range(XTRIG_NUM_CTM_PORTS):
            masks = [1 << (src_idx % XTRIG_NUM_CTM_PORTS), (1 << src_idx) | (1 << ((src_idx + 1) % XTRIG_NUM_CTM_PORTS)), (~(1 << src_idx)) & XTRIG_CTM_SELECT_MASK]
            neighbor = ctm_config_addr((src_idx + 1) % XTRIG_NUM_CTM_PORTS)
            before_neighbor = await self.csr_read(neighbor, label=f"allsrc{src_idx}.neighbor_before")
            for mask_idx, dst_mask in enumerate(masks):
                await self.write_read_check(ctm_config_addr(src_idx), dst_mask, dst_mask, mask=XTRIG_CTM_SELECT_MASK, label=f"allsrc{src_idx}.mask{mask_idx}")
            after_neighbor = await self.csr_read(neighbor, label=f"allsrc{src_idx}.neighbor_after")
            if ((src_idx + 1) % XTRIG_NUM_CTM_PORTS) != src_idx:
                self.assert_equal(f"allsrc{src_idx}.neighbor_no_alias", after_neighbor & XTRIG_CTM_SELECT_MASK, before_neighbor & XTRIG_CTM_SELECT_MASK)
        self.log_summary("ctm_all_source_select", sources=XTRIG_NUM_CTM_PORTS)
