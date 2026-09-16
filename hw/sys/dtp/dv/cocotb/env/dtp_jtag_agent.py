# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP JTAG UVM agent.

The UVM driver translates ``DtpJtagItem`` transactions into the unified OCAH
JTAG BFM calls against the DUT primary TAP, then broadcasts completed
transactions (with results) on an analysis port for the scoreboard.
"""

from __future__ import annotations

from cocotb.triggers import NextTimeStep, ReadOnly, Timer
from ocah_jtag_vip import OcahJtagMasterDriver, OcahJtagState
from pyuvm import (
    ConfigDB,
    uvm_agent,
    uvm_analysis_port,
    uvm_driver,
    uvm_sequencer,
)

from .dtp_jtag_item import DtpJtagItem, DtpJtagOp
from .dtp_tap_device import DtpTapDevice
from .dtp_types import (
    DTP_IR_WIDTH,
    DtpJtag2AxiOp,
    DtpJtag2AxiStatus,
    pack_single_op,
    unpack_single_op,
)

# Status re-reads while the JTAG2AXI bridge completes the CDC + AXI round trip.
J2A_STATUS_POLLS = 16


class DtpJtagDriver(uvm_driver):
    """Drives DtpJtagItem transactions through the unified OCAH JTAG BFM."""

    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.ap = uvm_analysis_port("ap", self)
        self.jtag: OcahJtagMasterDriver | None = None
        self.tap_device = DtpTapDevice(idle_delay=self.cfg.idle_tck)
        self.tb_if = ConfigDB().get(self, "", "tb_if")

    async def run_phase(self) -> None:
        self.jtag = OcahJtagMasterDriver(
            self.tb_if.jtag,
            name="dtp_ptap",
            tck_period_ns=self.cfg.jtag_period_ns,
            ir_width=DTP_IR_WIDTH,
            tap_type="ptap",
            signal_map=self.tb_if.JTAG_SIGNAL_MAP,
        )
        self.jtag.init_signals()
        # Wait until the base test has clocks running and resets released.
        await self.cfg.reset_done.wait()
        await self.jtag.reset_tap()
        self.logger.info("OCAH JTAG BFM ready")

        while True:
            item = await self.seq_item_port.get_next_item()
            await self._drive(item)
            self.ap.write(item)
            self.seq_item_port.item_done()

    async def _drive(self, item: DtpJtagItem) -> None:
        jtag = self.jtag
        if item.op is DtpJtagOp.RESET:
            await jtag.reset_tap()
        elif item.op is DtpJtagOp.RESET_FSM:
            await jtag.reset_tap()
            await ReadOnly()
            item.result = self.tb_if.sample("jtag_ptap_state")
            await NextTimeStep()
        elif item.op is DtpJtagOp.TMS_STEP:
            await self._drive_tms_step(item)
        elif item.op is DtpJtagOp.SHIFT_IR:
            item.result = await self._shift_ir(item)
        elif item.op is DtpJtagOp.SHIFT_DR:
            item.result = await self._shift_dr(item)
        elif item.op is DtpJtagOp.SET_TRST:
            await self._set_trst(item)
        elif item.op is DtpJtagOp.PULSE_POR:
            await self._pulse_por(item)
        elif item.op is DtpJtagOp.SAMPLE:
            await self._sample_observables(item)
        elif item.op is DtpJtagOp.READ:
            item.result = await self._read_reg(item.reg, shift_value=item.value)
        elif item.op is DtpJtagOp.WRITE:
            await self._write_reg(item.reg, item.value)
        elif item.op is DtpJtagOp.J2A_WRITE:
            await self._write_reg(
                "SMC_AXI_SINGLE_OP",
                pack_single_op(
                    DtpJtag2AxiOp.WRITE,
                    item.axi_addr,
                    item.axi_data,
                    wstrb=item.axi_wstrb,
                    size=item.axi_size,
                ),
            )
            item.status, _ = await self._poll_single_op_status()
        elif item.op is DtpJtagOp.J2A_READ:
            await self._write_reg(
                "SMC_AXI_SINGLE_OP",
                pack_single_op(DtpJtag2AxiOp.READ, item.axi_addr, size=item.axi_size),
            )
            item.status, item.rdata = await self._poll_single_op_status()
        else:
            raise ValueError(f"unknown JTAG op {item.op}")
        self.logger.debug("drove %s", item)

    async def _drive_tms_step(self, item: DtpJtagItem) -> None:
        """Drive one IEEE 1149.1 TMS cycle and sample the DUT TAP state."""
        await self.jtag.step_tms(item.tms)
        await ReadOnly()
        item.result = self.tb_if.sample("jtag_ptap_state")
        await NextTimeStep()

    async def _shift_ir(self, item: DtpJtagItem) -> int:
        """Shift a raw IR value and return captured previous-IR bits."""
        width = item.width or DTP_IR_WIDTH
        return await self.jtag.shift_ir(
            item.value,
            width=width,
            back_to_rti=item.back_to_rti,
        )

    async def _shift_dr(self, item: DtpJtagItem) -> int:
        """Shift raw DR data and return captured TDO bits."""
        if item.width <= 0:
            raise ValueError("SHIFT_DR requires item.width > 0")
        return await self.jtag.shift_dr(
            item.value,
            width=item.width,
            back_to_rti=item.back_to_rti,
        )

    async def _set_trst(self, item: DtpJtagItem) -> None:
        """Drive TRST_N, hold it across TCK cycles, and sample the TAP state.

        Asserting samples the state once the pin has settled and before any
        TCK edge, then clocks TCK with TMS low, which leaves Test-Logic-Reset
        unless the reset holds the controller there. Releasing clocks TCK
        with TMS high, the Test-Logic-Reset self-loop.
        """
        asserted = (item.value & 0x1) == 0
        self.tb_if.jtag.trst_n.value = item.value & 0x1
        await ReadOnly()
        item.reset_state = self.tb_if.sample("jtag_ptap_state")
        await NextTimeStep()
        for _ in range(max(item.cycles, 1)):
            await self.jtag.step_tms(0 if asserted else 1)
        await self._sample_observables(item)

    async def _pulse_por(self, item: DtpJtagItem) -> None:
        """Hold power-on reset for TCK periods with TCK idle and sample the TAP under it.

        The pulse carries no TCK edge, so the sampled Test-Logic-Reset comes
        from the reset alone; the BFM's tracked state is re-synchronized to
        the controller the reset moved without a clock on this bus.
        """
        hold_ns = max(item.cycles, 1) * self.cfg.jtag_period_ns
        self.tb_if.por_rst_n.value = 0
        await Timer(hold_ns, unit="ns")
        await self._sample_observables(item)
        self.tb_if.por_rst_n.value = 1
        await Timer(hold_ns, unit="ns")
        self.jtag.sync_model(OcahJtagState.TEST_LOGIC_RESET)

    async def _sample_observables(self, item: DtpJtagItem) -> None:
        """Sample the DTP observables of the domain interfaces by their flat names."""
        await ReadOnly()
        item.result = self.tb_if.sample("jtag_ptap_state")
        item.signals = {"jtag_ptap_state": item.result}
        item.decoded = self.tb_if.sample("jtag_ptap_inst_decoded")
        item.signals["jtag_ptap_inst_decoded"] = item.decoded
        for name in (
            "jtag_trst",
            "jtag_bsr_select",
            "jtag_bsr_shift_en",
            "jtag_bsr_capture_en",
            "jtag_bsr_update_en",
            "jtag_bsr_run_test_idle",
            "jtag_bsr_test_logic_reset",
            "jtag_bsr_runbist",
            "jtag_dft_secure_select",
            "jtag_dft_secure_shift_en",
            "jtag_dft_secure_capture_en",
            "jtag_dft_secure_update_en",
            "jtag_dft_select",
            "jtag_dft_shift_en",
            "jtag_dft_capture_en",
            "jtag_dft_update_en",
            "jtag_dft_run_test_idle",
            "jtag_dft_test_logic_reset",
            "jtag_dft_runbist",
            "jtag_dfd_select",
            "jtag_dfd_shift_en",
            "jtag_dfd_capture_en",
            "jtag_dfd_update_en",
            "jtag_stap_host_select",
            "jtag_stap_host_shift_en",
            "jtag_stap_host_capture_en",
            "jtag_stap_host_update_en",
            "jtag_stap_io_tms",
            "jtag_stap_io_tck",
            "jtag_stap_io_trst_n",
            "jtag_stap_io_tdo_oen",
            "jtag_stap_smc_tms",
            "jtag_stap_smc_tck",
            "jtag_stap_smc_trst_n",
            "jtag_stap_smc_tdo_oen",
            "jtag_stap_sep_tms",
            "jtag_stap_sep_tck",
            "jtag_stap_sep_trst_n",
            "jtag_stap_sep_tdo_oen",
            "jtag_stap_extra0_tms",
            "jtag_stap_extra0_tck",
            "jtag_stap_extra0_trst_n",
            "jtag_stap_extra0_tdo_oen",
            "stop_clks",
            "cla_clock_stop_en",
            "jtag_boot_stall_ovrd",
            "jtag_boot_stall",
            "jtag_ic_reset_smc_ovrd",
            "jtag_ic_reset_smc_ctrl_n",
            "jtag_ic_reset_sep_ovrd",
            "jtag_ic_reset_sep_ctrl_n",
            "jtag_ic_reset_ext_ovrd",
            "jtag_ic_reset_ext_ctrl_n",
            "xtrig_clk_stop_req",
            "dbg_disable_stap_io",
            "dbg_disable_stap_smc",
            "dbg_disable_stap_sep",
            "dbg_disable_stap_extra",
            "dbg_disable_stap_host",
            "dbg_disable_dft_secure",
            "dbg_disable_dft_nonsecure",
            "dbg_disable_dfd",
            "dbg_disable_smc_jtag2axi",
            "dbg_disable_smc_otp_jtag2axi",
            "dbg_disable_sep_otp_jtag2axi",
            "smc_axi_awvalid_count",
            "smc_axi_wvalid_count",
            "smc_axi_arvalid_count",
            "smc_otp_axil_awvalid_count",
            "smc_otp_axil_wvalid_count",
            "smc_otp_axil_arvalid_count",
            "sep_otp_axil_awvalid_count",
            "sep_otp_axil_wvalid_count",
            "sep_otp_axil_arvalid_count",
            "xtrig_axil_awvalid_count",
            "xtrig_axil_wvalid_count",
            "xtrig_axil_arvalid_count",
            "xtrig_ctm_src_req",
            "xtrig_ctm_src_ack",
            "xtrig_ctm_dst_req",
            "xtrig_ctm_dst_ack",
            "xtrig_ctp_req_out_dout",
            "xtrig_ctp_req_out_dout_en",
            "xtrig_ctp_req_out_din",
            "xtrig_ctp_req_out_din_en",
            "xtrig_ctp_req_in_din",
            "xtrig_ctp_req_in_din_en",
            "xtrig_ctp_ack_in_din",
            "xtrig_ctp_ack_in_din_en",
            "xtrig_ctp_ack_out_dout",
            "xtrig_ctp_ack_out_dout_en",
        ):
            if self.tb_if.has(name):
                item.signals[name] = self.tb_if.sample(name)
        await NextTimeStep()

    async def _read_reg(self, name: str, shift_value: int = 0) -> int:
        """Read a DTP TDR by register-map name through the OCAH JTAG BFM."""
        reg = self.tap_device.reg(name)
        shift_value &= (1 << reg.width) - 1
        await self.jtag.shift_ir(reg.instr, width=DTP_IR_WIDTH)
        value = await self.jtag.shift_dr(shift_value, width=reg.width, back_to_rti=True)
        await self._idle_tck()
        return value

    async def _write_reg(self, name: str, value: int) -> None:
        """Write a DTP TDR by register-map name through the OCAH JTAG BFM."""
        reg = self.tap_device.reg(name)
        await self.jtag.shift_ir(reg.instr, width=DTP_IR_WIDTH)
        await self.jtag.shift_dr(value, width=reg.width, back_to_rti=True)
        await self._idle_tck()

    async def _idle_tck(self) -> None:
        for _ in range(self.tap_device.idle_delay):
            await self.jtag.step_tms(0)

    async def _poll_single_op_status(self) -> tuple[int, int]:
        """Re-read SMC_AXI_SINGLE_OP (a NOP op) until the bridge reports done.

        The first read after issuing an op can return BUSY_OR_FULL while the
        TCK<->ACLK CDC and AXI transaction complete; keep reading (each read
        carries the device idle delay) until the status settles.
        """
        status, rdata = DtpJtag2AxiStatus.BUSY_OR_FULL, 0
        for _ in range(J2A_STATUS_POLLS):
            raw = await self._read_reg("SMC_AXI_SINGLE_OP")
            status, rdata = unpack_single_op(raw)
            if status != DtpJtag2AxiStatus.BUSY_OR_FULL:
                break
        return status, rdata


class DtpJtagAgent(uvm_agent):
    def build_phase(self) -> None:
        self.sequencer = uvm_sequencer("sequencer", self)
        self.driver = DtpJtagDriver("driver", self)

    def connect_phase(self) -> None:
        self.driver.seq_item_port.connect(self.sequencer.seq_item_export)
        self.ap = self.driver.ap
