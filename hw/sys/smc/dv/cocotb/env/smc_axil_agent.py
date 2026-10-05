# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS AXI-Lite observer UVM agent (per-interface)."""

from __future__ import annotations

import cocotb
from pyuvm import (
    ConfigDB,
    uvm_agent,
    uvm_analysis_port,
    uvm_driver,
    uvm_sequencer,
)

from .smc_axil_item import SmcAxilItem, SmcAxilOp


class SmcAxilDriver(uvm_driver):
    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.ap = uvm_analysis_port("ap", self)
        self.dut = None

    async def run_phase(self) -> None:
        self.dut = cocotb.top
        await self.cfg.reset_done.wait()
        self.logger.info("SMC AXI-Lite observer driver ready")
        while True:
            item = await self.seq_item_port.get_next_item()
            if item.op is SmcAxilOp.SAMPLE:
                self._sample(item)
            else:
                raise ValueError(f"unsupported SmcAxilOp: {item.op}")
            self.ap.write(item)
            self.seq_item_port.item_done()

    def _sample(self, item: SmcAxilItem) -> None:
        dut = self.dut
        signals = {
            "dtp_csr_active": dut.tb_axil_dtp_csr_active,
            "external_active": dut.tb_axil_external_active,
            "efuse_bank_active": dut.tb_axil_efuse_bank_active,
            "any_master_active": dut.tb_axil_any_master_active,
        }
        all_resolvable = True
        for attr, sig in signals.items():
            v = sig.value
            if v.is_resolvable:
                setattr(item, attr, int(v))
            else:
                all_resolvable = False
                setattr(item, attr, -1)
        item.resolvable = all_resolvable
        self.logger.info("Sampled %s", item)


class SmcAxilAgent(uvm_agent):
    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.sequencer = uvm_sequencer("sequencer", self)
        self.driver = SmcAxilDriver("driver", self)

    def connect_phase(self) -> None:
        self.driver.seq_item_port.connect(self.sequencer.seq_item_export)
        self.ap = self.driver.ap
