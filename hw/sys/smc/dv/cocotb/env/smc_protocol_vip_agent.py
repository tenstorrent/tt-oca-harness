# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC protocol VIP agent.

The public OSS SMC top does not expose every protocol pad/responder. This agent
provides positive protocol-intent evidence for proxy/depth tests: sequences own
the real SEP_IN AXI accesses, while this agent emits a checked protocol
transaction record to the scoreboard.
"""

from __future__ import annotations

from pyuvm import (
    ConfigDB,
    uvm_agent,
    uvm_analysis_port,
    uvm_driver,
    uvm_sequencer,
)


class SmcProtocolVipDriver(uvm_driver):
    """Completes protocol VIP items and broadcasts them to the scoreboard."""

    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.ap = uvm_analysis_port("ap", self)

    async def run_phase(self) -> None:
        await self.cfg.reset_done.wait()
        self.logger.info("SMC protocol VIP driver ready")
        while True:
            item = await self.seq_item_port.get_next_item()
            self.logger.info("Completed SMC protocol VIP item: %s", item)
            self.ap.write(item)
            self.seq_item_port.item_done()


class SmcProtocolVipAgent(uvm_agent):
    """SMC OSS protocol VIP agent: sequencer + record driver + analysis port."""

    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.sequencer = uvm_sequencer("sequencer", self)
        self.driver = SmcProtocolVipDriver("driver", self)

    def connect_phase(self) -> None:
        self.driver.seq_item_port.connect(self.sequencer.seq_item_export)
        self.ap = self.driver.ap
