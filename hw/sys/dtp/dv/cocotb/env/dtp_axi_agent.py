# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP SMC fabric debug AXI UVM agent.

Wraps the unified OCAH AXI RAM BFM as the memory responder on the JTAG2AXI
bridge's AXI4 manager port (u_smc_axi_slave_if in tb_top), and exposes
backdoor access for the scoreboard / sequences. One passive shared monitor per
bridge port runs in every test and publishes each completed transaction on
``port_aps[<bridge>]`` for the JTAG2AXI reference models; a test that enables
the shared AXI scoreboard also gets its watchers and port histories.
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

# The monitor on each bridge port; its name is the `source` of every item it publishes.
PORT_MONITOR_NAMES: dict[str, str] = {
    "smc_axi": "dtp_smc_axi_monitor",
    "smc_otp": "dtp_smc_otp_monitor",
    "sep_otp": "dtp_sep_otp_monitor",
}


class DtpAxiAgent(uvm_agent):
    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.tb_if = ConfigDB().get(self, "", "tb_if")
        self.axi_ram: OcahAxiSlaveSequence | None = None
        self.smc_otp_axil_ram = None
        self.sep_otp_axil_ram = None
        self.port_aps = {
            target: uvm_analysis_port(f"{target}_ap", self) for target in PORT_MONITOR_NAMES
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
            id_width=2,
            addr_width=56,
            data_width=64,
            strb_width=8,
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
        monitors = {
            "smc_axi": OcahAxiMonitor(
                tb.axi_bus("smc_axi", passive=True),
                tb.clk,
                reset=tb.rst_n,
                reset_active_level=False,
                name=PORT_MONITOR_NAMES["smc_axi"],
            ),
            "smc_otp": OcahAxiLiteMonitor(
                tb.axi_bus("smc_otp", passive=True),
                tb.clk,
                reset=tb.rst_n,
                reset_active_level=False,
                name=PORT_MONITOR_NAMES["smc_otp"],
            ),
            "sep_otp": OcahAxiLiteMonitor(
                tb.axi_bus("sep_otp", passive=True),
                tb.clk,
                reset=tb.rst_n,
                reset_active_level=False,
                name=PORT_MONITOR_NAMES["sep_otp"],
            ),
        }
        for target, monitor in monitors.items():
            monitor.add_item_callback(self.port_aps[target].write)
        self.port_monitors = monitors
        if not getattr(self.cfg, "axi_scoreboard_enabled", False):
            for monitor in monitors.values():
                await monitor.start()
            return
        scoreboard = self.cfg.axi_scoreboard
        assert scoreboard is not None, "DtpAxiScoreboard did not publish a scoreboard"
        watchers = {
            "smc_axi": OcahAxiProtocolWatcher(
                tb.axi_bus("smc_axi", passive=True),
                tb.clk,
                reset=tb.rst_n,
                reset_active_level=False,
                name="dtp_smc_axi_watcher",
            ),
            "smc_otp": OcahAxiLiteProtocolWatcher(
                tb.axi_bus("smc_otp", passive=True),
                tb.clk,
                reset=tb.rst_n,
                reset_active_level=False,
                name="dtp_smc_otp_watcher",
            ),
            "sep_otp": OcahAxiLiteProtocolWatcher(
                tb.axi_bus("sep_otp", passive=True),
                tb.clk,
                reset=tb.rst_n,
                reset_active_level=False,
                name="dtp_sep_otp_watcher",
            ),
        }
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

    def backdoor_read64(self, addr: int) -> int:
        """Little-endian 64-bit backdoor read from the AXI memory."""
        return int.from_bytes(self.axi_ram.read(addr, 8), "little")
