# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM combined-observability test.

Sample the reset observables and the I2C observables back-to-back in the
same scenario. Demonstrates multi-agent dispatch within one test: the test
supplies tiny helper coroutines to the sequence that drive each item onto
the matching agent's sequencer via per-item one-shot sub-sequences.

This is a workaround for pyuvm: a single ``uvm_sequence`` can only ``start``
on one sequencer, so we use the per-item start/finish via ad-hoc sequences
for each agent.
"""

from __future__ import annotations

import pyuvm
from pyuvm import uvm_sequence
from seq_lib.smc_combined_observability_test_seq import (
    smc_combined_observability_test_seq,
)
from smc_base_test import smc_base_test


class _OneShotSeq(uvm_sequence):
    """Wrap a single item dispatch as a sequence so it can hop sequencers."""

    def __init__(self, item, name: str = "one_shot") -> None:
        super().__init__(name)
        self._item = item

    async def body(self) -> None:
        await self.start_item(self._item)
        await self.finish_item(self._item)


@pyuvm.test()
class smc_combined_observability_test(smc_base_test):
    async def run_scenario(self) -> None:
        seq = smc_combined_observability_test_seq("combined_obs_seq")

        async def dispatch_reset(item) -> None:
            inner = _OneShotSeq(item, "reset_oneshot")
            await inner.start(self.env.reset_agent.sequencer)

        async def dispatch_i2c(item) -> None:
            inner = _OneShotSeq(item, "i2c_oneshot")
            await inner.start(self.env.i2c_agent.sequencer)

        seq.dispatch_reset = dispatch_reset
        seq.dispatch_i2c = dispatch_i2c
        seq.cfg = self.env.cfg

        # Start the outer sequence on whichever sequencer; it just uses the
        # supplied dispatchers and never calls start_item itself.
        await seq.start(self.env.reset_agent.sequencer)
