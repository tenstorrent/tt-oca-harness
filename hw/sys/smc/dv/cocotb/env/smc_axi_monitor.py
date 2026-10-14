# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Passive AXI protocol/integrity monitor for the SMC SEP_IN ``s_axi`` bus.

This monitor snoops the top-level ``s_axi_*`` channels independently from the
active cocotbext-axi master. It catches issues that can be hidden once response
data is converted to Python integers, such as fully unresolved read data or a
DECERR response.
"""

from __future__ import annotations

from collections import deque

import cocotb
from cocotb.triggers import RisingEdge
from pyuvm import ConfigDB, uvm_component
from seq_lib.smc_addr_map import (
    check_rdl_windows,
    smc_addr_is_deadspace,
    smc_deadspace_ranges,
    smc_map_extent,
    smc_rdl_windows,
)


def _hi(sig) -> bool:
    """A handshake bit is asserted only if it resolves to 1."""
    try:
        return int(sig.value) == 1
    except Exception:
        return False


def _value(sig):
    try:
        return int(sig.value)
    except Exception:
        return None


def _is_all_x(sig) -> bool:
    """True only if every bit of a bus is X/Z."""
    try:
        int(sig.value)
        return False
    except Exception:
        text = str(sig.value).lower()
        return len(text) > 0 and all(ch in "xz" for ch in text)


_RESP_NAME = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR", None: "unparsable"}


class SmcAxiMonitor(uvm_component):
    """Independent SMC SEP_IN AXI read/write-response monitor.

    Every response beat is judged against the address of its own transaction.
    The AW and AR handshakes are queued per ID, and a B beat or the last R beat
    of a burst pops the oldest address of its ID, so with several accesses
    outstanding a DECERR is excused only where that transaction's address
    allows it. The queues empty whenever the primary reset asserts, as the
    manager abandons its outstanding accesses then.
    """

    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.errors: list[str] = []
        self.r_beats = 0
        self.b_resps = 0
        self.unmatched_resps = 0
        self.pending_ar: dict[int | None, deque[int | None]] = {}
        self.pending_aw: dict[int | None, deque[int | None]] = {}
        self.resp_tally = {0: 0, 1: 0, 2: 0, 3: 0, None: 0}
        # DECERR is a protocol failure inside any RDL-declared window. Deadspace
        # -- the gaps between the generated map's windows and everything outside
        # the map -- is derived from the RDL windows (smc_deadspace_ranges). A
        # test that provokes DECERR inside a declared window (an unimplemented
        # `external` region, an integration error slave) registers those
        # addresses in `expected_decerr_addrs`.
        check_rdl_windows()
        self.rdl_windows = smc_rdl_windows()
        self.deadspace_ranges = smc_deadspace_ranges()
        self.expected_decerr_addrs: set[int] = set()
        self.allow_decerr = False
        lo, hi = smc_map_extent()
        self.logger.info(
            "SMC AXI monitor: %d RDL windows and %d deadspace gaps in 0x%08x-0x%08x; "
            "DECERR is expected only in deadspace, outside the map, or at registered addresses",
            len(self.rdl_windows),
            len(self.deadspace_ranges),
            lo,
            hi,
        )

    def _decerr_expected(self, addr: int | None) -> bool:
        if self.allow_decerr:
            return True
        if addr is None:
            return False
        if addr in self.expected_decerr_addrs:
            return True
        return smc_addr_is_deadspace(addr & 0xFFFF_FFFF)

    def _fail(self, msg: str) -> None:
        self.errors.append(msg)
        self.logger.error("SMC AXI MONITOR FAIL: %s", msg)

    @staticmethod
    def _key(id_sig) -> int | None:
        return _value(id_sig) if id_sig is not None else None

    def _push(self, pending: dict, id_sig, addr: int | None) -> None:
        pending.setdefault(self._key(id_sig), deque()).append(addr)

    def _pop(self, pending: dict, id_sig, channel: str, last: bool) -> int | None:
        """Address of the transaction a response beat belongs to; popped on its last beat."""
        key = self._key(id_sig)
        queue = pending.get(key)
        if not queue:
            self.unmatched_resps += 1
            self._fail(f"{channel} beat on ID {key} with no request outstanding")
            return None
        return queue.popleft() if last else queue[0]

    @staticmethod
    def _where(channel: str, addr: int | None) -> str:
        return f" @ {channel} 0x{addr:014x}" if addr is not None else f" (no {channel} recorded)"

    async def run_phase(self) -> None:
        dut = cocotb.top
        sig = {
            name: getattr(dut, f"s_axi_{name}", None)
            for name in (
                "arvalid",
                "arready",
                "araddr",
                "awvalid",
                "awready",
                "awaddr",
                "rvalid",
                "rready",
                "rdata",
                "rresp",
                "bvalid",
                "bready",
                "bresp",
                "awid",
                "bid",
                "arid",
                "rid",
                "rlast",
            )
        }
        required = ("rvalid", "rready", "rdata", "rresp", "bvalid", "bready", "bresp")
        if any(sig[name] is None for name in required):
            self.logger.info("s_axi response channels not found; SMC AXI monitor idle")
            return

        await self.cfg.reset_done.wait()
        self.logger.info("SMC AXI monitor active on SEP_IN s_axi bus")

        rst = getattr(dut, "rst_primary_smc_clk_no", None)
        while True:
            await RisingEdge(dut.clk_smc_i)
            if rst is not None and _value(rst) == 0:
                self.pending_ar.clear()
                self.pending_aw.clear()
                continue
            if sig["arvalid"] is not None and _hi(sig["arvalid"]) and _hi(sig["arready"]):
                self._push(self.pending_ar, sig["arid"], _value(sig["araddr"]))
            if sig["awvalid"] is not None and _hi(sig["awvalid"]) and _hi(sig["awready"]):
                self._push(self.pending_aw, sig["awid"], _value(sig["awaddr"]))

            if _hi(sig["rvalid"]) and _hi(sig["rready"]):
                self.r_beats += 1
                last = sig["rlast"] is None or _hi(sig["rlast"])
                addr = self._pop(self.pending_ar, sig["rid"], "R", last)
                where = self._where("AR", addr)
                code = _value(sig["rresp"])
                self.resp_tally[code if code in (0, 1, 2, 3) else None] += 1
                if _is_all_x(sig["rdata"]):
                    self._fail(f"R beat returned all-X data{where}")
                if code == 3:
                    if self._decerr_expected(addr):
                        self.logger.info("R beat DECERR (expected)%s", where)
                    else:
                        self._fail(f"R beat returned DECERR{where}")

            if _hi(sig["bvalid"]) and _hi(sig["bready"]):
                self.b_resps += 1
                addr = self._pop(self.pending_aw, sig["bid"], "B", True)
                where = self._where("AW", addr)
                code = _value(sig["bresp"])
                if code == 3:
                    if self._decerr_expected(addr):
                        self.logger.info("B beat DECERR (expected)%s", where)
                    else:
                        self._fail(f"B beat returned DECERR{where}")

    def check_phase(self) -> None:
        assert not self.errors, (
            f"SMC AXI monitor found {len(self.errors)} protocol error(s): "
            + "; ".join(self.errors[:8])
        )
        self.logger.info(
            "SMC AXI monitor: %d R beats, %d B resps, %d without a matching request; "
            "R-resp tally %s; 0 errors",
            self.r_beats,
            self.b_resps,
            self.unmatched_resps,
            ", ".join(f"{_RESP_NAME[k]}={v}" for k, v in self.resp_tally.items() if v),
        )
