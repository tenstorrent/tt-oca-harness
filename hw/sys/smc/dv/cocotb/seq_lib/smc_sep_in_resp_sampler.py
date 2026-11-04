# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Passive sampler of the SEP_IN AR, AW, R and B handshakes.

The bench item carries one merged response code per transfer and reports the request
attributes it was given, so a leaf that grades a multi-beat burst per beat, or that
grades what the port carried, reads the port pins instead.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge


class SepInRespSampler:
    """R beats as ``(rresp, rdata, rlast)``, B as ``bresp``, AR and AW as their AxLOCK."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.r: list[tuple[int | None, int | None, int | None]] = []
        self.b: list[int | None] = []
        self.ar: list[int | None] = []
        self.aw: list[int | None] = []
        self.unresolved = 0
        self._task = cocotb.start_soon(self._run())

    def stop(self) -> None:
        self._task.cancel()

    @staticmethod
    def _int(sig) -> int | None:
        return int(sig.value) if sig.value.is_resolvable else None

    async def _run(self) -> None:
        dut = self.dut
        while True:
            await RisingEdge(dut.clk_smc_i)
            await ReadOnly()
            rv, rr = self._int(dut.s_axi_rvalid), self._int(dut.s_axi_rready)
            bv, br = self._int(dut.s_axi_bvalid), self._int(dut.s_axi_bready)
            arv, arr = self._int(dut.s_axi_arvalid), self._int(dut.s_axi_arready)
            awv, awr = self._int(dut.s_axi_awvalid), self._int(dut.s_axi_awready)
            if None in (rv, rr, bv, br, arv, arr, awv, awr):
                self.unresolved += 1
                continue
            if arv and arr:
                self.ar.append(self._int(dut.s_axi_arlock))
            if awv and awr:
                self.aw.append(self._int(dut.s_axi_awlock))
            if rv and rr:
                self.r.append(
                    (
                        self._int(dut.s_axi_rresp),
                        self._int(dut.s_axi_rdata),
                        self._int(dut.s_axi_rlast),
                    )
                )
            if bv and br:
                self.b.append(self._int(dut.s_axi_bresp))

    def take(self) -> tuple[list, list, list, list]:
        """Return and clear the ``(r, b, ar, aw)`` records sampled so far."""
        taken = (self.r, self.b, self.ar, self.aw)
        self.r, self.b, self.ar, self.aw = [], [], [], []
        return taken
