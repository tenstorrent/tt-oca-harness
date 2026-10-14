# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS GPIO-observer UVM agent.

Passive agent that samples the OR-of-vector GPIO observability outputs
exposed at tb_top: ``tb_gpio_core2pad_any``, ``tb_gpio_core2pad_en_any``,
``tb_gpio_pad2core_en_any``.

NOTE: these are OR-reductions over the *whole* pad bus, which also carries
idle-high LSIO pads (e.g. UART TX). With no GPIO CSR programming they therefore
read **1** (not 0) at idle on both Verilator and VCS -- the aggregate value is
not GPIO-diagnostic, and no frontdoor stimulus can drive any of them to 0. All
three are consequently listed in ``env.smc_probe_liveness.UNBACKABLE_PROBES``:
a net tied to constant 1 reads exactly like the real aggregate, so their value is
an OBSERVED-ONLY diagnostic and never checked evidence.

The same SAMPLE therefore also captures the **raw pad-output bus vectors**
mirrored at tb_top (``tb_core2pad_o`` / ``tb_core2pad_en_o``).
Those move under real frontdoor GPIO CSR programming, which is what makes a
stated expectation on them backable, and they are what
``smc_gpio_output_driveback_test`` and
``seq_lib.smc_probe_positive_control.prove_gpio_pad_bus_probe`` use to isolate a
single GPIO wrap by delta.
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

    @staticmethod
    def _vec_int(sig) -> int:
        """Read a wide pad-bus vector, resolving X/Z bits to 0 (positions kept).

        Mirrors ``smc_gpio_output_driveback_test_seq._resolve_int``: VCS leaves
        undriven upper pad bits at X (X-init pessimism) while Verilator
        zero-inits them. Every consumer of these vectors isolates GPIO wrap 0 by
        a single-bit delta, so an undriven X bit reading 0 is harmless, and a
        *driven* bit that is X also reads 0 -- which makes the delta and exact
        compares fail loudly instead of passing.
        """
        v = sig.value
        try:
            return int(v)
        except Exception:  # noqa: BLE001 - X/Z present (VCS undriven pads)
            s = getattr(v, "binstr", None) or str(v)
            bits = "".join(c if c in "01" else "0" for c in s if c not in " _")
            return int(bits, 2) if bits else 0

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
        # Raw pad-output bus vectors, sampled in the same delta cycle as the
        # aggregates so a scoreboard cross-check between them is coherent.
        if hasattr(dut, "tb_core2pad_o") and hasattr(dut, "tb_core2pad_en_o"):
            item.core2pad_vec = self._vec_int(dut.tb_core2pad_o)
            item.core2pad_en_vec = self._vec_int(dut.tb_core2pad_en_o)
            item.vec_width = len(dut.tb_core2pad_en_o.value)
        self.logger.info("Sampled %s", item)


class SmcGpioAgent(uvm_agent):
    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.sequencer = uvm_sequencer("sequencer", self)
        self.driver = SmcGpioDriver("driver", self)

    def connect_phase(self) -> None:
        self.driver.seq_item_port.connect(self.sequencer.seq_item_export)
        self.ap = self.driver.ap
