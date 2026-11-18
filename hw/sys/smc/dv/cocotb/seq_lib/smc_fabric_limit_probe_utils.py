# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Outstanding-transaction counters at the handshake points of the fabric limits.

Spec source: fabric.adoc SMC Fabric Transaction Limits. Each limit of that table bounds
the transactions a counter sees between the request handshake that pushes it and the
response handshake that pops it. `OutstandingProbe` counts both handshakes at one such
point of the bench, so the outstanding count it reports is the count the limiter itself
sees, whatever the pipeline registers between that point and the SEP_IN port hold.

The sequences hold the SEP_IN manager's RREADY (or W) low, so nothing retires at the port
and every limiter on the path fills until its own bound withholds the next request. The
probe records the peak, the cycles the next request stayed presented and withheld at that
peak, and the first handshakes after the release, which show the withheld request being
accepted only after a response retired an earlier one.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot

AXI_RESP_DECERR = 3


def r_sink_channel(agent):
    """The R-channel sink of a bench AXI master agent, whose `pause` holds RREADY low."""
    return agent.driver.axi.driver.channels["r_ready_delay"]


def hold_rready(agent) -> None:
    chan = r_sink_channel(agent)
    chan.clear_pause_generator()
    chan.pause = True


def release_rready(agent) -> None:
    r_sink_channel(agent).pause = False


def read_item(
    label: str,
    addr: int,
    want: int | None,
    length: int = 4,
    axi_id: int | None = None,
    decerr: bool = False,
) -> SmcSysAxiItem:
    item = SmcSysAxiItem(f"rd_{label}")
    item.op = SmcSysAxiOp.READ
    item.addr = addr
    item.length = length
    item.axi_id = axi_id
    if decerr:
        item.allow_error = True
        item.expect_error = True
        item.expected_resp = AXI_RESP_DECERR
    else:
        item.expected = want
    return item


def verify_items(name: str, items: list[SmcSysAxiItem]) -> None:
    for item in items:
        where = f"{name} {item.get_name()} @ 0x{item.addr:08x}"
        if item.expect_error:
            assert item.resp_code == AXI_RESP_DECERR, f"{where}: resp {item.resp_code}, want DECERR"
            continue
        assert item.resp_code == 0, f"{where}: resp {item.resp_code}, want OKAY"
        if item.op == SmcSysAxiOp.READ:
            mask = (1 << (8 * item.length)) - 1
            assert item.rdata & mask == item.expected, (
                f"{where}: read 0x{item.rdata & mask:X}, want 0x{item.expected:X}"
            )


def start_group(name: str, items: list[SmcSysAxiItem], sequencer, timing=None):
    """Start every member of `items` on `sequencer` at once; returns the task to await."""
    group = SmcSysAxiGroupItem(name, items, timing=timing)
    return cocotb.start_soon(_OneShot(group, f"{name}_os").start(sequencer))


class OutstandingProbe:
    """Count transactions outstanding at one request / response handshake point of the bench.

    Sampled every `clk_smc_i` rise. `prefix` names the bench nets: the request VALID and
    READY are `<prefix>_<req[0]>` and `<prefix>_<req[1]>`, a request is counted on their
    handshake, or on `<prefix>_<req_hs>` when that net is given; a response retires one
    request when every `<prefix>_<n>` of `rsp` is 1 (`rvalid`, `rready` and `rlast` for an AXI
    read, no `rlast` for AXI-Lite, one FIFO pop net for a queue). `<prefix>_arid` is recorded
    on every request when `with_id`. `witness` names the limiter's own full flag; it is
    sampled on every withheld cycle and never decides anything by itself.
    """

    def __init__(
        self,
        dut,
        prefix: str,
        *,
        req: tuple[str, str] = ("arvalid", "arready"),
        req_hs: str | None = None,
        rsp: tuple[str, ...] = ("rvalid", "rready", "rlast"),
        with_id: bool = False,
        witness: str | None = None,
    ) -> None:
        self.dut = dut
        self.prefix = prefix
        self.req = req
        self.req_hs = req_hs
        self.rsp = rsp
        self.with_id = with_id
        self.witness = witness
        self.stop = False
        self.cycle = 0
        self.ar_hs = 0
        self.r_hs = 0
        self.peak = 0
        self.withheld = 0
        self.streak = 0
        self.witness_hits = 0
        self.ar_ids: list[int] = []
        self.ar_hs_cycles: list[int] = []
        self.r_hs_cycles: list[int] = []

    @property
    def outstanding(self) -> int:
        return self.ar_hs - self.r_hs

    def _bit(self, name: str) -> int:
        value = getattr(self.dut, name).value
        assert value.is_resolvable, f"{name} is X/Z while the probe samples it"
        return int(value)

    def reset_counts(self) -> None:
        self.ar_hs = self.r_hs = self.peak = self.withheld = self.streak = 0
        self.witness_hits = 0
        self.ar_ids.clear()
        self.ar_hs_cycles.clear()
        self.r_hs_cycles.clear()

    def first_hs_after(self, cycle: int) -> tuple[int | None, int | None]:
        """Cycle of the first request and the first retiring response after `cycle`."""
        ar = next((c for c in self.ar_hs_cycles if c > cycle), None)
        r = next((c for c in self.r_hs_cycles if c > cycle), None)
        return ar, r

    def summary(self) -> str:
        return (
            f"{self.prefix}: req_hs={self.ar_hs} rsp_hs={self.r_hs} peak_outstanding="
            f"{self.peak} withheld_cycles={self.withheld} witness_hits={self.witness_hits}"
        )

    async def run(self) -> None:
        while not self.stop:
            await RisingEdge(self.dut.clk_smc_i)
            await ReadOnly()
            self.cycle += 1
            valid = self._bit(f"{self.prefix}_{self.req[0]}")
            ready = self._bit(f"{self.prefix}_{self.req[1]}")
            req_hs = self._bit(f"{self.prefix}_{self.req_hs}") if self.req_hs else valid and ready
            if all(self._bit(f"{self.prefix}_{n}") for n in self.rsp):
                self.r_hs += 1
                self.r_hs_cycles.append(self.cycle)
            if req_hs:
                self.ar_hs += 1
                self.ar_hs_cycles.append(self.cycle)
                if self.with_id:
                    self.ar_ids.append(self._bit(f"{self.prefix}_arid"))
                self.streak = 0
            elif valid and self.outstanding > 0 and self.outstanding == self.peak:
                self.withheld += 1
                self.streak += 1
                if self.witness is not None and self._bit(self.witness):
                    self.witness_hits += 1
            else:
                self.streak = 0
            self.peak = max(self.peak, self.outstanding)


async def wait_withheld(probe: OutstandingProbe, streak: int, bound_cycles: int) -> int:
    """Return the cycle at which `probe` has withheld a request for `streak` consecutive cycles.

    Raises when `bound_cycles` rises pass first: the limit under test never withheld anything
    for that long, which is a finding of its own, not something to wait longer for.
    """
    clk = probe.dut.clk_smc_i
    for _ in range(bound_cycles):
        await RisingEdge(clk)
        await ReadOnly()
        if probe.streak >= streak:
            return probe.cycle
    raise AssertionError(
        f"{probe.prefix}: no request withheld for {streak} consecutive cycles within "
        f"{bound_cycles} rises; {probe.summary()}"
    )


class HeldRun:
    """What one held group measured at its limiter's probe and at the SEP_IN port."""

    def __init__(self, probe: OutstandingProbe, port: OutstandingProbe, release_cycle: int):
        self.peak = probe.peak
        self.withheld = probe.withheld
        self.streak = probe.streak
        self.witness_hits = probe.witness_hits
        self.ar_hs = probe.ar_hs
        self.ids = sorted(set(probe.ar_ids))
        self.port_ar_hs = port.ar_hs
        self.port_peak = port.peak
        self.release_cycle = release_cycle
        self.ar_after: int | None = None
        self.r_after: int | None = None
        self.final_ar_hs = 0
        self.final_r_hs = 0
        self.port_final_ar_hs = 0

    def close(self, probe: OutstandingProbe, port: OutstandingProbe) -> None:
        self.ar_after, self.r_after = probe.first_hs_after(self.release_cycle)
        self.final_ar_hs = probe.ar_hs
        self.final_r_hs = probe.r_hs
        self.port_final_ar_hs = port.ar_hs

    def retire_first(self) -> bool:
        """True when the first request accepted after the release followed a retiring response."""
        return (
            self.r_after is not None and self.ar_after is not None and self.r_after < self.ar_after
        )

    def text(self) -> str:
        return (
            f"peak_outstanding={self.peak} withheld_cycles={self.withheld} (streak "
            f"{self.streak}, witness_full_hits={self.witness_hits}) req_hs_at_hold={self.ar_hs} "
            f"port_ar_hs_at_hold={self.port_ar_hs} after_release: first_rsp_cycle="
            f"{self.r_after} first_req_cycle={self.ar_after} final req_hs={self.final_ar_hs} "
            f"rsp_hs={self.final_r_hs} port_ar_hs={self.port_final_ar_hs}"
        )
