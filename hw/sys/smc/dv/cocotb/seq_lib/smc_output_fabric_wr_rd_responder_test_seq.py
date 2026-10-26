# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Response USER observation for smc_output_fabric_wr_rd_responder_test.

The SYS_OUT responder draws BUSER/RUSER from a fixed seed; a passive sampler
records every accepted B and R beat at the responder (``u_output_axi_if``) and
at the JTAG-AXI manager port (``jtag_axi_*``) so each JTAG response can be
paired with the beat the responder drove for it.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from cocotb.utils import get_sim_time

# Fixed responder USER seed; part of the test, not a regression knob.
RESP_USER_SEED = 0xB4A5
# SYS_OUT and JTAG-AXI USER width on every AXI4 channel (fabric.adoc, USER_WIDTH 12).
USER_WIDTH = 12
USER_MASK = (1 << USER_WIDTH) - 1
# Bound, in clk_smc_i cycles, for the sampler to have recorded the JTAG response
# beat once the JTAG-AXI driver has returned the completed access.
SAMPLER_CATCH_UP_CYCLES = 16


@dataclass(frozen=True)
class UserBeat:
    """One accepted B or R beat; ``user``/``data`` are None when X/Z."""

    chan: str
    resp: int | None
    user: int | None
    data: int | None
    time_ps: int


def _value(sig) -> int | None:
    value = sig.value
    return int(value) if value.is_resolvable else None


class SmcRspUserSampler:
    """Record accepted B/R beats at the SYS_OUT responder and at the JTAG-AXI port."""

    def __init__(self) -> None:
        self.stop = False
        self.responder: list[UserBeat] = []
        self.jtag: list[UserBeat] = []

    @staticmethod
    def _beat(chan: str, valid, ready, resp, user, data) -> UserBeat | None:
        v, r = _value(valid), _value(ready)
        assert v is not None and r is not None, f"{valid._name}/{ready._name} are X/Z"
        if not (v and r):
            return None
        return UserBeat(
            chan,
            _value(resp),
            _value(user),
            None if data is None else _value(data),
            int(get_sim_time("ps")),
        )

    async def run(self) -> None:
        top = cocotb.top
        ifc = top.u_output_axi_if
        while not self.stop:
            await RisingEdge(top.clk_smc_i)
            await ReadOnly()
            beats = (
                (self.responder, "b", ifc.bvalid, ifc.bready, ifc.bresp, ifc.buser, None),
                (self.responder, "r", ifc.rvalid, ifc.rready, ifc.rresp, ifc.ruser, ifc.rdata),
                (
                    self.jtag,
                    "b",
                    top.jtag_axi_bvalid,
                    top.jtag_axi_bready,
                    top.jtag_axi_bresp,
                    top.jtag_axi_buser,
                    None,
                ),
                (
                    self.jtag,
                    "r",
                    top.jtag_axi_rvalid,
                    top.jtag_axi_rready,
                    top.jtag_axi_rresp,
                    top.jtag_axi_ruser,
                    top.jtag_axi_rdata,
                ),
            )
            for log, chan, valid, ready, resp, user, data in beats:
                beat = self._beat(chan, valid, ready, resp, user, data)
                if beat is not None:
                    log.append(beat)

    def mark(self) -> tuple[int, int]:
        return len(self.responder), len(self.jtag)

    async def wait_jtag_beat(self, mark: tuple[int, int], chan: str, label: str) -> UserBeat:
        """Bounded wait for exactly one JTAG ``chan`` beat after ``mark``."""
        seen: list[UserBeat] = []
        for _ in range(SAMPLER_CATCH_UP_CYCLES):
            seen = [b for b in self.jtag[mark[1] :] if b.chan == chan]
            if seen:
                break
            await RisingEdge(cocotb.top.clk_smc_i)
        assert len(seen) == 1, (
            f"{label}: expected exactly one JTAG {chan.upper()} beat within "
            f"{SAMPLER_CATCH_UP_CYCLES} clk_smc_i cycles of the access completing, "
            f"saw {len(seen)}: {seen}"
        )
        return seen[0]

    def responder_beats(self, mark: tuple[int, int], chan: str, until_ps: int) -> list[UserBeat]:
        return [b for b in self.responder[mark[0] :] if b.chan == chan and b.time_ps <= until_ps]
