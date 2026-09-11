# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared AXI helpers for SMU external SMN port and outbound observe.

All SMN AXI traffic goes through the shared ``ocah_axi_vip`` master sequence.
Helpers accept and return plain values only: response codes are the OCAH
``RESP_*`` integers and IDs come from the result objects' independently
sampled ``observed_id``, so no backend transaction objects escape.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cocotb.triggers import RisingEdge, Timer
from ocah_axi_vip import OcahAxiMasterAgent, OcahAxiMasterSequence, resp_name

from seq_lib.smu_tb_pins import smu_axi_in_prefix

__all__ = [
    "AXI_TIMEOUT_NS",
    "AXI_BOUND_LABEL",
    "make_smu_axi_master",
    "axi_read32",
    "axi_read32_resp",
    "axi_read32_resp_ids",
    "axi_read32_resp_ids_bounded",
    "axi_read32_resp_bounded",
    "axi_write32",
    "axi_write32_resp",
    "axi_write32_resp_bounded",
    "axi_write32_resp_ids",
    "wait_signal_high",
    "OutboundAxiRecord",
    "SmuOutboundMonitor",
    "wait_outbound_aw_count",
    "resp_name",
]

# Bounded completion wait for SMN ingress (must fail the testcase on expiry).
AXI_TIMEOUT_NS = 200_000
AXI_BOUND_LABEL = "bound=200us"


async def make_smu_axi_master(
    dut, clk, reset, *, prefix: str | None = None
) -> OcahAxiMasterSequence:
    """Master on the SMU AXI slave, named by whichever TB top is loaded.

    tb/tb_top.sv flattens it as ``s_axi_*``; tb/tb_wrapper_top.sv exposes the
    same interface -- ``smu_axi_in_req_i`` / ``smu_axi_in_resp_o`` on
    smu_wrapper.sv -- as ``ext_in_*``. The prefix is detected rather than
    passed, so a shared sequence runs on either DUT unchanged.

    The wrapper side carries the required AXI4 signals but not the optional
    qualifiers (prot/cache/qos/region/lock, and the user fields), which
    cocotbext-axi treats as optional, so a master builds on either prefix. A
    test that asserts on those qualifiers needs them wired out first.
    """
    agent = OcahAxiMasterAgent.from_prefix(dut, prefix or smu_axi_in_prefix(dut), clk, reset)
    await agent.start()
    await Timer(1, unit="ns")
    return agent.sequence


async def axi_read32(master: OcahAxiMasterSequence, addr: int) -> int:
    result = await master.read_bytes_result(addr, 4, check_response=False)
    return result.data


async def axi_read32_resp(
    master: OcahAxiMasterSequence,
    addr: int,
    *,
    arid: int | None = None,
) -> tuple[int, int]:
    """Return (rdata32, RESP_*) so callers can assert DECERR vs OKAY."""
    result = await master.read_bytes_result(
        addr, 4, id=0 if arid is None else int(arid), check_response=False
    )
    return result.data, result.resp


async def axi_read32_resp_ids(
    master: OcahAxiMasterSequence,
    addr: int,
    *,
    arid: int | None = None,
    timeout_ns: int | None = None,
    label: str = "axi_read",
) -> tuple[int, int, int, int]:
    """Return (rdata32, RESP_*, arid_issued, rid_returned).

    RID is the result's ``observed_id``, sampled from the live R channel on the
    completing beat — never a copy of the issued ARID, so RID==ARID compares
    stay falsifiable. A capture miss fails the call.
    """
    issued = 0 if arid is None else int(arid)
    result = await master.read_bytes_result(
        addr,
        4,
        id=issued,
        check_response=False,
        timeout_ns=timeout_ns,
        allow_timeout=timeout_ns is not None,
    )
    if result.timed_out:
        raise AssertionError(
            f"TIMEOUT {label}: {AXI_BOUND_LABEL} last_state=no_rresp addr=0x{addr:08x}"
        )
    if result.observed_id is None:
        raise AssertionError(f"RID capture miss after read addr=0x{addr:08x} arid=0x{issued:x}")
    return result.data, result.resp, int(result.issued_id), int(result.observed_id)


async def axi_read32_resp_ids_bounded(
    master: OcahAxiMasterSequence,
    addr: int,
    *,
    arid: int | None = None,
    label: str = "axi_read",
    timeout_ns: int = AXI_TIMEOUT_NS,
) -> tuple[int, int, int, int]:
    """Like axi_read32_resp_ids but fail-closed on hang with last-state diagnostics."""
    return await axi_read32_resp_ids(master, addr, arid=arid, timeout_ns=timeout_ns, label=label)


async def axi_read32_resp_bounded(
    master: OcahAxiMasterSequence,
    addr: int,
    *,
    label: str = "axi_read",
    timeout_ns: int = AXI_TIMEOUT_NS,
) -> tuple[int, int]:
    """Like axi_read32_resp but fail-closed on hang."""
    result = await master.read_bytes_result(
        addr, 4, check_response=False, timeout_ns=timeout_ns, allow_timeout=True
    )
    if result.timed_out:
        raise AssertionError(
            f"TIMEOUT {label}: {AXI_BOUND_LABEL} last_state=no_rresp addr=0x{addr:08x}"
        )
    return result.data, result.resp


async def axi_write32(master: OcahAxiMasterSequence, addr: int, value: int) -> None:
    await master.write_bytes_result(
        addr, value.to_bytes(4, byteorder="little"), check_response=False
    )


async def axi_write32_resp(
    master: OcahAxiMasterSequence,
    addr: int,
    value: int,
    *,
    awid: int | None = None,
) -> int:
    """Return the RESP_* code from a 32-bit write."""
    result = await master.write_bytes_result(
        addr,
        value.to_bytes(4, byteorder="little"),
        id=0 if awid is None else int(awid),
        check_response=False,
    )
    return result.resp


async def axi_write32_resp_bounded(
    master: OcahAxiMasterSequence,
    addr: int,
    value: int,
    *,
    label: str = "axi_write",
    timeout_ns: int = AXI_TIMEOUT_NS,
) -> int:
    """Like axi_write32_resp but fail-closed on hang."""
    result = await master.write_bytes_result(
        addr,
        value.to_bytes(4, byteorder="little"),
        check_response=False,
        timeout_ns=timeout_ns,
        allow_timeout=True,
    )
    if result.timed_out:
        raise AssertionError(
            f"TIMEOUT {label}: {AXI_BOUND_LABEL} last_state=no_bresp addr=0x{addr:08x}"
        )
    return result.resp


async def axi_write32_resp_ids(
    master: OcahAxiMasterSequence,
    addr: int,
    value: int,
    *,
    awid: int | None = None,
    timeout_ns: int | None = None,
    label: str = "axi_write",
) -> tuple[int, int, int]:
    """Return (RESP_*, awid_issued, bid_returned).

    BID is the result's ``observed_id``, sampled from the live B channel —
    never a copy of the issued AWID. A capture miss fails the call.
    """
    issued = 0 if awid is None else int(awid)
    result = await master.write_bytes_result(
        addr,
        value.to_bytes(4, byteorder="little"),
        id=issued,
        check_response=False,
        timeout_ns=timeout_ns,
        allow_timeout=timeout_ns is not None,
    )
    if result.timed_out:
        raise AssertionError(
            f"TIMEOUT {label}: {AXI_BOUND_LABEL} last_state=no_bresp addr=0x{addr:08x}"
        )
    if result.observed_id is None:
        raise AssertionError(f"BID capture miss after write addr=0x{addr:08x} awid=0x{issued:x}")
    return result.resp, int(result.issued_id), int(result.observed_id)


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
