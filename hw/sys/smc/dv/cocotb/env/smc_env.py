# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM environment.

Agent / monitor honesty (U6-1):
  * SAMPLE-only agents: i2c / reset / clk / irq / gpio / axil — observability
    sampling, not protocol BFMs.
  * Protocol / traffic agents: sep_in_axi (alias: sys_axi) / sys_in_axi /
    jtag_axi / protocol_vip.
  * Passive monitors: axi_monitor (SEP_IN), output_axi_monitor (SYS_OUT, U6-2),
    cpu_trace_mon (hart-0 retirement trace; idle without a firmware image).
"""

from __future__ import annotations

from pyuvm import ConfigDB, uvm_env

from .smc_axi_monitor import SmcAxiMonitor
from .smc_axil_agent import SmcAxilAgent
from .smc_clk_agent import SmcClkAgent
from .smc_cpu_trace_monitor import SmcCpuTraceMonitor
from .smc_gpio_agent import SmcGpioAgent
from .smc_i2c_agent import SmcI2cAgent
from .smc_irq_agent import SmcIrqAgent
from .smc_output_axi_monitor import SmcOutputAxiMonitor
from .smc_protocol_vip_agent import SmcProtocolVipAgent
from .smc_reset_agent import SmcResetAgent
from .smc_scoreboard import SmcScoreboard
from .smc_sys_axi_agent import SmcJtagAxiAgent, SmcSysAxiAgent, SmcSysInAxiAgent


class SmcEnv(uvm_env):
    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        # --- SAMPLE-only agents ---
        self.i2c_agent = SmcI2cAgent("i2c_agent", self)
        self.reset_agent = SmcResetAgent("reset_agent", self)
        self.clk_agent = SmcClkAgent("clk_agent", self)
        self.irq_agent = SmcIrqAgent("irq_agent", self)
        self.gpio_agent = SmcGpioAgent("gpio_agent", self)
        self.axil_agent = SmcAxilAgent("axil_agent", self)
        # --- Protocol / traffic agents ---
        # Port identity ([ADDRESS-FROM-AUTHORITATIVE-MAP]):
        #
        #   sep_in_axi_agent (SmcSysAxiAgent,   bus_prefix "s_axi")
        #       -> tb_top s_axi_* bridge -> smc.sep_axi_in_req_i   ["SEP_IN AXI"]
        #   sys_in_axi_agent (SmcSysInAxiAgent, bus_prefix "sys_axi")
        #       -> smc.sys_axi_in_req_i                            ["SYS_IN AXI"]
        #
        # `sys_axi_agent` is an alias of `sep_in_axi_agent` (the same object), so
        # `bus_name` in every kept log line is the authority on which port was
        # driven.
        self.sep_in_axi_agent = SmcSysAxiAgent("sep_in_axi_agent", self)
        self.sys_axi_agent = self.sep_in_axi_agent
        self.sys_in_axi_agent = SmcSysInAxiAgent("sys_in_axi_agent", self)
        self.jtag_axi_agent = SmcJtagAxiAgent("jtag_axi_agent", self)
        self.protocol_vip_agent = SmcProtocolVipAgent("protocol_vip_agent", self)
        # --- Bus monitors ---
        self.axi_monitor = SmcAxiMonitor("axi_monitor", self)
        self.output_axi_monitor = SmcOutputAxiMonitor("output_axi_monitor", self)
        self.cpu_trace_mon = SmcCpuTraceMonitor("cpu_trace_mon", self)
        self.scoreboard = SmcScoreboard("scoreboard", self)

    def connect_phase(self) -> None:
        self.i2c_agent.ap.connect(self.scoreboard.analysis_export)
        self.reset_agent.ap.connect(self.scoreboard.analysis_export)
        self.clk_agent.ap.connect(self.scoreboard.analysis_export)
        self.irq_agent.ap.connect(self.scoreboard.analysis_export)
        self.gpio_agent.ap.connect(self.scoreboard.analysis_export)
        self.axil_agent.ap.connect(self.scoreboard.analysis_export)
        self.sep_in_axi_agent.ap.connect(self.scoreboard.analysis_export)
        self.sys_in_axi_agent.ap.connect(self.scoreboard.analysis_export)
        self.jtag_axi_agent.ap.connect(self.scoreboard.analysis_export)
        self.protocol_vip_agent.ap.connect(self.scoreboard.analysis_export)
