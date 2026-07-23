# SPDX-License-Identifier: Apache-2.0
"""SMC OSS GPIO-observer UVM agent.

Passive agent that samples the OR-of-vector GPIO observability outputs
exposed at tb_top: ``tb_gpio_core2pad_any``, ``tb_gpio_core2pad_en_any``,
``tb_gpio_pad2core_en_any``.

NOTE: these are OR-reductions over the *whole* pad bus, which also carries
idle-high LSIO pads (e.g. UART TX). With no GPIO CSR programming they therefore
read **1** (not 0) at idle on both Verilator and VCS -- the aggregate value is
not GPIO-diagnostic. The passive SAMPLE only proves the observables are
resolvable (no X); isolated per-pad GPIO drive behaviour is proven separately by
``smc_gpio_output_driveback_test`` (wrap-0 delta on the raw ``core2pad_*``
vectors).
"""

from __future__ import annotations

import cocotb
from pyuvm import (
    ConfigDB,
    uvm_agent,
    uvm_analysis_port,
    uvm_driver,
    uvm_sequencer,
)

from .smc_gpio_item import SmcGpioItem, SmcGpioOp


class SmcGpioDriver(uvm_driver):

    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.ap = uvm_analysis_port("ap", self)
        self.dut = None

    async def run_phase(self) -> None:
        self.dut = cocotb.top
        await self.cfg.reset_done.wait()
        self.logger.info("SMC GPIO observer driver ready")
        while True:
            item = await self.seq_item_port.get_next_item()
            if item.op is SmcGpioOp.SAMPLE:
                self._sample(item)
            else:
                raise ValueError(f"unsupported SmcGpioOp: {item.op}")
            self.ap.write(item)
            self.seq_item_port.item_done()

    def _sample(self, item: SmcGpioItem) -> None:
        dut = self.dut
        signals = {
            "core2pad_any": dut.tb_gpio_core2pad_any,
            "core2pad_en_any": dut.tb_gpio_core2pad_en_any,
            "pad2core_en_any": dut.tb_gpio_pad2core_en_any,
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


class SmcGpioAgent(uvm_agent):

    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.sequencer = uvm_sequencer("sequencer", self)
        self.driver = SmcGpioDriver("driver", self)

    def connect_phase(self) -> None:
        self.driver.seq_item_port.connect(self.sequencer.seq_item_export)
        self.ap = self.driver.ap
