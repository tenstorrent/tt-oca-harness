# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
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
    """Return (rdata32, AxiResp, arid_issued, rid_returned).

    RID comes from the live R-channel id on the completing beat. Never fall back
    to the issued ARID — that made RID==ARID compares tautological under
    cocotbext.axi AxiReadResp (no id field).
    """
    issued = 0 if arid is None else int(arid)
    read_if = master.read_if
    bus_r = read_if.bus.r
    clock = read_if.clock
    captured: dict[str, int | None] = {"rid": None}

    async def _watch_rid() -> None:
        while True:
            await RisingEdge(clock)
            try:
                if int(bus_r.rvalid.value) == 0 or int(bus_r.rready.value) == 0:
                    continue
            except ValueError:
                continue
            rid_val = bus_r.rid.value
            if not rid_val.is_resolvable:
                raise AssertionError(f"X/Z on rid during beat: {rid_val}")
            captured["rid"] = int(rid_val)
            try:
                if int(bus_r.rlast.value) == 1:
                    return
            except ValueError:
                return

    watcher = cocotb.start_soon(_watch_rid())
    try:
        beat = await master.read(addr, 4, arid=arid)
    except Exception:
        if not watcher.done():
            watcher.kill()
        raise

    if not watcher.done():
        for _ in range(8):
            if watcher.done():
                break
            await RisingEdge(clock)
        if not watcher.done():
            watcher.kill()

    if captured["rid"] is None:
        raise AssertionError(
            f"RID capture miss after read addr=0x{addr:08x} arid=0x{issued:x}"
        )
    value = int.from_bytes(bytes(beat.data), byteorder="little")
    return value, beat.resp, issued, int(captured["rid"])


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
    except AssertionError:
        raise
    except Exception:
        raise AssertionError(
            f"TIMEOUT {label}: {AXI_BOUND_LABEL} last_state=no_rresp addr=0x{addr:08x}"
        ) from None


async def axi_read32_resp_bounded(
    master: AxiMaster,
    addr: int,
    *,
    label: str = "axi_read",
    timeout_ns: int = AXI_TIMEOUT_NS,
) -> tuple[int, object]:
    """Like axi_read32_resp but fail-closed on hang."""
    try:
        return await with_timeout(
            axi_read32_resp(master, addr),
            timeout_time=timeout_ns,
            timeout_unit="ns",
        )
    except AssertionError:
        raise
    except Exception:
        raise AssertionError(
            f"TIMEOUT {label}: {AXI_BOUND_LABEL} last_state=no_rresp "
            f"addr=0x{addr:08x}"
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


async def axi_write32_resp_bounded(
    master: AxiMaster,
    addr: int,
    value: int,
    *,
    label: str = "axi_write",
    timeout_ns: int = AXI_TIMEOUT_NS,
) -> object:
    """Like axi_write32_resp but fail-closed on hang."""
    try:
        return await with_timeout(
            axi_write32_resp(master, addr, value),
            timeout_time=timeout_ns,
            timeout_unit="ns",
        )
    except AssertionError:
        raise
    except Exception:
        raise AssertionError(
            f"TIMEOUT {label}: {AXI_BOUND_LABEL} last_state=no_bresp "
            f"addr=0x{addr:08x}"
        ) from None


async def axi_write32_resp_ids(
    master: AxiMaster,
    addr: int,
    value: int,
    *,
    awid: int | None = None,
) -> tuple[object, int, int]:
    """Return (AxiResp, awid_issued, bid_returned).

    BID is sampled from the live B-channel id — never fall back to issued AWID.
    """
    issued = 0 if awid is None else int(awid)
    write_if = master.write_if
    bus_b = write_if.bus.b
    clock = write_if.clock
    captured: dict[str, int | None] = {"bid": None}

    async def _watch_bid() -> None:
        while True:
            await RisingEdge(clock)
            try:
                if int(bus_b.bvalid.value) == 0 or int(bus_b.bready.value) == 0:
                    continue
            except ValueError:
                continue
            bid_val = bus_b.bid.value
            if not bid_val.is_resolvable:
                raise AssertionError(f"X/Z on bid during beat: {bid_val}")
            captured["bid"] = int(bid_val)
            return

    watcher = cocotb.start_soon(_watch_bid())
    try:
        beat = await master.write(
            addr, value.to_bytes(4, byteorder="little"), awid=awid
        )
    except Exception:
        if not watcher.done():
            watcher.kill()
        raise

    if not watcher.done():
        for _ in range(8):
            if watcher.done():
                break
            await RisingEdge(clock)
        if not watcher.done():
            watcher.kill()

    if captured["bid"] is None:
        raise AssertionError(
            f"BID capture miss after write addr=0x{addr:08x} awid=0x{issued:x}"
        )
    return beat.resp, issued, int(captured["bid"])


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
