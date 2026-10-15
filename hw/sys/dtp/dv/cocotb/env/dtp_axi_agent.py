# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG2AXI bridge-port agent.

One shared ``ocah_axi_vip`` responder per bridge port: an AXI4 RAM on the SMC
fabric port and an AXI-Lite RAM on each of the SMC OTP and SEP OTP ports,
published on the env cfg for the sequences' backdoor checks. One passive
shared monitor per bridge port runs in every test and publishes each
completed transaction on ``port_aps[<bridge>]`` for the JTAG2AXI reference
models; a test that enables the shared AXI scoreboard also gets its watchers
and port histories.
"""

from __future__ import annotations

from ocah_axi_vip import (
    OcahAxiLiteMonitor,
    OcahAxiLiteProtocolWatcher,
    OcahAxiLiteSlaveAgent,
    OcahAxiMonitor,
    OcahAxiProtocolWatcher,
    OcahAxiSlaveAgent,
    OcahAxiSlaveSequence,
)
from pyuvm import ConfigDB, uvm_agent, uvm_analysis_port

from .dtp_axi_port_history import DtpAxiPortHistory
from .dtp_types import (
    DTP_SMC_AXI_ADDR_WIDTH,
    DTP_SMC_AXI_DATA_WIDTH,
    DTP_SMC_AXI_ID_WIDTH,
    JTAG2AXI_TARGETS,
)

__all__ = ["DtpAxiAgent"]


class DtpAxiAgent(uvm_agent):
    """The bridge-port responders and monitors, one of each per JTAG2AXI bridge."""

    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.tb_if = ConfigDB().get(self, "", "tb_if")
        self.axi_ram: OcahAxiSlaveSequence | None = None
        self.smc_otp_axil_ram = None
        self.sep_otp_axil_ram = None
        self.port_aps = {
            target: uvm_analysis_port(f"{target}_ap", self) for target in JTAG2AXI_TARGETS
        }
        self.port_monitors: dict[str, OcahAxiMonitor | OcahAxiLiteMonitor] = {}

    async def run_phase(self) -> None:
        tb = self.tb_if
        self.axi_ram = OcahAxiSlaveAgent(
            tb.axi_bus("smc_axi"),
            tb.clk,
            tb.rst_n,
            reset_active_level=False,
            size=self.cfg.axi_mem_size,
            id_width=DTP_SMC_AXI_ID_WIDTH,
            addr_width=DTP_SMC_AXI_ADDR_WIDTH,
            data_width=DTP_SMC_AXI_DATA_WIDTH,
            strb_width=DTP_SMC_AXI_DATA_WIDTH // 8,
        ).sequence
        # The bridge carries response USER across its CDC and never reads it,
        # so any value is legal; seeded draws toggle every bit of that path.
        self.axi_ram.randomize_resp_user(self.cfg.resp_user_seed)
        # Publish for backdoor checks once the memory model exists.
        self.cfg.axi_ram = self.axi_ram
        self.smc_otp_axil_ram = OcahAxiLiteSlaveAgent(
            tb.axi_bus("smc_otp"),
            tb.clk,
            tb.rst_n,
            reset_active_level=False,
            size=self.cfg.otp_axil_mem_size,
        ).sequence
        self.sep_otp_axil_ram = OcahAxiLiteSlaveAgent(
            tb.axi_bus("sep_otp"),
            tb.clk,
            tb.rst_n,
            reset_active_level=False,
            size=self.cfg.otp_axil_mem_size,
        ).sequence
        self.cfg.smc_otp_axil_ram = self.smc_otp_axil_ram
        self.cfg.sep_otp_axil_ram = self.sep_otp_axil_ram
        self.cfg.jtag2axi_responders = {
            "smc_axi": self.cfg.axi_ram,
            "smc_otp": self.smc_otp_axil_ram,
            "sep_otp": self.sep_otp_axil_ram,
        }
        self.logger.info("OCAH AXI RAM responder ready (%d bytes)", self.cfg.axi_mem_size)
        self.logger.info(
            "OTP AXI-Lite RAM responders ready (%d bytes each)",
            self.cfg.otp_axil_mem_size,
        )
        await self.cfg.reset_done.wait()
        await self._start_port_monitors()

    async def _start_port_monitors(self) -> None:
        """Start the bridge-port monitors; attach the shared AXI scoreboard when enabled."""
        tb = self.tb_if
        monitors: dict[str, OcahAxiMonitor | OcahAxiLiteMonitor] = {}
        for target, cfg in JTAG2AXI_TARGETS.items():
            monitor_cls = OcahAxiLiteMonitor if cfg.bus_type else OcahAxiMonitor
            monitors[target] = monitor_cls(
                tb.axi_bus(target, passive=True),
                tb.clk,
                reset=tb.rst_n,
                reset_active_level=False,
                name=cfg.monitor_name,
            )
            monitors[target].add_item_callback(self.port_aps[target].write)
        self.port_monitors = monitors
        if not getattr(self.cfg, "axi_scoreboard_enabled", False):
            for monitor in monitors.values():
                await monitor.start()
            return
        scoreboard = self.cfg.axi_scoreboard
        assert scoreboard is not None, "DtpAxiScoreboard did not publish a scoreboard"
        watchers: dict[str, OcahAxiProtocolWatcher | OcahAxiLiteProtocolWatcher] = {}
        for target, cfg in JTAG2AXI_TARGETS.items():
            watcher_cls = OcahAxiLiteProtocolWatcher if cfg.bus_type else OcahAxiProtocolWatcher
            watchers[target] = watcher_cls(
                tb.axi_bus(target, passive=True),
                tb.clk,
                reset=tb.rst_n,
                reset_active_level=False,
                name=cfg.watcher_name,
            )
        histories = {target: DtpAxiPortHistory() for target in monitors}
        for target, monitor in monitors.items():
            scoreboard.attach_monitor(monitor, stream=target)
            monitor.add_item_callback(histories[target].observe)
            await monitor.start()
        for watcher in watchers.values():
            await watcher.start()
        self.cfg.axi_monitors = monitors
        self.cfg.axi_watchers = watchers
        self.cfg.axi_port_histories = histories
        self.logger.info("Shared AXI monitors/watchers attached to scoreboard")
