# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS I2C UVM agent.

Observation-style UVM agent: the driver consumes ``SmcI2cItem`` transactions
and samples the top-level I2C observability ports of ``smc_uvm_top``. Each
completed transaction is broadcast on an analysis port so the scoreboard can
verify the post-reset state.
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

from .smc_i2c_item import SmcI2cItem, SmcI2cOp


class SmcI2cDriver(uvm_driver):
    """Samples SMC OSS I2C observability ports on every transaction."""

    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.ap = uvm_analysis_port("ap", self)
        self.dut = None

    async def run_phase(self) -> None:
        self.dut = cocotb.top
        await self.cfg.reset_done.wait()
        self.logger.info("SMC I2C observation driver ready")
        while True:
            item = await self.seq_item_port.get_next_item()
            self._sample(item)
            self.ap.write(item)
            self.seq_item_port.item_done()

    def _sample(self, item: SmcI2cItem) -> None:
        if item.op is not SmcI2cOp.SAMPLE:
            raise ValueError(f"unsupported SmcI2cOp: {item.op}")
        cg_val = self.dut.tb_i2c_cg_en.value
        db_val = self.dut.tb_i2c_debug_lo.value
        item.resolvable = bool(cg_val.is_resolvable) and bool(db_val.is_resolvable)
        item.cg_en = int(cg_val) if cg_val.is_resolvable else -1
        item.debug_lo = int(db_val) if db_val.is_resolvable else -1
        self.logger.info("Sampled %s", item)


class SmcI2cAgent(uvm_agent):
    """SMC OSS I2C agent: sequencer + observation driver + analysis port.

    Note: the driver's ``ap`` is forwarded to the agent in ``connect_phase``,
    not ``build_phase``. Under pyuvm 4 the child driver's ``build_phase`` (which
    creates the ``ap``) runs only after the parent agent's ``build_phase``
    returns, so the assignment is moved one phase later.
    """

    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.sequencer = uvm_sequencer("sequencer", self)
        self.driver = SmcI2cDriver("driver", self)

    def connect_phase(self) -> None:
        self.driver.seq_item_port.connect(self.sequencer.seq_item_export)
        # Driver's ``ap`` exists now because the child build_phase has run.
        self.ap = self.driver.ap
