# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared PyUVM base test for SMC OSS (`--dut smc`).

Builds `SmcEnv`, runs power-good + cold-reset bring-up, and delegates scenario
work to `run_scenario()`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles
from pyuvm import ConfigDB, uvm_test

_COCOTB_ROOT = Path(__file__).resolve().parents[1]
_OSS_HW_ROOT = Path(__file__).resolve().parents[5]
for _path in (_COCOTB_ROOT, _OSS_HW_ROOT / "common" / "dv" / "vip"):
    _path_str = str(_path)
    if _path_str not in sys.path:
        sys.path.insert(0, _path_str)

from env.smc_env import SmcEnv
from env.smc_env_cfg import SmcEnvCfg
from env.smc_protocol_vip_item import SmcProtocolVipItem, SmcProtocolVipKind
from seq_lib._one_shot import _OneShot

# LEGACY registry: test-class-name -> protocol VIP kind for the auto-record at
# the end of run_phase. Prefer setting the ``protocol_vip_kind`` class attribute
# on the test itself (see smc_base_test.run_phase) for NEW tests -- that keeps the
# kind next to the test and avoids editing this central map (a typo here silently
# skips the auto-record). This dict is kept for the existing tests already listed.
_PROTOCOL_VIP_TESTS = {
    "smc_i2c_master_target_test": SmcProtocolVipKind.I2C,
    "smc_i2c_p1_rdwr_protocol_test": SmcProtocolVipKind.I2C,
    "smc_i2c_error_fifo_depth_test": SmcProtocolVipKind.I2C,
    "smc_smbus_pmbus_test": SmcProtocolVipKind.I2C,
    "smc_smbus_hostnotify_test": SmcProtocolVipKind.I2C,
    "smc_i3c_to_fabric_test": SmcProtocolVipKind.I3C,
    "smc_i3c_ccc_ibi_full_test": SmcProtocolVipKind.I3C,
    "smc_ijtag_basic_test": SmcProtocolVipKind.JTAG,
    "smc_efuse_jtag_lc_negative_test": SmcProtocolVipKind.JTAG,
    "smc_efuse_jtag_lc_access_matrix_test": SmcProtocolVipKind.JTAG,
    "smc_jtag_reset_proxy_test": SmcProtocolVipKind.JTAG,
    "smc_input_output_fabric_wr_rd_test": SmcProtocolVipKind.OUTPUT_FABRIC,
    "smc_output_filter_remap_security_test": SmcProtocolVipKind.OUTPUT_FABRIC,
    "smc_output_fabric_wr_rd_responder_test": SmcProtocolVipKind.OUTPUT_FABRIC,
    "smc_output_fabric_slverr_inject_test": SmcProtocolVipKind.OUTPUT_FABRIC,
    "smc_mailbox_irq_test": SmcProtocolVipKind.MAILBOX,
    "smc_mailbox_data_error_test": SmcProtocolVipKind.MAILBOX,
    "smc_mailbox_event_irq_test": SmcProtocolVipKind.MAILBOX,
    "smc_efuse_otp_clock_test": SmcProtocolVipKind.EFUSE,
    "smc_efuse_otp_clock_config_depth_test": SmcProtocolVipKind.EFUSE,
    "smc_efuse_permission_boundary_test": SmcProtocolVipKind.EFUSE,
    "smc_efuse_chip_config_read_test": SmcProtocolVipKind.EFUSE,
    "smc_pll_pvt_clock_config_test": SmcProtocolVipKind.CLOCK,
    "smc_pll_dvfs_depth_test": SmcProtocolVipKind.CLOCK,
    "smc_static_cg_sanity_test": SmcProtocolVipKind.CLOCK,
    "smc_gpio_irq_active_test": SmcProtocolVipKind.GPIO_IRQ,
    "smc_gpio_strap_sanity_test": SmcProtocolVipKind.GPIO_IRQ,
    "smc_external_interrupts_test": SmcProtocolVipKind.GPIO_IRQ,
    "smc_uart_spi_log_engine_test": SmcProtocolVipKind.UART_LOG,
    "smc_uart_log_engine_reg_rw_test": SmcProtocolVipKind.UART_LOG,
    "smc_uart_log_engine_error_boundary_test": SmcProtocolVipKind.UART_LOG,
    "smc_uart_loopback_test": SmcProtocolVipKind.UART_LOG,
    "smc_spi_loopback_test": SmcProtocolVipKind.UART_LOG,
    "smc_spi_pad_bfm_test": SmcProtocolVipKind.UART_LOG,
    "smc_sideband_protocol_smoke_test": SmcProtocolVipKind.SIDEBAND,
    "smc_sideband_avsbus_octs_bfm_test": SmcProtocolVipKind.SIDEBAND,
    "smc_octs_dual_sync_test": SmcProtocolVipKind.SIDEBAND,
    "octs_sanity_test": SmcProtocolVipKind.SIDEBAND,
    "smc_avsbus_sanity_test": SmcProtocolVipKind.SIDEBAND,
    "smc_avsbus_status_depth_test": SmcProtocolVipKind.SIDEBAND,
    "smc_avsbus_clock_config_proxy_test": SmcProtocolVipKind.SIDEBAND,
    "smc_zeroer_dma_timeout_test": SmcProtocolVipKind.ZEROER_DMA,
    "smc_zeroer_sanity_test": SmcProtocolVipKind.ZEROER_DMA,
    "smc_dma_sanity_test": SmcProtocolVipKind.ZEROER_DMA,
    "smc_ecc_dfd_dbs_sanity_test": SmcProtocolVipKind.DIAGNOSTIC,
    "smc_dfd_sanity_test": SmcProtocolVipKind.DIAGNOSTIC,
    "smc_cpu_ecc_lint_pint_depth_test": SmcProtocolVipKind.DIAGNOSTIC,
    "smc_dbs_idle_test": SmcProtocolVipKind.DIAGNOSTIC,
    "smc_cpu_to_sep_axi_test": SmcProtocolVipKind.CPU,
    "smc_cpu_sanity_test": SmcProtocolVipKind.CPU,
    "smc_cpu_firmware_boot_test": SmcProtocolVipKind.CPU,
    "smc_occp_sanity_secure_error_test": SmcProtocolVipKind.CPU,
    "smc_efuse_otp_burn_shadow_test": SmcProtocolVipKind.EFUSE,
    "smc_ecc_fault_inject_test": SmcProtocolVipKind.DIAGNOSTIC,
    "smc_dfd_dbs_fault_inject_test": SmcProtocolVipKind.DIAGNOSTIC,
    "smc_cpu_ctrl_map_depth_test": SmcProtocolVipKind.CPU,
    "smc_cpu_ctrl_scratch_window_test": SmcProtocolVipKind.CPU,
    # P1 coverage-gap depth slate (13 new tests, 2026-07-02)
    "smc_mailbox_inbound_test": SmcProtocolVipKind.MAILBOX,
    "smc_i2c_multi_instance_test": SmcProtocolVipKind.I2C,
    "smc_efuse_map_read_test": SmcProtocolVipKind.EFUSE,
    "smc_efuse_shim_ctrl_test": SmcProtocolVipKind.EFUSE,
    "smc_pll_cgm_awm_config_test": SmcProtocolVipKind.CLOCK,
    "smc_gpio_ctrl_full_sweep_test": SmcProtocolVipKind.GPIO_IRQ,
    "smc_uart_multi_instance_test": SmcProtocolVipKind.UART_LOG,
    "smc_telemetry_receiver_csr_test": SmcProtocolVipKind.SIDEBAND,
    "smc_cluster_cpu_infra_test": SmcProtocolVipKind.CPU,
    "smc_pvt_analog_sensor_test": SmcProtocolVipKind.CLOCK,
    "smc_remap_cla_test": SmcProtocolVipKind.OUTPUT_FABRIC,
    # P1 coverage-gap round 2 (2026-07-02)
    "smc_mailbox_multi_instance_test": SmcProtocolVipKind.MAILBOX,
    "smc_filter_multi_entry_test": SmcProtocolVipKind.OUTPUT_FABRIC,
    # P1 coverage-gap round 3 (2026-07-02)
    "smc_gpio_intf_full_sweep_test": SmcProtocolVipKind.GPIO_IRQ,
    "smc_mailbox_field_sweep_test": SmcProtocolVipKind.MAILBOX,
    "smc_filter_field_sweep_test": SmcProtocolVipKind.OUTPUT_FABRIC,
    "smc_pll_awm_freq_sweep_test": SmcProtocolVipKind.CLOCK,
    # P1 coverage-gap round 4 (2026-07-02) — previously-unreached CSR blocks
    "smc_xvisor_remap_test": SmcProtocolVipKind.OUTPUT_FABRIC,
    "smc_cluster_beu_test": SmcProtocolVipKind.CPU,
    # P1 coverage-gap round 5 (2026-07-02) — remaining leftover CSR blocks
    "smc_pvt_droop_test": SmcProtocolVipKind.CLOCK,
}


class smc_base_test(uvm_test):
    """Shared SMC OSS test: env build, clock/reset bring-up, scenario hook.

    A concrete test may set the class attribute ``protocol_vip_kind`` (a
    ``SmcProtocolVipKind``) to auto-record a protocol VIP evidence item after
    ``run_scenario``; this is preferred over adding the test to the legacy
    ``_PROTOCOL_VIP_TESTS`` map below. Set ``auto_protocol_vip = False`` to skip.
    """

    # Optional per-test override; None => fall back to the legacy name map.
    protocol_vip_kind = None

    @staticmethod
    def random_seed() -> int:
        return int(os.environ.get("RANDOM_SEED", "1"), 0)

    def build_phase(self) -> None:
        self.cfg = SmcEnvCfg("cfg")
        self.cfg.randomize_timing(self.random_seed())
        self.logger.info(
            "SMC timing: ref=%dns smc=%dns periph=%dns (seed=%d)",
            self.cfg.ref_clk_period_ns,
            self.cfg.smc_clk_period_ns,
            self.cfg.periph_clk_period_ns,
            self.random_seed(),
        )
        ConfigDB().set(None, "*", "cfg", self.cfg)
        self.env = SmcEnv("env", self)

    async def start_seq(self, seq, sequencer=None) -> None:
        seq.cfg = self.env.cfg
        seq.env = self.env
        if sequencer is None:
            sequencer = self.env.i2c_agent.sequencer
        await seq.start(sequencer)

    async def record_protocol_vip(
        self,
        kind: SmcProtocolVipKind,
        scenario: str,
        *,
        csr_accesses: int = 0,
        timeouts: int = 0,
        proxy: bool = True,
        details: str = "",
        expected_bytes: bytes | None = None,
        observed_bytes: bytes | None = None,
    ) -> None:
        item = SmcProtocolVipItem(f"{kind.value}_{scenario}")
        item.kind = kind
        item.scenario = scenario
        item.proxy = proxy
        item.csr_accesses = csr_accesses
        item.timeouts = timeouts
        item.details = details
        item.expected_bytes = expected_bytes
        item.observed_bytes = observed_bytes
        await _OneShot(item, "protocol_vip_os").start(self.env.protocol_vip_agent.sequencer)

    async def _bring_up(self) -> None:
        dut = cocotb.top
        self.logger.info("Bringing up SMC clocks and cold reset")
        dut.powergood_i.value = 0
        dut.rst_cold_ni.value = 0
        if hasattr(dut, "tb_i2c0_scl_ext_low"):
            dut.tb_i2c0_scl_ext_low.value = 0
        if hasattr(dut, "tb_i2c0_sda_ext_low"):
            dut.tb_i2c0_sda_ext_low.value = 0
        if hasattr(dut, "tb_i3c0_scl_ext_low"):
            dut.tb_i3c0_scl_ext_low.value = 0
        if hasattr(dut, "tb_i3c0_sda_ext_low"):
            dut.tb_i3c0_sda_ext_low.value = 0
        # DFT test_en defaults deasserted (functional mode).
        if hasattr(dut, "tb_test_en_i"):
            dut.tb_test_en_i.value = 0
        if hasattr(dut, "tb_cpu_jtag_tck"):
            dut.tb_cpu_jtag_tck.value = 0
            dut.tb_cpu_jtag_tms.value = 1
            dut.tb_cpu_jtag_tdi.value = 0
            dut.tb_cpu_jtag_reset.value = 1
        if hasattr(dut, "tb_sep_mailbox_interrupts"):
            dut.tb_sep_mailbox_interrupts.value = 0
        if hasattr(dut, "tb_gpio_ext_drive_en"):
            dut.tb_gpio_ext_drive_en.value = 0
            dut.tb_gpio_ext_drive_value.value = 0
        if hasattr(dut, "tb_boot_stall_jtag_ovrd_i"):
            dut.tb_boot_stall_jtag_ovrd_i.value = 0
            dut.tb_boot_stall_jtag_val_i.value = 0
        if hasattr(dut, "tb_sep_wdt_reset_n"):
            dut.tb_sep_wdt_reset_n.value = 1
        if hasattr(dut, "tb_ndmreset_request"):
            dut.tb_ndmreset_request.value = 0
        if hasattr(dut, "tb_cfg_flr_pf_active"):
            dut.tb_cfg_flr_pf_active.value = 0
        if hasattr(dut, "tb_temp_interrupt_i"):
            dut.tb_temp_interrupt_i.value = 0
        if hasattr(dut, "tb_ext_interrupt_0_i"):
            dut.tb_ext_interrupt_0_i.value = 0
        if hasattr(dut, "tb_captured_straps"):
            dut.tb_captured_straps.value = 0
        if hasattr(dut, "tb_ss_reset_complete"):
            dut.tb_ss_reset_complete.value = 0xFFFFFFFF
        if hasattr(dut, "tb_jtag_reset_ctrl"):
            dut.tb_jtag_reset_ctrl.value = 0
        if hasattr(dut, "tb_sep_axi_r_hold"):
            dut.tb_sep_axi_r_hold.value = 0
        if hasattr(dut, "tb_sys_axi_r_hold"):
            dut.tb_sys_axi_r_hold.value = 0
        if hasattr(dut, "tb_output_axi_resp_hold"):
            dut.tb_output_axi_resp_hold.value = 0
        if hasattr(dut, "tb_mem_repair_abort"):
            dut.tb_mem_repair_abort.value = 0
        if hasattr(dut, "tb_mbist_abort"):
            dut.tb_mbist_abort.value = 0
        if hasattr(dut, "tb_uart0_rx_ext_drive"):
            dut.tb_uart0_rx_ext_drive.value = 1  # UART idle-high
        # Product lc_state_i idle = complementary TEST_DEV ({~0, 0} = 0xF0).
        if hasattr(dut, "tb_lc_state"):
            dut.tb_lc_state.value = 0xF0
        # SPI octal pads (U2-1): idle-safe — enable off, CS deasserted, OE/IE
        # negated high (pads not driving). OcahSpiFlash adapter is U2-2.
        if hasattr(dut, "tb_spi_enable"):
            dut.tb_spi_enable.value = 0
            dut.tb_spi_clk.value = 0
            dut.tb_spi_txd.value = 0
            dut.tb_spi_cs_n.value = 1
            dut.tb_spi_cs_oe_n.value = 1
            dut.tb_spi_cs_ie_n.value = 1
            dut.tb_spi_clk_ie_n.value = 1
            dut.tb_spi_clk_oe_n.value = 1
            dut.tb_spi_dqs_ie_n.value = 1
            dut.tb_spi_dqs_oe_n.value = 1
            dut.tb_spi_dq_ie_n.value = 0xFF
            dut.tb_spi_dq_oe_n.value = 0xFF
            if hasattr(dut, "tb_spi_miso_ext"):
                dut.tb_spi_miso_ext.value = 0
        # Telemetry ATB receiver 0 (U4-6): idle quiet, AFREADY high.
        if hasattr(dut, "tb_telemetry0_atvalid"):
            dut.tb_telemetry0_atdata.value = 0
            dut.tb_telemetry0_atid.value = 0
            dut.tb_telemetry0_atvalid.value = 0
            dut.tb_telemetry0_afready.value = 1
        # AVSBus sdata (pad 51): idle-high (pull-up / no ACK).
        if hasattr(dut, "tb_avs_sdata_ext"):
            dut.tb_avs_sdata_ext.value = 1
        # OCTS dual-chiplet: default PRIMARY; secondary pad inject idle-low.
        if hasattr(dut, "tb_chiplet_is_primary"):
            dut.tb_chiplet_is_primary.value = 1
        if hasattr(dut, "tb_octs_sync_load_ext"):
            dut.tb_octs_sync_load_ext.value = 0
        if hasattr(dut, "tb_octs_cnt_credit_ext"):
            dut.tb_octs_cnt_credit_ext.value = 0
        # Output-fabric SLVERR inject (U1-2): off by default.
        if hasattr(dut, "tb_output_err_we"):
            dut.tb_output_err_we.value = 0
            dut.tb_output_err_resp.value = 0
            dut.tb_output_err_addr.value = 0
        # Cool reset starts deasserted (released) so the cool-domain logic
        # does not block the cold-reset bring-up. Tests can drive it low via
        # the reset agent COOL_RST_LO op.
        dut.rst_cool_ni.value = 1
        cocotb.start_soon(Clock(dut.clk_ref_i, self.cfg.ref_clk_period_ns, units="ns").start())
        cocotb.start_soon(Clock(dut.clk_smc_i, self.cfg.smc_clk_period_ns, units="ns").start())
        cocotb.start_soon(Clock(dut.clk_periph_i, self.cfg.periph_clk_period_ns, units="ns").start())

        await ClockCycles(dut.clk_ref_i, 10)
        self.logger.info("Asserting powergood")
        dut.powergood_i.value = 1
        await ClockCycles(dut.clk_ref_i, 10)
        self.logger.info("Releasing cold reset")
        dut.rst_cold_ni.value = 1
        await ClockCycles(dut.clk_ref_i, self.cfg.post_reset_settle_cycles)
        self.cfg.reset_done.set()

    async def run_scenario(self) -> None:
        raise NotImplementedError

    async def run_phase(self) -> None:
        self.raise_objection()
        await self._bring_up()
        await self.run_scenario()
        test_name = type(self).__name__
        # Prefer the per-test class attribute; fall back to the legacy name map.
        kind = self.protocol_vip_kind or _PROTOCOL_VIP_TESTS.get(test_name)
        if getattr(self, "auto_protocol_vip", True) and kind is not None:
            await self.record_protocol_vip(
                kind,
                test_name,
                details="OSS-safe protocol VIP evidence after scenario completion",
            )
        self.drop_objection()
