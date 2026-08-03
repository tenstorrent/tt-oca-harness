# SPDX-License-Identifier: Apache-2.0
"""Shared AXI helpers for SMU external SMN port and outbound observe."""

from __future__ import annotations

from dataclasses import dataclass, field

import cocotb
from cocotb.triggers import RisingEdge, Timer, with_timeout
from cocotbext.axi import AxiBus, AxiMaster, AxiResp

# Bounded completion wait for SMN ingress (must fail the testcase on expiry).
AXI_TIMEOUT_NS = 200_000
AXI_BOUND_LABEL = "bound=200us"


async def make_smu_axi_master(dut, clk, reset) -> AxiMaster:
    bus = AxiBus.from_prefix(dut, "s_axi")
    master = AxiMaster(bus, clk, reset, reset_active_level=False)
    await Timer(1, unit="ns")
    return master


async def axi_read32(master: AxiMaster, addr: int) -> int:
    data = await master.read(addr, 4)
    return int.from_bytes(bytes(data.data), byteorder="little")


async def axi_read32_resp(
    master: AxiMaster,
    addr: int,
    *,
    arid: int | None = None,
) -> tuple[int, object]:
    """Return (rdata32, AxiResp) so callers can assert DECERR vs OKAY."""
    beat = await master.read(addr, 4, arid=arid)
    value = int.from_bytes(bytes(beat.data), byteorder="little")
    return value, beat.resp


async def axi_read32_resp_ids(
    master: AxiMaster,
    addr: int,
    *,
    arid: int | None = None,
) -> tuple[int, object, int, int]:
    """Return (rdata32, AxiResp, arid_issued, rid_returned)."""
    issued = 0 if arid is None else int(arid)
    beat = await master.read(addr, 4, arid=arid)
    value = int.from_bytes(bytes(beat.data), byteorder="little")
    rid = int(beat.id) if hasattr(beat, "id") else issued
    return value, beat.resp, issued, rid


async def axi_read32_resp_ids_bounded(
    master: AxiMaster,
    addr: int,
    *,
    arid: int | None = None,
    label: str = "axi_read",
    timeout_ns: int = AXI_TIMEOUT_NS,
) -> tuple[int, object, int, int]:
    """Like axi_read32_resp_ids but fail-closed on hang with last-state diagnostics."""
    try:
        return await with_timeout(
            axi_read32_resp_ids(master, addr, arid=arid),
            timeout_time=timeout_ns,
            timeout_unit="ns",
        )
    except Exception:
        raise AssertionError(
            f"TIMEOUT {label}: {AXI_BOUND_LABEL} last_state=no_rresp addr=0x{addr:08x}"
        ) from None


async def axi_write32(master: AxiMaster, addr: int, value: int) -> None:
    await master.write(addr, value.to_bytes(4, byteorder="little"))


async def axi_write32_resp(
    master: AxiMaster,
    addr: int,
    value: int,
    *,
    awid: int | None = None,
) -> object:
    """Return AxiResp from a 32-bit write."""
    beat = await master.write(addr, value.to_bytes(4, byteorder="little"), awid=awid)
    return beat.resp


async def axi_write32_resp_ids(
    master: AxiMaster,
    addr: int,
    value: int,
    *,
    awid: int | None = None,
) -> tuple[object, int, int]:
    """Return (AxiResp, awid_issued, bid_returned)."""
    issued = 0 if awid is None else int(awid)
    beat = await master.write(addr, value.to_bytes(4, byteorder="little"), awid=awid)
    bid = int(beat.id) if hasattr(beat, "id") else issued
    return beat.resp, issued, bid


async def wait_signal_high(signal, clk, timeout_cycles: int = 5000, name: str = "sig") -> None:
    for _ in range(timeout_cycles):
        await RisingEdge(clk)
        try:
            if int(signal.value) == 1:
                return
        except ValueError:
            pass
    raise AssertionError(f"timeout waiting for {name}==1")


def _sample(signal, name: str) -> int:
    val = signal.value
    if not val.is_resolvable:
        raise AssertionError(f"X/Z sample on {name}: {val}")
    return int(val)


@dataclass
class OutboundAxiRecord:
    """Captured smu_axi_out handshake summary."""

    aw_fires: int = 0
    ar_fires: int = 0
    b_fires: int = 0
    r_fires: int = 0
    last_aw_addr: int | None = None
    last_ar_addr: int | None = None
    last_bresp: int | None = None
    last_rresp: int | None = None
    last_bid: int | None = None
    last_rid: int | None = None
    _timeout_paths: list[str] = field(default_factory=list)


class SmuOutboundMonitor:
    """Passive observe via top-level TB counters (Verilator-safe)."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.record = OutboundAxiRecord()

    def snapshot(self) -> None:
        self.record.aw_fires = int(self.dut.smu_axi_out_awvalid_count.value)

    def start(self):
        self.snapshot()
        return None

    def stop(self) -> None:
        self.snapshot()


async def wait_outbound_aw_count(
    dut,
    *,
    baseline: int,
    min_delta: int,
    clk,
    bound: int,
    label: str,
) -> int:
    """Bounded poll of top-level smu_axi_out_awvalid_count."""
    last = baseline
    for _ in range(bound):
        await RisingEdge(clk)
        last = _sample(dut.smu_axi_out_awvalid_count, "smu_axi_out_awvalid_count")
        if last >= baseline + min_delta:
            return last
    raise AssertionError(
        f"TIMEOUT {label}: bound={bound} last_count={last} "
        f"baseline={baseline} need_delta>={min_delta}"
    )


def resp_name(resp) -> str:
    if resp == AxiResp.OKAY:
        return "OKAY"
    if resp == AxiResp.DECERR:
        return "DECERR"
    if resp == AxiResp.SLVERR:
        return "SLVERR"
    if resp == AxiResp.EXOKAY:
        return "EXOKAY"
    return str(resp)
